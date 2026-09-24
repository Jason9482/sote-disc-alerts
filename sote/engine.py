from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from zoneinfo import ZoneInfo
import json
import os
import time
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from .http import StoreClient, FetchError
from .model import Listing, canonical_url, same_site
from .parsers import parse_html, parse_shopify, discover_html, sitemap_links
from .notify import Discord, NotificationError, safe_text
from .discovery import ordered_child_maps

SCANNER_REVISION = "store-repair-2"


def read_config(path: str) -> dict:
    cfg = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(cfg.get("sources"), list) or not cfg["sources"]:
        raise ValueError("config.json must contain a nonempty sources array")
    ids = set()
    for src in cfg["sources"]:
        if not src.get("id") or src["id"] in ids or not src.get("name"):
            raise ValueError("Each source needs a unique id and a name")
        ids.add(src["id"])
        base = src.get("base", "")
        p = urlsplit(base)
        if p.scheme != "https" or not p.hostname or not same_site(base, base):
            raise ValueError("Every source base must be a public HTTPS store URL")
        if p.hostname in {"localhost", "127.0.0.1", "0.0.0.0", "169.254.169.254"} or "." not in p.hostname:
            raise ValueError("Local/private hostnames are not supported")
        for u in src.get("products", []) + src.get("catalogues", []):
            if not same_site(u, base):
                raise ValueError(f"{src['name']}: configured URL does not match source domain")
    repo = os.getenv("GITHUB_REPOSITORY", "")
    if repo:
        cfg["repository_url"] = "https://github.com/" + repo
    return cfg


def product_check(client: StoreClient, source: dict, url: str) -> list[Listing]:
    if source.get("adapter") == "shopify":
        p = urlsplit(url)
        js_url = urlunsplit((p.scheme, p.netloc, p.path.rstrip("/") + ".js", "", ""))
        try:
            obj = json.loads(client.get(js_url))
            if isinstance(obj, dict) and "title" in obj:
                return parse_shopify(obj, source, url)
        except (FetchError, ValueError):
            # A permitted public HTML fallback, never a proxy or access-control workaround.
            pass
    return parse_html(client.get(url), source, url)


def scan_source(source: dict, source_state: dict, cfg: dict, now: float,
                client_factory=StoreClient) -> tuple[list[Listing], dict]:
    client = client_factory(source, source_state, cfg)
    observations: list[Listing] = []
    report = {"name": source["name"], "checked_at": now, "product_pages": 0, "discovery_pages": 0,
              "observations": 0, "errors": [], "warnings": [], "sitemap_attempts": [], "requests": 0, "discovery": "not due"}
    known = source_state.setdefault("known", {})
    # A bounded URL list avoids unbounded crawling or state growth.
    for old in list(known):
        if float(known[old]) < now - 90 * 86400:
            del known[old]
    urls = {canonical_url(u) for u in source.get("products", [])}
    urls.update(known)

    def error(where: str, exc: Exception):
        # Store URLs can be public; do not store stack traces or raw response bodies.
        report["errors"].append(f"{where}: {type(exc).__name__}: {str(exc)[:160]}")

    prechecked = set()
    for url in sorted(urls):
        if url not in {canonical_url(u) for u in source.get("products", [])}:
            continue
        prechecked.add(url)
        try:
            found = product_check(client, source, url)
            if found:
                report["product_pages"] += 1
                observations.extend(found)
                if any(x.status == "unknown" for x in found):
                    report["errors"].append("A matching page has unreadable/ambiguous stock signals")
            else:
                report["errors"].append("Seed page did not expose a matching primary product; not an out-of-stock result")
        except (FetchError, ValueError, TypeError, KeyError) as exc:
            error("product", exc)

    due = (source_state.get("scanner_revision") != SCANNER_REVISION or
           now - float(source_state.get("discovery_at", 0)) >= cfg.get("discovery_hours", 6) * 3600)
    if due:
        # Recheck discovery once after an upgrade; preserve alerts, known URLs and
        # site-requested cooldowns. No user has to delete the state branch.
        source_state["scanner_revision"] = SCANNER_REVISION
        source_state["discovery_at"] = now
        report["discovery"] = "bounded catalogue/sitemap sample (not exhaustive)"
        for catalogue in source.get("catalogues", [])[:2]:
            next_url = catalogue
            for _ in range(int(cfg.get("catalogue_pages", 2))):
                if not next_url:
                    break
                try:
                    found, next_url = discover_html(client.get(next_url), next_url)
                    report["discovery_pages"] += 1
                    urls.update(found)
                    known.update({u: now for u in found})
                except (FetchError, ValueError) as exc:
                    error("catalogue", exc)
                    break
        if source.get("sitemap_discovery", False):
            try:
                client.load_robots()
                maps = list(client.robots.site_maps() or []) if client.robots else []
                maps = list(dict.fromkeys(u for u in maps if same_site(u, source["base"])))
                if len(maps) > 1:
                    root_cursor = int(source_state.get("sitemap_root_cursor", 0)) % len(maps)
                    maps = maps[root_cursor:] + maps[:root_cursor]
                    source_state["sitemap_root_cursor"] = (root_cursor + 1) % len(maps)
                cached = [u for u in source_state.get("working_sitemaps", []) if same_site(u, source["base"])]
                base = source["base"].rstrip("/")
                fallbacks = [base + p for p in ("/sitemap.xml", "/sitemap_index.xml", "/wp-sitemap.xml")]
                # Do not throw away all but the first robots.txt sitemap. Normal
                # request, robots and response limits still apply to every URL.
                roots = list(dict.fromkeys(maps + cached + fallbacks))
                guessed = set(fallbacks) - set(maps) - set(cached)
                queue = list(roots)
                max_maps = max(1, min(8, int(cfg.get("sitemap_pages", 3))))
                seen = set()
                successful_roots = []
                map_attempted_at = source_state.setdefault("sitemap_attempted_at", {})
                # Bound persisted scheduling history without erasing alert state.
                if len(map_attempted_at) > 256:
                    newest = sorted(map_attempted_at, key=lambda u: map_attempted_at[u], reverse=True)[:256]
                    map_attempted_at = {u: map_attempted_at[u] for u in newest}
                    source_state["sitemap_attempted_at"] = map_attempted_at
                while queue and len(seen) < max_maps:
                    current = queue.pop(0)
                    if current in seen or not same_site(current, base):
                        continue
                    seen.add(current)
                    map_attempted_at[current] = now
                    label = urlsplit(current).path or "/"
                    attempt = {"path": label, "result": "failed"}
                    report["sitemap_attempts"].append(attempt)
                    try:
                        getter = getattr(client, "get_sitemap", client.get)
                        map_stats = {}
                        children, found = sitemap_links(getter(current), base, report["warnings"], map_stats)
                        report["discovery_pages"] += 1
                        attempt["result"] = (f"parsed; {len(found)} candidate URL(s); {len(children)} child map(s); "
                                             f"{map_stats.get('page_urls', 0)} page URL(s) inspected")
                        opaque = map_stats.get("opaque_without_title", 0)
                        if opaque:
                            report["warnings"].append(
                                f"{label}: {opaque} opaque product URL(s) had no identifying title; "
                                "their editions were NOT checked")
                        leads = {canonical_url(u) for u in found}
                        urls.update(leads)
                        known.update({u: now for u in leads})
                        if current in roots:
                            successful_roots.append(current)
                        # A verified map takes priority over additional guessed paths.
                        queue = [u for u in queue if u not in guessed]
                        if children:
                            ranked = ordered_child_maps(children, base, map_attempted_at)
                            queue = list(dict.fromkeys(ranked + queue))
                    except Exception as exc:
                        # One missing or malformed map must not stop other declared
                        # maps. Blocks/backoff are NOT permission to try alternatives.
                        error("sitemap " + label[:70], exc)
                        attempt["result"] = (type(exc).__name__ + ": " + str(exc))[:180]
                        status = getattr(exc, "status_code", None)
                        if (status in {401, 403, 429, 503} or
                                float(source_state.get("cooldown_until", 0)) > time.time()):
                            break
                if successful_roots:
                    source_state["working_sitemaps"] = list(dict.fromkeys(successful_roots + cached))[:8]
                if queue:
                    reason = ("Sitemap sampling limit reached" if len(seen) >= max_maps else
                              "Sitemap access was deferred")
                    report["warnings"].append(reason + "; other map files were not checked")
            except Exception as exc:
                error("sitemap setup", exc)

    max_products = int(cfg.get("products_per_store", 10))
    # Explicit known-edition pages get priority over newly discovered leads.
    priority = {canonical_url(u) for u in source.get("products", [])}
    ordered = sorted(urls, key=lambda u: (u not in priority, u))
    if len(ordered) > max_products:
        report["errors"].append("Product check cap reached; remaining candidates need a later/manual check")
    for url in ordered[:max_products]:
        if url in prechecked:
            continue
        if not same_site(url, source["base"]):
            continue
        try:
            found = product_check(client, source, url)
            if found:
                report["product_pages"] += 1
                observations.extend(found)
                if any(x.status == "unknown" for x in found):
                    report["errors"].append("A matching page has unreadable/ambiguous stock signals")
            else:
                report["errors"].append("Candidate page did not expose a matching primary product; not an out-of-stock result")
        except (FetchError, ValueError, TypeError, KeyError) as exc:
            error("product", exc)
    report["observations"] = len(observations)
    report["requests"] = client.calls
    if not due and not ordered:
        previous = source_state.get("report", {})
        report["discovery"] = "next sample not due; last attempt " + str(source_state.get("discovery_at", "never"))
        # Carry the last known discovery failures into health summaries until rechecked.
        report["errors"].extend(previous.get("errors", []))
    source_state["report"] = report
    return observations, report


def event_for(item: Listing, history: dict, now: float, cfg: dict) -> str | None:
    """Observe stock; failures/unknowns never erase the last definite stock state."""
    entry = history.setdefault(item.key, {"stock_cycle": 0, "alerted_cycle": 0, "possible_sent": False})
    last_definite = entry.get("last_definite")
    if item.status == "in_stock":
        if last_definite != "in_stock":
            entry["stock_cycle"] += 1
        entry["last_definite"] = "in_stock"
    elif item.status in {"out_of_stock", "backorder"}:
        entry["last_definite"] = item.status
    entry.update({"last_seen": now, "item": item.as_dict()})
    cap = cfg.get("max_price_inr")
    if cap and item.currency == "INR" and item.price != "Not verified":
        if float(item.price.replace(",", "")) > float(cap):
            return None
    if item.status in {"out_of_stock", "backorder"}:
        return None
    if item.match == "exact" and item.status == "in_stock":
        if entry["stock_cycle"] > entry["alerted_cycle"]:
            return "IN-STOCK LEAD"
    elif (cfg.get("alert_possible", True) and not entry["possible_sent"]
          and (item.status == "in_stock" or not entry.get("last_definite"))):
        return "CHECK MANUALLY"
    return None


def acknowledge(item: Listing, history: dict, kind: str) -> None:
    entry = history[item.key]
    if kind == "IN-STOCK LEAD":
        entry["alerted_cycle"] = entry["stock_cycle"]
    else:
        entry["possible_sent"] = True


def health_text(reports: list[dict], state: dict, reddit_status: str) -> str:
    when = datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%d %b %Y, %I:%M %p IST")
    lines = [f"Last scan: {when}", f"Code: {SCANNER_REVISION}", "", "Configured does not mean successfully checked:"]
    for r in reports:
        if r["product_pages"]:
            msg = f"{r['product_pages']} matching product page(s) read"
        elif r["discovery_pages"]:
            msg = "discovery sample read; no readable matching product"
        elif r["errors"]:
            msg = "NOT CHECKED / check failed"
        else:
            msg = "no known product; discovery not due"
        if r["errors"]:
            msg += f"; {len(r['errors'])} issue(s)"
        if r.get("warnings"):
            msg += "; discovery notes in report"
        lines.append(f"{r['name']}: {msg}")
    lines.extend(["", f"Reddit: {reddit_status}",
                  "Delivery/PIN and payment protection are never automatically confirmed.",
                  "See the GitHub run summary for failures and coverage. Missing daily messages: inspect Actions."])
    return "\n".join(lines)


def write_run_summary(reports: list[dict], observations: list[Listing], notes: list[str]) -> str:
    lines = ["# SOTE tracker run", "", f"Code: {SCANNER_REVISION}", "", "Stock signals are store claims, not verified checkout/delivery.", "",
             "| Source | Matching pages | Discovery pages | Issues |", "|---|---:|---:|---|"]
    for r in reports:
        details = r["errors"] + ["Note: " + w for w in r.get("warnings", [])]
        issues = "; ".join(details[:4]).replace("|", "/").replace("\n", " ") or "None this run"
        lines.append(f"| {r['name']} | {r['product_pages']} | {r['discovery_pages']} | {issues} |")
    lines.extend(["", "## Matching observations", ""])
    for item in observations:
        lines.append(f"- {item.source}: {item.status}, {item.match}, {item.variant or 'single/unspecified variant'}; {item.url}")
        evidence = item.evidence.replace("\n", " ").replace("`", "")[:300]
        lines.append(f"  - Evidence: {evidence}")
    attempts = [(r["name"], a) for r in reports for a in r.get("sitemap_attempts", [])]
    if attempts:
        lines.extend(["", "## Discovery diagnostics", "", "Paths below are sitemap files, not stock claims. Game/product maps are prioritized; lower-priority maps may remain unchecked.", ""])
        for name, attempt in attempts:
            text = (attempt["path"] + " - " + attempt["result"]).replace("\n", " ").replace("`", "")
            lines.append(f"- {name}: {text}")
    lines.extend(["", "## Notes", "", *["- " + n for n in notes]])
    result = "\n".join(lines) + "\n"
    Path("last-run.md").write_text(result, encoding="utf-8")
    summary_path = os.getenv("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as file:
            file.write(result)
    return result


def run_scan(cfg: dict, store, notifier: Discord | None, *, dry_run: bool = False, force_health: bool = False) -> int:
    now = time.time()
    state = store.load()
    enabled = [s for s in cfg["sources"] if s.get("enabled", True)]
    observations, reports, notes = [], [], []
    for src in enabled:
        state["sources"].setdefault(src["id"], {})
    with ThreadPoolExecutor(max_workers=min(4, max(1, len(enabled)))) as executor:
        jobs = {executor.submit(scan_source, s, state["sources"][s["id"]], cfg, now): s for s in enabled}
        for future in as_completed(jobs):
            src = jobs[future]
            try:
                items, report = future.result()
            except Exception as exc:
                # Safe fixed diagnostic for unexpected errors; never dump credentials/response bodies.
                items = []
                report = {"name": src["name"], "product_pages": 0, "discovery_pages": 0,
                          "errors": ["Unexpected adapter error: " + type(exc).__name__]}
            observations.extend(items)
            reports.append(report)
    reports.sort(key=lambda r: r["name"].lower())
    # Avoid duplicates from a catalogue link plus an explicit URL.
    observations = list({x.key: x for x in observations}.values())
    sent, delivery_failed = 0, False
    for item in sorted(observations, key=lambda x: (x.status != "in_stock", x.source, x.url)):
        kind = event_for(item, state["listings"], now, cfg)
        if not kind:
            continue
        if dry_run:
            notes.append(f"Would notify: {kind} - {item.source} - {item.url}")
        elif sent < int(cfg.get("max_alerts_per_run", 12)):
            try:
                assert notifier is not None
                notifier.listing(item, kind)
                acknowledge(item, state["listings"], kind)
                sent += 1
            except NotificationError as exc:
                notes.append(str(exc))
                delivery_failed = True
                break
    reddit_status = "off in GitHub; external MonitoRSS feeds are separate and not checked here"
    if not cfg.get("reddit", {}).get("enabled") and state["reddit"].get("items") and not dry_run:
        from .reddit import remove_alerts
        try:
            remove_alerts(state["reddit"], notifier, all_items=True)
        except NotificationError as exc:
            notes.append(str(exc))
    if cfg.get("reddit", {}).get("enabled"):
        if dry_run:
            reddit_status = "not queried during dry-run"
        else:
            from .reddit import scan_reddit
            reddit_status = scan_reddit(cfg["reddit"], state["reddit"], notifier, now)
    if not dry_run and (force_health or now - float(state.get("heartbeat_at", 0)) >= 86400):
        try:
            assert notifier is not None
            notifier.send("HEALTH: SOTE tracker", safe_text(health_text(reports, state, reddit_status), 3900))
            state["heartbeat_at"] = now
        except NotificationError as exc:
            notes.append(str(exc))
            delivery_failed = True
    for key in list(state["listings"]):
        if state["listings"][key].get("last_seen", now) < now - 90 * 86400:
            del state["listings"][key]
    state["last_scan_at"] = now
    notes.extend([f"Delivered {sent} retailer alert(s).", f"Reddit: {reddit_status}",
                  "Sitemap/catalogue discovery is bounded and not exhaustive.",
                  "No automated checkout or PIN-code delivery test is performed."])
    summary = write_run_summary(reports, observations, notes)
    print(summary)
    if not dry_run:
        store.save(state)
    all_failed = bool(reports) and all(not r["product_pages"] and not r["discovery_pages"] and r["errors"] for r in reports)
    return 1 if delivery_failed or all_failed else 0

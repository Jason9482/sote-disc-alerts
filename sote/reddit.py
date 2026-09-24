"""Optional, read-only Reddit API module. Disabled without explicit approval + OAuth.
No scraping fallback. No private messages, replies, or automated purchases.
Only link-only leads are sent; usernames, post text and titles are not persisted.
"""
from __future__ import annotations

import os
import hashlib
import hmac
from urllib.parse import urlsplit
import re
import requests

from .model import match_title, normalized
from .notify import NotificationError


class RedditError(RuntimeError):
    pass


def relevant(data: dict) -> bool:
    title = str(data.get("title", ""))
    body = str(data.get("selftext", data.get("body", "")))
    text = normalized(title + " " + body)
    flair = normalized(str(data.get("link_flair_text", "")))
    if data.get("removed_by_category") or body in {"[deleted]", "[removed]"}:
        return False
    if re.search(r"\bwtb\b|\bwant(?:ed)? to buy\b|\blooking (?:to buy|for)\b", normalized(title) or text[:100]):
        return False
    if re.search(r"\b(sold|closed)\b", flair) or re.match(r"\[?sold\]?", title.lower()):
        return False
    # Do not treat generic discussion of the DLC as a sale.
    sale = bool(re.search(r"\bwts\b|\bfor sale\b|\bselling\b|\bwant to sell\b", text) or "sale" in flair)
    if not sale:
        return False
    return match_title(title + " " + body) != "reject"


class RedditClient:
    def __init__(self):
        if os.getenv("REDDIT_APPROVED", "").lower() != "true":
            raise RedditError("disabled: Reddit approval has not been confirmed")
        names = ["REDDIT_CLIENT_ID", "REDDIT_CLIENT_SECRET", "REDDIT_REFRESH_TOKEN", "REDDIT_USER_AGENT"]
        vals = {n: os.getenv(n, "") for n in names}
        if not all(vals.values()):
            raise RedditError("disabled: approved OAuth credentials/user-agent are incomplete")
        self.dedupe_key = vals["REDDIT_CLIENT_SECRET"].encode("utf-8")
        self.session = requests.Session()
        self.session.headers["User-Agent"] = vals["REDDIT_USER_AGENT"]
        try:
            r = self.session.post("https://www.reddit.com/api/v1/access_token",
                                  auth=(vals["REDDIT_CLIENT_ID"], vals["REDDIT_CLIENT_SECRET"]),
                                  data={"grant_type": "refresh_token", "refresh_token": vals["REDDIT_REFRESH_TOKEN"]},
                                  timeout=20, allow_redirects=False)
            if r.status_code != 200:
                raise RedditError(f"OAuth failed (HTTP {r.status_code}); no scraping fallback")
            obj = r.json()
            token = obj.get("access_token")
            if not token:
                raise RedditError("OAuth access token missing")
            if "read" not in str(obj.get("scope", "read")).split() and obj.get("scope") != "*":
                raise RedditError("Approved OAuth token does not have read permission")
            self.session.headers["Authorization"] = "Bearer " + token
        except requests.RequestException:
            raise RedditError("OAuth network request failed") from None
        except (ValueError, TypeError):
            raise RedditError("OAuth response unreadable") from None

    def fingerprint(self, fullname: str) -> str:
        return hmac.new(self.dedupe_key, fullname.encode("utf-8"), hashlib.sha256).hexdigest()

    def get(self, path: str, params: dict) -> list[dict]:
        try:
            r = self.session.get("https://oauth.reddit.com" + path, params=params, timeout=20,
                                 allow_redirects=False)
            if r.status_code != 200:
                raise RedditError(f"API returned HTTP {r.status_code}; query deferred")
            return [x["data"] for x in r.json().get("data", {}).get("children", []) if isinstance(x.get("data"), dict)]
        except requests.RequestException:
            raise RedditError("API network request failed") from None
        except (ValueError, TypeError, KeyError):
            raise RedditError("API response format changed") from None


def remove_alerts(state: dict, notifier, *, all_items: bool = False, now: float = 0, retention: int = 86400) -> int:
    removed = 0
    items = state.setdefault("items", {})
    for ident, record in list(items.items()):
        if all_items or now - record.get("sent_at", 0) >= retention:
            notifier.delete(record["message_id"])
            del items[ident]
            removed += 1
    return removed


def scan_reddit(cfg: dict, state: dict, notifier, now: float) -> str:
    try:
        # Removing our own old messages does not need Reddit access.
        remove_alerts(state, notifier, now=now, retention=int(cfg.get("message_retention_hours", 24) * 3600))
        client = RedditClient()
        items = state.setdefault("items", {})
        # Recover source IDs from our private Discord messages rather than public Git history.
        pending = {}
        for key, record in list(items.items()):
            link = notifier.message_link(record["message_id"])
            if not link:
                del items[key]
                continue
            p = urlsplit(link)
            segments = p.path.strip("/").split("/")
            if p.hostname not in {"www.reddit.com", "reddit.com"} or len(segments) < 4 or segments[2] != "comments":
                raise RedditError("Cannot identify the source of an existing Reddit alert")
            ident = ("t1_" + segments[5]) if len(segments) >= 6 and segments[5] else ("t3_" + segments[3])
            if not re.fullmatch(r"t[13]_[a-z0-9]+", ident):
                raise RedditError("Invalid Reddit permalink in a prior alert")
            pending[ident] = key
        ids = list(pending)
        for offset in range(0, len(ids), 50):
            chunk = ids[offset:offset + 50]
            current = {d.get("name"): d for d in client.get("/api/info", {"id": ",".join(chunk)})}
            for ident in chunk:
                data = current.get(ident)
                if not data or not relevant(data):
                    key = pending[ident]
                    notifier.delete(items[key]["message_id"])
                    del items[key]
        delivered, read_count, capped = 0, 0, False
        limit = min(100, max(10, int(cfg.get("limit", 100))))
        previous_scan = float(state.get("last_scan", now - int(cfg.get("max_age_hours", 24)) * 3600))
        for sub in cfg.get("subreddits", []):
            if not re.fullmatch(r"[A-Za-z0-9_]{2,30}", sub):
                raise RedditError("Invalid subreddit in configuration")
            paths = [f"/r/{sub}/new"]
            if cfg.get("include_comments", True):
                paths.append(f"/r/{sub}/comments")
            for path in paths:
                data = client.get(path, {"limit": limit, "raw_json": 1})
                read_count += len(data)
                if len(data) >= limit and min((d.get("created_utc", now) for d in data), default=now) > previous_scan:
                    capped = True  # More items may have been posted than one page can cover.
                for d in data:
                    ident = str(d.get("name", ""))
                    if not re.fullmatch(r"t[13]_[a-z0-9]+", ident):
                        continue
                    key = client.fingerprint(ident)
                    if key in items:
                        continue
                    if now - float(d.get("created_utc", 0)) > int(cfg.get("max_age_hours", 24)) * 3600:
                        continue
                    if not relevant(d) or delivered >= 8 or len(items) >= 30:
                        continue
                    path = str(d.get("permalink", ""))
                    if not path.startswith("/r/") or path.startswith("//"):
                        continue
                    link = "https://www.reddit.com" + path
                    msg = notifier.send("REDDIT: possible PS5 SOTE sale",
                                        "A text match was found in an approved subreddit feed. "
                                        "Open the original post/comment to check the edition, photos and sale status. "
                                        "Private seller: buyer protection is NOT established. "
                                        "No post text or username has been copied into this alert.", link=link)
                    # Keyed hashes + opaque Discord IDs only; no Reddit IDs, links or content in public Git history.
                    items[key] = {"message_id": msg, "sent_at": now}
                    delivered += 1
        state["last_scan"] = now
        return f"approved API: read {read_count} items, sent {delivered} link-only leads" + (
            "; feed cap reached, some activity may have been missed" if capped else "")
    except (RedditError, NotificationError) as exc:
        return "NEEDS ATTENTION: " + str(exc)

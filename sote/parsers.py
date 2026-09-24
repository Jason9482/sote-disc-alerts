from __future__ import annotations

import json
import re
from decimal import Decimal, InvalidOperation
from urllib.parse import urljoin, urlencode, urlsplit, parse_qsl
import xml.etree.ElementTree as ET
from bs4 import BeautifulSoup, Tag

from .model import Listing, canonical_url, condition, dlc_status, is_buyback, match_title, normalized, same_site


def money(value: object, cents: bool = False) -> str:
    try:
        n = Decimal(str(value).replace(",", ""))
        if not n.is_finite() or n <= 0:
            return "Not verified"
        if cents:
            n /= 100
        return f"{n:,.2f}"
    except (InvalidOperation, ValueError, TypeError):
        return "Not verified"


def parse_shopify(data: dict, source: dict, url: str) -> list[Listing]:
    title = str(data.get("title", ""))
    level = match_title(title, url)
    if level == "reject":
        return []
    variants = data.get("variants")
    if not isinstance(variants, list) or not variants:
        return [Listing(source["name"], title, url, match=level,
                        evidence="Product found, but individual purchase variants are unavailable")]
    results = []
    for v in variants:
        label = str(v.get("title", ""))
        if is_buyback(label) or v.get("requires_shipping") is False:
            continue
        variant_level = match_title(title + " " + label, url)
        if variant_level == "reject":
            continue
        ident = v.get("id")
        if ident is None:
            continue
        # Never use the product-level 'available': it may refer to BUYBACK only.
        available = v.get("available")
        status = "in_stock" if available is True else "out_of_stock" if available is False else "unknown"
        if v.get("requires_selling_plan") is True:
            status = "unknown"
        results.append(Listing(source["name"], title,
                               url.split("?")[0].rstrip("/") + "?" + urlencode({"variant": ident}),
                               status=status, match=variant_level, variant=label,
                               price=money(v.get("price"), cents=True),
                               currency=source.get("currency", "INR"),
                               condition=condition(label + " " + title), dlc=dlc_status(label),
                               evidence="Shopify purchase-variant available flag; delivery not tested"))
    return results


def json_nodes(value: object):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            if isinstance(child, (list, dict)):
                yield from json_nodes(child)
    elif isinstance(value, list):
        for child in value:
            yield from json_nodes(child)


def _typed(node: dict, kind: str) -> bool:
    types = node.get("@type", [])
    return kind in (types if isinstance(types, list) else [types])


def primary_scope(soup: BeautifulSoup, heading: Tag | None) -> Tag | None:
    if heading is None:
        return None
    for parent in [heading.parent, *heading.parents]:
        if not isinstance(parent, Tag) or parent.name in {"body", "html", "[document]"}:
            continue
        classes = set(parent.get("class", []))
        if classes & {"summary", "product-summary", "product-info", "product__info", "product-info-main"}:
            return parent
    for parent in heading.parents:
        if not isinstance(parent, Tag) or parent.name in {"body", "html", "[document]"}:
            continue
        if "product" in parent.get("class", []) or parent.get("itemtype", "").endswith("/Product"):
            # Work with a copy so that removing recommendations cannot affect JSON-LD lookup.
            copy = BeautifulSoup(str(parent), "html.parser")
            for node in copy.select(".related, .upsells, .cross-sells, .recommendations, .recently-viewed, .reviews, #reviews"):
                node.decompose()
            return copy
    return None


def clean_purchase_scope(scope: Tag | None) -> Tag | None:
    """Exclude hidden templates, related cards and store-wide policy fragments.

    This is static parsing, not a browser: external CSS/JavaScript is not evaluated.
    """
    if scope is None:
        return None
    copy = BeautifulSoup(str(scope), "html.parser")
    selector = ("script, style, template, noscript, [hidden], [aria-hidden='true'], "
                ".related, .upsells, .cross-sells, .recommendations, .recently-viewed, "
                ".reviews, #reviews")
    for node in list(copy.select(selector)):
        if node.parent is not None:
            node.decompose()
    for node in list(copy.select("[style]")):
        if node.parent is not None and re.search(
                r"(?:display\s*:\s*none|visibility\s*:\s*hidden)", str(node.get("style", "")), re.I):
            node.decompose()
    return copy


def stock_label(text: str) -> str | None:
    """Recognize a short affirmative stock label, not a shipping-policy paragraph."""
    t = normalized(text)
    if not t or len(t) > 140 or re.search(r"\b(?:policy|policies|terms|rules|guidelines|instructions|example)\b", t):
        return None
    # The wrapper must be affirmative and local, e.g. 'Availability: Out of stock'.
    t = re.sub(r"^(?:availability|stock status|status)\s+", "", t)
    t = re.sub(r"^(?:this\s+)?(?:item|product)\s+is\s+", "", t)
    if re.match(r"^(?:out of stock|sold out|currently unavailable)(?:$|\s)", t):
        return "out_of_stock"
    if re.match(r"^(?:available on back ?order|on back ?order|back ?order(?:ed)?|"
                r"available (?:for|on) pre ?order|pre ?order(?:s)?(?: available| now)?)(?:$|\s)", t):
        if not re.search(r"\b(?:not|unavailable|disabled|closed|cannot)\b", t):
            return "backorder"
    return None


def scope_stock_labels(scope: Tag) -> set[str]:
    states = set()
    # Short labels only. Do not scan the entire purchase area's combined text:
    # that includes generic 'preorder policy' or 'notify when back in stock' copy.
    for node in scope.select("p, span, div, strong, button, .stock, .availability, .product-availability"):
        if any(x.name in {"p", "div", "form", "section", "h1"} for x in node.find_all(recursive=False)):
            continue
        state = stock_label(node.get_text(" ", strip=True))
        if state:
            states.add(state)
    return states


def availability_from_offer(offer: dict) -> str:
    value = str(offer.get("availability", "")).rsplit("/", 1)[-1].lower()
    return {"instock": "in_stock", "outofstock": "out_of_stock", "soldout": "out_of_stock",
            "discontinued": "out_of_stock", "backorder": "backorder", "preorder": "backorder",
            "presale": "backorder"}.get(value, "unknown")


def parse_html(html: str, source: dict, url: str) -> list[Listing]:
    soup = BeautifulSoup(html, "html.parser")
    heading = soup.select_one("h1.product_title, h1.product-title, h1.product__title, main h1, h1")
    # A primary heading is mandatory: related products must not impersonate the main item.
    if heading is None:
        return []
    title = heading.get_text(" ", strip=True)
    level = match_title(title, url)
    if level == "reject":
        return []
    scope = clean_purchase_scope(primary_scope(soup, heading))
    scope_text = scope.get_text(" ", strip=True) if scope else ""

    # Shopify HTML can contain complete product JSON. Do not guess from free text.
    if source.get("adapter") == "shopify":
        for script in soup.select('script[type="application/json"]'):
            try:
                raw = json.loads(script.string or script.get_text())
                for node in json_nodes(raw):
                    if "variants" in node and normalized(node.get("title", "")) == normalized(title):
                        found = parse_shopify(node, source, url)
                        if found:
                            return found
            except (ValueError, TypeError):
                pass
        return [Listing(source["name"], title, url, match=level,
                        evidence="Individual Shopify variants not readable; aggregate stock ignored")]

    # WooCommerce variants must be evaluated individually, not as an aggregate offer.
    form = soup.select_one("form.variations_form[data-product_variations]")
    if form is not None:
        try:
            variants = json.loads(form.get("data-product_variations", "false"))
        except (ValueError, TypeError):
            variants = None
        if isinstance(variants, list) and variants:
            results = []
            for v in variants:
                label = " / ".join(str(x) for x in v.get("attributes", {}).values())
                if is_buyback(label):
                    continue
                variant_level = match_title(title + " " + label, url)
                if variant_level == "reject":
                    continue
                active = v.get("variation_is_active", True) is not False
                buyable = v.get("is_purchasable", True) is not False
                available = v.get("is_in_stock")
                status = "in_stock" if available is True and active and buyable else (
                    "out_of_stock" if available is False or not active or not buyable else "unknown")
                availability = clean_purchase_scope(BeautifulSoup(str(v.get("availability_html", "")), "html.parser"))
                labels = scope_stock_labels(availability) if availability is not None else set()
                availability_label = stock_label(availability.get_text(" ", strip=True)) if availability is not None else None
                if "out_of_stock" in labels or availability_label == "out_of_stock":
                    status = "out_of_stock"
                elif status == "in_stock" and ("backorder" in labels or availability_label == "backorder"):
                    status = "backorder"
                query = {"variation_id": v.get("variation_id", ""), **v.get("attributes", {})}
                results.append(Listing(source["name"], title, url.split("?")[0] + "?" + urlencode(query),
                                       status=status, match=variant_level, variant=label,
                                       price=money(v.get("display_price")), currency=source.get("currency", "INR"),
                                       condition=condition(label + " " + title), dlc=dlc_status(label),
                                       evidence="WooCommerce purchase-variant stock flag; delivery not tested"))
            return results
        return [Listing(source["name"], title, url, match=level,
                        evidence="Variant selection requires JavaScript; aggregate stock ignored")]

    # Match structured data to this page, never simply take the first in-stock Product.
    products = []
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            products.extend(n for n in json_nodes(json.loads(script.string or script.get_text()))
                            if _typed(n, "Product") and
                            normalized(n.get("name", "")) == normalized(title))
        except (ValueError, TypeError, RecursionError):
            continue
    product = next((p for p in products if canonical_url(str(p.get("url", url))) == canonical_url(url)),
                   products[0] if products else {})
    offers = product.get("offers", {})
    if isinstance(offers, dict):
        offers = [offers]
    offers = [o for o in offers if isinstance(o, dict)] if isinstance(offers, list) else []
    offer_states = {availability_from_offer(o) for o in offers} - {"unknown"}
    status = next(iter(offer_states)) if len(offer_states) == 1 else "unknown"
    evidence = "Primary-product structured availability; delivery not tested" if offer_states else "No reliable stock signal"
    price = money(offers[0].get("price")) if len(offers) == 1 else "Not verified"
    currency = str(offers[0].get("priceCurrency", source.get("currency", "INR"))) if offers else source.get("currency", "INR")

    if scope:
        text = normalized(scope_text)
        out_nodes = scope.select(".stock.out-of-stock, .stock.outofstock, .out-of-stock-message")
        stock_nodes = scope.select(".stock.in-stock, .stock.instock")
        labels = scope_stock_labels(scope)
        if out_nodes or "out_of_stock" in labels:
            status, evidence = "out_of_stock", "Primary purchase section explicitly says unavailable; generic preorder/waitlist text is ignored"
        elif "backorder" in labels:
            status, evidence = "backorder", "Explicit primary-product backorder/preorder label; not ready stock"
        elif is_buyback(text):
            status, evidence = "unknown", "Mixed buy/sell content: purchase variant could not be isolated"
        elif stock_nodes:
            if status in {"out_of_stock", "backorder"}:
                status, evidence = "unknown", "Conflicting primary stock label and structured offer; manual verification required"
            else:
                status, evidence = "in_stock", "Primary purchase section explicitly says in stock; delivery not tested"
        else:
            button = scope.select_one("button.single_add_to_cart_button, button[name='add-to-cart']")
            if button is not None:
                disabled = button.has_attr("disabled") or button.get("aria-disabled") == "true" or "disabled" in button.get("class", [])
                if disabled and status == "in_stock":
                    status, evidence = "unknown", "Conflicting signals: structured in-stock but purchase button disabled"
                elif not disabled:
                    if status in {"out_of_stock", "backorder"}:
                        status, evidence = "unknown", "Enabled Add to Cart conflicts with structured unavailability; manual verification required"
                    else:
                        status, evidence = "in_stock", "Enabled product-specific Add to Cart button; delivery not tested"
        pnode = next((node for selector in (".price ins .amount", ".price ins", ".price > .amount", ".price .amount")
                          if (node := scope.select_one(selector)) is not None), None)
        if pnode:
            text_price = pnode.get_text(" ", strip=True)
            numeric = re.search(r"\d[\d,]*(?:\.\d{1,2})?", text_price)
            if numeric:
                price = money(numeric.group())

    # A mixed-platform heading can never produce a strong stock alert.
    return [Listing(source["name"], title, url, status=status, match=level, price=price,
                    currency=currency, condition=condition(title + " " + source.get("default_condition", "")),
                    dlc=dlc_status(title + " " + scope_text), evidence=evidence)]


def discover_html(html: str, url: str) -> tuple[list[str], str | None]:
    soup = BeautifulSoup(html, "html.parser")
    urls = set()
    for a in soup.select("a[href]"):
        href = urljoin(url, str(a["href"]))
        if not same_site(href, url) or any(x in href.lower() for x in ("add-to-cart", "/cart", "/checkout", "/account", "/tag/", "/product-tag/")):
            continue
        name = a.get_text(" ", strip=True) or str(a.get("title", ""))
        img = a.find("img")
        if not name and img:
            name = str(img.get("alt", ""))
        slug = normalized(href)
        # URL slug is only a discovery lead. The detail page must still pass title checks.
        if match_title(name, href) != "reject" or re.search(r"shadow (?:of )?(?:the )?erdtree", slug):
            if any(p in href for p in ("/product/", "/products/", "/shop/", "/Games/", "/p/")):
                urls.add(canonical_url(href))
    next_link = soup.select_one("a.next.page-numbers, a[rel='next'], a.pagination__next")
    next_url = urljoin(url, next_link["href"]) if next_link and next_link.get("href") else None
    return sorted(urls), next_url if next_url and same_site(next_url, url) else None


def sitemap_links(xml: str, base: str, warnings: list[str] | None = None,
                  stats: dict | None = None) -> tuple[list[str], list[str]]:
    """Extract discovery leads, never availability, from a verified sitemap root.

    A narrowly scoped retry repairs unescaped ampersands only. Other malformed
    XML, HTML error pages and entity declarations still fail closed. Image URLs
    must not be mistaken for product-page URLs.
    """
    if "<!DOCTYPE" in xml.upper() or "<!ENTITY" in xml.upper():
        raise ValueError("Unsupported XML declaration")
    xml = xml.lstrip("\ufeff \t\r\n")
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        # Protect CDATA/comments: their ampersands are not XML entities.
        pieces = re.split(r"(<!\[CDATA\[.*?\]\]>|<!--.*?-->)", xml, flags=re.S)
        for n in range(0, len(pieces), 2):
            pieces[n] = re.sub(r"&(?!amp;|lt;|gt;|quot;|apos;|#\d+;|#x[0-9A-Fa-f]+;)", "&amp;", pieces[n])
        repaired = "".join(pieces)
        if repaired == xml:
            raise
        root = ET.fromstring(repaired)
        if warnings is not None:
            warnings.append("Sitemap contained unescaped ampersands; repaired for URL discovery only")

    def local(tag: str) -> str:
        return tag.rsplit("}", 1)[-1]

    kind = local(root.tag)
    if kind not in {"sitemapindex", "urlset"}:
        raise ValueError("Response is not an XML sitemap (HTML/error page is not catalogue coverage)")
    urls: list[str] = []
    if stats is not None:
        stats.update(page_urls=0, opaque_without_title=0)
    for entry in root:
        if local(entry.tag) != ("sitemap" if kind == "sitemapindex" else "url"):
            continue
        loc = next((x for x in entry if local(x.tag) == "loc" and x.text), None)
        if loc is None:
            continue
        u = loc.text.strip()
        if not same_site(u, base):
            continue
        if kind == "sitemapindex":
            urls.append(u)
        else:
            # A URL or an explicit sitemap title is only a discovery hint.
            # Numeric-ID pages still require the normal primary-title/stock check.
            titles = [x.text or "" for x in entry.iter() if local(x.tag) == "title"]
            if stats is not None:
                stats["page_urls"] += 1
                parsed = urlsplit(u)
                ids = {k.lower() for k, _ in parse_qsl(parsed.query)}
                identifier_only = bool(ids & {"boxid", "id", "product_id", "pid"}) or bool(
                    re.search(r"/(?:product|products|detail|details)/[0-9a-f-]{8,}/?$", parsed.path, re.I))
                descriptive = bool(re.search(r"shadow (?:of )?(?:the )?erdtree|\bsote\b", normalized(u)))
                if identifier_only and not any(t.strip() for t in titles) and not descriptive:
                    stats["opaque_without_title"] += 1
            if (re.search(r"shadow (?:of )?(?:the )?erdtree|\bsote\b", normalized(u))
                    or any(match_title(t, u) != "reject" for t in titles)):
                urls.append(u)
    urls = list(dict.fromkeys(urls))
    if kind == "sitemapindex":
        return sorted(urls, key=lambda u: ("product" not in u.lower(), u)), []
    return [], urls

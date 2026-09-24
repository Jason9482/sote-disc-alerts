from __future__ import annotations

import json
import re
from decimal import Decimal, InvalidOperation
from urllib.parse import urljoin, urlencode
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
    scope = primary_scope(soup, heading)
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
                if "backorder" in str(v.get("availability_html", "")).lower():
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
        if re.search(r"\bback order\b|\bbackorder\b|\bpre order\b|\bpreorder\b", text):
            status, evidence = "backorder", "Primary purchase section says backorder/preorder"
        elif out_nodes or re.search(r"\bout of stock\b|\bsold out\b|\bcurrently unavailable\b", text):
            status, evidence = "out_of_stock", "Primary purchase section explicitly says unavailable"
        elif is_buyback(text):
            status, evidence = "unknown", "Mixed buy/sell content: purchase variant could not be isolated"
        elif stock_nodes:
            status, evidence = "in_stock", "Primary purchase section explicitly says in stock; delivery not tested"
        else:
            button = scope.select_one("button.single_add_to_cart_button, button[name='add-to-cart']")
            if button is not None:
                disabled = button.has_attr("disabled") or button.get("aria-disabled") == "true" or "disabled" in button.get("class", [])
                if disabled and status == "in_stock":
                    status, evidence = "unknown", "Conflicting signals: structured in-stock but purchase button disabled"
                elif not disabled:
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


def sitemap_links(xml: str, base: str) -> tuple[list[str], list[str]]:
    """Return child sitemap URLs and exact-ish product URL leads. Bounded by HTTP size limit."""
    # stdlib ElementTree does not fetch external entities, but reject declarations anyway.
    if "<!DOCTYPE" in xml.upper() or "<!ENTITY" in xml.upper():
        raise ValueError("Unsupported XML declaration")
    root = ET.fromstring(xml)
    locs = [x.text.strip() for x in root.iter() if x.tag.rsplit("}", 1)[-1] == "loc" and x.text]
    locs = [u for u in locs if same_site(u, base)]
    if root.tag.rsplit("}", 1)[-1] == "sitemapindex":
        # Product maps first; never claim complete catalogue coverage from a bounded scan.
        return sorted(locs, key=lambda u: ("product" not in u.lower(), u)), []
    matches = [u for u in locs if re.search(r"shadow (?:of )?(?:the )?erdtree|\bsote\b", normalized(u))]
    return [], matches

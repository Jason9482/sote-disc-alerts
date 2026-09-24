from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit, unquote


def normalized(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", unquote(str(text)).lower())).strip()


def canonical_url(url: str) -> str:
    p = urlsplit(url)
    # Variant and product identifiers affect the item; analytics parameters do not.
    kept = [(k, v) for k, v in parse_qsl(p.query) if k.lower() in
            {"variant", "pid", "id", "product_id", "variation_id"}]
    return urlunsplit((p.scheme.lower(), p.netloc.lower(), p.path.rstrip("/") or "/",
                       urlencode(sorted(kept)), ""))


def same_site(url: str, base: str) -> bool:
    a, b = urlsplit(url), urlsplit(base)
    return (a.scheme == "https" and not a.username and not a.password
            and a.port in (None, 443)
            and (a.hostname or "").removeprefix("www.") ==
            (b.hostname or "").removeprefix("www."))


def is_buyback(text: str) -> bool:
    t = normalized(text)
    return bool(re.search(r"\bbuy\s?back\b|\btrade in\b|\bsell to us\b|\bsell your\b|\bsell only\b", t)
                or t in {"sell", "selling price", "cash sell price"})


def match_title(title: str, url: str = "") -> str:
    """Return exact, possible, or reject. Only title/URL, never recommendations/body."""
    t = normalized(title)
    u = normalized(urlsplit(url).path)
    if is_buyback(t):
        return "reject"
    if re.search(r"\bnightreign\b|\btarnished edition\b|\bcollector(?: s)? edition\b|\bcollectors edition\b", t):
        return "reject"
    if re.search(r"\b(case|box|steelbook) only\b|\bempty (case|box)\b|\bno (game|disc)\b", t):
        return "reject"
    if re.search(r"\b(dlc|expansion|code|key) only\b|\b(account|steam|rental)\b|\bdigital (download|edition|game|key|code|version|delivery)\b|\bdigital$", t):
        return "reject"
    edition = bool(re.search(r"\bshadow (?:of )?(?:the )?erdtree\b|\bsote\b", t))
    if not edition:
        return "reject"
    ps5 = bool(re.search(r"\bps\s?5\b|\bplaystation\s?5\b", t))
    other = bool(re.search(r"\bps\s?4\b|\bplaystation\s?4\b|\bxbox\b|\bswitch\b|\bpc\b", t))
    if other and not ps5:
        return "reject"
    if other and ps5:
        return "possible"  # Platform or bundle ambiguity must be inspected.
    if ps5:
        return "exact"
    if re.search(r"\bps\s?5\b|\bplaystation\s?5\b", u):
        return "exact"
    return "possible"


def condition(text: str) -> str:
    t = normalized(text)
    if re.search(r"\bpre owned\b|\bpreowned\b|\bused\b|\bsecond hand\b", t):
        return "Used (seller label)"
    if re.search(r"\bnew\b|\bsealed\b", t):
        return "New (seller label)"
    return "Not stated"


def dlc_status(text: str) -> str:
    t = normalized(text)
    if re.search(r"\b(without|no|excludes?) (the )?(dlc|expansion|download|voucher)\b|\bcode not included\b", t):
        return "Not included (seller statement)"
    if re.search(r"\b(code|dlc|voucher).{0,25}\b(already )?(used|redeemed)\b", t):
        return "Redeemed/used (seller statement)"
    if re.search(r"\b(unused|unredeemed).{0,25}\b(code|voucher|dlc)\b", t):
        return "Claimed unused; region/expiry unverified"
    return "Unknown; verify code, region and expiry"


@dataclass
class Listing:
    source: str
    title: str
    url: str
    status: str = "unknown"  # in_stock, out_of_stock, backorder, unknown
    match: str = "exact"
    variant: str = ""
    price: str = "Not verified"
    currency: str = "INR"
    condition: str = "Not stated"
    dlc: str = "Unknown; verify code, region and expiry"
    evidence: str = "No reliable availability signal"

    @property
    def key(self) -> str:
        return sha256((self.source + "|" + canonical_url(self.url)).encode()).hexdigest()[:24]

    def as_dict(self) -> dict:
        return asdict(self)

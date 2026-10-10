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


SUPPORTED_TARGETS = {"sote", "pragmata", "onimusha", "acecombat8"}


def target_name(target: str = "sote") -> str:
    return {"sote": "SOTE", "pragmata": "Pragmata",
            "onimusha": "Onimusha: Way of the Sword",
            "acecombat8": "Ace Combat 8: Wings of Theve"}.get(target, "SOTE")


def match_product(title: str, url: str = "", target: str = "sote") -> str:
    """Classify a primary product title. Discovery never establishes availability."""
    if target == "sote":
        return match_title(title, url)
    if target == "acecombat8":
        return match_acecombat8(title, url)
    if target == "onimusha":
        return match_onimusha(title, url)
    if target != "pragmata":
        return "reject"
    t = normalized(title)
    u = normalized(urlsplit(url).path)
    if not re.search(r"\bpragmata\b", t) or is_buyback(t):
        return "reject"
    if re.search(r"\b(?:digital|account|rental|rent|steam|key|code|voucher|dlc|upgrade|bonus|demo|soundtrack|artbook|poster|statue|figure|amiibo)\b", t):
        return "reject"
    if re.search(r"\b(?:case|box|steelbook) only\b|\bempty (?:case|box)\b|\bno (?:game|disc)\b|\bdisc not included\b|\bwtb\b|\bwanted\b|\blooking to buy\b", t):
        return "reject"
    ps5 = bool(re.search(r"\bps\s?5\b|\bplaystation\s?5\b", t))
    other = bool(re.search(r"\bps\s?4\b|\bplaystation\s?4\b|\bxbox\b|\bswitch\b|\bpc\b", t))
    if other:
        return "possible" if ps5 else "reject"
    if ps5 or re.search(r"\bps\s?5\b|\bplaystation\s?5\b", u):
        return "exact"
    return "possible"


def discovery_hint(text: str, target: str = "sote") -> bool:
    t = normalized(text)
    if target == "acecombat8":
        return bool(re.search(r"\bace\s*combat\s*(?:8|viii)\b|\bwings (?:of )?(?:the )?theve\b", t))
    if target == "onimusha":
        return bool(re.search(r"\bonimusha\b|\bway (?:of )?(?:the )?sword\b", t))
    if target == "pragmata":
        return bool(re.search(r"\bpragmata\b", t))
    return bool(re.search(r"shadow (?:of )?(?:the )?erdtree|\bsote\b", t))



def match_onimusha(title: str, url: str = "") -> str:
    """Identify Way of the Sword, not merely a game in the Onimusha series.

    A primary title is mandatory. A descriptive URL can supply a missing
    subtitle/platform, but cannot overrule an explicitly wrong game or platform.
    Generic 'Onimusha PS5' is possible, not a confirmed exact-edition match.
    """
    t = normalized(title)
    u = normalized(urlsplit(url).path)
    if not re.search(r"\bonimusha\b", t) or is_buyback(t):
        return "reject"
    if re.search(r"\bwarlords\b|\bsamurai(?: s)? destiny\b|\bdemon siege\b|"
                 r"\bdawn of dreams\b|\bblade warriors\b|\btactics\b|"
                 r"\bonimusha\s+(?:[1234]|ii|iii|iv)\b", t):
        return "reject"
    if re.search(r"\b(?:digital|account|rental|rent|steam|key|code|voucher|dlc|upgrade|"
                 r"bonus|demo|soundtrack|artbook|poster|statue|figure|amiibo|"
                 r"deposit|reservation|booking|walkthrough|guide)\b", t):
        return "reject"
    if re.search(r"\b(?:case|box|steel\s?book) only\b|\bempty (?:case|box|steel\s?book)\b|"
                 r"\bno (?:game|disc)\b|\b(?:game\s+)?disc (?:is )?not included\b|"
                 r"\bwithout (?:a |the )?(?:game|disc)\b|\bwtb\b|\bwanted\b|\blooking to buy\b", t):
        return "reject"
    ps5 = bool(re.search(r"\bps\s?5\b|\bplaystation\s?5\b", t))
    other = bool(re.search(r"\bps\s?[1234]\b|\bplaystation\s?[1234]\b|\bxbox\b|\bswitch\b|\bpc\b", t))
    if other:
        return "possible" if ps5 else "reject"
    subtitle = bool(re.search(r"\bway (?:of )?(?:the )?sword\b|\bwots\b", t))
    # An exact, same-site product slug may disambiguate an abbreviated title.
    if not subtitle:
        subtitle = bool(re.search(r"\bonimusha\b", u) and
                        re.search(r"\bway (?:of )?(?:the )?sword\b", u))
    if not subtitle:
        return "possible"
    if ps5 or re.search(r"\bps\s?5\b|\bplaystation\s?5\b", u):
        return "exact"
    return "possible"



def match_acecombat8(title: str, url: str = "") -> str:
    """Match a primary PS5 game title, not a themed controller or an older game.

    Recognised compact spellings are normalised for matching. URL evidence can
    fill a missing platform/subtitle, but cannot rescue a wrong primary title.
    A mixed-platform offer stays possible and is not alerted by default.
    """
    t = normalized(title)
    u = normalized(urlsplit(url).path)
    t = re.sub(r"\bace\s*combat\s*(\d+|viii)\b", r"ace combat \1", t)
    u = re.sub(r"\bace\s*combat\s*(\d+|viii)\b", r"ace combat \1", u)
    numbered = bool(re.search(r"\bace combat (?:8|viii)\b", t))
    subtitle = bool(re.search(r"\bwings (?:of )?(?:the )?theve\b", t))
    if not (numbered or subtitle) or is_buyback(t):
        return "reject"
    # Old titles must not be rescued by an AC8 slug or compatibility wording.
    if re.search(r"\bace combat (?:[0-7]|9|[1-9]\d+|zero|assault horizon|infinity)\b|\bskies unknown\b", t):
        return "reject"
    # Bare subtitle listings need AC8 in their actual product URL to be exact.
    identified = numbered or bool(subtitle and re.search(r"\bace combat (?:8|viii)\b", u))
    # These are not physical-game offers. A disc plus an optional digital bonus
    # may need manual review; prioritise avoiding code/account false positives.
    if re.search(r"\b(?:digital|account|rental|rent|steam|key|keys|code|codes|voucher|dlc|upgrade|"
                 r"bonus|demo|soundtrack|artbook|poster|statue|figure|amiibo|deposit|reservation|"
                 r"booking|walkthrough|guide|wtb|wanted)\b|\blooking to buy\b", t):
        return "reject"
    if re.search(r"\b(?:case|box|steel\s?book) only\b|\bempty (?:case|box|steel\s?book)\b|"
                 r"\bno (?:game|disc)\b|\b(?:game\s+)?disc (?:is )?not included\b|"
                 r"\bwithout (?:a |the )?(?:game|disc)\b", t):
        return "reject"
    # A shop's game title may say '(compatible with Thrustmaster...)'. That
    # trailing note is not the product identity. A hardware-first title is.
    product_identity = re.split(r"\bcompatible with\b", t, maxsplit=1)[0]
    if re.search(r"\b(?:thrustmaster|hotas|joystick|flightstick|controller|headset|console)\b|"
                 r"\bt flight\b|\bflight stick\b", product_identity):
        return "reject"
    ps5 = bool(re.search(r"\bps\s?5\b|\bplaystation\s?5\b", t))
    other = bool(re.search(r"\bps\s?[1234]\b|\bplaystation\s?[1234]\b|\bxbox\b|\bswitch\b|\bpc\b", t))
    if other:
        return "possible" if ps5 else "reject"
    if not identified:
        return "possible"
    if ps5 or re.search(r"\bps\s?5\b|\bplaystation\s?5\b", u):
        return "exact"
    return "possible"

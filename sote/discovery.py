"""Sitemap ordering is a search hint, never evidence of product availability."""
from __future__ import annotations

import re
from urllib.parse import urlsplit

from .model import normalized, same_site


def sitemap_priority(url: str) -> int:
    """Prefer game/product maps over taxonomy and unrelated electronics maps.

    Deliberately inspect the path, not the store hostname (which often contains
    'games'). No maps or product URLs are manufactured by this ranking.
    """
    path = normalized(urlsplit(url).path)
    if re.search(r"\b(?:category|categories|cat|brand|brands|tag|tags|taxonomy|author|post|page|blog)\b", path):
        return 5
    if re.search(r"\b(?:camera|cameras|lens|lenses|laptop|laptops|phone|phones|smartphone|smartphones|watch|watches|controller|controllers|console|consoles|accessory|accessories|gpu|graphics)\b", path):
        return 4
    if re.search(r"\b(?:ps\s?5|playstation\s?5)\b", path):
        return 0
    if re.search(r"\b(?:game|games|gaming|playstation|ps\s?4|xbox|nintendo|switch|disc|discs|software)\b", path):
        return 1
    if re.search(r"\bproducts?\d*\b", path):
        return 2
    return 3


def ordered_child_maps(children: list[str], base: str, attempted_at: dict) -> list[str]:
    """Least-recently-attempted ordering within each relevance tier.

    Prioritizing by relevance can defer lower tiers indefinitely; the report
    therefore continues to call discovery a sample, never exhaustive coverage.
    """
    unique = list(dict.fromkeys(u for u in children if same_site(u, base)))
    def key(url: str):
        try:
            when = float(attempted_at.get(url, 0))
        except (ValueError, TypeError):
            when = 0
        return sitemap_priority(url), when, url
    return sorted(unique, key=key)

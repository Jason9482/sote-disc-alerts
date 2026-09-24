from __future__ import annotations

from datetime import datetime, timezone
import os
import re
import time
from urllib.parse import urlsplit
import requests

from .model import Listing


class NotificationError(RuntimeError):
    pass


def safe_text(value: object, limit: int = 1000) -> str:
    # Prevent source content from creating mention/link formatting. Mentions are also disabled below.
    text = str(value).replace("@", "@\u200b")
    return re.sub(r"([\\`*_{}\[\]()<>|~])", r"\\\1", text)[:limit]


def webhook_valid(url: str) -> bool:
    p = urlsplit(url)
    return bool(p.scheme == "https" and p.hostname in {"discord.com", "discordapp.com"}
                and not p.username and not p.password and p.port in (None, 443)
                and re.fullmatch(r"/api/(?:v\d+/)?webhooks/\d+/[A-Za-z0-9_.-]+", p.path)
                and not p.query and not p.fragment)


class Discord:
    def __init__(self, url: str | None = None):
        self.url = (url if url is not None else os.getenv("DISCORD_WEBHOOK_URL", "")).strip()
        if not webhook_valid(self.url):
            raise NotificationError("DISCORD_WEBHOOK_URL is missing/invalid. Set it as a GitHub Actions secret.")
        self.session = requests.Session()

    def send(self, title: str, description: str = "", fields: list[dict] | None = None,
             link: str | None = None) -> str:
        embed = {"title": safe_text(title, 240), "description": description[:3900],
                 "timestamp": datetime.now(timezone.utc).isoformat(),
                 "footer": {"text": "SOTE Watcher | A lead, not a seller endorsement"}}
        if fields:
            embed["fields"] = fields[:20]
        if link and link.startswith("https://"):
            embed["url"] = link
        payload = {"username": "SOTE Watcher", "allowed_mentions": {"parse": []}, "embeds": [embed]}
        # wait=true gives delivery acknowledgement; mark alerts sent only after success.
        for attempt in range(3):
            try:
                r = self.session.post(self.url, params={"wait": "true"}, json=payload,
                                      timeout=20, allow_redirects=False)
            except requests.RequestException:
                # A timeout could be after delivery. Retry next scan; duplicate delivery is possible.
                raise NotificationError("Discord delivery could not be confirmed; will retry on a later scan") from None
            if r.status_code == 429 and attempt < 2:
                try:
                    delay = float(r.json().get("retry_after", 2))
                except (ValueError, TypeError):
                    delay = 2
                if delay > 30:
                    raise NotificationError("Discord rate limit is long; delivery deferred")
                time.sleep(max(1, delay))
                continue
            if r.status_code != 200:
                raise NotificationError(f"Discord returned HTTP {r.status_code}; webhook/token not logged")
            try:
                ident = str(r.json()["id"])
            except (ValueError, KeyError, TypeError):
                raise NotificationError("Discord returned no message confirmation") from None
            return ident
        raise NotificationError("Discord rate limited this message")

    def message_link(self, message_id: str) -> str | None:
        """Read our private Discord message; avoids storing Reddit IDs/links in a public repo."""
        if not str(message_id).isdigit():
            raise NotificationError("Invalid stored Discord message ID")
        try:
            r = self.session.get(self.url + "/messages/" + str(message_id), timeout=20,
                                 allow_redirects=False)
        except requests.RequestException:
            raise NotificationError("Could not recheck an existing Reddit alert") from None
        if r.status_code == 404:
            return None
        if r.status_code != 200:
            raise NotificationError(f"Discord message lookup returned HTTP {r.status_code}")
        try:
            return r.json().get("embeds", [{}])[0].get("url")
        except (ValueError, TypeError, IndexError):
            raise NotificationError("Stored Discord alert format changed") from None

    def delete(self, message_id: str) -> None:
        if not str(message_id).isdigit():
            return
        try:
            r = self.session.delete(self.url + "/messages/" + str(message_id), timeout=20,
                                    allow_redirects=False)
        except requests.RequestException:
            raise NotificationError("Could not remove an expired Reddit alert") from None
        if r.status_code not in {204, 404}:
            raise NotificationError(f"Discord message deletion returned HTTP {r.status_code}")

    def listing(self, item: Listing, kind: str) -> str:
        fields = [
            {"name": "Store / condition", "value": safe_text(f"{item.source} | {item.condition}"), "inline": False},
            {"name": "Listed price", "value": safe_text(f"{item.currency} {item.price}"), "inline": True},
            {"name": "Site availability", "value": safe_text(item.status.replace("_", " ")), "inline": True},
            {"name": "Selected variant", "value": safe_text(item.variant or "Not separately stated"), "inline": False},
            {"name": "DLC voucher", "value": safe_text(item.dlc), "inline": False},
            {"name": "Evidence", "value": safe_text(item.evidence), "inline": False},
            {"name": "Before paying", "value": "Delivery/PIN, original SOTE case, seller and payment protection are NOT verified. Open the listing and check them.", "inline": False},
        ]
        return self.send(f"{kind}: PS5 Shadow of the Erdtree", safe_text(item.title), fields, item.url)

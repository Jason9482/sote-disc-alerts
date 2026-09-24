from __future__ import annotations

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import gzip
import io
import re
import time
from urllib.parse import urljoin, urlsplit, unquote
from urllib.robotparser import RobotFileParser
import requests

from .model import same_site


class FetchError(RuntimeError):
    """Safe-to-log fetch error; never contains an authentication token."""
    def __init__(self, message: str, *, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


def retry_seconds(value: str | None, default: int = 3600) -> int:
    try:
        if value and value.strip().isdigit():
            return min(7 * 86400, max(60, int(value)))
        if value:
            target = parsedate_to_datetime(value)
            if target.tzinfo is None:
                target = target.replace(tzinfo=timezone.utc)
            return min(7 * 86400, max(60, int((target - datetime.now(timezone.utc)).total_seconds())))
    except (ValueError, TypeError, OverflowError):
        pass
    return default


def robots_allowed(lines: list[str], agent: str, url: str) -> bool:
    """Honor common robots wildcard/end-anchor rules that stdlib's parser misses."""
    groups = []
    agents, rules = [], []
    had_directive = False
    for raw in lines + ["User-agent: __end__"]:
        line = raw.split("#", 1)[0].strip()
        if ":" not in line:
            continue
        key, value = [x.strip() for x in line.split(":", 1)]
        key = key.lower()
        if key == "user-agent":
            if had_directive and agents:
                groups.append((agents, rules))
                agents, rules, had_directive = [], [], False
            agents.append(value.lower())
        elif agents:
            had_directive = True
            if key in {"allow", "disallow"} and value:
                rules.append((key, value))
    matches = []
    for names, rs in groups:
        specific = [len(n) for n in names if n != "*" and n in agent.lower()]
        score = max(specific) if specific else (0 if "*" in names else -1)
        if score >= 0:
            matches.append((score, rs))
    if not matches:
        return True
    best_group = max(score for score, _ in matches)
    p = urlsplit(url)
    target = unquote(p.path or "/") + ("?" + unquote(p.query) if p.query else "")
    applicable = []
    for score, rs in matches:
        if score != best_group:
            continue
        for key, raw in rs:
            raw = unquote(raw)
            anchored = raw.endswith("$")
            pattern = raw[:-1] if anchored else raw
            regex = "^" + re.escape(pattern).replace(r"\*", ".*") + ("$" if anchored else "")
            if re.search(regex, target):
                applicable.append((len(pattern.replace("*", "")), key == "allow"))
    return max(applicable)[1] if applicable else True


class RobotsRules(RobotFileParser):
    def parse(self, lines):
        self.raw_lines = list(lines)
        super().parse(self.raw_lines)

    def can_fetch(self, useragent, url):
        return robots_allowed(self.raw_lines, useragent, url)


class StoreClient:
    """One client per store. No login, CAPTCHA bypass, proxy rotation or cart writes."""
    def __init__(self, source: dict, state: dict, config: dict):
        self.source = source
        self.base = source["base"]
        self.state = state
        self.config = config
        self.agent = "SOTEStockWatcher"
        repo = config.get("repository_url", "personal-stock-monitor")
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": f"{self.agent}/1.0 (+{repo})",
                                     "Accept": "text/html,application/json,application/xml;q=0.9,*/*;q=0.5"})
        self.robots = None
        self.last_request = 0.0
        self.delay = float(config.get("request_delay_seconds", 2))
        self.calls = 0
        self.cache: dict[str, str] = {}
        self.max_calls = int(config.get("max_requests_per_store", 14))

    def _request(self, url: str, *, robots_request: bool = False) -> requests.Response:
        if not same_site(url, self.base):
            raise FetchError("Off-site or non-HTTPS request rejected")
        if float(self.state.get("cooldown_until", 0)) > time.time():
            raise FetchError("Store is in a temporary backoff window")
        if self.calls >= self.max_calls:
            raise FetchError("Per-store request budget reached; coverage is partial")
        delay = self.delay - (time.monotonic() - self.last_request)
        if delay > 0:
            time.sleep(delay)
        self.calls += 1
        try:
            response = self.session.get(url, timeout=(8, 15), allow_redirects=False, stream=True)
            self.last_request = time.monotonic()
        except requests.exceptions.SSLError:
            raise FetchError("TLS certificate/handshake failed; verification was NOT disabled") from None
        except requests.exceptions.Timeout:
            raise FetchError("Connection or read timed out; not a stock result") from None
        except requests.exceptions.ConnectionError as exc:
            # Inspect, but do not print, the exception: raw messages may contain URLs.
            detail = str(exc).lower()
            dns = any(x in detail for x in ("name resolution", "failed to resolve", "getaddrinfo", "nameresolutionerror"))
            raise FetchError("DNS resolution failed; not a stock result" if dns else
                             "Network connection failed; not a stock result") from None
        except requests.RequestException:
            raise FetchError("HTTP request failed; not a stock result") from None
        if response.status_code in {301, 302, 303, 307, 308}:
            target = urljoin(url, response.headers.get("Location", ""))
            response.close()
            if not same_site(target, self.base):
                raise FetchError("Store redirected outside its configured domain")
            # Check the destination against robots before following a normal-page redirect.
            if not robots_request and self.robots and not self.robots.can_fetch(self.agent, target):
                raise FetchError("Redirect destination is disallowed by robots.txt")
            return self._request(target, robots_request=robots_request)
        if response.status_code in {403, 429, 503}:
            seconds = retry_seconds(response.headers.get("Retry-After"), 6 * 3600)
            self.state["cooldown_until"] = time.time() + seconds
        return response

    @staticmethod
    def _read(response: requests.Response, max_bytes: int = 4_000_000, *, allow_gzip: bool = False) -> str:
        pieces, size = [], 0
        try:
            for chunk in response.iter_content(65536):
                size += len(chunk)
                if size > max_bytes:
                    raise FetchError(f"Response exceeds {max_bytes:,}-byte safety limit; check skipped")
                pieces.append(chunk)
        except requests.RequestException:
            raise FetchError("Response download failed") from None
        finally:
            response.close()
        encoding = response.encoding
        if not encoding or encoding.lower() == "iso-8859-1":
            encoding = "utf-8"
        data = b"".join(pieces)
        # Requests decodes HTTP Content-Encoding gzip itself. A .xml.gz document
        # without that header is still compressed; decode it once, with a hard cap.
        if allow_gzip and data.startswith(b"\x1f\x8b"):
            try:
                with gzip.GzipFile(fileobj=io.BytesIO(data)) as stream:
                    data = stream.read(max_bytes + 1)
            except (OSError, EOFError):
                raise FetchError("Invalid/truncated compressed sitemap; check skipped") from None
            if len(data) > max_bytes:
                raise FetchError("Decompressed sitemap exceeds safety limit; check skipped")
        return data.decode(encoding, errors="replace")

    def load_robots(self) -> None:
        if self.robots is not None:
            return
        url = self.base.rstrip("/") + "/robots.txt"
        response = self._request(url, robots_request=True)
        robot = RobotsRules(url)
        if response.status_code == 404:
            response.close()
            robot.parse(["User-agent: *", "Allow: /"])
        elif response.status_code == 200:
            text = self._read(response, 256_000)
            if "<html" in text[:500].lower():
                raise FetchError("robots.txt returned HTML; automated check deferred")
            robot.parse(text.splitlines())
        else:
            status = response.status_code
            response.close()
            raise FetchError(f"robots.txt not accessible (HTTP {status}); check deferred", status_code=status)
        delay = robot.crawl_delay(self.agent) or robot.crawl_delay("*") or 0
        rate = robot.request_rate(self.agent) or robot.request_rate("*")
        if rate and rate.requests:
            delay = max(delay, rate.seconds / rate.requests)
        if delay > 30:
            self.state["cooldown_until"] = time.time() + 86400
            raise FetchError("Site requests a long crawl interval; automatic check deferred")
        self.delay = max(self.delay, delay)
        self.robots = robot

    def get_sitemap(self, url: str) -> str:
        """Permit protocol-sized sitemaps, but keep ordinary HTML capped at 4 MB."""
        return self.get(url, sitemap=True)

    def get(self, url: str, *, sitemap: bool = False) -> str:
        if url in self.cache:
            return self.cache[url]
        self.load_robots()
        assert self.robots is not None
        if not self.robots.can_fetch(self.agent, url):
            raise FetchError("Disallowed by this site's robots.txt")
        response = self._request(url)
        if response.status_code != 200:
            status = response.status_code
            response.close()
            raise FetchError(f"HTTP {status}; not a stock result", status_code=status)
        # The sitemap protocol permits up to 50 MiB. Both compressed and expanded
        # data remain bounded. No blanket increase for ordinary product pages.
        limit = 52_428_800 if sitemap else 4_000_000
        text = self._read(response, max_bytes=limit, allow_gzip=sitemap)
        first = text[:15000].lower()
        if ("<title>just a moment" in first or "<title>access denied" in first or
                "verify you are human" in first or "cf-chl-" in first):
            self.state["cooldown_until"] = time.time() + 6 * 3600
            raise FetchError("Anti-bot/challenge page; no bypass attempted")
        self.cache[url] = text
        return text

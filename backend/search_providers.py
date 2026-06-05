"""Multi-provider web-search pool with automatic failover.

One `web_search(query)` entry point tries providers in priority order and returns
the first non-empty result set, so a single blocked/exhausted engine never stops
the app. Keyless providers (DuckDuckGo, Mojeek) work with zero config; add
TAVILY_API_KEY / BRAVE_SEARCH_API_KEY / Google CSE keys for higher quality + volume.

Every provider normalises to: {"title": str, "url": str, "snippet": str}.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

import httpx
from selectolax.parser import HTMLParser

from backend.config import settings

log = logging.getLogger(__name__)

_COOLDOWN_MINUTES = 10
_TIMEOUT = 12
_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

_cooldown: dict[str, datetime] = {}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _cool(name: str, minutes: int = _COOLDOWN_MINUTES) -> None:
    _cooldown[name] = _now() + timedelta(minutes=minutes)


def _ready(name: str) -> bool:
    return _cooldown.get(name, _now()) <= _now()


# ── Individual providers (each returns normalised dicts or raises) ─────────────

def _tavily(query: str, limit: int) -> list[dict]:
    r = httpx.post(
        "https://api.tavily.com/search",
        json={"api_key": settings.TAVILY_API_KEY, "query": query,
              "max_results": min(limit, 10), "search_depth": "basic"},
        timeout=_TIMEOUT,
    )
    if r.status_code in (429, 432, 403):
        _cool("tavily"); return []
    r.raise_for_status()
    return [{"title": x.get("title", ""), "url": x.get("url", ""),
             "snippet": x.get("content", "")} for x in r.json().get("results", [])]


def _brave(query: str, limit: int) -> list[dict]:
    r = httpx.get(
        "https://api.search.brave.com/res/v1/web/search",
        params={"q": query, "count": min(limit, 20)},
        headers={"X-Subscription-Token": settings.BRAVE_SEARCH_API_KEY,
                 "Accept": "application/json"},
        timeout=_TIMEOUT,
    )
    if r.status_code in (429, 403):
        _cool("brave"); return []
    r.raise_for_status()
    results = (r.json().get("web") or {}).get("results", []) or []
    return [{"title": x.get("title", ""), "url": x.get("url", ""),
             "snippet": x.get("description", "")} for x in results]


def _duckduckgo(query: str, limit: int) -> list[dict]:
    r = httpx.get(
        "https://html.duckduckgo.com/html/",
        params={"q": query},
        headers={"User-Agent": _BROWSER_UA, "Accept": "text/html"},
        timeout=_TIMEOUT, follow_redirects=True,
    )
    if r.status_code in (429, 403, 202):
        _cool("duckduckgo"); return []
    r.raise_for_status()
    tree = HTMLParser(r.text)
    out: list[dict] = []
    for res in tree.css(".result, .web-result"):
        a = res.css_first("a.result__a")
        if not a:
            continue
        href = a.attributes.get("href", "")
        # Skip DDG ad/redirect units (duckduckgo.com/y.js?ad_domain=...)
        if "duckduckgo.com/y.js" in href or "ad_domain=" in href:
            continue
        # DDG wraps organic links: //duckduckgo.com/l/?uddg=<encoded>
        if "uddg=" in href:
            qs = parse_qs(urlparse(href).query)
            href = (qs.get("uddg") or [href])[0]
        snip = res.css_first(".result__snippet")
        out.append({"title": a.text(strip=True), "url": href,
                    "snippet": snip.text(strip=True) if snip else ""})
        if len(out) >= limit:
            break
    return out


def _mojeek(query: str, limit: int) -> list[dict]:
    r = httpx.get(
        "https://www.mojeek.com/search",
        params={"q": query},
        headers={"User-Agent": _BROWSER_UA, "Accept": "text/html"},
        timeout=_TIMEOUT, follow_redirects=True,
    )
    if r.status_code in (429, 403):
        _cool("mojeek"); return []
    r.raise_for_status()
    tree = HTMLParser(r.text)
    out: list[dict] = []
    for li in tree.css(".results-standard li, ul.results-standard li, .results li"):
        a = li.css_first("a.title, h2 a, a")
        if not a:
            continue
        snip = li.css_first(".s, p")
        out.append({"title": a.text(strip=True), "url": a.attributes.get("href", ""),
                    "snippet": snip.text(strip=True) if snip else ""})
        if len(out) >= limit:
            break
    return out


def _google_cse(query: str, limit: int) -> list[dict]:
    r = httpx.get(
        "https://www.googleapis.com/customsearch/v1",
        params={"key": settings.GOOGLE_API_KEY, "cx": settings.GOOGLE_CSE_ID,
                "q": query, "num": min(limit, 10)},
        timeout=_TIMEOUT,
    )
    if r.status_code in (429, 403):
        _cool("google_cse", minutes=60); return []
    r.raise_for_status()
    return [{"title": x.get("title", ""), "url": x.get("link", ""),
             "snippet": x.get("snippet", "")} for x in r.json().get("items", [])]


# (name, fn, requires-key predicate) in priority order.
_PROVIDERS = [
    ("tavily", _tavily, lambda: bool(settings.TAVILY_API_KEY)),
    ("brave", _brave, lambda: bool(settings.BRAVE_SEARCH_API_KEY)),
    ("duckduckgo", _duckduckgo, lambda: True),
    ("mojeek", _mojeek, lambda: True),
    ("google_cse", _google_cse, lambda: bool(settings.GOOGLE_API_KEY and settings.GOOGLE_CSE_ID)),
]


def web_search(query: str, limit: int = 10) -> list[dict]:
    """Return the first non-empty result set from the provider chain."""
    last_err: Exception | None = None
    for name, fn, has_key in _PROVIDERS:
        if not has_key() or not _ready(name):
            continue
        try:
            results = fn(query, limit)
            if results:
                log.debug(f"[search_pool] '{query[:40]}' served by {name} ({len(results)})")
                return results
        except Exception as e:
            last_err = e
            log.warning(f"[search_pool] {name} failed for {query!r}: {e}")
            continue
    if last_err:
        log.warning(f"[search_pool] all providers empty/failed for {query!r}")
    return []


def search_status() -> dict:
    return {
        "providers": [n for n, _, k in _PROVIDERS if k()],
        "available": [n for n, _, k in _PROVIDERS if k() and _ready(n)],
    }

from __future__ import annotations

import logging
import re
import time

import httpx
from selectolax.parser import HTMLParser

log = logging.getLogger(__name__)
NAME = "bing"  # name kept for backward DB compat; engine is Mojeek

_MOJEEK = "https://www.mojeek.com/search"
_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15"


def _mojeek_search(query: str, limit: int = 10) -> list[dict]:
    """Mojeek doesn't bot-block and returns server-rendered HTML."""
    try:
        r = httpx.get(
            _MOJEEK,
            params={"q": query},
            headers={"User-Agent": _UA, "Accept": "text/html"},
            timeout=12,
            follow_redirects=True,
        )
        if r.status_code != 200:
            return []
        tree = HTMLParser(r.text)
        results: list[dict] = []
        for li in tree.css(".results-standard li"):
            a = li.css_first("a.title, h2 a, a")
            snip = li.css_first(".s, p")
            url_el = li.css_first(".ob a")
            if not a:
                continue
            href = a.attributes.get("href", "")
            title = a.text(strip=True)
            description = snip.text(strip=True) if snip else ""
            results.append({"title": title, "url": href, "snippet": description})
            if len(results) >= limit:
                break
        return results
    except Exception as e:
        log.warning(f"Mojeek search failed for {query!r}: {e}")
        return []


_BAD_NAME_WORDS = {
    "the", "how", "what", "why", "when", "best", "top", "guide", "tips",
    "compensation", "startup", "founders", "founder", "ceo", "cto",
    "fintech", "payments", "build", "building", "becoming", "remote",
}


def _looks_like_person(title: str, snippet: str) -> tuple[str | None, str | None]:
    """Conservatively extract a person name + title from a search result.

    Mojeek mostly returns articles/blogs, not personal sites. We only flag a
    result as 'a person' if the title starts with a clean 2-3 word name followed
    by ' - Title at Company' — and even then, reject obvious article phrases.
    """
    # Strict pattern: must be Firstname Lastname [- or |] Title
    m = re.match(r"^([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,2})\s*[-–|]\s*(.{5,80})", title)
    if not m:
        return None, None
    name = m.group(1).strip()
    role_text = m.group(2).strip()
    # Reject when any word looks like article noise
    words_lower = {w.lower() for w in name.split()}
    if words_lower & _BAD_NAME_WORDS:
        return None, None
    # Reject obviously generic role text (article titles)
    if any(noise in role_text.lower() for noise in ("how to", "what is", "guide", "best ", "top ")):
        return None, None
    return name, role_text[:80]


def _domain_of(url: str) -> str | None:
    try:
        from urllib.parse import urlparse
        host = urlparse(url).netloc
        return host[4:] if host.startswith("www.") else host or None
    except Exception:
        return None


def fetch(icp_params: dict, limit: int = 50) -> list[dict]:
    """Search the open web (via Mojeek) for content matching the ICP.

    Returns leads built from search results — people mentioned in blog posts,
    company about pages, podcast interviews, etc. Skips obvious junk
    (course/tutorial pages, generic articles).
    """
    # Build queries from the ICP — prefer role + industry combos
    roles = (icp_params.get("target_roles") or [])[:2]
    industries = (icp_params.get("target_industries") or [])[:2]
    intent_keywords = (icp_params.get("buyer_intent_keywords") or [])[:3]
    exclude = " ".join(f"-{w}" for w in (icp_params.get("exclude_keywords") or [])[:4])

    queries: list[str] = []
    # Intent-driven queries get priority — they target the actual buyer signal
    for intent in intent_keywords:
        for industry in industries:
            queries.append(f'"{intent}" "{industry}" {exclude}'.strip())
    # Role × industry as fallback
    for role in roles:
        for industry in industries:
            queries.append(f'"{role}" "{industry}" {exclude}'.strip())
    # Last-ditch fallback
    if not queries:
        for industry in industries:
            queries.append(f'{industry} startup founder')

    leads: list[dict] = []
    seen_urls: set[str] = set()

    for query in queries[:3]:
        results = _mojeek_search(query, limit=10)
        for r in results:
            url = r.get("url", "")
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)

            # Skip pages we know are noise
            domain = _domain_of(url) or ""
            if any(b in domain for b in ("youtube.com", "wikipedia.org", "reddit.com", "twitter.com")):
                continue

            title = r.get("title", "")
            snippet = r.get("snippet", "")
            name, role_text = _looks_like_person(title, snippet)

            # Only keep results that look like they're about a real person
            if not name:
                continue

            leads.append({
                "external_id": f"bing_{url[:80]}",
                "person_name": name,
                "person_title": role_text,
                "company_name": None,  # the LLM scorer will decide if this is useful
                "company_domain": domain or None,
                "source": NAME,
                "source_url": url,
                "source_profile_url": url,
                "source_snippet": f"Web search: {query}\n\n{title}\n{snippet[:500]}",
                "raw_data": {
                    "context": snippet[:500],
                    "search_url": url,
                    "search_query": query,
                },
                "intent_signals": ["mentioned_in_web_search"],
            })
            if len(leads) >= limit:
                return leads[:limit]

        time.sleep(1)  # gentle on Mojeek

    return leads[:limit]

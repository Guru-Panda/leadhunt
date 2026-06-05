"""LinkedIn profile discovery via Google CSE (primary) or Mojeek (fallback).

We never touch linkedin.com directly — we only read search-engine result pages
that have already indexed public profiles.

Query strategy (ICP-driven, not random):
  site:linkedin.com/in "Head of Marketing" "B2B SaaS"
  site:linkedin.com/in "Founder" "fintech"
  site:linkedin.com/in "looking for outreach tool"   ← buyer phrase on their profile
"""
from __future__ import annotations

import logging
import re
import time
from urllib.parse import urlparse

import httpx
from selectolax.parser import HTMLParser

from backend.config import settings

log = logging.getLogger(__name__)
NAME = "linkedin"

_MOJEEK = "https://www.mojeek.com/search"
_GOOGLE_CSE = "https://www.googleapis.com/customsearch/v1"
_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15"
)


# ── helpers ──────────────────────────────────────────────────────────────────

def _google_cse_search(query: str, limit: int = 10) -> list[dict]:
    """Search using Google Custom Search Engine. Returns same format as _mojeek_search."""
    if not (settings.GOOGLE_API_KEY and settings.GOOGLE_CSE_ID):
        return []
    try:
        r = httpx.get(
            _GOOGLE_CSE,
            params={
                "key": settings.GOOGLE_API_KEY,
                "cx": settings.GOOGLE_CSE_ID,
                "q": query,
                "num": min(limit, 10),
            },
            timeout=10,
        )
        if r.status_code == 429:
            log.warning("[linkedin] Google CSE quota exhausted")
            return []
        if r.status_code == 403:
            log.error("[linkedin] Google CSE 403 Forbidden — enable the Custom Search API "
                      "and remove key restrictions in Google Cloud Console.")
            return []
        r.raise_for_status()
        out = []
        for item in r.json().get("items", []):
            out.append({
                "title": item.get("title", ""),
                "url": item.get("link", ""),
                "snippet": item.get("snippet", ""),
            })
        return out
    except Exception as e:
        log.warning(f"[linkedin] Google CSE search failed for {query!r}: {e}")
        return []


def _mojeek_search(query: str, limit: int = 10) -> list[dict]:
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
        out: list[dict] = []
        for li in tree.css(".results-standard li, ul.results-standard li, .results li"):
            a = li.css_first("a.title, h2 a, a")
            snip = li.css_first(".s, p")
            if not a:
                continue
            out.append({
                "title": a.text(strip=True),
                "url": a.attributes.get("href", ""),
                "snippet": snip.text(strip=True) if snip else "",
            })
            if len(out) >= limit:
                break
        return out
    except Exception as e:
        log.warning(f"Mojeek search failed for {query!r}: {e}")
        return []


def _is_linkedin_profile(url: str) -> bool:
    """True only for personal /in/ profiles, not company pages or job posts."""
    if not url:
        return False
    try:
        p = urlparse(url)
        return "linkedin.com" in p.netloc and p.path.startswith("/in/")
    except Exception:
        return False


def _slug_to_name(slug: str) -> str:
    """Convert a LinkedIn URL slug to a readable name.

    '/in/john-doe-123abc' → 'John Doe'
    '/in/jane-smith-mba' → 'Jane Smith'
    """
    # Remove /in/ prefix
    name_part = re.sub(r"^/?in/?", "", slug.lstrip("/"))
    # Strip trailing numeric/alphanumeric IDs (e.g. -a3b4c5)
    name_part = re.sub(r"-[a-z0-9]{4,}$", "", name_part)
    # Title-case alpha segments only
    words = [w.capitalize() for w in name_part.split("-") if re.match(r"^[a-z]+$", w, re.IGNORECASE)]
    return " ".join(words)


def _parse_result(result_title: str) -> tuple[str | None, str | None]:
    """Parse role and company from a LinkedIn search result title.

    'Jane Smith - VP of Sales at Acme Corp | LinkedIn' → ('VP of Sales', 'Acme Corp')
    'John Doe - Founder | LinkedIn'                   → ('Founder', None)
    """
    # Strip ' | LinkedIn' and similar suffixes
    clean = re.sub(r"\s*[\|•]\s*(LinkedIn.*)?$", "", result_title, flags=re.IGNORECASE).strip()
    if " - " in clean:
        _, role_part = clean.split(" - ", 1)
        if " at " in role_part:
            role, company = role_part.split(" at ", 1)
            return role.strip() or None, company.strip() or None
        return role_part.strip() or None, None
    return None, None


def _name_from_title(title: str) -> str | None:
    """Extract the person's real name from a search result title.

    'Jane Smith - VP of Sales at Acme | LinkedIn' → 'Jane Smith'
    More reliable than guessing from the URL slug (which is a vanity string).
    Returns None if the head doesn't look like a 2-4 word personal name.
    """
    clean = re.sub(r"\s*[\|•].*$", "", title or "").strip()
    head = clean.split(" - ", 1)[0].strip()
    words = head.split()
    if 2 <= len(words) <= 4 and all(re.match(r"^[A-Za-z.'’-]+$", w) for w in words):
        return head
    return None


def _build_queries(icp: dict) -> list[str]:
    """Build up to 6 site:linkedin.com/in queries from ICP fields.

    Priority order:
    1. role × industry combos  (most precise — finds the right people)
    2. buyer_phrase on profile  (people whose summary/headline mentions the need)
    3. keywords fallback
    """
    roles      = (icp.get("target_roles")      or [])[:4]
    industries = (icp.get("target_industries") or icp.get("industries") or [])[:3]
    phrases    = (icp.get("buyer_phrases")      or [])[:3]
    keywords   = (icp.get("keywords")           or [])[:2]

    queries: list[str] = []

    # Role × industry combinations
    for role in roles[:3]:
        if industries:
            for ind in industries[:2]:
                queries.append(f'site:linkedin.com/in "{role}" "{ind}"')
        else:
            queries.append(f'site:linkedin.com/in "{role}"')

    # Buyer phrases — people whose profiles show the buying signal
    for phrase in phrases[:2]:
        queries.append(f'site:linkedin.com/in "{phrase}"')

    # Keyword fallback
    for kw in keywords[:1]:
        queries.append(f'site:linkedin.com/in "{kw}"')

    # Deduplicate, cap at 6
    seen: set[str] = set()
    out: list[str] = []
    for q in queries:
        if q not in seen:
            seen.add(q)
            out.append(q)
    return out[:6]


# ── main entry point ──────────────────────────────────────────────────────────

def fetch(icp_params: dict, limit: int = 50) -> list[dict]:
    queries = _build_queries(icp_params)
    if not queries:
        log.debug("linkedin: no queries built from ICP — skipping")
        return []

    from backend.search_providers import web_search

    leads: list[dict] = []
    seen_urls: set[str] = set()

    for query in queries:
        results = web_search(query, limit=10)
        for r in results:
            url = (r.get("url") or "").strip()
            if not _is_linkedin_profile(url) or url in seen_urls:
                continue
            seen_urls.add(url)

            path = urlparse(url).path
            title = r.get("title", "")
            # Prefer the real displayed name from the result title; fall back to the
            # slug only as a last resort (slugs are vanity strings, often wrong).
            name = _name_from_title(title) or _slug_to_name(path)
            if not name or len(name.split()) < 2:
                continue

            role, company = _parse_result(title)
            snippet = r.get("snippet", "")
            slug = path.split("/in/")[-1].strip("/")

            # Only claim a role/industry match when we actually parsed one.
            signals = ["linkedin_icp_match"]
            if role or company:
                signals.append("profile_role_industry_match")

            leads.append({
                "external_id": f"li_{slug[:120]}",
                "person_name": name,
                "person_title": role,
                "company_name": company,
                "person_linkedin_url": url,
                "source": NAME,
                "source_url": url,
                "source_profile_url": url,
                "source_snippet": (
                    f"LinkedIn profile — {title or name}\n{snippet}"
                ),
                "raw_data": {
                    "linkedin_url": url,
                    "search_query": query,
                    "context": snippet,
                },
                "intent_signals": signals,
            })
            if len(leads) >= limit:
                return leads[:limit]

    return leads[:limit]

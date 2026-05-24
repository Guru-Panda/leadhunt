from __future__ import annotations

import logging
import re
import time
from urllib.parse import urlparse

import httpx
from selectolax.parser import HTMLParser

log = logging.getLogger(__name__)
NAME = "ycombinator"

_ALGOLIA_APP = "45BWZJ1SGC"
_ALGOLIA_URL = "https://45bwzj1sgc-dsn.algolia.net/1/indexes/YCCompany_production/query"
_DIRECTORY_URL = "https://www.ycombinator.com/companies"
_UA = "Mozilla/5.0 (Windows NT 10.0) AppleWebKit/537.36 LeadHunt/1.0"

# Algolia keys rotate. We extract the live one from the YC directory page on first
# use and cache it. Re-fetch on 403.
_algolia_key_cache: str | None = None


def _fetch_algolia_key() -> str | None:
    """Scrape the live Algolia API key from the YC companies page."""
    global _algolia_key_cache
    try:
        r = httpx.get(_DIRECTORY_URL, headers={"User-Agent": _UA}, timeout=10, follow_redirects=True)
        if r.status_code != 200:
            return None
        # Algolia search-only keys on YC are 250+ char base64-ish strings
        matches = re.findall(r'["\']([A-Za-z0-9+/=_-]{200,})["\']', r.text)
        if matches:
            _algolia_key_cache = matches[0]
            log.info(f"YC Algolia key cached ({len(_algolia_key_cache)} chars)")
            return _algolia_key_cache
    except Exception as e:
        log.warning(f"Failed to fetch YC Algolia key: {e}")
    return None


def _algolia_search(query: str, hits: int = 10) -> list[dict]:
    key = _algolia_key_cache or _fetch_algolia_key()
    if not key:
        return []
    payload = {
        "query": query,
        "hitsPerPage": hits,
        "attributesToRetrieve": ["name", "slug", "one_liner", "batch", "industries", "website"],
    }
    headers = {
        "x-algolia-application-id": _ALGOLIA_APP,
        "x-algolia-api-key": key,
        "Content-Type": "application/json",
    }
    try:
        r = httpx.post(_ALGOLIA_URL, json=payload, headers=headers, timeout=10)
        if r.status_code == 403:
            # key rotated — try once more with fresh
            log.info("YC Algolia 403 — refreshing key")
            globals()["_algolia_key_cache"] = None
            key = _fetch_algolia_key()
            if not key:
                return []
            headers["x-algolia-api-key"] = key
            r = httpx.post(_ALGOLIA_URL, json=payload, headers=headers, timeout=10)
        r.raise_for_status()
        return r.json().get("hits", [])
    except Exception as e:
        log.warning(f"YC Algolia search failed for {query!r}: {e}")
        return []


_NAME_SPLIT = re.compile(r"\s*(?:Founder|Co-Founder|Cofounder|CEO|CTO|CPO|COO|President|Engineer|Designer)\b", re.I)


def _extract_founder_name_from_context(text: str) -> str | None:
    """YC concatenates 'Hasan NawazFounder' with no space. Split on role keywords."""
    text = text.strip()
    if not text:
        return None
    parts = _NAME_SPLIT.split(text, maxsplit=1)
    name = parts[0].strip()
    # Sanity: real names are 2-50 chars, mostly word characters
    if 2 < len(name) < 60 and re.match(r"^[A-Z][\w\s.\-']{1,}$", name):
        return name
    return None


def _scrape_founders(slug: str) -> list[dict]:
    """Pull founder name + LinkedIn from a YC company page."""
    try:
        r = httpx.get(f"https://www.ycombinator.com/companies/{slug}",
                      headers={"User-Agent": _UA}, timeout=10, follow_redirects=True)
        if r.status_code != 200:
            return []
        tree = HTMLParser(r.text)
        seen: set[str] = set()
        founders: list[dict] = []
        for link in tree.css('a[href*="linkedin.com"]'):
            href = link.attributes.get("href", "")
            if not href or "linkedin.com/in" not in href:
                continue
            if href in seen:
                continue
            seen.add(href)
            # Walk up looking for context with a Founder/CEO-style title
            parent = link.parent
            name = None
            for _ in range(6):
                if parent is None:
                    break
                txt = parent.text(strip=True)
                if 15 < len(txt) < 300:
                    name = _extract_founder_name_from_context(txt)
                    if name:
                        break
                parent = parent.parent
            if not name:
                continue
            founders.append({
                "external_id": f"yc_{slug}_{name.lower().replace(' ', '_')}",
                "person_name": name,
                "person_title": "Founder",
                "person_linkedin_url": href.split("?")[0],
            })
        return founders
    except Exception as e:
        log.debug(f"YC founder scrape failed for {slug}: {e}")
        return []


def _extract_domain(url: str | None) -> str | None:
    if not url:
        return None
    try:
        host = urlparse(url).netloc
        if host.startswith("www."):
            host = host[4:]
        return host or None
    except Exception:
        return None


def fetch(icp_params: dict, limit: int = 50) -> list[dict]:
    industries = icp_params.get("industries", [])
    queries = industries[:3] if industries else [""]
    leads: list[dict] = []
    seen_companies: set[str] = set()

    # Cap companies scraped per query — each page is a separate HTTP round-trip
    companies_per_query = max(3, min(8, limit // max(len(queries), 1)))
    for query in queries:
        hits = _algolia_search(query, hits=companies_per_query)
        for hit in hits:
            slug = hit.get("slug", "")
            if not slug or slug in seen_companies:
                continue
            seen_companies.add(slug)

            company_name = hit.get("name", "")
            domain = _extract_domain(hit.get("website"))
            one_liner = hit.get("one_liner", "")
            batch = hit.get("batch", "")

            yc_page = f"https://www.ycombinator.com/companies/{slug}"
            snippet_base = f"YC {batch} — {company_name}\n\n{one_liner}"

            founders = _scrape_founders(slug)
            if not founders:
                # Even without founders, surface the company itself
                leads.append({
                    "external_id": f"yc_company_{slug}",
                    "person_name": company_name,
                    "person_title": f"YC {batch} company",
                    "company_name": company_name,
                    "company_domain": domain,
                    "source": NAME,
                    "source_url": yc_page,
                    "source_profile_url": yc_page,
                    "source_snippet": snippet_base,
                    "intent_signals": ["yc_company"],
                    "raw_data": {
                        "context": f"YC {batch} company: {one_liner}",
                        "yc_url": yc_page,
                        "industries": hit.get("industries", []),
                    },
                })
            else:
                for founder in founders:
                    founder.update({
                        "company_name": company_name,
                        "company_domain": domain,
                        "source": NAME,
                        "source_url": yc_page,
                        "source_profile_url": founder.get("person_linkedin_url") or yc_page,
                        "source_snippet": f"{snippet_base}\n\nFounder: {founder.get('person_name')}",
                        "intent_signals": ["yc_founder"],
                        "raw_data": {
                            "context": f"YC {batch} founder of {company_name}: {one_liner}",
                            "yc_url": yc_page,
                            "industries": hit.get("industries", []),
                        },
                    })
                    leads.append(founder)

            if len(leads) >= limit:
                return leads[:limit]

            time.sleep(0.3)  # gentle on YC

    return leads[:limit]

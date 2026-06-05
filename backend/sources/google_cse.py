from __future__ import annotations

import logging
import re
import time

import httpx

from backend.config import settings

log = logging.getLogger(__name__)
NAME = "google_cse"

_API_URL = "https://www.googleapis.com/customsearch/v1"


def fetch(icp_params: dict, limit: int = 50) -> list[dict]:
    if not settings.GOOGLE_CSE_ID or not settings.GOOGLE_API_KEY:
        log.warning("Google CSE credentials not set — skipping")
        return []

    # The LLM frequently omits google_search_patterns — fall back to building
    # LinkedIn-profile queries from the ICP so this source isn't silently dead.
    patterns = icp_params.get("google_search_patterns", []) or _build_fallback_patterns(icp_params)
    if not patterns:
        log.debug("[google_cse] no patterns and no ICP to build them — skipping")
        return []
    leads: list[dict] = []

    for pattern in patterns[:5]:
        for start in range(1, min(limit, 50), 10):
            try:
                r = httpx.get(
                    _API_URL,
                    params={
                        "key": settings.GOOGLE_API_KEY,
                        "cx": settings.GOOGLE_CSE_ID,
                        "q": pattern,
                        "start": start,
                        "num": 10,
                    },
                    timeout=10,
                )
                if r.status_code == 429:
                    log.warning("Google CSE quota exhausted")
                    return leads
                if r.status_code == 403:
                    log.error(
                        "[google_cse] 403 Forbidden — the Custom Search JSON API key is being "
                        "rejected. Fix in Google Cloud Console: (1) enable 'Custom Search API', "
                        "(2) remove HTTP-referrer/IP restrictions on the key. Skipping this run."
                    )
                    return leads  # give up immediately — every pattern will 403
                r.raise_for_status()
                items = r.json().get("items", [])

                for item in items:
                    name, title, company = _parse_snippet(item.get("snippet", ""), item.get("title", ""))
                    link = item.get("link", "")
                    is_linkedin = "linkedin.com/in/" in link
                    # Quality gate: only emit a real PERSON. Skip results where we
                    # couldn't parse a name (was emitting page titles as people with
                    # a false "linkedin_profile_match" signal).
                    if not name:
                        continue
                    linkedin_url = link if is_linkedin else None
                    snip = item.get("snippet", "")
                    leads.append({
                        "external_id": f"google_{link[:80]}",
                        "person_name": name,
                        "person_title": title,
                        "company_name": company,
                        "person_linkedin_url": linkedin_url,
                        "source": NAME,
                        "source_url": link,
                        "source_profile_url": linkedin_url or link,
                        "source_snippet": f"Google search for: {pattern}\n\n{item.get('title', '')}\n{snip[:500]}",
                        "raw_data": {
                            "context": snip[:500],
                            "search_url": link,
                        },
                        "intent_signals": ["linkedin_profile_match"] if is_linkedin else ["web_search_match"],
                    })
                    if len(leads) >= limit:
                        return leads[:limit]

                time.sleep(1)
            except Exception as e:
                log.warning(f"Google CSE fetch failed for pattern '{pattern}': {e}")
                break

    return leads[:limit]


def _build_fallback_patterns(icp: dict) -> list[str]:
    """Build LinkedIn-profile search patterns from the ICP when the LLM didn't
    supply google_search_patterns. Mirrors the linkedin source's query logic so
    this source still finds role×industry-matched profiles."""
    roles = (icp.get("target_roles") or [])[:3]
    industries = (icp.get("target_industries") or icp.get("industries") or [])[:2]
    patterns: list[str] = []
    for role in roles:
        if industries:
            for ind in industries:
                patterns.append(f'site:linkedin.com/in "{role}" "{ind}"')
        else:
            patterns.append(f'site:linkedin.com/in "{role}"')
    # De-dupe, cap
    seen: set[str] = set()
    return [p for p in patterns if not (p in seen or seen.add(p))][:5]


def _parse_snippet(snippet: str, title: str) -> tuple[str | None, str | None, str | None]:
    # LinkedIn title format: "Name - Title at Company | LinkedIn"
    match = re.match(r"^([^-|]+)\s*[-–]\s*([^|]+?)(?:\s+at\s+([^|]+))?\s*\|", title)
    if match:
        return match.group(1).strip(), match.group(2).strip(), match.group(3).strip() if match.group(3) else None
    return None, None, None

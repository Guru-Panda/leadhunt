"""Job-posting intent source — companies HIRING are companies GROWING = buyers.

If your strategy solves a problem for a specific team (HR, DevOps, Sales, etc.),
a company actively hiring for that team is in buying mode RIGHT NOW.

We search public ATS platforms (Lever, Greenhouse, Ashby, Workable) via the
search engine — these pages are indexed and contain the company name + role.

Example signal:
  Strategy: "we sell onboarding software to HR teams"
  → company hiring "HR Coordinator" / "People Ops Manager" = active buyer

Uses Google CSE (primary) → Mojeek (fallback), same as the linkedin source.
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
NAME = "jobs"

_GOOGLE_CSE = "https://www.googleapis.com/customsearch/v1"
_MOJEEK = "https://www.mojeek.com/search"
_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15"
)

# Public ATS domains whose job pages are reliably indexed
_ATS_SITES = [
    "jobs.lever.co",
    "boards.greenhouse.io",
    "jobs.ashbyhq.com",
    "apply.workable.com",
]

# Map ATS domain → how to pull the company slug out of the URL path
#   jobs.lever.co/acme/<job-id>         → acme
#   boards.greenhouse.io/acme/jobs/123  → acme
#   jobs.ashbyhq.com/acme/<uuid>        → acme
#   apply.workable.com/acme/j/ABC/      → acme


def _company_from_url(url: str) -> str | None:
    try:
        parts = [p for p in urlparse(url).path.split("/") if p]
        return parts[0] if parts else None
    except Exception:
        return None


def _prettify(slug: str) -> str:
    return " ".join(w.capitalize() for w in re.split(r"[-_]", slug) if w)


def _google_cse_search(query: str, limit: int = 10) -> list[dict]:
    if not (settings.GOOGLE_API_KEY and settings.GOOGLE_CSE_ID):
        return []
    try:
        r = httpx.get(
            _GOOGLE_CSE,
            params={"key": settings.GOOGLE_API_KEY, "cx": settings.GOOGLE_CSE_ID,
                    "q": query, "num": min(limit, 10)},
            timeout=10,
        )
        if r.status_code != 200:
            return []
        return [{"title": i.get("title", ""), "url": i.get("link", ""),
                 "snippet": i.get("snippet", "")} for i in r.json().get("items", [])]
    except Exception as e:
        log.warning(f"[jobs] Google CSE failed for {query!r}: {e}")
        return []


def _mojeek_search(query: str, limit: int = 10) -> list[dict]:
    try:
        r = httpx.get(_MOJEEK, params={"q": query},
                      headers={"User-Agent": _UA, "Accept": "text/html"},
                      timeout=12, follow_redirects=True)
        if r.status_code != 200:
            return []
        tree = HTMLParser(r.text)
        out = []
        for li in tree.css(".results-standard li, ul.results-standard li, .results li"):
            a = li.css_first("a.title, h2 a, a")
            snip = li.css_first(".s, p")
            if not a:
                continue
            out.append({"title": a.text(strip=True), "url": a.attributes.get("href", ""),
                        "snippet": snip.text(strip=True) if snip else ""})
            if len(out) >= limit:
                break
        return out
    except Exception as e:
        log.warning(f"[jobs] Mojeek failed for {query!r}: {e}")
        return []


def _build_queries(icp: dict) -> list[str]:
    """Build job-board queries from the ICP target roles.

    The roles a company hires for ARE the teams that would buy our solution.
    """
    roles = (icp.get("target_roles") or [])[:4]
    # Also derive "hiring" intent keywords if the strategy is about hiring/growth
    if not roles:
        return []

    queries: list[str] = []
    # One query per ATS site × top roles (capped to conserve quota)
    for site in _ATS_SITES:
        for role in roles[:2]:
            queries.append(f'site:{site} "{role}"')
    return queries[:6]


def fetch(icp_params: dict, limit: int = 50) -> list[dict]:
    queries = _build_queries(icp_params)
    if not queries:
        log.debug("[jobs] no target_roles in ICP — skipping")
        return []

    use_google = bool(settings.GOOGLE_API_KEY and settings.GOOGLE_CSE_ID)
    leads: list[dict] = []
    seen_companies: set[str] = set()

    for query in queries:
        results = _google_cse_search(query, 10) if use_google else _mojeek_search(query, 10)
        if not results and use_google:
            results = _mojeek_search(query, 10)

        for r in results:
            url = (r.get("url") or "").strip()
            if not url or not any(s in url for s in _ATS_SITES):
                continue
            slug = _company_from_url(url)
            if not slug or slug in seen_companies:
                continue
            seen_companies.add(slug)

            company = _prettify(slug)
            title = r.get("title", "")
            snippet = r.get("snippet", "")
            # The role they're hiring for — extract from the search query
            hiring_role = re.search(r'"([^"]+)"', query)
            role_str = hiring_role.group(1) if hiring_role else ""

            leads.append({
                "external_id": f"jobs_{slug[:80]}",
                "person_name": company,  # company-level lead
                "person_title": None,
                "company_name": company,
                "company_domain": None,
                "source": NAME,
                "source_url": url,
                "source_profile_url": url,  # the job listing — passes has_contact
                "source_snippet": (
                    f"{company} is hiring: {title}\n"
                    f"Active hiring signal for '{role_str}' → growing team, likely buyer.\n{snippet[:300]}"
                ),
                "raw_data": {
                    "bio": snippet[:400],
                    "context": f"Hiring for {role_str} (job posting on {urlparse(url).netloc})",
                    "job_url": url,
                    "hiring_role": role_str,
                },
                "intent_signals": ["active_hiring_signal", "company_growth_signal"],
            })
            if len(leads) >= limit:
                return leads[:limit]

        if not use_google:
            time.sleep(1.5)

    log.info(f"[jobs] fetched {len(leads)} hiring-signal company leads")
    return leads[:limit]

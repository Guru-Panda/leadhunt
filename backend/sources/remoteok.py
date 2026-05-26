from __future__ import annotations

import logging
import re
from urllib.parse import urlparse

import httpx

log = logging.getLogger(__name__)
NAME = "remoteok"

_API = "https://remoteok.com/api"
_UA = "Mozilla/5.0 LeadHunt/1.0"


def _word_in(needle: str, haystack: str) -> bool:
    """Whole-word match — 'engineer' doesn't match 'reengineered'."""
    if len(needle) < 2:
        return False
    return re.search(r"\b" + re.escape(needle.lower()) + r"\b", haystack.lower()) is not None


def _matches_icp(job: dict, target_roles: list[str], tech_keywords: list[str], intent_keywords: list[str]) -> bool:
    """STRICT rules:
      - Intent keywords (if set): must appear in position OR description OR tags.
      - Otherwise: role in position title OR tech keyword in tags.
    """
    position = job.get("position", "") or ""
    description = (job.get("description", "") or "")[:1500]
    tags_str = " ".join(job.get("tags", []) or [])
    full_blob = f"{position} {description} {tags_str}"
    if not position:
        return False
    # When intent keywords are set, they're MANDATORY — anything not signaling
    # the buyer intent isn't a useful lead, even if role/tech happen to match.
    if intent_keywords:
        return any(_word_in(kw, full_blob) for kw in intent_keywords if kw)
    return (
        any(_word_in(role, position) for role in target_roles)
        or any(_word_in(kw, tags_str) for kw in tech_keywords)
    )


def _domain_of(url: str | None) -> str | None:
    if not url:
        return None
    try:
        host = urlparse(url).netloc
        return host[4:] if host.startswith("www.") else host or None
    except Exception:
        return None


def fetch(icp_params: dict, limit: int = 50) -> list[dict]:
    """Pull RemoteOK's full feed (~100 jobs), filter to ICP-relevant ones.

    Each match becomes a company-level lead with 'actively_hiring' intent signal.
    """
    target_roles = icp_params.get("target_roles", [])
    tech_keywords = icp_params.get("tech_keywords", [])
    intent_keywords = icp_params.get("buyer_intent_keywords", [])
    if not target_roles and not tech_keywords and not intent_keywords:
        return []

    try:
        r = httpx.get(_API, headers={"User-Agent": _UA}, timeout=15)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        log.warning(f"RemoteOK fetch failed: {e}")
        return []

    # First item is metadata; skip it
    jobs = [j for j in data if isinstance(j, dict) and j.get("position")]

    leads: list[dict] = []
    seen_companies: set[str] = set()

    for job in jobs:
        if not _matches_icp(job, target_roles, tech_keywords, intent_keywords):
            continue
        company = job.get("company", "")
        if not company or company in seen_companies:
            continue
        seen_companies.add(company)

        job_url = job.get("url", "")
        position = job.get("position", "")
        tags = job.get("tags", [])
        leads.append({
            "external_id": f"remoteok_{job.get('id', company)}",
            "person_name": company,
            "person_title": f"Hiring: {position[:80]}",
            "company_name": company,
            "company_domain": _domain_of(job.get("apply_url") or job_url),
            "person_location": (job.get("location") or "Remote") if job.get("location") else "Remote",
            "source": NAME,
            "source_url": job_url,
            "source_profile_url": job_url,
            "source_snippet": f"{company} is hiring: {position}\n\nTags: {', '.join(tags[:8])}\nLocation: {job.get('location') or 'Remote'}",
            "raw_data": {
                "context": f"Hiring '{position}' on RemoteOK — tags: {', '.join(tags[:5])}",
                "remoteok_url": job_url,
                "tags": tags,
                "salary": job.get("salary", ""),
            },
            "intent_signals": ["actively_hiring", "hiring_remote"],
        })
        if len(leads) >= limit:
            break

    return leads[:limit]

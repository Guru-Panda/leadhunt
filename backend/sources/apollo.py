"""Apollo.io lead source — 275M+ contact database with verified emails.

Apollo People Search API:
  https://apolloio.github.io/apollo-api-docs/?shell#people-search

Free tier: 50 email exports / month.
Paid ($49/mo): 1,000 exports/month.

Why Apollo beats scraping:
  - Verified business emails (not guesses)
  - LinkedIn URL included
  - Company data (size, industry, domain) included
  - Intent data available on paid plans
  - No scraping, no CAPTCHAs, no IP blocks

Set APOLLO_API_KEY in env to enable.
"""
from __future__ import annotations

import logging

import httpx

from backend.config import settings

log = logging.getLogger(__name__)
NAME = "apollo"

_BASE = "https://api.apollo.io/v1"


def _build_person_params(icp_params: dict, page: int = 1) -> dict:
    """Convert ICP params to Apollo People Search parameters."""
    roles = icp_params.get("target_roles") or []
    industries = icp_params.get("industries") or icp_params.get("target_industries") or []
    locations = icp_params.get("target_locations") or []
    size_min = icp_params.get("company_size_min") or 1
    size_max = icp_params.get("company_size_max") or 10000

    params: dict = {
        "page": page,
        "per_page": 25,
        "contact_email_status[]": ["verified", "likely to engage"],  # only leads with good emails
    }

    if roles:
        params["person_titles[]"] = roles[:5]
    if industries:
        params["organization_industry_tag_ids[]"] = []  # Apollo uses tag IDs — use keyword search instead
        params["q_organization_keyword_tags"] = " OR ".join(industries[:3])
    if locations:
        params["person_locations[]"] = locations[:3]

    # Company size filter (Apollo uses employee ranges)
    # Map our min/max to Apollo's bracket system
    size_brackets = []
    if size_max <= 10:
        size_brackets = ["1,10"]
    elif size_max <= 50:
        size_brackets = ["1,10", "11,20", "21,50"]
    elif size_max <= 200:
        size_brackets = ["11,20", "21,50", "51,100", "101,200"]
    elif size_max <= 1000:
        size_brackets = ["51,100", "101,200", "201,500", "501,1000"]
    else:
        size_brackets = ["201,500", "501,1000", "1001,2000", "2001,5000", "5001,10000"]

    if size_brackets:
        params["organization_num_employees_ranges[]"] = size_brackets[:3]

    return params


def fetch(icp_params: dict, limit: int = 50) -> list[dict]:
    api_key = settings.APOLLO_API_KEY if hasattr(settings, "APOLLO_API_KEY") else ""
    if not api_key:
        log.debug("[apollo] APOLLO_API_KEY not set — skipping")
        return []

    headers = {
        "Content-Type": "application/json",
        "Cache-Control": "no-cache",
        "X-Api-Key": api_key,
    }

    leads: list[dict] = []
    page = 1

    while len(leads) < limit:
        params = _build_person_params(icp_params, page=page)
        try:
            r = httpx.post(
                f"{_BASE}/mixed_people/search",
                json=params,
                headers=headers,
                timeout=15,
            )
            if r.status_code == 422:
                log.warning(f"[apollo] Invalid params: {r.text[:300]}")
                break
            if r.status_code == 429:
                log.warning("[apollo] Rate limited")
                break
            r.raise_for_status()

            data = r.json()
            people = data.get("people") or data.get("contacts") or []
            if not people:
                break

            for person in people:
                # Extract verified email
                email = person.get("email") or ""
                email_status = person.get("email_status", "")
                if email_status not in ("verified", "likely to engage", ""):
                    email = ""  # don't use bounced/invalid

                linkedin_url = person.get("linkedin_url") or ""
                if linkedin_url and not linkedin_url.startswith("http"):
                    linkedin_url = f"https://{linkedin_url}"

                org = person.get("organization") or {}
                company_name = org.get("name") or person.get("organization_name") or ""
                company_domain = org.get("website_url") or person.get("organization_website_url") or ""
                company_size = str(org.get("estimated_num_employees") or "")
                company_industry = (org.get("industry") or "").title()

                person_name = f"{person.get('first_name', '')} {person.get('last_name', '')}".strip()
                if not person_name:
                    continue

                slug = (linkedin_url.rstrip("/").split("/")[-1] if linkedin_url else person.get("id", ""))
                external_id = f"apollo_{person.get('id', slug)}"

                leads.append({
                    "external_id": external_id,
                    "person_name": person_name,
                    "person_title": person.get("title") or person.get("headline"),
                    "person_email": email or None,
                    "email_verified": email_status == "verified",
                    "email_source": "apollo" if email else None,
                    "person_linkedin_url": linkedin_url or None,
                    "person_location": person.get("city") or person.get("state"),
                    "company_name": company_name or None,
                    "company_domain": company_domain or None,
                    "company_size": company_size or None,
                    "company_industry": company_industry or None,
                    "source": NAME,
                    "source_url": linkedin_url or f"https://app.apollo.io/#/people/{person.get('id', '')}",
                    "source_profile_url": linkedin_url or None,
                    "source_snippet": (
                        f"{person_name} — {person.get('title', '')} at {company_name}\n"
                        f"Industry: {company_industry} | Size: {company_size} employees\n"
                        f"Location: {person.get('city', '')}, {person.get('state', '')}"
                    ),
                    "raw_data": {
                        "bio": person.get("headline") or "",
                        "context": f"Apollo.io match — {person.get('title', '')} at {company_name}",
                        "apollo_id": person.get("id"),
                        "seniority": person.get("seniority"),
                        "departments": person.get("departments", []),
                        "email_status": email_status,
                    },
                    "intent_signals": ["apollo_icp_match", "verified_contact"],
                })

                if len(leads) >= limit:
                    break

            # Check pagination
            pagination = data.get("pagination") or {}
            total_pages = pagination.get("total_pages") or 1
            if page >= total_pages or page >= 3:  # cap at 3 pages to conserve quota
                break
            page += 1

        except Exception as e:
            log.warning(f"[apollo] fetch failed (page {page}): {e}")
            break

    log.info(f"[apollo] fetched {len(leads)} leads")
    return leads[:limit]

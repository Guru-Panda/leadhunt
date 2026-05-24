from __future__ import annotations

import logging

import httpx

from backend.config import settings

log = logging.getLogger(__name__)
NAME = "companies_house"

_BASE = "https://api.company-information.service.gov.uk"


def _auth() -> tuple[str, str] | None:
    """Companies House uses HTTP Basic Auth with the API key as username, blank password."""
    if not settings.COMPANIES_HOUSE_KEY:
        return None
    return (settings.COMPANIES_HOUSE_KEY, "")


def fetch(icp_params: dict, limit: int = 50) -> list[dict]:
    """Run Companies House when:
      - the strategy explicitly targets UK locations, OR
      - no locations are set (Companies House is a global free-data source worth trying)
    Skip when the strategy explicitly targets non-UK regions (US, India, etc.)
    """
    locations = icp_params.get("target_locations") or []

    if locations:
        is_uk_relevant = any(
            any(uk in loc.lower() for uk in ("uk", "london", "england", "britain", "europe", "ireland", "wales", "scotland"))
            for loc in locations
        )
        explicitly_non_uk = any(
            any(non in loc.lower() for non in ("usa", "us", "united states", "india", "asia", "africa", "china"))
            for loc in locations
        ) and not is_uk_relevant
        if explicitly_non_uk:
            return []

    industries = icp_params.get("industries", [])
    if not industries:
        return []

    auth = _auth()
    if not auth:
        log.info("COMPANIES_HOUSE_KEY not set — skipping. Get a free key at developer.company-information.service.gov.uk")
        return []

    leads: list[dict] = []

    for keyword in industries[:3]:
        try:
            r = httpx.get(
                f"{_BASE}/search/companies",
                params={"q": keyword, "items_per_page": 20},
                headers={"User-Agent": "LeadHunt/1.0"},
                auth=auth,
                timeout=10,
            )
            r.raise_for_status()
            companies = r.json().get("items", [])

            for company in companies:
                company_number = company.get("company_number", "")
                company_name = company.get("title", "")

                officers = _get_officers(company_number)
                company_url = f"https://find-and-update.company-information.service.gov.uk/company/{company_number}"
                for officer in officers[:3]:
                    officer_links = officer.get("links", {})
                    officer_path = officer_links.get("officer", {}).get("appointments", "")
                    officer_url = f"https://find-and-update.company-information.service.gov.uk{officer_path}" if officer_path else company_url
                    name = officer.get("name", "").title()
                    role = officer.get("officer_role", "Director").title()
                    leads.append({
                        "external_id": f"ch_{company_number}_{name[:20]}",
                        "person_name": name,
                        "person_title": role,
                        "company_name": company_name,
                        "person_location": "United Kingdom",
                        "source": NAME,
                        "source_url": company_url,
                        "source_profile_url": officer_url,
                        "source_snippet": f"{name} — {role} at {company_name}\nCompany number: {company_number}\nSource: UK Companies House",
                        "raw_data": {
                            "context": f"Director at {company_name} (Companies House)",
                            "company_number": company_number,
                        },
                        "intent_signals": ["uk_company_director"],
                    })
                    if len(leads) >= limit:
                        return leads[:limit]
        except Exception as e:
            log.warning(f"Companies House fetch failed for '{keyword}': {e}")

    return leads[:limit]


def _get_officers(company_number: str) -> list[dict]:
    auth = _auth()
    if not auth:
        return []
    try:
        r = httpx.get(
            f"{_BASE}/company/{company_number}/officers",
            headers={"User-Agent": "LeadHunt/1.0"},
            auth=auth,
            timeout=10,
        )
        if r.status_code != 200:
            return []
        return [o for o in r.json().get("items", []) if o.get("resigned_on") is None]
    except Exception:
        return []

from __future__ import annotations

import logging
import time

import httpx
from selectolax.parser import HTMLParser

log = logging.getLogger(__name__)
NAME = "indeed"

_BASE = "https://www.indeed.com"
_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"


def fetch(icp_params: dict, limit: int = 50) -> list[dict]:
    """Indeed scrapes are routinely Cloudflare-blocked (403 security check).

    We attempt the request; if blocked we return [] silently. Production usage
    requires a residential proxy or a paid scraping service. The RemoteOK
    source provides similar hiring-intent signals without that constraint.
    """
    queries = icp_params.get("indeed_job_queries", [])
    if not queries:
        return []

    leads: list[dict] = []
    blocked = False

    for query in queries[:2]:
        try:
            r = httpx.get(
                f"{_BASE}/jobs",
                params={"q": query, "sort": "date"},
                headers={"User-Agent": _UA},
                timeout=15,
                follow_redirects=True,
            )
            if r.status_code in (403, 429):
                blocked = True
                break
            if r.status_code != 200:
                continue
            tree = HTMLParser(r.text)
            cards = tree.css('[class*="job_seen_beacon"], [data-jk]')

            for card in cards:
                company_el = card.css_first('[data-testid="company-name"], .companyName')
                location_el = card.css_first('[data-testid="text-location"], .companyLocation')
                title_el = card.css_first('[class*="jobTitle"] a, .jobTitle span')
                company = company_el.text(strip=True) if company_el else None
                if not company:
                    continue
                leads.append({
                    "external_id": f"indeed_{query[:20]}_{company[:30]}",
                    "person_name": company,
                    "person_title": f"Hiring: {title_el.text(strip=True)[:80]}" if title_el else "Hiring",
                    "company_name": company,
                    "person_location": location_el.text(strip=True) if location_el else None,
                    "source": NAME,
                    "raw_data": {"context": f"Actively hiring {query} on Indeed"},
                    "intent_signals": ["actively_hiring"],
                })
                if len(leads) >= limit:
                    return leads[:limit]

            time.sleep(3)
        except Exception as e:
            log.warning(f"Indeed scrape failed for {query!r}: {e}")

    if blocked and not leads:
        log.info("Indeed: blocked by Cloudflare (use RemoteOK or residential proxy for production)")
    return leads[:limit]

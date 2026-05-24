from __future__ import annotations

import logging
import time

import httpx
from selectolax.parser import HTMLParser

log = logging.getLogger(__name__)
NAME = "wellfound"

_BASE = "https://wellfound.com"
_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"


def fetch(icp_params: dict, limit: int = 50) -> list[dict]:
    """Wellfound (ex-AngelList) routinely returns 403 to non-browser clients.

    We attempt a single lightweight probe; if blocked we return [] silently.
    Use the YC + RemoteOK sources for startup-hiring intent without that
    constraint, or supply a residential proxy in production.
    """
    roles = icp_params.get("target_roles", [])
    if not roles:
        return []

    leads: list[dict] = []
    blocked = False

    for role in roles[:2]:
        slug = role.lower().replace(" ", "-")
        try:
            r = httpx.get(
                f"{_BASE}/role/{slug}",
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
            cards = tree.css('[class*="startup-link"], [class*="company-link"], article')
            for card in cards:
                name_el = card.css_first("h2, h3, strong, [class*='name']")
                link_el = card.css_first("a[href*='/company/']")
                company = name_el.text(strip=True) if name_el else None
                if not company:
                    continue
                leads.append({
                    "external_id": f"wellfound_{company[:40]}",
                    "person_name": company,
                    "person_title": f"Hiring {role}",
                    "company_name": company,
                    "source": NAME,
                    "raw_data": {
                        "context": f"Startup on Wellfound hiring for {role}",
                        "wellfound_url": f"{_BASE}{link_el.attrs.get('href', '')}" if link_el else None,
                    },
                    "intent_signals": ["startup_hiring", "wellfound_listed"],
                })
                if len(leads) >= limit:
                    return leads[:limit]
            time.sleep(3)
        except Exception as e:
            log.warning(f"Wellfound scrape failed for {role!r}: {e}")
            break

    if blocked and not leads:
        log.info("Wellfound: blocked by Cloudflare (use YC + RemoteOK or residential proxy)")
    return leads[:limit]

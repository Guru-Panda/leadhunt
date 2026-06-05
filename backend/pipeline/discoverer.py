from __future__ import annotations

import logging

import httpx
from sqlalchemy.orm import Session

from backend.llm import llm_call, llm_json
from backend.models import DiscoveredSource

log = logging.getLogger(__name__)


def discover_sources_for_strategy(strategy, db: Session) -> list[DiscoveredSource]:
    prompt = f"""You are a lead-generation researcher. Find 15 NEW free public web sources to find leads matching this ICP.
ICP:
- Business solves: {strategy.main_problem}
- Ideal customer: {strategy.ideal_customer}
- Target roles: {strategy.target_roles}
- Target industries: {strategy.target_industries}

Already covered (do NOT suggest): GitHub, ProductHunt, Y Combinator, HackerNews, Reddit, Indeed, Wellfound, Google CSE, WHOIS, Bing, Companies House, RemoteOK.

CRITICAL — AVOID these site categories (they don't return scrapable HTML):
- DEAD sites: Lanyrd (shut down 2014), Klout, Quibb, Branch.com, App.net, any pre-2018 site that's clearly defunct
- JS-only SPAs (return empty HTML to scrapers): Crunchbase, Pitchbook, AngelList/Wellfound profile pages, modern Notion public pages, Mixpanel customer pages
- HARD bot-blocked: LinkedIn pages directly (use site:linkedin.com via search instead), Indeed, Glassdoor, Twitter/X scraping, Facebook
- Paywalled: Bloomberg, WSJ, FT, Forbes premium articles, NYT
- Aggregator-only metadata pages with no people: Stackshare tech pages without team sections, Wikipedia category pages

PREFER sites that:
- Return REAL HTML with names + bios server-rendered (no JS execution required)
- Are NICHE / industry-specific (less likely to bot-block)
- Have OPEN member directories, speaker lists, OSS maintainer lists, podcast guest pages, conference attendee pages, awards lists, "state of X" survey respondents
- Examples that work well: Indie Hackers (member profiles), Dev.to/Hashnode (author pages), podcast show notes with guest names + Twitter/LinkedIn, conference speaker pages (e.g. PyConIndia.com/speakers), Substack discovery pages, GitHub topic pages
- Public Meetup.com event pages

Return ONLY JSON list (no markdown):
[
  {{
    "name": "human-readable name",
    "type": "directory|forum|community|search|jobboard|listing|blog|conference|awards",
    "url": "real URL or template with {{role}}, {{location}}, {{keyword}} placeholders",
    "access_method": "scrape_html|api|rss|sitemap",
    "rationale": "1 sentence why this fits the ICP"
  }}
]
Be SPECIFIC. Real URLs only. 15 sources minimum."""

    try:
        candidates = llm_json(prompt, high_quality=True, max_tokens=2500)
    except Exception as e:
        log.error(f"Discovery LLM call failed for strategy {strategy.id}: {e}")
        return []

    saved: list[DiscoveredSource] = []
    for c in candidates:
        if not isinstance(c, dict):
            continue
        url = c.get("url", "")
        for var, val in [
            ("{role}", (strategy.target_roles or [""])[0]),
            ("{location}", (strategy.target_locations or [""])[0]),
            ("{keyword}", (strategy.keywords or [""])[0]),
        ]:
            url = url.replace(var, val)

        try:
            r = httpx.get(url, timeout=6, headers={"User-Agent": "Mozilla/5.0 LeadHunt/1.0"}, follow_redirects=True)
            if r.status_code != 200 or len(r.text) < 500:
                continue
            verify = llm_call(
                f"Does this page contain real people/companies that could be sales leads? Reply ONLY 'yes' or 'no'.\nURL: {url}\nPage excerpt: {r.text[:2000]}",
                max_tokens=10,
            )
            if not verify.strip().lower().startswith("yes"):
                continue

            ds = DiscoveredSource(
                strategy_id=strategy.id,
                name=c.get("name", url[:60]),
                type=c.get("type", "listing"),
                url_pattern=c.get("url", url),
                access_method=c.get("access_method", "scrape_html"),
                status="active",
            )
            db.add(ds)
            saved.append(ds)
            log.info(f"Discovered source saved: {ds.name} for strategy {strategy.id}")
        except Exception as e:
            log.warning(f"Discovery test failed for {url}: {e}")

    if saved:
        db.commit()
    return saved

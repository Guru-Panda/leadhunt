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

Already covered (do NOT suggest): GitHub, ProductHunt, Y Combinator, HackerNews, Reddit, Indeed, Wellfound, Google CSE, WHOIS, Bing, Companies House.

Look for things like:
- Industry-specific job boards
- Niche directories
- Public community member lists (Indie Hackers, Dev.to, Hashnode)
- Conference speaker pages
- Awards lists (Forbes 30 Under 30, Fast Company)
- Industry blog/podcast author pages
- Newsletter directories (Substack discover)
- Open-source maintainer lists
- Public Meetup.com event pages
- Crunchbase company news (free pages)

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
            r = httpx.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0 LeadHunt/1.0"}, follow_redirects=True)
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

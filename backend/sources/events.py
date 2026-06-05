"""Opportunity engine — events / webinars / conferences.

Beyond people-leads: surface places where your buyers GATHER, so the user can
attend, sponsor, speak, or exhibit. Works both locally (e.g. a DJ → bridal expos
near them) and worldwide (e.g. SaaS → industry conferences).

Deterministic + LLM-free: detects events by known event domains
(Eventbrite/Meetup/Lu.ma/Ticketmaster/confs.tech…) or event keywords in the title,
so it keeps producing opportunities even when the LLM pool is exhausted.
Optionally enriched by the Ticketmaster Discovery API when a key is set.
"""
from __future__ import annotations

import logging

import httpx

from backend.config import settings
from backend.search_providers import web_search

log = logging.getLogger(__name__)
NAME = "events"

_EVENT_DOMAINS = (
    "eventbrite.", "meetup.com", "lu.ma", "luma.com", "ticketmaster.", "confs.tech",
    "10times.com", "eventful.", "sessionize.com", "dev.events", "hopin.", "bizzabo.",
    "allevents.in",
)
_EVENT_WORDS = (
    "conference", "summit", "webinar", "expo", "meetup", "workshop", "festival",
    "convention", "symposium", "bootcamp", "masterclass", "trade show", "tradeshow",
)


def _is_event(title: str, url: str) -> bool:
    u = (url or "").lower()
    t = (title or "").lower()
    return any(d in u for d in _EVENT_DOMAINS) or any(w in t for w in _EVENT_WORDS)


def _ticketmaster(keyword: str, location: str | None, limit: int) -> list[dict]:
    """Ticketmaster Discovery API — best-effort, only if a key is configured."""
    if not settings.TICKETMASTER_API_KEY:
        return []
    try:
        params = {"apikey": settings.TICKETMASTER_API_KEY, "keyword": keyword, "size": min(limit, 20)}
        if location:
            params["city"] = location
        r = httpx.get("https://app.ticketmaster.com/discovery/v2/events.json", params=params, timeout=12)
        if r.status_code != 200:
            return []
        out = []
        for ev in (r.json().get("_embedded") or {}).get("events", []):
            out.append({
                "title": ev.get("name", ""),
                "url": ev.get("url", ""),
                "snippet": (ev.get("info") or ev.get("pleaseNote") or "")[:300],
            })
        return out
    except Exception as e:
        log.debug(f"[events] ticketmaster failed for {keyword!r}: {e}")
        return []


def _build_queries(icp: dict) -> list[str]:
    industries = (icp.get("target_industries") or icp.get("industries") or [])[:2]
    keywords = (icp.get("keywords") or icp.get("buyer_intent_keywords") or [])[:2]
    locations = (icp.get("target_locations") or [])
    terms = [t for t in (industries + keywords) if t] or [icp.get("_ideal_customer", "")]

    queries: list[str] = []
    for t in terms:
        if not t:
            continue
        queries.append(f"{t} conference 2026")
        queries.append(f'"{t}" webinar')
        queries.append(f"site:eventbrite.com {t}")
        if locations:
            queries.append(f"{t} events {locations[0]}")
    # de-dupe, cap
    seen: set[str] = set()
    return [q for q in queries if not (q in seen or seen.add(q))][:6]


def fetch(icp_params: dict, limit: int = 30) -> list[dict]:
    queries = _build_queries(icp_params)
    if not queries:
        return []

    locations = icp_params.get("target_locations") or []
    location = locations[0] if locations else None

    leads: list[dict] = []
    seen: set[str] = set()

    # Optional Ticketmaster enrichment (consumer/local events)
    for t in (icp_params.get("target_industries") or icp_params.get("keywords") or [])[:1]:
        for ev in _ticketmaster(t, location, 10):
            url = ev.get("url", "")
            if url and url not in seen and _is_event(ev.get("title", ""), url):
                seen.add(url)
                leads.append(_event_lead(ev, "ticketmaster"))

    for query in queries:
        for r in web_search(query, limit=6):
            url = (r.get("url") or "").strip()
            title = r.get("title", "")
            if not url or url in seen or not _is_event(title, url):
                continue
            seen.add(url)
            leads.append(_event_lead(r, query))
            if len(leads) >= limit:
                log.info(f"[events] {len(leads)} event opportunities")
                return leads[:limit]

    log.info(f"[events] {len(leads)} event opportunities")
    return leads[:limit]


def _event_lead(r: dict, origin: str) -> dict:
    title = (r.get("title") or "Event")[:160]
    url = r.get("url", "")
    snippet = r.get("snippet", "")
    return {
        "external_id": f"event_{url[:90]}",
        "person_name": title,            # the event itself (an opportunity, not a person)
        "person_title": None,
        "company_name": None,
        "source": NAME,
        "source_url": url,
        "source_profile_url": url,
        "source_snippet": (
            f"📅 Event opportunity: {title}\n{snippet[:300]}\n"
            f"Attend / sponsor / speak to reach your ICP."
        ),
        "raw_data": {"context": snippet, "event_url": url, "origin": origin},
        "intent_signals": ["event_opportunity"],
    }

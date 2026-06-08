"""Opportunity engine — webinars (global) + events (location-scoped).

Beyond people-leads: surface places where your buyers GATHER, so the user can
attend, sponsor, speak, or exhibit.

Two distinct opportunity types, controlled per-strategy:
  • WEBINARS — online, so they're GLOBAL. No location filter is applied; a
    relevant webinar is worth knowing about wherever it's hosted. Gated by
    `webinars_enabled` (default on).
  • IN-PERSON EVENTS (conferences, expos, meetups) — physical, so they're scoped
    to the strategy's `target_locations`. Gated by `events_enabled` (default on).
    With no locations set, falls back to general (un-scoped) event discovery.

The user picks these when creating the strategy and can change them later.

Deterministic + LLM-free: detects opportunities by known event domains
(Eventbrite/Meetup/Lu.ma/Ticketmaster/confs.tech…) or event keywords in the
title, so it keeps producing results even when the LLM pool is exhausted.
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
# Words that mark an opportunity as an online webinar (→ treated as global).
_WEBINAR_WORDS = ("webinar", "masterclass", "online workshop", "virtual summit", "livestream")


def _is_event(title: str, url: str) -> bool:
    u = (url or "").lower()
    t = (title or "").lower()
    return any(d in u for d in _EVENT_DOMAINS) or any(w in t for w in _EVENT_WORDS)


def _event_kind(title: str, url: str) -> str:
    """'webinar' (online/global) or 'event' (in-person)."""
    blob = f"{title} {url}".lower()
    return "webinar" if any(w in blob for w in _WEBINAR_WORDS) else "event"


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


def _terms(icp: dict) -> list[str]:
    """The subject terms to search opportunities for (industries + keywords + user event keywords)."""
    industries = (icp.get("target_industries") or icp.get("industries") or [])[:2]
    keywords = (icp.get("keywords") or icp.get("buyer_intent_keywords") or [])[:2]
    event_kws = (icp.get("event_keywords") or [])[:3]  # user-specified, highest priority
    terms = [t for t in (event_kws + industries + keywords) if t]
    if not terms and icp.get("_ideal_customer"):
        terms = [icp["_ideal_customer"]]
    # de-dupe, preserve order, cap
    seen: set[str] = set()
    return [t for t in terms if not (t in seen or seen.add(t))][:4]


def _webinar_queries(terms: list[str]) -> list[str]:
    """GLOBAL — no location, webinars are online."""
    queries: list[str] = []
    for t in terms:
        queries.append(f'"{t}" webinar 2026')
        queries.append(f'"{t}" online masterclass')
    return _dedupe(queries)[:6]


def _event_queries(terms: list[str], location: str | None) -> list[str]:
    """LOCATION-SCOPED in-person events when a location is set, else general."""
    queries: list[str] = []
    for t in terms:
        if location:
            queries.append(f"{t} conference {location} 2026")
            queries.append(f"{t} events {location}")
            queries.append(f"site:eventbrite.com {t} {location}")
        else:
            queries.append(f"{t} conference 2026")
            queries.append(f"site:eventbrite.com {t}")
    return _dedupe(queries)[:6]


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    return [x for x in items if x and not (x in seen or seen.add(x))]


def fetch(icp_params: dict, limit: int = 30) -> list[dict]:
    terms = _terms(icp_params)
    if not terms:
        return []

    # Per-strategy toggles (default both on for backward compatibility).
    webinars_on = icp_params.get("webinars_enabled", True)
    events_on = icp_params.get("events_enabled", True)
    locations = icp_params.get("target_locations") or []
    location = locations[0] if locations else None

    leads: list[dict] = []
    seen: set[str] = set()

    def _consume(results: list[dict], origin: str) -> bool:
        """Add event-like results; return True once the limit is hit."""
        for r in results:
            url = (r.get("url") or "").strip()
            title = r.get("title", "")
            if not url or url in seen or not _is_event(title, url):
                continue
            seen.add(url)
            leads.append(_event_lead(r, origin, _event_kind(title, url)))
            if len(leads) >= limit:
                return True
        return False

    # ── Webinars (global) ──
    if webinars_on:
        for q in _webinar_queries(terms):
            if _consume(web_search(q, limit=6), f"webinar:{q}"):
                log.info(f"[events] {len(leads)} opportunities (limit hit)")
                return leads[:limit]

    # ── In-person events (location-scoped) ──
    if events_on:
        # Optional Ticketmaster enrichment for consumer/local events near the user.
        for t in terms[:1]:
            for ev in _ticketmaster(t, location, 10):
                url = (ev.get("url") or "").strip()
                if url and url not in seen and _is_event(ev.get("title", ""), url):
                    seen.add(url)
                    leads.append(_event_lead(ev, "ticketmaster", "event"))
        for q in _event_queries(terms, location):
            if _consume(web_search(q, limit=6), f"event:{q}"):
                log.info(f"[events] {len(leads)} opportunities (limit hit)")
                return leads[:limit]

    log.info(
        f"[events] {len(leads)} opportunities "
        f"(webinars={'on' if webinars_on else 'off'}, events={'on' if events_on else 'off'}, location={location})"
    )
    return leads[:limit]


def _event_lead(r: dict, origin: str, kind: str = "event") -> dict:
    title = (r.get("title") or "Event")[:160]
    url = r.get("url", "")
    snippet = r.get("snippet", "")
    is_webinar = kind == "webinar"
    icon = "💻" if is_webinar else "📅"
    scope = "Global online webinar" if is_webinar else "In-person event"
    # Every opportunity keeps "event_opportunity" (scorer + Opportunities feed key
    # off it); the kind tag distinguishes webinar vs in-person.
    signals = ["event_opportunity", "webinar_opportunity" if is_webinar else "in_person_event", kind]
    return {
        "external_id": f"event_{url[:90]}",
        "person_name": title,            # the opportunity itself (not a person)
        "person_title": None,
        "company_name": None,
        "source": NAME,
        "source_url": url,
        "source_profile_url": url,
        "source_snippet": (
            f"{icon} {scope}: {title}\n{snippet[:300]}\n"
            f"Attend / sponsor / speak to reach your ICP."
        ),
        "raw_data": {"context": snippet, "event_url": url, "origin": origin, "event_kind": kind},
        "intent_signals": signals,
    }

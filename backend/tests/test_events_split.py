"""Webinars (global) vs in-person events (location-scoped) + toggles + event keywords."""
from __future__ import annotations

from backend.sources import events


def test_webinar_queries_have_no_location():
    qs = events._webinar_queries(["fintech"])
    assert qs and all("webinar" in q or "masterclass" in q for q in qs)
    # Global → a city name must never appear in webinar queries.
    assert all("London" not in q for q in qs)


def test_event_queries_scope_to_location_when_present():
    scoped = events._event_queries(["fintech"], "London")
    assert any("London" in q for q in scoped)
    general = events._event_queries(["fintech"], None)
    assert general and all("London" not in q for q in general)


def test_event_keywords_take_priority_in_terms():
    terms = events._terms({"event_keywords": ["growth marketing"], "target_industries": ["fintech"]})
    assert terms[0] == "growth marketing"


def test_kind_classification():
    assert events._event_kind("AI Webinar", "https://x.com") == "webinar"
    assert events._event_kind("FinTech Summit", "https://eventbrite.com/e/x") == "event"


def test_webinars_disabled_skips_webinar_search(monkeypatch):
    calls = []
    def fake_search(q, limit=6):
        calls.append(q)
        return [{"title": "X Webinar", "url": "https://acme.com/w", "snippet": ""}]
    monkeypatch.setattr(events, "web_search", fake_search)
    monkeypatch.setattr(events, "_ticketmaster", lambda *a, **k: [])

    events.fetch({"target_industries": ["fintech"], "webinars_enabled": False, "events_enabled": True}, limit=10)
    # No webinar-flavored query should have run.
    assert all("webinar" not in q and "masterclass" not in q for q in calls)


def test_both_disabled_returns_nothing(monkeypatch):
    monkeypatch.setattr(events, "web_search", lambda q, limit=6: [
        {"title": "X Summit", "url": "https://eventbrite.com/e/x", "snippet": ""}])
    monkeypatch.setattr(events, "_ticketmaster", lambda *a, **k: [])
    out = events.fetch({"target_industries": ["fintech"], "webinars_enabled": False, "events_enabled": False}, limit=10)
    assert out == []


def test_webinar_lead_tagged_global(monkeypatch):
    monkeypatch.setattr(events, "web_search", lambda q, limit=6: [
        {"title": "Growth Webinar 2026", "url": "https://acme.com/learn", "snippet": "join"}])
    monkeypatch.setattr(events, "_ticketmaster", lambda *a, **k: [])
    out = events.fetch({"event_keywords": ["growth"], "webinars_enabled": True, "events_enabled": False}, limit=5)
    assert out and "webinar_opportunity" in out[0]["intent_signals"]
    assert "event_opportunity" in out[0]["intent_signals"]  # still in the opportunities feed

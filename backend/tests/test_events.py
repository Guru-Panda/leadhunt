"""Opportunity engine (events) — deterministic detection + filtering."""
from __future__ import annotations

from backend.sources import events


def test_detects_event_by_domain_or_keyword():
    assert events._is_event("Some Page", "https://eventbrite.com/e/x")
    assert events._is_event("Annual Marketing Summit", "https://example.com/x")
    assert events._is_event("DevOps Webinar", "https://acme.com/learn")
    assert not events._is_event("Best CRM Software 2026", "https://pcmag.com/x")


def test_fetch_keeps_only_events(monkeypatch):
    monkeypatch.setattr(events, "web_search", lambda q, limit=6: [
        {"title": "FinTech Summit 2026", "url": "https://eventbrite.com/e/fintech", "snippet": "join us"},
        {"title": "Best CRM listicle", "url": "https://blog.example.com/crm", "snippet": "top 10"},
    ])
    monkeypatch.setattr(events, "_ticketmaster", lambda *a, **k: [])
    leads = events.fetch({"target_industries": ["fintech"]}, limit=10)
    assert len(leads) == 1
    assert leads[0]["source"] == "events"
    assert "event_opportunity" in leads[0]["intent_signals"]
    assert "Summit" in leads[0]["person_name"]
    assert leads[0]["source_url"].startswith("https://eventbrite.com")


def test_no_terms_returns_empty():
    assert events.fetch({}, limit=5) == []

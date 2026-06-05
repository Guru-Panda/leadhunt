"""Competitor switch-intent source — pipeline verified with stubbed search/LLM."""
from __future__ import annotations

from backend.sources import competitor


def test_no_competitors_returns_empty():
    assert competitor.fetch({}, limit=5) == []


def test_skips_when_llm_unavailable(monkeypatch):
    monkeypatch.setattr(competitor, "llm_status", lambda: {"rate_limited": True})
    assert competitor.fetch({"competitors": ["Acme"]}, limit=5) == []


def test_extracts_grounded_switch_lead(monkeypatch):
    mention = "Acme is way too expensive, I'm switching to a cheaper tool"
    monkeypatch.setattr(competitor, "llm_status", lambda: {"rate_limited": False})
    monkeypatch.setattr(competitor, "web_search",
                        lambda q, limit=5: [{"title": "Reddit", "url": "https://reddit.com/r/x/1", "snippet": mention}])
    monkeypatch.setattr(competitor, "_negative_app_reviews", lambda name, max_reviews=30: [])
    monkeypatch.setattr(competitor, "llm_json",
                        lambda *a, **k: [{"person_name": "", "complaint": "Acme is way too expensive",
                                          "url": "https://reddit.com/r/x/1"}])
    leads = competitor.fetch({"competitors": ["Acme"], "_main_problem": "a cheaper tool"}, limit=5)
    assert len(leads) == 1
    lead = leads[0]
    assert lead["source"] == "competitor"
    assert "switch_intent" in lead["intent_signals"]
    assert "Acme" in lead["source_snippet"]
    assert lead["source_url"] == "https://reddit.com/r/x/1"


def test_drops_hallucinated_complaint(monkeypatch):
    # LLM invents a complaint not present in the gathered text → must be dropped.
    monkeypatch.setattr(competitor, "llm_status", lambda: {"rate_limited": False})
    monkeypatch.setattr(competitor, "web_search",
                        lambda q, limit=5: [{"title": "Reddit", "url": "https://reddit.com/r/x/2", "snippet": "Acme is great, love it"}])
    monkeypatch.setattr(competitor, "_negative_app_reviews", lambda name, max_reviews=30: [])
    monkeypatch.setattr(competitor, "llm_json",
                        lambda *a, **k: [{"person_name": "Nobody Real", "complaint": "totally fabricated rage quote",
                                          "url": "https://reddit.com/r/x/2"}])
    assert competitor.fetch({"competitors": ["Acme"]}, limit=5) == []

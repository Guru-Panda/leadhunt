"""Targeted-website source — site:-scoped extraction, graceful degradation."""
from __future__ import annotations

from backend.sources import sites


def test_no_websites_returns_empty():
    assert sites.fetch({}, limit=10) == []


def test_skips_when_llm_down(monkeypatch):
    monkeypatch.setattr(sites, "llm_status", lambda: {"rate_limited": True})
    assert sites.fetch({"target_websites": ["example.com"]}, limit=10) == []


def test_candidate_urls_scope_to_domain(monkeypatch):
    monkeypatch.setattr(sites, "web_search", lambda q, limit=4: [
        {"url": "https://example.com/team/jane"},
        {"url": "https://other.com/x"},  # off-domain — must be dropped
    ])
    urls = sites._candidate_urls("example.com", {"buyer_phrases": ["looking for"]})
    assert all("example.com" in u for u in urls)
    assert any("/team/jane" in u for u in urls)
    assert urls[0] == "https://example.com"  # root always probed first


def test_fetch_extracts_and_tags(monkeypatch):
    monkeypatch.setattr(sites, "llm_status", lambda: {"rate_limited": False})
    monkeypatch.setattr(sites, "web_search", lambda q, limit=4: [])
    # Stub the universal extractor the source imports lazily.
    import backend.pipeline.universal_extractor as ue
    monkeypatch.setattr(ue, "extract_leads_from_url", lambda url, strat: [
        {"person_name": "Jane Doe", "person_email": "jane@example.com", "context": "Head of Ops"}
    ])

    out = sites.fetch({"target_websites": ["example.com"], "_main_problem": "p", "_ideal_customer": "c"}, limit=10)
    assert len(out) >= 1
    lead = out[0]
    assert lead["source"] == "sites"
    assert lead["company_domain"] == "example.com"
    assert "from_target_site" in lead["intent_signals"]
    assert lead["external_id"].startswith("sites_example.com")

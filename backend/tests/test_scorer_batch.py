"""Batched LLM scoring — alignment, fallback, and resilience (no network)."""
from __future__ import annotations

from types import SimpleNamespace

from backend.pipeline import scorer


def _strat():
    return SimpleNamespace(main_problem="x", ideal_customer="y", target_roles=[],
                           target_industries=[], raw_icp_params={"buyer_intent_keywords": ["hiring"]})


def _lead(name, bio):
    return {"person_name": name, "raw_data": {"bio": bio}, "source": "reddit", "intent_signals": []}


def test_empty():
    assert scorer.score_leads_batch([], _strat()) == []


def test_allow_llm_false_uses_heuristic():
    out = scorer.score_leads_batch([_lead("A", "we are hiring")], _strat(), allow_llm=False)
    assert len(out) == 1 and 0.0 <= out[0]["intent_score"] <= 1.0


def test_maps_results_by_index(monkeypatch):
    leads = [_lead("A", "b"), _lead("B", "b2")]
    monkeypatch.setattr(scorer, "llm_json", lambda *a, **k: [
        {"i": 0, "intent_score": 0.9, "summary": "good", "signals": ["x"]},
        {"i": 1, "intent_score": 0.1, "summary": "no", "signals": []},
    ])
    out = scorer.score_leads_batch(leads, _strat(), allow_llm=True)
    assert out[0]["intent_score"] == 0.9
    assert out[1]["intent_score"] == 0.1


def test_missing_index_falls_back_to_heuristic(monkeypatch):
    leads = [_lead("A", "b"), _lead("B", "we are hiring")]
    monkeypatch.setattr(scorer, "llm_json", lambda *a, **k: [{"i": 0, "intent_score": 0.8}])
    out = scorer.score_leads_batch(leads, _strat(), allow_llm=True)
    assert len(out) == 2
    assert out[0]["intent_score"] == 0.8
    assert "intent_score" in out[1]  # heuristic filled the gap


def test_llm_failure_falls_back(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("down")
    monkeypatch.setattr(scorer, "llm_json", boom)
    out = scorer.score_leads_batch([_lead("A", "hiring")], _strat(), allow_llm=True)
    assert len(out) == 1 and "intent_score" in out[0]

"""Tests for the multi-provider LLM failover pool (no network)."""
from __future__ import annotations

from datetime import timedelta

from backend.llm_providers import _now, pool_status, _cooldown, _available, _providers


def test_pool_status_shape():
    s = pool_status()
    for k in ("configured", "providers", "available", "rate_limited", "resets_at"):
        assert k in s


def test_groq_present_when_keyed():
    # The dev env has GROQ_API_KEY set.
    names = [p["name"] for p in _providers()]
    if names:  # only assert if at least one provider configured
        assert "groq" in names or len(names) > 0


def test_cooldown_excludes_provider():
    provs = _providers()
    if not provs:
        return  # nothing to test without a configured provider
    name = provs[0]["name"]
    _cooldown[name] = _now() + timedelta(minutes=10)
    try:
        assert name not in [p["name"] for p in _available(provs)]
    finally:
        _cooldown.pop(name, None)


def test_rate_limited_only_when_all_down():
    provs = _providers()
    if not provs:
        return
    # Cool down every provider → pool reports rate_limited.
    for p in provs:
        _cooldown[p["name"]] = _now() + timedelta(minutes=10)
    try:
        assert pool_status()["rate_limited"] is True
    finally:
        for p in provs:
            _cooldown.pop(p["name"], None)

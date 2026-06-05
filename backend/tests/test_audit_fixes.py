"""Regression tests for the 2026-06-05 forensic-audit fixes.

Pure-function tests — no network, no DB, no LLM. Each asserts a specific bug
stays fixed. Run: `python -m pytest backend/tests -q` from the repo root.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest


def _strategy(**kw):
    base = dict(
        id=1, main_problem="", ideal_customer="", keywords=[],
        target_industries=[], target_roles=[], target_locations=[],
        buyer_phrases=[], raw_icp_params={},
    )
    base.update(kw)
    return SimpleNamespace(**base)


# ── Company-aware source selection ────────────────────────────────────────────

class TestSourceSelector:
    def test_dj_company_never_gets_github(self):
        from backend.pipeline.source_selector import classify_vertical, select_source_names
        s = _strategy(main_problem="We book wedding DJs for events",
                      ideal_customer="couples planning a wedding")
        assert classify_vertical(s) == "consumer_local"
        names, _ = select_source_names(s)
        assert "github" not in names
        assert "stackoverflow" not in names
        assert "reddit" in names  # consumer buyers are on reddit

    def test_dev_tool_gets_github(self):
        from backend.pipeline.source_selector import classify_vertical, select_source_names
        s = _strategy(main_problem="We sell an API load-testing SDK for developers",
                      ideal_customer="backend engineers at SaaS companies")
        assert classify_vertical(s) == "dev_tools"
        names, _ = select_source_names(s)
        assert "github" in names

    def test_dev_only_stripped_even_if_llm_recommends_them_for_nontech(self):
        # LLM leaks github into a consumer ICP — the hard guard must remove it.
        from backend.pipeline.source_selector import select_source_names
        s = _strategy(main_problem="wedding photography studio",
                      ideal_customer="engaged couples",
                      raw_icp_params={"recommended_sources": ["github", "reddit", "bing"]})
        names, _ = select_source_names(s)
        assert "github" not in names
        assert "reddit" in names and "bing" in names

    def test_never_empty(self):
        from backend.pipeline.source_selector import select_source_names
        names, _ = select_source_names(_strategy(main_problem="", ideal_customer=""))
        assert len(names) > 0


# ── Domain normalization (the lstrip("www.") bug) ─────────────────────────────

class TestDomainNormalization:
    def test_www_prefix_stripped(self):
        from backend.enrichment.email import _normalize_domain
        assert _normalize_domain("www.acme.com") == "acme.com"

    def test_non_www_domain_not_corrupted(self):
        # lstrip("www.") would have mangled these to "b.example.com" / "eb.x.com".
        from backend.enrichment.email import _normalize_domain
        assert _normalize_domain("web.example.com") == "web.example.com"
        assert _normalize_domain("https://news.ycombinator.com") == "news.ycombinator.com"

    def test_strips_scheme_and_path(self):
        from backend.enrichment.email import _normalize_domain
        assert _normalize_domain("https://www.Acme.com/contact") == "acme.com"


# ── Graded email confidence ───────────────────────────────────────────────────

class TestEmailConfidence:
    def test_published_email_high(self):
        from backend.enrichment.email import compute_email_confidence
        assert compute_email_confidence("source_text", False, True) >= 0.9

    def test_pattern_guess_low(self):
        from backend.enrichment.email import compute_email_confidence
        assert compute_email_confidence("pattern_guess", False, True) < 0.5

    def test_no_mx_heavily_discounted(self):
        from backend.enrichment.email import compute_email_confidence
        assert compute_email_confidence("pattern_guess", False, False) <= 0.2

    def test_verified_bumps_confidence(self):
        from backend.enrichment.email import compute_email_confidence
        assert compute_email_confidence("whois", True, True) >= 0.9


# ── Email de-obfuscation + Cloudflare decode ──────────────────────────────────

class TestExtractors:
    def test_at_dot_obfuscation(self):
        from backend.enrichment.extractors import extract_emails_from_text
        assert extract_emails_from_text("reach me at jane [at] acme [dot] com") == ["jane@acme.com"]
        assert extract_emails_from_text("john (at) foo (dot) io") == ["john@foo.io"]

    def test_no_false_positive_on_prose(self):
        from backend.enrichment.extractors import extract_emails_from_text
        assert extract_emails_from_text("let's meet at noon at the cafe") == []

    def test_plain_email(self):
        from backend.enrichment.extractors import extract_emails_from_text
        assert extract_emails_from_text("bob.smith@startup.dev here") == ["bob.smith@startup.dev"]

    def test_cloudflare_roundtrip(self):
        from backend.enrichment.extractors import decode_cfemail
        key = 0x7a
        email = "sam@corp.com"
        enc = format(key, "02x") + "".join(format(ord(c) ^ key, "02x") for c in email)
        assert decode_cfemail(enc) == email


# ── Apollo masked-email detection ─────────────────────────────────────────────

class TestApolloMask:
    def test_placeholder_is_masked(self):
        from backend.sources.apollo import _is_masked
        assert _is_masked("email_not_unlocked@domain.com") is True
        assert _is_masked(None) is True

    def test_real_email_not_masked(self):
        from backend.sources.apollo import _is_masked
        assert _is_masked("jane@realcompany.io") is False


# ── LinkedIn: name from title, not slug ───────────────────────────────────────

class TestLinkedInName:
    def test_name_from_title(self):
        from backend.sources.linkedin import _name_from_title
        assert _name_from_title("Jane Smith - VP of Sales at Acme | LinkedIn") == "Jane Smith"

    def test_rejects_non_name_title(self):
        from backend.sources.linkedin import _name_from_title
        assert _name_from_title("Top 10 Marketing Tips | Blog") is None


# ── HackerNews: no fabricated GitHub URL ──────────────────────────────────────

class TestHackerNewsNoFabrication:
    def test_no_fabricated_github_url(self):
        from backend.sources.hackernews import _build_lead
        lead = _build_lead("someuser", "123", "we are hiring engineers", "test")
        assert "person_github_url" not in lead
        # the HN profile page IS a valid contact link
        assert lead["source_profile_url"] == "https://news.ycombinator.com/user?id=someuser"


# ── Scorer heuristic path (LLM budget exhausted) ──────────────────────────────

class TestScorerHeuristic:
    def test_allow_llm_false_returns_heuristic_without_network(self):
        from backend.pipeline.scorer import score_lead_smart
        s = _strategy(raw_icp_params={"buyer_intent_keywords": ["hiring"]})
        lead = {"source": "linkedin", "person_name": "Jane Doe",
                "raw_data": {"bio": "we are hiring"}, "source_snippet": "hiring now",
                "intent_signals": []}
        r = score_lead_smart(lead, s, allow_llm=False)
        assert "intent_score" in r and 0.0 <= r["intent_score"] <= 1.0
        assert "LLM" in r["ai_summary"] or "Heuristic" in r["ai_summary"]


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))

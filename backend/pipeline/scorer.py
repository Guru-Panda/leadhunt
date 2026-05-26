from __future__ import annotations

import logging
import re

from backend.llm import llm_json

log = logging.getLogger(__name__)


def _signal_label(score: float) -> str:
    if score >= 0.85:
        return "Strong buying signal — highly likely to purchase"
    if score >= 0.7:
        return "Strong buying signal"
    if score >= 0.5:
        return "Moderate buying signal"
    if score >= 0.3:
        return "Weak signal — may be worth a soft outreach"
    return "Minimal signal — likely not a fit"


def _compute_matched_keywords(content: str, intent_keywords: list[str]) -> list[str]:
    """Substring match (case-insensitive) of each intent keyword against the lead's content."""
    if not content or not intent_keywords:
        return []
    haystack = content.lower()
    return [kw for kw in intent_keywords if kw and kw.lower() in haystack]


def score_lead(lead: dict, strategy) -> dict:
    """Rate a lead 0.0-1.0 + collect PROOF of why.

    Returns dict with:
      - intent_score: float
      - reasoning: str (kept for backwards-compat)
      - intent_signals: list[str] (kept for backwards-compat)
      - matched_phrases: list[str] (verbatim quotes from the lead's content proving intent)
      - matched_keywords: list[str] (intent keywords that appeared in content, computed locally)
      - ai_summary: str (1-sentence "why this person is a buyer")
      - signal_label: str ("Strong buying signal" / etc., derived from score)
    """
    bio = str((lead.get("raw_data") or {}).get("bio", ""))[:600]
    context = str((lead.get("raw_data") or {}).get("context", ""))[:300]
    snippet = str(lead.get("source_snippet") or "")[:600]
    full_content = f"{bio}\n{context}\n{snippet}".strip()

    intent_keywords = []
    if strategy.raw_icp_params:
        intent_keywords = strategy.raw_icp_params.get("buyer_intent_keywords", []) or []

    intent_block = ""
    if intent_keywords:
        intent_block = f"""

⚠️ CRITICAL — BUYER INTENT FILTER:
The strategy looks for people whose content shows ANY of these intent signals:
{intent_keywords}

The lead is ONLY useful if their bio / post / company description SHOWS that intent.
- Industry+role match but NO intent signal in content → max 0.3.
- Use the WORDS the person actually wrote, not assumptions about their role."""

    prompt = f"""Score this person 0.0-1.0 as a potential customer AND extract proof.

OUR ICP:
- We solve: {strategy.main_problem}
- Ideal customer: {strategy.ideal_customer}
- Target roles: {strategy.target_roles}
- Target industries: {strategy.target_industries}{intent_block}

THIS PERSON:
- Name: {lead.get('person_name')}
- Title: {lead.get('person_title') or 'unknown'}
- Company: {lead.get('company_name') or 'unknown'} ({lead.get('company_industry') or 'unknown'})
- Source: {lead.get('source')}
- Existing intent signals: {lead.get('intent_signals', [])}
- Content (bio + context + snippet):
\"\"\"
{full_content[:1800]}
\"\"\"

Return ONLY JSON. Be RIGOROUS — never make up phrases not in the content.

{{
  "intent_score": 0.0,
  "ai_summary": "1 short sentence — why THIS person is (or isn't) a potential buyer for our ICP. Reference what they actually said.",
  "matched_phrases": [
    "verbatim 5-15 word quote from the content showing buyer intent",
    "another verbatim quote",
    "..."
  ],
  "intent_signals": ["short_tag1", "another_tag"]
}}

RULES:
- matched_phrases MUST be verbatim substrings of the content above. Up to 3. Empty list if nothing matches.
- Score 0.8-1.0 only if you can quote phrases that clearly show buyer intent.
- Score 0.5-0.7 if there's industry/role match plus weak intent signal.
- Score 0.0-0.3 if it's just generic industry match with no intent."""

    try:
        result = llm_json(prompt, high_quality=False, max_tokens=400)
        score = max(0.0, min(1.0, float(result.get("intent_score", 0.0))))

        # Verify matched_phrases are actually substrings (LLM can hallucinate)
        raw_phrases = result.get("matched_phrases", []) or []
        content_lower = full_content.lower()
        verified_phrases = [
            p.strip() for p in raw_phrases
            if isinstance(p, str) and p.strip() and p.strip().lower() in content_lower
        ][:3]

        return {
            "intent_score": score,
            "reasoning": result.get("ai_summary", ""),
            "intent_signals": result.get("intent_signals", []) or lead.get("intent_signals", []),
            "matched_phrases": verified_phrases,
            "matched_keywords": _compute_matched_keywords(full_content, intent_keywords),
            "ai_summary": result.get("ai_summary", ""),
            "signal_label": _signal_label(score),
        }
    except Exception as e:
        log.warning(f"Scoring failed for {lead.get('person_name')}: {e}")
        return {
            "intent_score": 0.4,
            "reasoning": "Scoring unavailable",
            "intent_signals": lead.get("intent_signals", []),
            "matched_phrases": [],
            "matched_keywords": _compute_matched_keywords(full_content, intent_keywords),
            "ai_summary": "Scoring unavailable — please review manually.",
            "signal_label": _signal_label(0.4),
        }

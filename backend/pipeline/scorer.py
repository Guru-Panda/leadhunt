from __future__ import annotations

import logging

from backend.llm import llm_json

log = logging.getLogger(__name__)


def score_lead(lead: dict, strategy) -> dict:
    """Rate a lead 0.0-1.0 as a potential customer.

    Sources like HackerNews and Reddit rarely include explicit title/company —
    the buyer-intent signal IS the source itself (someone posted asking for
    help, hiring for the role, etc.). So we tell the LLM to weigh bio/context
    and the source signal, not penalize missing structured fields.
    """
    bio = str((lead.get("raw_data") or {}).get("bio", ""))[:600]
    context = str((lead.get("raw_data") or {}).get("context", ""))[:300]

    prompt = f"""Score this person 0.0-1.0 as a potential customer.

OUR ICP:
- We solve: {strategy.main_problem}
- Ideal customer: {strategy.ideal_customer}
- Target roles: {strategy.target_roles}
- Target industries: {strategy.target_industries}

THIS PERSON:
- Name: {lead.get('person_name')}
- Title: {lead.get('person_title') or 'unknown'}
- Company: {lead.get('company_name') or 'unknown'} ({lead.get('company_industry') or 'unknown'})
- Location: {lead.get('person_location') or 'unknown'}
- Source: {lead.get('source')}
- Intent signals: {lead.get('intent_signals', [])}
- Context: {context}
- Bio / post content: {bio}

SCORING RULES:
- DO NOT auto-penalize unknown title/company. Many leads come from forums/communities where titles aren't stated. Judge based on what IS visible.
- If bio/context strongly matches our ICP (mentions our target tech, industry, or problem) → 0.7-0.9.
- If person clearly fits target role/industry → 0.7-1.0.
- If source signal is strong (e.g. actively_hiring our role, buyer_intent_post, yc_founder) → at least 0.5.
- If bio/context is empty AND no other strong signal → 0.2-0.4.
- Reserve 0.0-0.2 only for clearly irrelevant matches (wrong industry, anti-target keywords).

Return ONLY JSON (no markdown, no commentary):
{{
  "intent_score": 0.0,
  "reasoning": "one sentence",
  "intent_signals": ["signal1", "signal2"]
}}"""

    try:
        result = llm_json(prompt, high_quality=False, max_tokens=250)
        score = float(result.get("intent_score", 0.0))
        return {
            "intent_score": max(0.0, min(1.0, score)),
            "reasoning": result.get("reasoning", ""),
            "intent_signals": result.get("intent_signals", []) or lead.get("intent_signals", []),
        }
    except Exception as e:
        log.warning(f"Scoring failed for {lead.get('person_name')}: {e}")
        # On failure, fall back to a mid-range score so leads aren't lost
        return {"intent_score": 0.4, "reasoning": "Scoring unavailable", "intent_signals": lead.get("intent_signals", [])}

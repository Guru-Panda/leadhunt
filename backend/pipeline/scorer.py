from __future__ import annotations

import logging

from backend.llm import llm_json

log = logging.getLogger(__name__)


def score_lead(lead: dict, strategy) -> dict:
    """Rate a lead 0.0-1.0 as a potential customer.

    When the strategy's ICP includes buyer_intent_keywords, the scorer's
    PRIMARY job is to verify the lead's content shows that exact intent.
    A 'CTO at a fintech' isn't a lead if our intent is 'sponsors podcasts'
    and nothing in their bio mentions sponsorship.
    """
    bio = str((lead.get("raw_data") or {}).get("bio", ""))[:600]
    context = str((lead.get("raw_data") or {}).get("context", ""))[:300]
    snippet = str(lead.get("source_snippet") or "")[:600]
    full_content = f"{bio}\n{context}\n{snippet}".strip()

    intent_keywords = (strategy.raw_icp_params or {}).get("buyer_intent_keywords", []) if strategy.raw_icp_params else []

    intent_block = ""
    if intent_keywords:
        intent_block = f"""

⚠️ CRITICAL — BUYER INTENT FILTER:
This strategy is looking for people/companies whose buyer signal includes:
{intent_keywords}

The lead is ONLY useful if their bio / post / company description SHOWS this intent.
- If you can find any of those keywords (or clear semantic equivalents) in the content below → high score.
- If the content is just generic industry-match with NO trace of the intent signal → score <= 0.3.
- Use the WORDS the person actually wrote/published, not assumptions about their role."""

    prompt = f"""Score this person 0.0-1.0 as a potential customer.

OUR ICP:
- We solve: {strategy.main_problem}
- Ideal customer: {strategy.ideal_customer}
- Target roles: {strategy.target_roles}
- Target industries: {strategy.target_industries}{intent_block}

THIS PERSON:
- Name: {lead.get('person_name')}
- Title: {lead.get('person_title') or 'unknown'}
- Company: {lead.get('company_name') or 'unknown'} ({lead.get('company_industry') or 'unknown'})
- Location: {lead.get('person_location') or 'unknown'}
- Source: {lead.get('source')}
- Existing intent signals: {lead.get('intent_signals', [])}
- Content (bio + context + snippet):
\"\"\"
{full_content[:1500]}
\"\"\"

SCORING RULES:
- {'Intent match is REQUIRED — see CRITICAL filter above.' if intent_keywords else 'Judge fit by content, role, industry.'}
- DO NOT auto-penalize unknown title/company. Forums/communities often omit titles.
- Strong industry+role+intent match → 0.8-1.0
- Strong industry+role match but no intent signal in content → max 0.3
- Generic match with no specific signal → 0.2-0.4
- Clearly wrong (anti-target keywords, off-topic content) → 0.0-0.1

Return ONLY JSON:
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

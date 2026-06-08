from __future__ import annotations

import logging
import re

from backend.llm import llm_json
from backend.pipeline import learning

log = logging.getLogger(__name__)


def _apply_learning(result: dict, lead: dict, strategy) -> dict:
    """Nudge a scored result by the strategy's learned approve/reject preferences.

    Bounded (±0.15) and re-derives the signal label so the UI stays consistent.
    No-op until the user has rated a few leads.
    """
    profile = getattr(strategy, "learning_profile", None)
    delta = learning.score_adjustment(lead, profile)
    if not delta:
        return result
    new_score = max(0.0, min(1.0, result.get("intent_score", 0.0) + delta))
    result["intent_score"] = new_score
    result["signal_label"] = _signal_label(new_score)
    result["learning_delta"] = round(delta, 3)
    return result


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


def _heuristic_score(lead: dict, content: str, icp: dict) -> dict:
    """Keyword-overlap fallback used when the LLM is unavailable (e.g. Groq daily
    cap hit). Keeps relevant leads alive instead of zeroing everything out.

    Scoring is based on how many distinct ICP signal-buckets the content hits:
      - intent keyword present       → strongest signal
      - industry term present        → medium
      - role term present            → medium
    """
    blob = content.lower()
    name = lead.get("person_name", "")
    matched_intent = _compute_matched_keywords(content, icp.get("buyer_intent_keywords", []) or [])
    industries = icp.get("target_industries") or icp.get("industries") or []
    roles = icp.get("target_roles") or []

    def _any_word(terms: list[str]) -> list[str]:
        hits = []
        for phrase in terms:
            for w in str(phrase).lower().split():
                if len(w) >= 3 and w in blob:
                    hits.append(phrase)
                    break
        return hits

    matched_inds = _any_word(industries)
    matched_roles = _any_word(roles)

    signals = set(lead.get("intent_signals", []))

    # Source signals that already encode strong ICP confidence — trust them
    # even when the LLM is unavailable. These signals come from targeted queries
    # (site:linkedin.com/in "role" "industry", buyer_phrase search, etc.) so a
    # match here is already meaningful.
    profile_signals = {
        "linkedin_icp_match",           # found via role×industry LinkedIn search
        "profile_role_industry_match",  # same
        "linkedin_profile_match",       # Google CSE LinkedIn result
        "apollo_icp_match",             # Apollo DB match on role+industry+location
        "verified_contact",             # Apollo verified email present
    }
    intent_signals = {
        "buyer_intent_post",        # Reddit/SO/DevTo post expressing a need
        "active_github_issue",      # opened an issue requesting a solution
        "active_so_question",       # asked SO question about our domain
        "active_hiring_thread",     # in HN Who-is-Hiring
        "active_hiring_signal",     # company hiring for our target role (jobs source)
        "company_growth_signal",    # growth signal from job postings
        "intent_match",
        "intent_in_one_liner",
        "email_in_post",
        "switch_intent",          # unhappy with a competitor → warm switch lead
        "competitor_complaint",
        "event_opportunity",      # event/webinar/conference to attend or sponsor
    }

    # Start from the strongest signal present, not a flat baseline
    if profile_signals & signals:
        score = 0.55  # already targeted by ICP query — likely a real match
    elif intent_signals & signals:
        score = 0.50  # actively expressing a need
    else:
        score = 0.30  # generic lead, needs keyword evidence to pass

    if matched_intent:
        score += 0.20
    if matched_inds:
        score += 0.10
    if matched_roles:
        score += 0.08
    score = max(0.0, min(1.0, score))

    summary_bits = []
    if matched_intent:
        summary_bits.append(f"mentions {', '.join(matched_intent[:2])}")
    if matched_inds:
        summary_bits.append(f"in {matched_inds[0]}")
    summary = (
        f"Heuristic match: {name} " + ("; ".join(summary_bits) if summary_bits else "shares some ICP terms")
        + " (LLM scoring unavailable — verify manually)."
    )

    return {
        "intent_score": score,
        "reasoning": summary,
        "intent_signals": lead.get("intent_signals", []),
        "matched_phrases": [],
        "matched_keywords": matched_intent,
        "ai_summary": summary,
        "signal_label": _signal_label(score),
    }


# Sources where the lead's POST/QUESTION content IS the buying signal.
# These get scored with score_post_for_intent() (MarketingAI style) — we read
# what they actually wrote and judge whether they're a buyer RIGHT NOW.
POST_BASED_SOURCES = {
    "reddit",
    "stackoverflow",
    "devto",
    "indiehackers",
    "bing",
    "hackernews",
}

# Sources that return ICP-matched PROFILES (no active post). These get scored
# with score_lead() — judged on role/industry/company fit, not live intent.
PROFILE_BASED_SOURCES = {
    "apollo",
    "linkedin",
    "google_cse",
}


def score_lead_smart(lead: dict, strategy, allow_llm: bool = True) -> dict:
    """Dispatch to the right scorer based on the lead's source.

    - Post-based sources (Reddit, SO, Dev.to, IH, web search, HN): the content
      the person wrote is the buying signal → score_post_for_intent().
    - Profile-based sources (Apollo, LinkedIn, Google CSE): no live post, just an
      ICP-matched profile → score_lead().
    - GitHub & discovered sources: fall through to score_lead() which already
      handles their intent_signals.
    """
    source = (lead.get("source") or "").split(":")[0]  # strip "discovered:" prefix
    icp = strategy.raw_icp_params or {}

    if source in POST_BASED_SOURCES:
        rd = lead.get("raw_data") or {}
        bio = str(rd.get("bio", ""))[:500]
        context = str(rd.get("context", ""))[:300]
        snippet = str(lead.get("source_snippet") or "")[:500]
        content = f"{bio}\n{context}\n{snippet}".strip()

        icp_ctx = {
            **icp,
            "_main_problem": strategy.main_problem,
            "_ideal_customer": strategy.ideal_customer,
        }
        result = score_post_for_intent(content, icp_ctx, allow_llm=allow_llm)

        score = result.get("intent_score", 0.0)
        summary = result.get("summary", "")
        matched_kw = result.get("matched_keywords", [])
        signals = result.get("signals", []) or lead.get("intent_signals", [])

        content_lower = content.lower()
        verified_phrases = [
            k for k in matched_kw
            if isinstance(k, str) and k.strip() and k.strip().lower() in content_lower
        ][:3]

        return _apply_learning({
            "intent_score": score,
            "reasoning": summary,
            "intent_signals": signals,
            "matched_phrases": verified_phrases,
            "matched_keywords": _compute_matched_keywords(content, icp.get("buyer_intent_keywords", []) or []),
            "ai_summary": summary,
            "signal_label": _signal_label(score),
        }, lead, strategy)

    # Profile-based and everything else → ICP-fit scoring
    return score_lead(lead, strategy, allow_llm=allow_llm)


def _lead_content(lead: dict) -> str:
    rd = lead.get("raw_data") or {}
    return f"{rd.get('bio','')}\n{rd.get('context','')}\n{lead.get('source_snippet','')}".strip()


def score_leads_batch(leads: list[dict], strategy, allow_llm: bool = True) -> list[dict]:
    """Score many leads in ONE LLM call instead of one call per lead.

    Cuts LLM usage ~Nx (N = batch size), which is the difference between scoring
    480 leads/run vs 60 on a free tier. Falls back to the per-lead heuristic for
    any entry the model omits, and for the whole batch if the LLM is unavailable.
    Returns a scored dict per input lead, in order.
    """
    icp = strategy.raw_icp_params or {}
    if not leads:
        return []
    if not allow_llm:
        return [_apply_learning(_heuristic_score(l, _lead_content(l), icp), l, strategy) for l in leads]

    intent_kws = icp.get("buyer_intent_keywords", []) or []
    entries = "\n\n".join(
        f"[{i}] name={l.get('person_name','?')} | title={l.get('person_title') or '?'} | source={l.get('source')}\n"
        f"content: {_lead_content(l)[:400]}"
        for i, l in enumerate(leads)
    )
    prompt = f"""Score EACH entry 0.0-1.0 as a potential customer for our ICP.

OUR ICP:
- We solve: {strategy.main_problem}
- Ideal customer: {strategy.ideal_customer}
- Target roles: {strategy.target_roles}
- Target industries: {strategy.target_industries}
- Buyer intent keywords: {intent_kws}

ENTRIES:
{entries}
{learning.prompt_hint(getattr(strategy, "learning_profile", None))}
Return ONLY a JSON list — exactly one object per entry index:
[{{"i": 0, "intent_score": 0.0, "summary": "one sentence referencing what they said", "signals": ["tag"]}}]
Scoring: 0.8-1.0 = clear buyer intent; 0.5-0.7 = solid role/industry fit; 0.3-0.5 = weak; 0.0-0.2 = off-topic. Be rigorous."""

    try:
        result = llm_json(prompt, high_quality=False, max_tokens=min(3000, 130 * len(leads) + 300))
        by_i: dict[int, dict] = {}
        if isinstance(result, list):
            for o in result:
                if isinstance(o, dict) and "i" in o:
                    try:
                        by_i[int(o["i"])] = o
                    except (TypeError, ValueError):
                        continue
    except Exception as e:
        log.warning(f"batch scoring failed ({e}) — heuristic fallback for {len(leads)} leads")
        return [_apply_learning(_heuristic_score(l, _lead_content(l), icp), l, strategy) for l in leads]

    out: list[dict] = []
    for i, l in enumerate(leads):
        o = by_i.get(i)
        content = _lead_content(l)
        if not o:
            out.append(_apply_learning(_heuristic_score(l, content, icp), l, strategy))
            continue
        score = max(0.0, min(1.0, float(o.get("intent_score", 0.0) or 0.0)))
        out.append(_apply_learning({
            "intent_score": score,
            "reasoning": o.get("summary", ""),
            "intent_signals": o.get("signals") or l.get("intent_signals", []),
            "matched_phrases": [],
            "matched_keywords": _compute_matched_keywords(content, intent_kws),
            "ai_summary": o.get("summary", ""),
            "signal_label": _signal_label(score),
        }, l, strategy))
    return out


def score_post_for_intent(content: str, icp_params: dict, allow_llm: bool = True) -> dict:
    """Score raw post/comment content for BUYING INTENT (0.0-1.0).

    Ported from MarketingAI's score_post() — intended for post-based sources
    (SO, Dev.to, IndieHackers, GitHub issues) where the post IS the buying signal.

    Returns:
        intent_score: float
        summary: str
        matched_keywords: list[str]
        signals: list[str]
    """
    buyer_phrases = icp_params.get("buyer_phrases") or []
    intent_kws = icp_params.get("buyer_intent_keywords") or []
    main_problem = icp_params.get("_main_problem") or ""
    ideal_customer = icp_params.get("_ideal_customer") or ""

    kw_str = ", ".join(intent_kws[:10]) if intent_kws else ""
    phrase_block = "\n".join(f"  - {p}" for p in buyer_phrases[:8]) if buyer_phrases else ""

    context_lines = []
    if main_problem:
        context_lines.append(f"Problem the business solves: {main_problem}")
    if ideal_customer:
        context_lines.append(f"Ideal customer: {ideal_customer}")
    if phrase_block:
        context_lines.append(f"Buyer phrases to look for:\n{phrase_block}")
    if kw_str:
        context_lines.append(f"Intent keywords: {kw_str}")
    context_block = "\n".join(context_lines)

    if not allow_llm:
        # LLM budget exhausted / rate-limited — heuristic without burning a call.
        matched = _compute_matched_keywords(content, intent_kws)
        score = 0.4 + (0.2 if matched else 0.0)
        return {
            "intent_score": score,
            "summary": f"Heuristic (LLM skipped): {'matched ' + ', '.join(matched[:2]) if matched else 'no strong signal'}",
            "matched_keywords": matched,
            "signals": ["buyer_intent_post"] if matched else [],
        }

    prompt = f"""Score this post/question for BUYER INTENT — how likely is the author to be actively seeking our solution?

Business context:
{context_block}

HIGH score (0.8-1.0): actively looking for this type of product/service, asking for recommendations, describing a problem we solve, ready to spend.
LOW score (0.0-0.3): general discussion, off-topic, author is NOT a potential buyer.

Post:
{content[:1500]}

Return ONLY valid JSON:
{{
  "intent_score": <0.0-1.0>,
  "summary": "<one sentence: why this person is or isn't a potential buyer>",
  "matched_keywords": ["<matched intent keywords/phrases found in post>"],
  "signals": ["<short_tag>"]
}}"""

    try:
        result = llm_json(prompt, high_quality=False, max_tokens=200)
        score = max(0.0, min(1.0, float(result.get("intent_score", 0.0))))
        return {
            "intent_score": score,
            "summary": result.get("summary", ""),
            "matched_keywords": result.get("matched_keywords", []),
            "signals": result.get("signals", []),
        }
    except Exception as e:
        log.warning(f"score_post_for_intent failed ({e}) — heuristic fallback")
        matched = _compute_matched_keywords(content, intent_kws)
        score = 0.4 + (0.2 if matched else 0.0)
        return {
            "intent_score": score,
            "summary": f"Heuristic: {'matched ' + ', '.join(matched[:2]) if matched else 'no strong signal'}",
            "matched_keywords": matched,
            "signals": ["buyer_intent_post"] if matched else [],
        }


def score_lead(lead: dict, strategy, allow_llm: bool = True) -> dict:
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
    # Trimmed windows to conserve Groq daily token budget
    bio = str((lead.get("raw_data") or {}).get("bio", ""))[:350]
    context = str((lead.get("raw_data") or {}).get("context", ""))[:200]
    snippet = str(lead.get("source_snippet") or "")[:350]
    full_content = f"{bio}\n{context}\n{snippet}".strip()

    if not allow_llm:
        # LLM budget exhausted / rate-limited — heuristic without burning a call.
        return _apply_learning(_heuristic_score(lead, full_content, strategy.raw_icp_params or {}), lead, strategy)

    intent_keywords = []
    if strategy.raw_icp_params:
        intent_keywords = strategy.raw_icp_params.get("buyer_intent_keywords", []) or []

    intent_block = ""
    if intent_keywords:
        intent_block = f"""

BUYER INTENT KEYWORDS (boost matching, don't auto-reject):
The strategy looks for buyer signals like:
{intent_keywords}

- If the content clearly shows ANY of these (or close synonym) → boost to 0.75-1.0.
- If just industry/role match but NO intent signal → cap around 0.5 (still passable, sorts lower).
- Use the WORDS the person actually wrote, don't assume from their role."""

    prompt = f"""Score this person 0.0-1.0 as a potential customer AND extract proof.

OUR ICP:
- We solve: {strategy.main_problem}
- Ideal customer: {strategy.ideal_customer}
- Target roles: {strategy.target_roles}
- Target industries: {strategy.target_industries}{intent_block}{learning.prompt_hint(getattr(strategy, "learning_profile", None))}

THIS PERSON:
- Name: {lead.get('person_name')}
- Title: {lead.get('person_title') or 'unknown'}
- Company: {lead.get('company_name') or 'unknown'} ({lead.get('company_industry') or 'unknown'})
- Source: {lead.get('source')}
- Existing intent signals: {lead.get('intent_signals', [])}
- Content (bio + context + snippet):
\"\"\"
{full_content[:900]}
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
- Score 0.8-1.0 if you can quote phrases showing CLEAR buyer intent.
- Score 0.5-0.7 if there's solid industry/role match, even without explicit intent.
- Score 0.3-0.5 if content is sparse but industry hints align.
- Score 0.0-0.2 only when clearly off-topic / wrong industry."""

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

        return _apply_learning({
            "intent_score": score,
            "reasoning": result.get("ai_summary", ""),
            "intent_signals": result.get("intent_signals", []) or lead.get("intent_signals", []),
            "matched_phrases": verified_phrases,
            "matched_keywords": _compute_matched_keywords(full_content, intent_keywords),
            "ai_summary": result.get("ai_summary", ""),
            "signal_label": _signal_label(score),
        }, lead, strategy)
    except Exception as e:
        # LLM unavailable (often Groq daily token cap). Fall back to a keyword
        # heuristic so relevant leads still survive instead of all scoring 0.4.
        log.warning(f"LLM scoring failed for {lead.get('person_name')} ({e}) — using heuristic fallback")
        icp = strategy.raw_icp_params or {}
        return _apply_learning(_heuristic_score(lead, full_content, icp), lead, strategy)

"""Feedback learning loop.

LeadHunt watches which leads the user APPROVES (thumbs-up / qualified / contacted)
vs REJECTS (thumbs-down / rejected) and distils that into a per-strategy
`learning_profile`. The profile then biases future hunting in two bounded,
fully-reversible ways:

  1. Scoring — `score_adjustment()` nudges each new lead's intent score up or down
     (capped at ±0.15) based on whether it resembles what the user kept or trashed.
  2. Source order — `apply_source_preferences()` floats sources that have produced
     approved leads to the front and demotes sources the user keeps rejecting.

Nothing here ever deletes a lead or hard-filters a source; it only re-weights.
The profile is recomputed cheaply whenever feedback changes and at each sync.
"""
from __future__ import annotations

import logging
import re
from collections import Counter

log = logging.getLogger(__name__)

# Bounded so learning can refine, never dominate, the base intent score.
MAX_ADJUSTMENT = 0.15

# Statuses/feedback that count as a positive or negative signal.
_APPROVE_STATUSES = {"qualified", "contacted", "liked", "won"}
_REJECT_STATUSES = {"rejected", "ignored"}

_STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "from", "have", "has", "are", "was",
    "you", "your", "our", "their", "them", "they", "what", "when", "where", "how",
    "who", "his", "her", "its", "but", "not", "all", "any", "can", "will", "just",
    "about", "into", "out", "over", "more", "than", "then", "some", "such", "also",
    "looking", "found", "opportunity", "event", "signal", "lead", "leads", "http",
    "https", "www", "com", "would", "could", "should", "been", "were", "there",
    "here", "very", "much", "many", "make", "made", "need", "needs", "want", "wants",
}

_WORD = re.compile(r"[a-z][a-z0-9+#.\-]{2,}")


def _lead_blob(lead) -> str:
    """All free text we have about a lead, lowercased — used for term matching."""
    rd = getattr(lead, "raw_data", None)
    if rd is None and isinstance(lead, dict):
        rd = lead.get("raw_data")
    rd = rd or {}
    parts = [
        _attr(lead, "person_title"),
        _attr(lead, "company_industry"),
        _attr(lead, "source_snippet"),
        str(rd.get("bio", "")),
        str(rd.get("context", "")),
    ]
    return " ".join(p for p in parts if p).lower()


def _attr(obj, key: str):
    if isinstance(obj, dict):
        return obj.get(key) or ""
    return getattr(obj, key, "") or ""


def _tokens(text: str) -> set[str]:
    return {w for w in _WORD.findall(text) if w not in _STOPWORDS and not w.isdigit()}


def compute_learning_profile(strategy, db) -> dict:
    """Aggregate the user's approve/reject history for `strategy` into a profile dict.

    Cheap enough to run on every feedback change. Returns {} when there isn't
    enough signal yet (so scoring stays neutral until the user has rated a few).
    """
    from backend.models import Lead

    leads = (
        db.query(Lead)
        .filter(Lead.strategy_id == strategy.id, Lead.user_id == strategy.user_id)
        .all()
    )

    approved, rejected = [], []
    for l in leads:
        if l.feedback == 1 or (l.status or "") in _APPROVE_STATUSES:
            approved.append(l)
        elif l.feedback == -1 or (l.status or "") in _REJECT_STATUSES:
            rejected.append(l)

    n_app, n_rej = len(approved), len(rejected)
    if n_app + n_rej < 3:
        # Not enough rated leads to learn anything trustworthy yet.
        return {"n_approved": n_app, "n_rejected": n_rej}

    # ── Term frequencies (document frequency: # of leads containing the term) ──
    app_terms: Counter[str] = Counter()
    rej_terms: Counter[str] = Counter()
    for l in approved:
        app_terms.update(_tokens(_lead_blob(l)))
    for l in rejected:
        rej_terms.update(_tokens(_lead_blob(l)))

    liked_terms, disliked_terms = [], []
    for term in set(app_terms) | set(rej_terms):
        a, r = app_terms[term], rej_terms[term]
        if a + r < 2:
            continue  # too rare to be a reliable signal
        # Normalised rates so an imbalance between approved/rejected counts doesn't skew it.
        a_rate = a / max(n_app, 1)
        r_rate = r / max(n_rej, 1)
        if a_rate - r_rate >= 0.34:
            liked_terms.append((term, round(a_rate - r_rate, 3)))
        elif r_rate - a_rate >= 0.34:
            disliked_terms.append((term, round(r_rate - a_rate, 3)))

    liked_terms.sort(key=lambda t: -t[1])
    disliked_terms.sort(key=lambda t: -t[1])

    # ── Source approval rates ──
    src_app: Counter[str] = Counter(l.source for l in approved)
    src_rej: Counter[str] = Counter(l.source for l in rejected)
    liked_sources, disliked_sources = [], []
    for src in set(src_app) | set(src_rej):
        a, r = src_app[src], src_rej[src]
        if a + r < 2:
            continue
        rate = (a - r) / (a + r)
        if rate >= 0.4:
            liked_sources.append(src)
        elif rate <= -0.4:
            disliked_sources.append(src)

    # ── Intent-signal approval ──
    sig_app: Counter[str] = Counter(s for l in approved for s in (l.intent_signals or []))
    sig_rej: Counter[str] = Counter(s for l in rejected for s in (l.intent_signals or []))
    liked_signals = [s for s in sig_app if sig_app[s] - sig_rej[s] >= 2]
    disliked_signals = [s for s in sig_rej if sig_rej[s] - sig_app[s] >= 2]

    profile = {
        "n_approved": n_app,
        "n_rejected": n_rej,
        "liked_terms": [t for t, _ in liked_terms[:15]],
        "disliked_terms": [t for t, _ in disliked_terms[:15]],
        "liked_sources": liked_sources,
        "disliked_sources": disliked_sources,
        "liked_signals": liked_signals,
        "disliked_signals": disliked_signals,
    }
    log.info(
        f"[learning] strategy={strategy.id} approved={n_app} rejected={n_rej} "
        f"liked_terms={profile['liked_terms'][:5]} disliked_terms={profile['disliked_terms'][:5]}"
    )
    return profile


def update_learning_profile(strategy, db) -> dict:
    """Recompute and persist the profile on the strategy. Returns it."""
    profile = compute_learning_profile(strategy, db)
    strategy.learning_profile = profile
    db.commit()
    return profile


def score_adjustment(lead, profile: dict | None) -> float:
    """Bounded score delta (−0.15…+0.15) from how the lead matches learned likes/dislikes."""
    if not profile or (profile.get("n_approved", 0) + profile.get("n_rejected", 0)) < 3:
        return 0.0

    blob_tokens = _tokens(_lead_blob(lead))
    delta = 0.0

    liked = set(profile.get("liked_terms") or [])
    disliked = set(profile.get("disliked_terms") or [])
    delta += 0.05 * len(blob_tokens & liked)
    delta -= 0.06 * len(blob_tokens & disliked)

    src = (_attr(lead, "source") or "").split(":")[0]
    if src in (profile.get("liked_sources") or []):
        delta += 0.03
    if src in (profile.get("disliked_sources") or []):
        delta -= 0.05

    signals = set(_attr(lead, "intent_signals") or [])
    if signals & set(profile.get("liked_signals") or []):
        delta += 0.04
    if signals & set(profile.get("disliked_signals") or []):
        delta -= 0.05

    return max(-MAX_ADJUSTMENT, min(MAX_ADJUSTMENT, delta))


def prompt_hint(profile: dict | None) -> str:
    """Short natural-language hint for the LLM scorer, or '' if nothing learned yet."""
    if not profile or (profile.get("n_approved", 0) + profile.get("n_rejected", 0)) < 3:
        return ""
    liked = ", ".join((profile.get("liked_terms") or [])[:8])
    disliked = ", ".join((profile.get("disliked_terms") or [])[:8])
    bits = []
    if liked:
        bits.append(f"the user has APPROVED leads mentioning: {liked}")
    if disliked:
        bits.append(f"the user has REJECTED leads mentioning: {disliked}")
    if not bits:
        return ""
    return (
        "\n\nLEARNED USER PREFERENCES (weigh these — "
        + "; ".join(bits)
        + "). Nudge scores toward approved-style leads and away from rejected-style ones."
    )


def apply_source_preferences(names: list[str], profile: dict | None) -> list[str]:
    """Reorder source names: liked sources first, disliked sources last. Never drops any."""
    if not profile:
        return names
    liked = set(profile.get("liked_sources") or [])
    disliked = set(profile.get("disliked_sources") or [])
    if not liked and not disliked:
        return names

    def rank(n: str) -> int:
        base = n.split(":")[0]
        if base in liked:
            return 0
        if base in disliked:
            return 2
        return 1

    # Stable sort preserves the original (vertical-driven) order within each tier.
    return sorted(names, key=rank)

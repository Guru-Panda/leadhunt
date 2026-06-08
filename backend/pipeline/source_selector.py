"""Company-aware source selection.

The single most important decision in the pipeline: given a business, WHERE do we
hunt for its leads? A wedding DJ has no GitHub presence; a developer-tool company
lives on GitHub/Stack Overflow. Scraping the wrong places wastes time, burns
rate limits, and produces irrelevant leads.

Selection priority:
  1. `recommended_sources` from the LLM ICP translation (smartest — it reasons
     about where THIS buyer actually spends time).
  2. A deterministic vertical heuristic when the LLM is unavailable / returned
     nothing (so a Groq rate-limit never collapses us to a dev-heavy default).

A hard guard then strips developer-only sources for clearly non-tech verticals,
even if they leaked into the LLM output — so a DJ company is NEVER scraped on
GitHub.
"""
from __future__ import annotations

import logging

import backend.sources as sources_pkg

log = logging.getLogger(__name__)

# Sources that only make sense for a technical/developer audience.
DEV_ONLY = {"github", "stackoverflow", "devto"}

# API-based sources that work from a datacenter IP without a search key — the only
# sources guaranteed to return data in production (web-search engines block servers).
DATACENTER_OK = ["hackernews", "stackoverflow", "devto", "github"]

# Vertical → ordered preferred source names (best fit first). Reflects WHERE that
# kind of buyer congregates online.
VERTICAL_SOURCES: dict[str, list[str]] = {
    "dev_tools":      ["github", "stackoverflow", "devto", "hackernews", "reddit", "indiehackers", "apollo", "linkedin", "jobs", "remoteok"],
    "indie_saas":     ["indiehackers", "hackernews", "reddit", "apollo", "linkedin", "bing"],
    "b2b_saas":       ["apollo", "linkedin", "google_cse", "reddit", "indiehackers", "bing", "jobs", "remoteok"],
    "agency":         ["apollo", "linkedin", "google_cse", "jobs", "reddit", "bing"],
    "consumer_local": ["reddit", "bing", "google_cse"],
    "professional":   ["apollo", "linkedin", "google_cse", "bing", "jobs"],
}

# Keyword signatures for each vertical. Most-specific verticals (consumer_local,
# dev_tools) win ties because their keywords are rarely ambiguous.
_VERTICAL_KEYWORDS: dict[str, list[str]] = {
    "consumer_local": [
        "dj", "wedding", "event", "photographer", "videographer", "caterer", "florist",
        "restaurant", "cafe", "bar", "salon", "spa", "barber", "gym", "fitness", "yoga",
        "coach", "tutor", "real estate", "realtor", "plumber", "electrician", "contractor",
        "landscap", "cleaning", "retail", "boutique", "store", "shop", "ecommerce",
        "musician", "band", "artist", "podcast", "creator", "influencer", "local", "venue",
        "hospitality", "travel", "tourism", "nonprofit", "church", "school",
    ],
    "dev_tools": [
        "developer", "api", "sdk", "devops", "open source", "open-source", "programming",
        "software engineer", "library", "framework", "cli", "kubernetes", "docker",
        "database", "infrastructure", "compiler", "data engineer", "machine learning",
        "ml ", "backend", "frontend", "self-hosted", "webhook",
    ],
    "indie_saas": [
        "indie", "bootstrapp", "solopreneur", "side project", "micro saas", "micro-saas",
        "one-person", "solo founder", "productized",
    ],
    "b2b_saas": [
        "saas", "b2b", "enterprise", "crm", "platform", "sales team", "marketing team",
        "hr software", "procurement", "workflow", "compliance", "fintech",
    ],
    "agency": [
        "agency", "consultancy", "consulting", "freelance", "dev shop", "design agency",
        "marketing agency", "done-for-you", "service provider", "we build", "we design",
    ],
}


def _module_map() -> dict:
    return {m.NAME: m for m in sources_pkg.BASE_SOURCES}


def classify_vertical(strategy) -> str:
    """Best-effort vertical for a strategy, from its freeform text + ICP fields."""
    blob = " ".join(str(x) for x in [
        strategy.main_problem or "",
        strategy.ideal_customer or "",
        " ".join(strategy.keywords or []),
        " ".join(strategy.target_industries or []),
        " ".join(strategy.target_roles or []),
    ]).lower()

    scores = {v: 0 for v in _VERTICAL_KEYWORDS}
    for vertical, kws in _VERTICAL_KEYWORDS.items():
        for kw in kws:
            if kw in blob:
                scores[vertical] += 1

    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "professional"


def heuristic_sources(strategy) -> list[str]:
    return VERTICAL_SOURCES.get(classify_vertical(strategy), VERTICAL_SOURCES["professional"])


def select_source_names(strategy) -> tuple[list[str], str]:
    """Return (source_names, reason) — the company-aware source list to hunt on."""
    vertical = classify_vertical(strategy)
    available = set(_module_map().keys())

    rec = (strategy.raw_icp_params or {}).get("recommended_sources") or []
    names = [n for n in rec if n in available]
    reason = "llm"
    if not names:
        names = [n for n in heuristic_sources(strategy) if n in available]
        reason = f"heuristic:{vertical}"

    # Always include the API-based sources that work from a DATACENTER IP without a
    # search key (hackernews/stackoverflow/devto/github). Web-search engines block
    # server IPs, so in production these are often the ONLY sources that return data.
    # (Dev-only ones are stripped just below for non-tech verticals.)
    names = names + [n for n in DATACENTER_OK if n in available]

    # Hard guard: never scrape developer-only sources for a non-tech business.
    if vertical in ("consumer_local", "professional"):
        names = [n for n in names if n not in DEV_ONLY]

    if not names:  # last-ditch so a strategy is never left with zero sources
        names = [n for n in ("bing", "reddit", "google_cse") if n in available]
        reason = "fallback"

    # Competitor switch-intent is opt-in — only run it when competitors are named.
    if getattr(strategy, "competitors", None) and "competitor" in available:
        names = names + ["competitor"]

    # Targeted-website hunting is opt-in — only when the user named specific sites.
    if getattr(strategy, "target_websites", None) and "sites" in available:
        names = names + ["sites"]

    # Event/webinar opportunities — only when at least one opportunity type is on.
    webinars_on = getattr(strategy, "webinars_enabled", True)
    events_on = getattr(strategy, "events_enabled", True)
    if (webinars_on or events_on) and "events" in available:
        names = names + ["events"]

    # De-dupe, preserve order
    seen: set[str] = set()
    ordered = [n for n in names if not (n in seen or seen.add(n))]

    # Feedback learning: float sources the user keeps approving to the front,
    # demote ones they keep rejecting (never drops any). Bounded, reversible.
    from backend.pipeline.learning import apply_source_preferences
    ordered = apply_source_preferences(ordered, getattr(strategy, "learning_profile", None))
    return ordered, reason


def select_source_modules(strategy) -> list:
    """Resolve the selected source names to their modules, in order."""
    names, reason = select_source_names(strategy)
    mm = _module_map()
    mods = [mm[n] for n in names if n in mm]
    log.info(
        f"[source_selector] strategy={getattr(strategy, 'id', '?')} "
        f"vertical={classify_vertical(strategy)} reason={reason} sources={names}"
    )
    return mods

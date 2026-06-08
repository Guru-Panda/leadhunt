from backend.sources import (
    github,
    hackernews,
    reddit,
    google_cse,
    bing,
    remoteok,
    linkedin,
    stackoverflow,
    devto,
    indiehackers,
    apollo,
    jobs,
    competitor,
    events,
    sites,
)

# Removed 2026-06-05 (audit): producthunt/ycombinator/companies_house (empty keys →
# always []), indeed/wellfound (Cloudflare bot-blocked → always []), whois (fetch()
# is a no-op; lookup_domain() is still used directly by enrichment). None of these
# were ever selected by source_selector, so removal is behaviour-neutral cleanup.

BASE_SOURCES = [
    github,
    hackernews,
    reddit,
    remoteok,
    google_cse,
    bing,
    linkedin,
    stackoverflow,
    devto,
    indiehackers,
    apollo,
    jobs,
    competitor,
    events,
    sites,
]

# INTENT sources — the default hourly hunt.
# These find prospects who are ACTIVELY expressing a need (buyer intent posts)
# or match the ICP profile precisely — not random accounts scraped from a community.
INTENT_SOURCES = [
    apollo,         # 275M contacts DB — verified emails + LinkedIn; best data quality
    linkedin,       # ICP-driven site:linkedin.com/in searches → exact role + industry match
    reddit,         # Subreddit-scoped + intent-boosted queries: "looking for X"
    github,         # Issues/Discussions (people asking for solutions) + user profiles
    stackoverflow,  # Questions matching buyer phrases — people actively seeking solutions
    devto,          # Tag-based search → developers discussing problems we solve
    indiehackers,   # RSS feed keyword-filtered → founders expressing needs
    bing,           # Mojeek web search → forum/Quora posts expressing buying intent
]

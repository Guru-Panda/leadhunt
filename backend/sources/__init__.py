from backend.sources import (
    github,
    hackernews,
    producthunt,
    ycombinator,
    reddit,
    indeed,
    wellfound,
    google_cse,
    whois_rdap,
    bing,
    companies_house,
    remoteok,
    linkedin,
)

BASE_SOURCES = [
    github,
    hackernews,
    producthunt,
    ycombinator,
    reddit,
    indeed,
    wellfound,
    remoteok,
    google_cse,
    whois_rdap,
    bing,
    companies_house,
    linkedin,
]

# INTENT sources — the default hourly hunt.
# These find prospects who are ACTIVELY expressing a need or match the ICP profile
# precisely — not random accounts scraped from a community.
INTENT_SOURCES = [
    linkedin,      # ICP-driven site:linkedin.com/in searches → exact role + industry match
    reddit,        # Intent-boosted queries: "looking for X", "recommendations for Y"
    bing,          # Mojeek web search → forum/Quora posts expressing buying intent
    hackernews,    # Ask HN + comments with buyer signals
]

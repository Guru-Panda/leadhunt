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
    stackoverflow,
    devto,
    indiehackers,
    apollo,
    jobs,
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
    stackoverflow,
    devto,
    indiehackers,
    apollo,
    jobs,
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

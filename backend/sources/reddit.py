from __future__ import annotations

import logging
import time

import httpx

log = logging.getLogger(__name__)
NAME = "reddit"

# Reddit's .json endpoints work without OAuth for read-only access.
# Rate-limited to ~60 req/min by IP, far more than we need.
_SEARCH_URL = "https://www.reddit.com/search.json"
_UA = "LeadHunt/1.0 (lead generation research bot)"


def _search(query: str, limit: int = 20, period: str = "month") -> list[dict]:
    """Search Reddit for posts matching `query`. Returns list of post dicts."""
    try:
        r = httpx.get(
            _SEARCH_URL,
            params={"q": query, "sort": "new", "t": period, "limit": limit},
            headers={"User-Agent": _UA},
            timeout=10,
        )
        if r.status_code == 429:
            log.warning("Reddit rate-limited (429), sleeping 10s")
            time.sleep(10)
            return []
        r.raise_for_status()
        return r.json().get("data", {}).get("children", [])
    except Exception as e:
        log.warning(f"Reddit search failed for {query!r}: {e}")
        return []


def fetch(icp_params: dict, limit: int = 50) -> list[dict]:
    # Prefer buyer_phrases (high-intent) but fall back to general queries
    queries = icp_params.get("hn_queries") or []
    buyer_phrases = []  # populated by ICP; live in strategy.buyer_phrases — not in raw_icp_params
    # icp_params doesn't carry buyer_phrases through, so we use hn_queries as the
    # closest proxy for "people talking about our problem"
    all_queries = (buyer_phrases or [])[:3] + queries[:3]
    if not all_queries:
        return []

    leads: list[dict] = []
    seen_authors: set[str] = set()

    for query in all_queries[:5]:
        posts = _search(query, limit=20, period="month")
        for post in posts:
            d = post.get("data", {})
            author = d.get("author", "")
            if not author or author in ("[deleted]", "AutoModerator", "automoderator"):
                continue
            if author in seen_authors:
                continue
            seen_authors.add(author)

            subreddit = d.get("subreddit", "")
            title = d.get("title", "")
            selftext = (d.get("selftext") or "")[:1200]
            permalink = d.get("permalink", "")
            post_url = f"https://reddit.com{permalink}" if permalink else None
            profile_url = f"https://reddit.com/user/{author}"
            snippet_parts = [f"r/{subreddit} — {title}"]
            if selftext:
                snippet_parts.append(selftext[:600])
            snippet = "\n\n".join(snippet_parts)

            # People in r/cofounderhunt etc. drop their emails ("DM me at...")
            from backend.enrichment.extractors import extract_emails_from_text
            emails_in_post = extract_emails_from_text(f"{title}\n{selftext}")
            primary_email = emails_in_post[0] if emails_in_post else None
            signals = ["buyer_intent_post", f"posted_in_r_{subreddit}"]
            if primary_email:
                signals.append("email_in_post")

            leads.append({
                "external_id": f"reddit_{d.get('id', author)}",
                "person_name": author,
                "person_title": None,
                "source": NAME,
                "source_url": post_url,
                "source_profile_url": profile_url,
                "source_snippet": snippet,
                "person_email": primary_email,
                "raw_data": {
                    "bio": selftext,
                    "context": f"Posted in r/{subreddit}: {title[:200]}",
                    "reddit_url": post_url,
                    "subreddit": subreddit,
                    "title": title,
                    "score": d.get("score", 0),
                    "num_comments": d.get("num_comments", 0),
                    "emails_in_post": emails_in_post,
                },
                "intent_signals": signals,
            })
            if len(leads) >= limit:
                return leads[:limit]

        time.sleep(1)  # gentle on Reddit

    return leads[:limit]

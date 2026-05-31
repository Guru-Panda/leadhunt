from __future__ import annotations

import logging
import time
from functools import lru_cache

import httpx

from backend.config import settings

log = logging.getLogger(__name__)
NAME = "reddit"

_UA = "LeadHunt/1.0 (lead generation research bot)"
_SEEKING_PREFIXES = ("looking for", "recommendations", "alternative", "best tool", "how to find", "need a", "suggest")


def _has_seeking_prefix(phrase: str) -> bool:
    p = phrase.lower().strip()
    return any(p.startswith(pref) for pref in _SEEKING_PREFIXES)


@lru_cache(maxsize=1)
def _get_oauth_token() -> str | None:
    """Get Reddit OAuth token using client credentials. Cached per process."""
    cid = settings.REDDIT_CLIENT_ID
    csec = settings.REDDIT_CLIENT_SECRET
    if not (cid and csec):
        return None
    try:
        r = httpx.post(
            "https://www.reddit.com/api/v1/access_token",
            data={"grant_type": "client_credentials"},
            auth=(cid, csec),
            headers={"User-Agent": _UA},
            timeout=10,
        )
        r.raise_for_status()
        token = r.json().get("access_token")
        log.info("[reddit] OAuth token obtained")
        return token
    except Exception as e:
        log.warning(f"[reddit] OAuth token fetch failed: {e}")
        return None


def _search(query: str, limit: int = 20, period: str = "month") -> list[dict]:
    """Search Reddit for posts. Uses OAuth API if credentials set, public API otherwise."""
    token = _get_oauth_token()
    if token:
        url = "https://oauth.reddit.com/search"
        headers = {"User-Agent": _UA, "Authorization": f"Bearer {token}"}
    else:
        url = "https://www.reddit.com/search.json"
        headers = {"User-Agent": _UA}

    try:
        r = httpx.get(
            url,
            params={"q": query, "sort": "new", "t": period, "limit": limit},
            headers=headers,
            timeout=10,
        )
        if r.status_code == 429:
            log.warning("Reddit rate-limited (429), sleeping 10s")
            time.sleep(10)
            return []
        if r.status_code == 401 and token:
            # Token expired — clear cache and give up for this call
            _get_oauth_token.cache_clear()
            log.warning("[reddit] OAuth token expired, skipping query")
            return []
        r.raise_for_status()
        return r.json().get("data", {}).get("children", [])
    except Exception as e:
        log.warning(f"Reddit search failed for {query!r}: {e}")
        return []


def fetch(icp_params: dict, limit: int = 50) -> list[dict]:
    buyer_phrases   = icp_params.get("buyer_phrases") or []
    intent_keywords = icp_params.get("buyer_intent_keywords") or []
    target_subreddits = icp_params.get("target_subreddits") or []

    all_queries: list[str] = []

    # Strategy 1: Subreddit-scoped queries (highest signal)
    # Searching WHERE buyers congregate + what they say when they need our solution
    if target_subreddits and buyer_phrases:
        for sub in target_subreddits[:3]:
            for phrase in buyer_phrases[:3]:
                # Search within the specific subreddit for the buying phrase
                all_queries.append(f"subreddit:{sub} {phrase}")
        # Also search subreddits for broader intent keywords
        for sub in target_subreddits[:2]:
            for kw in intent_keywords[:2]:
                all_queries.append(f"subreddit:{sub} {kw}")

    # Strategy 2: Phrase-based search (buying intent expressions)
    for phrase in buyer_phrases[:4]:
        if not _has_seeking_prefix(phrase):
            all_queries.append(f"looking for {phrase}")
            all_queries.append(f"recommendations {phrase}")
        else:
            all_queries.append(phrase)

    # Strategy 3: Keyword fallback
    for kw in intent_keywords[:2]:
        all_queries.append(kw)

    all_queries = list(dict.fromkeys(q for q in all_queries if q.strip()))

    if not all_queries:
        raw_text = (icp_params.get("_main_problem") or "").strip()
        if raw_text:
            all_queries = [
                f"looking for {raw_text[:60]}",
                raw_text[:80],
            ]
    if not all_queries:
        return []

    leads: list[dict] = []
    seen_authors: set[str] = set()

    for query in all_queries[:8]:
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

        time.sleep(0.5)

    return leads[:limit]

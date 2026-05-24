from __future__ import annotations

import logging
import re

import httpx

log = logging.getLogger(__name__)
NAME = "hackernews"

_ALGOLIA = "https://hn.algolia.com/api/v1/search"
_ALGOLIA_DATE = "https://hn.algolia.com/api/v1/search_by_date"


def _search_algolia(query: str, tags: str = "(comment,ask_hn,story)", limit: int = 30, by_date: bool = False) -> list[dict]:
    url = _ALGOLIA_DATE if by_date else _ALGOLIA
    r = httpx.get(url, params={"query": query, "tags": tags, "hitsPerPage": limit}, timeout=10)
    r.raise_for_status()
    return r.json().get("hits", [])


def _latest_who_is_hiring_id() -> str | None:
    """Find the story_id of the most recent 'Who is hiring?' thread."""
    try:
        hits = _search_algolia("Ask HN: Who is hiring", tags="story", limit=5, by_date=True)
        for hit in hits:
            title = hit.get("title", "")
            if "Who is hiring" in title:
                return hit.get("objectID")
    except Exception as e:
        log.warning(f"Failed to find Who-is-hiring thread: {e}")
    return None


def _strip_html(text: str) -> str:
    if not text:
        return ""
    clean = re.sub(r"<[^>]+>", " ", text)
    return (
        clean.replace("&#x27;", "'").replace("&#x2F;", "/").replace("&quot;", '"')
        .replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").replace("&nbsp;", " ")
    )


def _build_lead(author: str, object_id: str, text_clean: str, query_label: str) -> dict:
    from backend.enrichment.extractors import extract_emails_from_text
    post_url = f"https://news.ycombinator.com/item?id={object_id}" if object_id else None
    profile_url = f"https://news.ycombinator.com/user?id={author}"
    snippet = f"{query_label}\n\n{text_clean[:800]}" if text_clean else f"Active on HackerNews: {query_label}"
    emails = extract_emails_from_text(text_clean)
    primary_email = emails[0] if emails else None
    signals = ["active_hn_discussion"]
    if primary_email:
        signals.append("email_in_post")
    return {
        "external_id": f"hn_{object_id or author}",
        "person_name": author,
        "person_title": None,
        "source": NAME,
        "source_url": post_url,
        "source_profile_url": profile_url,
        "source_snippet": snippet,
        "person_github_url": f"https://github.com/{author}",
        "person_email": primary_email,
        "raw_data": {
            "bio": text_clean[:500],
            "context": f"Active on HackerNews: {query_label}",
            "hn_url": profile_url,
            "emails_in_comment": emails,
        },
        "intent_signals": signals,
    }


def fetch(icp_params: dict, limit: int = 50) -> list[dict]:
    leads: list[dict] = []
    seen_ids: set[str] = set()
    hn_queries = icp_params.get("hn_queries", [])

    # ── PASS 1: Search the current Who-is-Hiring thread (email-rich!)
    # Use industries + roles (broader than narrow hn_queries) since hiring posts
    # use generic role terms ("engineer", "CTO") rather than buyer phrases.
    hiring_queries = list(dict.fromkeys(
        (icp_params.get("target_industries") or [])[:3]
        + (icp_params.get("target_roles") or [])[:3]
        + hn_queries[:2]
    ))
    hiring_story = _latest_who_is_hiring_id()
    if hiring_story:
        for query in hiring_queries[:5]:
            try:
                hits = _search_algolia(query, tags=f"comment,story_{hiring_story}", limit=10)
                for hit in hits:
                    author = hit.get("author", "")
                    if not author or author in seen_ids:
                        continue
                    seen_ids.add(author)
                    text = _strip_html(hit.get("comment_text") or "")
                    lead = _build_lead(author, hit.get("objectID", ""), text, f"Who-is-hiring: {query}")
                    # Boost intent signal for hiring threads
                    if "active_hiring_thread" not in lead["intent_signals"]:
                        lead["intent_signals"].insert(0, "active_hiring_thread")
                    leads.append(lead)
                    if len(leads) >= limit:
                        return leads[:limit]
            except Exception as e:
                log.warning(f"HN hiring-thread search failed for {query!r}: {e}")

    # ── PASS 2: General discussion search (existing behaviour)
    for query in hn_queries[:5]:
        try:
            hits = _search_algolia(query, tags="(comment,ask_hn,story)", limit=20)
            for hit in hits:
                author = hit.get("author", "")
                if not author or author in seen_ids:
                    continue
                seen_ids.add(author)
                text = _strip_html(hit.get("comment_text") or hit.get("story_text") or "")
                lead = _build_lead(author, hit.get("objectID", ""), text, query)
                leads.append(lead)
                if len(leads) >= limit:
                    return leads[:limit]
        except Exception as e:
            log.warning(f"HN search failed for {query!r}: {e}")

    return leads[:limit]

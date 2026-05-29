"""
Dev.to lead source.
Uses the free, public dev.to REST API — no auth required.
Finds developers discussing problems our solution addresses.
"""
from __future__ import annotations

import logging

import httpx

log = logging.getLogger(__name__)
NAME = "devto"

_BASE = "https://dev.to/api"
_HEADERS = {
    "User-Agent": "LeadHunt/1.0",
    "Accept": "application/vnd.forem.api-v1+json",
}


def _build_lead(article: dict, query_label: str) -> dict:
    art_id = article.get("id", "")
    title = article.get("title", "")
    description = article.get("description") or ""
    content = f"{title}\n\n{description}".strip() if description else title
    user = article.get("user", {})
    author_name = user.get("name") or user.get("username") or ""
    username = user.get("username") or ""
    article_url = article.get("url") or f"https://dev.to/{username}/{article.get('slug', '')}"
    profile_url = f"https://dev.to/{username}" if username else None

    signals = ["active_devto_author", "buyer_intent_post"]
    tags = [t.get("name", "") for t in (article.get("tags") or []) if isinstance(t, dict)]
    tag_names = article.get("tag_list") or tags

    return {
        "external_id": f"devto_{art_id}",
        "person_name": author_name or f"dev.to user {art_id}",
        "person_title": None,
        "source": NAME,
        "source_url": article_url,
        "source_profile_url": profile_url,
        "source_snippet": f"Dev.to: {title}\nTags: {', '.join(tag_names)}\n\n{description[:500]}",
        "person_email": None,
        "raw_data": {
            "bio": content[:500],
            "context": f"Dev.to article on: {query_label}",
            "devto_url": article_url,
            "tags": tag_names,
            "reactions": article.get("positive_reactions_count", 0),
        },
        "intent_signals": signals,
    }


def _tag_targets(icp_params: dict) -> list[str]:
    """Extract Dev.to-compatible tag slugs from ICP params."""
    buyer_phrases = icp_params.get("buyer_phrases") or []
    keywords = icp_params.get("buyer_intent_keywords") or icp_params.get("tech_keywords") or []
    industries = icp_params.get("target_industries") or []

    def _to_slug(s: str) -> str:
        return s.lower().strip().replace(" ", "").replace("-", "").replace("_", "")

    # Prefer specific keywords over broad industry terms
    raw = [_to_slug(k) for k in (keywords[:5] + industries[:2]) if k and k.strip()]
    # Also try single words from buyer phrases (Dev.to has no full-text search)
    for phrase in buyer_phrases[:3]:
        for word in phrase.split():
            if len(word) >= 4:
                raw.append(_to_slug(word))

    return list(dict.fromkeys(t for t in raw if t))[:8]


def fetch(icp_params: dict, limit: int = 50) -> list[dict]:
    if not icp_params:
        return []

    tags = _tag_targets(icp_params)
    if not tags:
        return []

    leads: list[dict] = []
    seen_ids: set[str] = set()

    for tag in tags:
        try:
            resp = httpx.get(
                f"{_BASE}/articles",
                params={"tag": tag, "per_page": min(limit, 30)},
                headers=_HEADERS,
                timeout=15,
            )
            resp.raise_for_status()
            for article in resp.json():
                ext_id = f"devto_{article.get('id', '')}"
                if ext_id in seen_ids:
                    continue
                seen_ids.add(ext_id)
                leads.append(_build_lead(article, tag))
                if len(leads) >= limit:
                    return leads[:limit]
        except Exception as e:
            log.warning(f"Dev.to fetch error for tag {tag!r}: {e}")

    log.info(f"[devto] fetched {len(leads)} leads from tags: {tags[:5]}")
    return leads[:limit]

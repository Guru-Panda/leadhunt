from __future__ import annotations

import logging

import httpx

from backend.config import settings

log = logging.getLogger(__name__)
NAME = "producthunt"

_GQL_URL = "https://api.producthunt.com/v2/api/graphql"
_QUERY = """
query {
  posts(first: 20, order: NEWEST) {
    edges {
      node {
        id
        name
        tagline
        websiteUrl
        makers {
          id
          name
          username
          twitterUsername
          websiteUrl
        }
      }
    }
  }
}
"""


def fetch(icp_params: dict, limit: int = 50) -> list[dict]:
    if not settings.PRODUCTHUNT_TOKEN:
        log.warning("PRODUCTHUNT_TOKEN not set — skipping ProductHunt source")
        return []

    try:
        r = httpx.post(
            _GQL_URL,
            json={"query": _QUERY},
            headers={
                "Authorization": f"Bearer {settings.PRODUCTHUNT_TOKEN}",
                "Content-Type": "application/json",
                "User-Agent": "LeadHunt/1.0",
            },
            timeout=15,
        )
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        log.warning(f"ProductHunt fetch failed: {e}")
        return []

    leads: list[dict] = []
    posts = data.get("data", {}).get("posts", {}).get("edges", [])

    for edge in posts:
        post = edge.get("node", {})
        product_name = post.get("name", "")
        product_id = post.get("id", "")
        tagline = post.get("tagline", "")
        domain = _extract_domain(post.get("websiteUrl"))
        product_url = f"https://www.producthunt.com/posts/{product_name.lower().replace(' ', '-')}" if product_name else None

        for maker in post.get("makers", []):
            username = maker.get("username", "")
            profile_url = f"https://www.producthunt.com/@{username}" if username else None
            snippet = f"Maker of {product_name} on ProductHunt\n\n{tagline}"
            leads.append({
                "external_id": f"ph_{maker.get('id', username)}",
                "person_name": maker.get("name", ""),
                "person_title": "Founder",
                "company_name": product_name,
                "company_domain": domain,
                "person_twitter_url": f"https://twitter.com/{maker['twitterUsername']}" if maker.get("twitterUsername") else None,
                "source": NAME,
                "source_url": product_url,
                "source_profile_url": profile_url,
                "source_snippet": snippet,
                "raw_data": {
                    "context": f"Maker of {product_name} on ProductHunt: {tagline}",
                    "ph_username": username,
                },
                "intent_signals": ["launched_product"],
            })
            if len(leads) >= limit:
                return leads[:limit]

    return leads[:limit]


def _extract_domain(url: str | None) -> str | None:
    if not url:
        return None
    try:
        from urllib.parse import urlparse
        parsed = urlparse(url)
        return parsed.netloc.lstrip("www.") or None
    except Exception:
        return None

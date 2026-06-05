from __future__ import annotations

import logging
import time

import httpx

from backend.config import settings

log = logging.getLogger(__name__)
NAME = "github"

_BASE = "https://api.github.com"
_HEADERS = {
    "Authorization": f"token {settings.GITHUB_TOKEN}",
    "Accept": "application/vnd.github+json",
    "User-Agent": "LeadHunt/1.0",
}


def _get(path: str, params: dict | None = None) -> dict | list:
    r = httpx.get(f"{_BASE}{path}", headers=_HEADERS, params=params, timeout=15)
    if r.status_code == 429:
        reset = int(r.headers.get("X-RateLimit-Reset", time.time() + 60))
        wait = max(reset - time.time(), 1)
        log.warning(f"GitHub rate limit hit, sleeping {wait:.0f}s")
        time.sleep(min(wait, 60))
        r = httpx.get(f"{_BASE}{path}", headers=_HEADERS, params=params, timeout=15)
    r.raise_for_status()
    return r.json()


def _auth_headers() -> dict:
    """Return auth headers. Falls back to unauthenticated (10 req/min) if no token."""
    h = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "LeadHunt/1.0",
    }
    if settings.GITHUB_TOKEN:
        h["Authorization"] = f"Bearer {settings.GITHUB_TOKEN}"
    return h


def _search_issues(query: str, limit: int = 20) -> list[dict]:
    """Search GitHub issues matching a query — highest buying intent signal.

    People open issues asking "does X support Y?" or "looking for alternative to Z"
    on repos they're evaluating. This is extremely high-intent.
    """
    try:
        resp = httpx.get(
            f"{_BASE}/search/issues",
            params={
                "q": f"{query} is:issue is:open",
                "sort": "created",
                "order": "desc",
                "per_page": min(limit, 30),
            },
            headers=_auth_headers(),
            timeout=15,
        )
        if resp.status_code == 403:
            log.warning("GitHub API rate limited — add GITHUB_TOKEN for higher limits")
            return []
        resp.raise_for_status()

        leads = []
        for item in resp.json().get("items", []):
            title = item.get("title", "")
            body = (item.get("body") or "")[:800]
            content = f"{title}\n\n{body}".strip() if body else title
            user = item.get("user", {}) or {}
            login = user.get("login") or ""
            issue_url = item.get("html_url") or ""
            profile_url = f"https://github.com/{login}" if login else None

            signals = ["active_github_issue", "buyer_intent_post"]
            seeking_phrases = ["looking for", "need a tool", "alternative to", "recommend", "does anyone", "how do i", "can i use", "feature request"]
            if any(p in content.lower() for p in seeking_phrases):
                signals.append("explicit_seeking_signal")

            leads.append({
                "external_id": f"gh_issue_{item.get('id', '')}",
                "person_name": login or "GitHub user",
                "person_title": None,
                "person_github_url": profile_url,
                "source": NAME,
                "source_url": issue_url,
                "source_profile_url": profile_url,
                "source_snippet": f"GitHub issue: {title}\n\n{content[:600]}",
                "person_email": None,
                "raw_data": {
                    "bio": content[:500],
                    "context": f"Opened GitHub issue: {title[:200]}",
                    "github_issue_url": issue_url,
                    "repo": item.get("repository_url", "").split("/")[-2:],
                },
                "intent_signals": signals,
            })
        log.info(f"GitHub issues search {query!r}: {len(leads)} results")
        return leads
    except Exception as e:
        log.warning(f"GitHub issues search error for {query!r}: {e}")
        return []


def _search_discussions(query: str, limit: int = 15) -> list[dict]:
    """Search GitHub Discussions via GraphQL — requires GITHUB_TOKEN."""
    if not settings.GITHUB_TOKEN:
        return []

    graphql_query = """
    query($q: String!, $limit: Int!) {
      search(query: $q, type: DISCUSSION, first: $limit) {
        nodes {
          ... on Discussion {
            id
            title
            body
            url
            author { login }
          }
        }
      }
    }"""
    try:
        resp = httpx.post(
            "https://api.github.com/graphql",
            json={"query": graphql_query, "variables": {"q": query, "limit": limit}},
            headers={**_auth_headers(), "Content-Type": "application/json"},
            timeout=15,
        )
        resp.raise_for_status()
        nodes = resp.json().get("data", {}).get("search", {}).get("nodes", [])
        leads = []
        for node in (nodes or []):
            if not node:
                continue
            title = node.get("title", "")
            body = (node.get("body") or "")[:800]
            content = f"{title}\n\n{body}".strip() if body else title
            login = (node.get("author") or {}).get("login") or ""
            disc_url = node.get("url") or ""
            profile_url = f"https://github.com/{login}" if login else None
            leads.append({
                "external_id": f"gh_disc_{node.get('id', '')}",
                "person_name": login or "GitHub user",
                "person_title": None,
                "person_github_url": profile_url,
                "source": NAME,
                "source_url": disc_url,
                "source_profile_url": profile_url,
                "source_snippet": f"GitHub Discussion: {title}\n\n{content[:600]}",
                "person_email": None,
                "raw_data": {
                    "bio": content[:500],
                    "context": f"GitHub Discussion: {title[:200]}",
                },
                "intent_signals": ["active_github_discussion", "buyer_intent_post"],
            })
        log.info(f"GitHub discussions search {query!r}: {len(leads)} results")
        return leads
    except Exception as e:
        log.warning(f"GitHub discussions search error for {query!r}: {e}")
        return []


def _issue_queries(icp_params: dict) -> list[str]:
    """Build GitHub issue search queries from ICP params."""
    buyer_phrases = icp_params.get("buyer_phrases") or []
    keywords = icp_params.get("buyer_intent_keywords") or icp_params.get("tech_keywords") or []
    kw_str = " ".join(keywords[:3]) if keywords else ""
    queries = []
    if buyer_phrases:
        queries += [p for p in buyer_phrases[:3] if p.strip()]
    if kw_str:
        queries += [
            f"looking for {kw_str}",
            f"alternative to {kw_str}",
            kw_str,
        ]
    return list(dict.fromkeys(q for q in queries if q.strip()))[:5]


def fetch(icp_params: dict, limit: int = 50) -> list[dict]:
    if not settings.GITHUB_TOKEN:
        log.warning("GITHUB_TOKEN not set — GitHub user search skipped (issues search will use public API)")

    leads: list[dict] = []
    seen_ids: set[str] = set()

    # ── PASS 1: Issues & Discussions search (buying intent from post content) ──
    for query in _issue_queries(icp_params):
        for lead in _search_issues(query, limit=15):
            if lead["external_id"] not in seen_ids:
                seen_ids.add(lead["external_id"])
                leads.append(lead)
                if len(leads) >= limit:
                    return leads[:limit]
        for lead in _search_discussions(query, limit=10):
            if lead["external_id"] not in seen_ids:
                seen_ids.add(lead["external_id"])
                leads.append(lead)
                if len(leads) >= limit:
                    return leads[:limit]

    # ── PASS 2: User profile search (ICP-match via bio/company) ──────────────
    if settings.GITHUB_TOKEN:
        for query in (icp_params.get("github_user_queries") or [])[:3]:
            try:
                data = _get("/search/users", {"q": query, "per_page": min(limit, 20)})
                for user in data.get("items", []):
                    login = user.get("login", "")
                    if login in seen_ids:
                        continue
                    seen_ids.add(login)
                    try:
                        profile = _get(f"/users/{login}")
                    except Exception:
                        continue
                    github_url = profile.get("html_url", f"https://github.com/{login}")
                    bio = profile.get("bio") or ""
                    snippet_lines = [f"GitHub: @{login}"]
                    if profile.get("name"): snippet_lines.append(profile["name"])
                    if profile.get("company"): snippet_lines.append(f"@{profile['company']}")
                    if profile.get("location"): snippet_lines.append(profile["location"])
                    if bio: snippet_lines += ["", bio[:500]]
                    leads.append({
                        "external_id": login,
                        "person_name": profile.get("name") or login,
                        "person_title": bio[:100] if bio else None,
                        "person_location": profile.get("location"),
                        "person_github_url": github_url,
                        "company_name": (profile.get("company") or "").lstrip("@") or None,
                        "company_domain": _extract_domain(profile.get("blog")),
                        "source": NAME,
                        "source_url": github_url,
                        "source_profile_url": github_url,
                        "source_snippet": "\n".join(snippet_lines),
                        "person_email": None,
                        "raw_data": {
                            "bio": bio,
                            "followers": profile.get("followers", 0),
                            "public_repos": profile.get("public_repos", 0),
                            "twitter_username": profile.get("twitter_username"),
                        },
                        "intent_signals": [],
                    })
                    if len(leads) >= limit:
                        return leads[:limit]
            except Exception as e:
                log.warning(f"GitHub user search error for {query!r}: {e}")

    return leads[:limit]


def _extract_domain(url: str | None) -> str | None:
    if not url:
        return None
    try:
        from urllib.parse import urlparse
        parsed = urlparse(url if url.startswith("http") else f"https://{url}")
        host = parsed.netloc or parsed.path
        return (host[4:] if host.startswith("www.") else host) or None
    except Exception:
        return None

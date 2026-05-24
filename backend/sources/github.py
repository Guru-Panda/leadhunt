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


def fetch(icp_params: dict, limit: int = 50) -> list[dict]:
    if not settings.GITHUB_TOKEN:
        log.warning("GITHUB_TOKEN not set — skipping GitHub source")
        return []

    leads: list[dict] = []
    queries = icp_params.get("github_user_queries", [])

    for query in queries[:3]:
        try:
            data = _get("/search/users", {"q": query, "per_page": min(limit, 30)})
            for user in data.get("items", []):
                login = user.get("login", "")
                try:
                    profile = _get(f"/users/{login}")
                except Exception:
                    continue
                github_url = profile.get("html_url", f"https://github.com/{login}")
                bio = profile.get("bio") or ""
                snippet_lines = [f"GitHub: @{login}"]
                if profile.get("name"): snippet_lines.append(profile.get("name"))
                if profile.get("company"): snippet_lines.append(f"@{profile.get('company')}")
                if profile.get("location"): snippet_lines.append(profile.get("location"))
                if bio: snippet_lines.append("")
                if bio: snippet_lines.append(bio[:500])
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
                    "raw_data": {
                        "bio": bio,
                        "followers": profile.get("followers", 0),
                        "public_repos": profile.get("public_repos", 0),
                        "twitter_username": profile.get("twitter_username"),
                    },
                    "intent_signals": [],
                })
                if len(leads) >= limit:
                    break
        except Exception as e:
            log.warning(f"GitHub fetch error for query '{query}': {e}")

        if len(leads) >= limit:
            break

    return leads[:limit]


def _extract_domain(url: str | None) -> str | None:
    if not url:
        return None
    try:
        from urllib.parse import urlparse
        parsed = urlparse(url if url.startswith("http") else f"https://{url}")
        host = parsed.netloc or parsed.path
        return host.lstrip("www.") or None
    except Exception:
        return None

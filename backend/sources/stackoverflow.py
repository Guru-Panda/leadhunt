"""
Stack Overflow / Stack Exchange lead source.
Uses the Stack Exchange API v2.3 — free, 300 req/day unauthenticated.
Finds people actively asking questions that our solution answers.
"""
from __future__ import annotations

import logging
import re

import httpx

from backend.config import settings

log = logging.getLogger(__name__)
NAME = "stackoverflow"

# Free tier: 300 req/day unauthenticated. Set STACKOVERFLOW_KEY for 10,000/day.
_SO_KEY: str = settings.STACKOVERFLOW_KEY

_BASE = "https://api.stackexchange.com/2.3"
_HEADERS = {"Accept-Encoding": "gzip"}


def _api_params(extra: dict) -> dict:
    p = {"site": "stackoverflow", "order": "desc", "sort": "creation", **extra}
    if _SO_KEY:
        p["key"] = _SO_KEY
    return p


def _strip_html(text: str) -> str:
    if not text:
        return ""
    clean = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", clean).strip()


def _build_lead(item: dict, query_label: str) -> dict:
    q_id = item.get("question_id", "")
    title = item.get("title", "")
    body = _strip_html(item.get("body_markdown") or item.get("body") or "")
    content = f"{title}\n\n{body}".strip() if body else title
    owner = item.get("owner", {})
    author_name = owner.get("display_name") or ""
    author_uid = str(owner.get("user_id", "")) or ""
    author_profile = owner.get("link") or (f"https://stackoverflow.com/users/{author_uid}" if author_uid else None)
    question_url = item.get("link") or f"https://stackoverflow.com/q/{q_id}"

    signals = ["active_so_question", "buyer_intent_post"]
    if any(t in content.lower() for t in ["looking for", "recommend", "alternative", "best tool", "how do i", "help me"]):
        signals.append("explicit_seeking_signal")

    return {
        "external_id": f"so_{q_id}",
        "person_name": author_name or f"SO user {author_uid}",
        "person_title": None,
        "source": NAME,
        "source_url": question_url,
        "source_profile_url": author_profile,
        "source_snippet": f"Asked on Stack Overflow: {title}\n\n{content[:600]}",
        "person_email": None,
        "raw_data": {
            "bio": content[:500],
            "context": f"Stack Overflow question: {query_label}",
            "so_url": question_url,
            "tags": item.get("tags", []),
        },
        "intent_signals": signals,
    }


def _so_queries(icp_params: dict) -> list[str]:
    """Build StackOverflow-optimised queries from ICP params."""
    buyer_phrases = icp_params.get("buyer_phrases") or []
    keywords = icp_params.get("buyer_intent_keywords") or icp_params.get("tech_keywords") or []
    industries = icp_params.get("target_industries") or []

    # Build explicit seeking queries from intent keywords
    kw_base = " ".join(keywords[:3]) if keywords else ""
    queries: list[str] = []

    if buyer_phrases:
        queries += [p for p in buyer_phrases[:4] if p.strip()]

    if kw_base:
        queries += [
            f"looking for {kw_base}",
            f"recommend {kw_base}",
            f"best tool for {kw_base}",
            kw_base,
        ]

    if industries:
        ind = industries[0]
        queries.append(f"{ind} tool recommendation")

    return list(dict.fromkeys(q for q in queries if q.strip()))[:6]


def fetch(icp_params: dict, limit: int = 50) -> list[dict]:
    if not icp_params:
        return []

    queries = _so_queries(icp_params)
    if not queries:
        return []

    leads: list[dict] = []
    seen_ids: set[str] = set()

    for query in queries:
        try:
            params = _api_params({
                "q": query,
                "pagesize": min(limit, 25),
                "filter": "withbody",
            })
            resp = httpx.get(
                f"{_BASE}/search/advanced",
                params=params,
                headers=_HEADERS,
                timeout=15,
            )
            if resp.status_code == 400:
                # Bad filter — retry without body
                params.pop("filter", None)
                resp = httpx.get(f"{_BASE}/search/advanced", params=params, headers=_HEADERS, timeout=15)
            if resp.status_code != 200:
                log.warning(f"SO search returned {resp.status_code} for {query!r}")
                continue

            for item in resp.json().get("items", []):
                ext_id = f"so_{item.get('question_id', '')}"
                if ext_id in seen_ids:
                    continue
                seen_ids.add(ext_id)
                leads.append(_build_lead(item, query))
                if len(leads) >= limit:
                    return leads[:limit]

        except Exception as e:
            log.warning(f"SO fetch error for query {query!r}: {e}")

    log.info(f"[stackoverflow] fetched {len(leads)} leads from {len(queries)} queries")
    return leads[:limit]

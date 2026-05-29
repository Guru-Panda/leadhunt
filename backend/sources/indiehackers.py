"""
IndieHackers lead source.
Uses IndieHackers' public RSS feed — no API key needed.
Great for finding founders and indie makers actively discussing problems.
"""
from __future__ import annotations

import hashlib
import logging
import re
import xml.etree.ElementTree as ET

import httpx

log = logging.getLogger(__name__)
NAME = "indiehackers"

_FEEDS = [
    "https://www.indiehackers.com/feed.xml",
    "https://www.indiehackers.com/posts/feed.xml",
]
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; LeadHunt/1.0) AppleWebKit/537.36",
}
_NS = {
    "atom":    "http://www.w3.org/2005/Atom",
    "content": "http://purl.org/rss/1.0/modules/content/",
    "dc":      "http://purl.org/dc/elements/1.1/",
}


def _stable_id(url: str, title: str) -> str:
    return f"ih_{hashlib.md5((url or title).encode()).hexdigest()[:16]}"


def _text(el, *paths: str) -> str:
    for path in paths:
        child = el.find(path, _NS)
        if child is not None and child.text:
            return child.text.strip()
    return ""


def _fetch_feed(url: str) -> list[dict]:
    try:
        resp = httpx.get(url, headers=_HEADERS, timeout=20, follow_redirects=True)
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
    except Exception as e:
        log.warning(f"IH feed unavailable {url}: {e}")
        return []

    posts = []
    for item in root.findall(".//item"):
        title  = _text(item, "title")
        desc   = _text(item, "description", "content:encoded")
        link   = _text(item, "link")
        author = _text(item, "author", "dc:creator")
        content = f"{title}\n\n{desc}".strip() if desc else title
        if not content:
            continue
        posts.append({
            "raw_id": _stable_id(link, title),
            "title": title,
            "content": content[:2000],
            "link": link or None,
            "author": author or None,
        })

    for entry in root.findall("atom:entry", _NS):
        title  = _text(entry, "atom:title", "title")
        desc   = _text(entry, "atom:summary", "atom:content", "summary", "content")
        link_el = entry.find("atom:link", _NS) or entry.find("link")
        link   = (link_el.get("href") if link_el is not None else None) or ""
        author_el = entry.find("atom:author/atom:name", _NS) or entry.find("author/name")
        author = author_el.text.strip() if author_el is not None and author_el.text else None
        content = f"{title}\n\n{desc}".strip() if desc else title
        if not content:
            continue
        posts.append({
            "raw_id": _stable_id(link, title),
            "title": title,
            "content": content[:2000],
            "link": link or None,
            "author": author,
        })

    log.info(f"IH feed {url}: {len(posts)} items")
    return posts


def _keyword_match(text: str, keywords: list[str], phrases: list[str]) -> bool:
    lower = text.lower()
    for phrase in phrases:
        if phrase.lower() in lower:
            return True
    for kw in keywords:
        if re.search(r"\b" + re.escape(kw.lower()) + r"\b", lower):
            return True
    return False


def _build_lead(post: dict) -> dict:
    signals = ["active_ih_discussion", "buyer_intent_post"]
    return {
        "external_id": post["raw_id"],
        "person_name": post["author"] or "IndieHackers member",
        "person_title": None,
        "source": NAME,
        "source_url": post["link"],
        "source_profile_url": None,
        "source_snippet": f"IndieHackers: {post['title']}\n\n{post['content'][:600]}",
        "person_email": None,
        "raw_data": {
            "bio": post["content"][:500],
            "context": f"IndieHackers post: {post['title'][:200]}",
        },
        "intent_signals": signals,
    }


def fetch(icp_params: dict, limit: int = 50) -> list[dict]:
    buyer_phrases = icp_params.get("buyer_phrases") or []
    keywords = (icp_params.get("buyer_intent_keywords") or []) + (icp_params.get("tech_keywords") or [])
    if not buyer_phrases and not keywords:
        return []

    seen: set[str] = set()
    matched: list[dict] = []

    for feed_url in _FEEDS:
        for post in _fetch_feed(feed_url):
            raw_id = post["raw_id"]
            if raw_id in seen:
                continue
            if not _keyword_match(post["content"], keywords, buyer_phrases):
                continue
            seen.add(raw_id)
            matched.append(_build_lead(post))
            if len(matched) >= limit:
                break
        if len(matched) >= limit:
            break

    log.info(f"[indiehackers] {len(matched)} leads matched keywords")
    return matched[:limit]

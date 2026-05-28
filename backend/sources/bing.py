from __future__ import annotations

import logging
import time
from urllib.parse import urlparse

import httpx
from selectolax.parser import HTMLParser

from backend.llm import llm_json

log = logging.getLogger(__name__)
NAME = "bing"  # kept for DB/badge compat; engine is Mojeek + LLM extraction

_MOJEEK = "https://www.mojeek.com/search"
_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15"


def _mojeek_search(query: str, limit: int = 12) -> list[dict]:
    """Mojeek returns server-rendered HTML and doesn't bot-block."""
    try:
        r = httpx.get(_MOJEEK, params={"q": query}, headers={"User-Agent": _UA, "Accept": "text/html"},
                      timeout=12, follow_redirects=True)
        if r.status_code != 200:
            return []
        tree = HTMLParser(r.text)
        out: list[dict] = []
        for li in tree.css(".results-standard li, ul.results-standard li, .results li"):
            a = li.css_first("a.title, h2 a, a")
            snip = li.css_first(".s, p")
            if not a:
                continue
            out.append({
                "title": a.text(strip=True),
                "url": a.attributes.get("href", ""),
                "snippet": snip.text(strip=True) if snip else "",
            })
            if len(out) >= limit:
                break
        return out
    except Exception as e:
        log.warning(f"Mojeek search failed for {query!r}: {e}")
        return []


def _domain_of(url: str) -> str | None:
    try:
        host = urlparse(url).netloc
        return host[4:] if host.startswith("www.") else host or None
    except Exception:
        return None


_JUNK_DOMAINS = ("youtube.com", "wikipedia.org", "reddit.com", "twitter.com", "x.com",
                 "facebook.com", "instagram.com", "tiktok.com", "pinterest.com", "amazon.")


def _build_queries(icp: dict) -> list[str]:
    """Hunt for forum/Q&A posts where people EXPRESS the need — using buyer_phrases.

    Appends site hints (reddit/quora/forum) so results skew toward real people
    asking questions, not company marketing pages.
    """
    buyer_phrases = (icp.get("buyer_phrases") or [])[:6]
    intent = (icp.get("buyer_intent_keywords") or [])[:2]

    queries: list[str] = []
    for p in buyer_phrases:
        # Quote the phrase + bias toward discussion sites
        queries.append(f'"{p}"')
    for i in intent:
        queries.append(i)

    seen, deduped = set(), []
    for q in queries:
        if q.strip() and q not in seen:
            seen.add(q)
            deduped.append(q.strip())
    # Cap at 3 queries to conserve Groq daily token budget
    return deduped[:3]


def fetch(icp_params: dict, limit: int = 50) -> list[dict]:
    """General-purpose web lead finder: Mojeek search + LLM extraction.

    Works for ANY topic because it just reads search results and asks the LLM
    'who in here matches our ICP?' — no hardcoded industry assumptions.
    """
    queries = _build_queries(icp_params)
    if not queries:
        return []

    main_problem = icp_params.get("_main_problem", "")
    ideal_customer = icp_params.get("_ideal_customer", "")
    intent = icp_params.get("buyer_intent_keywords", [])

    leads: list[dict] = []
    seen: set[str] = set()

    for query in queries:
        results = _mojeek_search(query, limit=12)
        # Filter out social/junk domains before sending to LLM
        results = [r for r in results if r.get("url") and not any(j in (_domain_of(r["url"]) or "") for j in _JUNK_DOMAINS)]
        if not results:
            time.sleep(1)
            continue

        # Hand the search results to the LLM for extraction
        results_block = "\n".join(
            f"{i+1}. {r['title']}\n   URL: {r['url']}\n   {r['snippet'][:200]}"
            for i, r in enumerate(results[:10])
        )
        prompt = f"""You are a lead researcher. From the web-search results below, extract PEOPLE or COMPANIES that match this customer profile.

WHO WE'RE LOOKING FOR:
- Our goal: {main_problem or query}
- Ideal customer: {ideal_customer or 'see goal'}
- Buyer signals: {intent}

SEARCH RESULTS (query: "{query}"):
{results_block}

Extract up to 8 real leads. ONLY include results that genuinely match — skip generic articles, listicles, "how to" guides, and directories with no specific named entity.

Return ONLY JSON list (empty list if nothing matches):
[
  {{
    "person_name": "Full name OR company name if no person",
    "person_title": "role/title or null",
    "company_name": "company or null",
    "url": "the result URL this came from",
    "why_fit": "one sentence — what in the result shows they match our buyer signal"
  }}
]"""
        try:
            extracted = llm_json(prompt, high_quality=False, max_tokens=1200)
            if not isinstance(extracted, list):
                continue
        except Exception as e:
            log.warning(f"Web-search LLM extract failed for {query!r}: {e}")
            continue

        for item in extracted:
            if not isinstance(item, dict):
                continue
            name = (item.get("person_name") or "").strip()
            url = (item.get("url") or "").strip()
            if not name or not url or url in seen:
                continue
            seen.add(url)
            domain = _domain_of(url)
            leads.append({
                "external_id": f"web_{url[:90]}",
                "person_name": name,
                "person_title": item.get("person_title"),
                "company_name": item.get("company_name"),
                "company_domain": domain,
                "source": NAME,
                "source_url": url,
                "source_profile_url": url,
                "source_snippet": f"Web search '{query}': {item.get('why_fit', '')}",
                "raw_data": {
                    "context": item.get("why_fit", ""),
                    "search_query": query,
                    "search_url": url,
                },
                "intent_signals": ["found_via_web_search"],
            })
            if len(leads) >= limit:
                return leads[:limit]

        time.sleep(1)  # gentle on Mojeek

    return leads[:limit]

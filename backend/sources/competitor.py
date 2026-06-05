"""Competitor switch-intent source.

Given the user's competitor names, mine public mentions for people/companies who
are UNHAPPY with that competitor or looking to switch — the warmest leads there
are. Uses the web-search pool (incl. Reddit via site: search) + negative app-store
reviews (google-play-scraper), then the LLM pool extracts genuine switch signals
with the complaint quote as proof.

Compliance: we surface the public complaint + where it was said; we do not harvest
private contact data. The user decides whether/how to reach out.
"""
from __future__ import annotations

import logging

from backend.llm import llm_json, llm_status
from backend.search_providers import web_search

log = logging.getLogger(__name__)
NAME = "competitor"


def _negative_app_reviews(name: str, max_reviews: int = 30) -> list[dict]:
    """Low-star Google Play reviews for the competitor's app (optional/best-effort)."""
    try:
        from google_play_scraper import Sort, reviews as gp_reviews, search as gp_search
    except Exception:
        return []
    try:
        hits = gp_search(name, n_hits=1)
        if not hits:
            return []
        app_id = hits[0]["appId"]
        revs, _ = gp_reviews(app_id, count=max_reviews, sort=Sort.NEWEST)
        return [
            {"text": f"App review ({r.get('score')}★): {r['content']}", "url": f"https://play.google.com/store/apps/details?id={app_id}"}
            for r in revs if (r.get("score") or 5) <= 2 and r.get("content")
        ]
    except Exception as e:
        log.debug(f"[competitor] play reviews failed for {name!r}: {e}")
        return []


def _gather_mentions(comp: str) -> list[dict]:
    out: list[dict] = []
    queries = [
        f'"{comp}" alternative',
        f'switching from "{comp}"',
        f'"{comp}" complaint OR cancel OR "switched from"',
        f'site:reddit.com "{comp}" alternative',
    ]
    for q in queries:
        for r in web_search(q, limit=5):
            if r.get("url"):
                out.append({"text": f"{r.get('title','')} — {r.get('snippet','')}", "url": r["url"]})
    out.extend(_negative_app_reviews(comp))
    return out


def fetch(icp_params: dict, limit: int = 30) -> list[dict]:
    competitors = icp_params.get("competitors") or []
    if not competitors:
        return []
    if llm_status().get("rate_limited"):
        log.info("[competitor] LLM unavailable — skipping (extraction needs the LLM)")
        return []

    main_problem = icp_params.get("_main_problem", "")
    leads: list[dict] = []
    seen: set[str] = set()

    for comp in competitors[:3]:
        mentions = _gather_mentions(comp)
        if not mentions:
            continue
        block = "\n".join(f"{i+1}. {m['text'][:300]} [{m['url']}]" for i, m in enumerate(mentions[:20]))
        prompt = f"""From these public mentions of the competitor "{comp}", find PEOPLE or COMPANIES who are unhappy with {comp} or looking to switch away — they are warm leads for us.
Our offering: {main_problem or f"an alternative to {comp}"}

MENTIONS:
{block}

Return ONLY a JSON list (empty if none qualify):
[{{"person_name": "name/company or null", "complaint": "verbatim quote of their dissatisfaction", "url": "the source URL from the list"}}]
Rules: only include GENUINE dissatisfaction or switch intent. `complaint` MUST be a quote that appears in the mentions above."""
        try:
            items = llm_json(prompt, high_quality=False, max_tokens=1200)
        except Exception as e:
            log.warning(f"[competitor] extraction failed for {comp!r}: {e}")
            continue
        if not isinstance(items, list):
            continue

        # Verify each complaint is grounded in the gathered text (anti-hallucination)
        corpus = " ".join(m["text"] for m in mentions).lower()
        for it in items:
            if not isinstance(it, dict):
                continue
            complaint = (it.get("complaint") or "").strip()
            url = (it.get("url") or "").strip()
            name = (it.get("person_name") or "").strip()
            if not complaint or url in seen:
                continue
            # Grounding check (anti-hallucination): keep if a chunk of the complaint
            # or the named person/company actually appears in the gathered text.
            probe = complaint.lower()[:25]
            name_l = name.lower()
            grounded = (probe and probe in corpus) or (len(name_l) > 3 and name_l in corpus)
            if not grounded:
                continue
            seen.add(url)
            is_http = url.startswith("http")
            leads.append({
                "external_id": f"competitor_{comp}_{url[:80]}",
                "person_name": name or f"Unhappy {comp} user",
                "company_name": name if (name and " " not in name) else None,
                "source": NAME,
                "source_url": url if is_http else None,
                "source_profile_url": url if is_http else None,
                "source_snippet": f"Switch signal from {comp}: “{complaint[:400]}”",
                "raw_data": {"competitor": comp, "complaint": complaint, "context": complaint},
                "intent_signals": ["switch_intent", "competitor_complaint"],
            })
            if len(leads) >= limit:
                log.info(f"[competitor] {len(leads)} switch-intent leads")
                return leads[:limit]

    log.info(f"[competitor] {len(leads)} switch-intent leads from {competitors[:3]}")
    return leads[:limit]

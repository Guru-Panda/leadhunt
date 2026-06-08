"""Targeted-website source.

When the user names specific websites on a strategy (`target_websites`), hunt
those sites directly instead of the open web:
  1. `site:domain "<buyer phrase>"` searches surface the most relevant pages on
     that domain (team, customer stories, forum threads, directory listings…).
  2. The universal extractor then pulls real people off those pages + a few
     conventional pages (/about, /team, /contact).

This is how "only look on these sites for me" works. Everything is grounded:
the extractor keeps only people whose name/email literally appears on the page.
"""
from __future__ import annotations

import logging
from types import SimpleNamespace

from backend.llm import llm_status
from backend.search_providers import web_search

log = logging.getLogger(__name__)
NAME = "sites"

_COMMON_PAGES = ("about", "team", "about-us", "company", "contact", "people")
_MAX_DOMAINS = 4
_MAX_PAGES_PER_DOMAIN = 5


def _shim_strategy(icp: dict) -> SimpleNamespace:
    """Minimal object exposing the fields the universal extractor reads."""
    return SimpleNamespace(
        main_problem=icp.get("_main_problem", "") or "",
        ideal_customer=icp.get("_ideal_customer", "") or "",
        target_roles=icp.get("target_roles") or [],
    )


def _candidate_urls(domain: str, icp: dict) -> list[str]:
    urls: list[str] = []
    # site:-scoped searches for the most relevant deep pages.
    probes = (icp.get("buyer_phrases") or [])[:2] + (icp.get("buyer_intent_keywords") or [])[:1]
    for p in probes:
        for r in web_search(f'site:{domain} "{p}"', limit=4):
            u = (r.get("url") or "").strip()
            if u and domain in u and u not in urls:
                urls.append(u)
    # Conventional contact-bearing pages.
    for path in _COMMON_PAGES:
        urls.append(f"https://{domain}/{path}")
    urls.insert(0, f"https://{domain}")
    # de-dupe, preserve order, cap
    seen: set[str] = set()
    return [u for u in urls if not (u in seen or seen.add(u))][:_MAX_PAGES_PER_DOMAIN]


def fetch(icp_params: dict, limit: int = 30) -> list[dict]:
    domains = icp_params.get("target_websites") or []
    if not domains:
        return []
    if llm_status().get("rate_limited"):
        log.info("[sites] LLM unavailable — skipping (lead extraction needs the LLM)")
        return []

    from backend.pipeline.universal_extractor import extract_leads_from_url

    shim = _shim_strategy(icp_params)
    leads: list[dict] = []
    seen_ext: set[str] = set()

    for domain in domains[:_MAX_DOMAINS]:
        for url in _candidate_urls(domain, icp_params):
            for p in extract_leads_from_url(url, shim):
                ext_id = (p.get("person_email") or p.get("person_linkedin_url")
                          or p.get("person_name") or "")
                if not ext_id or ext_id in seen_ext:
                    continue
                seen_ext.add(ext_id)
                p["external_id"] = f"sites_{domain}_{ext_id}"[:480]
                p["source"] = NAME
                p.setdefault("company_domain", domain)
                p["source_url"] = url
                p.setdefault("source_profile_url", p.get("person_linkedin_url") or url)
                if not p.get("source_snippet"):
                    ctx = p.get("context") or ""
                    p["source_snippet"] = f"Found on {domain}\n{url}\n\n{ctx}".strip()
                p.setdefault("raw_data", {})
                p["raw_data"].setdefault("context", p.get("context", ""))
                p["raw_data"]["target_site"] = domain
                p["intent_signals"] = ["from_target_site"]
                leads.append(p)
                if len(leads) >= limit:
                    log.info(f"[sites] {len(leads)} leads from {domains[:_MAX_DOMAINS]} (limit hit)")
                    return leads[:limit]

    log.info(f"[sites] {len(leads)} leads from target sites {domains[:_MAX_DOMAINS]}")
    return leads[:limit]

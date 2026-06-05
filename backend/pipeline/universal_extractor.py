from __future__ import annotations

import logging

import httpx
from selectolax.parser import HTMLParser

from backend.llm import llm_json

log = logging.getLogger(__name__)


def extract_visible_text_with_links(html: str, limit: int = 20000) -> str:
    try:
        tree = HTMLParser(html)
        for tag in tree.css("script, style, nav, footer, header"):
            tag.decompose()
        text = tree.root.text(separator=" ", strip=True)
        return text[:limit]
    except Exception:
        return html[:limit]


def extract_leads_from_url(url: str, strategy) -> list[dict]:
    try:
        r = httpx.get(
            url, timeout=15,
            headers={"User-Agent": "Mozilla/5.0 LeadHunt/1.0"},
            follow_redirects=True,
        )
        html = r.text
    except Exception as e:
        log.warning(f"Universal extractor fetch failed for {url}: {e}")
        return []

    text = extract_visible_text_with_links(html, limit=20000)

    prompt = f"""Extract people who could be leads for this business from the page below.
Our business solves: {strategy.main_problem}
Our ideal customer: {strategy.ideal_customer}
Target roles: {strategy.target_roles}
URL: {url}

Page content:
{text[:18000]}

Return ONLY JSON list (no markdown):
[
  {{
    "person_name": "Full Name",
    "person_title": "Job title or null",
    "person_email": "email if visible or null",
    "person_linkedin_url": "if present or null",
    "person_github_url": "if present or null",
    "company_name": "Company or null",
    "company_domain": "Domain or null",
    "person_location": "Location or null",
    "context": "1 sentence: why they fit",
    "fit_score": 0.0
  }}
]
ONLY include people who plausibly match the ICP. Skip irrelevant ones.
Max 30 people per page. Empty list if no fits."""

    try:
        result = llm_json(prompt, high_quality=False, max_tokens=2500)
        if not isinstance(result, list):
            return []
        # Anti-hallucination: keep only people whose name OR email literally
        # appears in the scraped page text. The LLM otherwise invents plausible
        # people that aren't actually on the page.
        low = text.lower()
        verified = []
        for p in result:
            if not isinstance(p, dict):
                continue
            nm = (p.get("person_name") or "").strip().lower()
            em = (p.get("person_email") or "").strip().lower()
            if (nm and nm in low) or (em and em in low):
                verified.append(p)
        if len(verified) < len(result):
            log.info(f"Universal extractor dropped {len(result) - len(verified)} hallucinated leads from {url}")
        return verified
    except Exception as e:
        log.warning(f"Universal extractor LLM parse failed for {url}: {e}")
        return []

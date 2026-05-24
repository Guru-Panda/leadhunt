from __future__ import annotations

import json
import logging

from sqlalchemy.orm import Session

from backend.llm import llm_json

log = logging.getLogger(__name__)


def translate_icp(strategy, db: Session) -> dict:
    prompt = f"""Convert this business strategy into structured ICP search parameters.
Business problem: {strategy.main_problem}
Ideal customer: {strategy.ideal_customer}
Keywords: {strategy.keywords}
Target locations: {strategy.target_locations}

Return ONLY valid JSON (no markdown):
{{
  "industries": ["fintech", "data analytics"],
  "target_roles": ["CTO", "Head of Engineering"],
  "company_size_min": 10,
  "company_size_max": 5000,
  "tech_keywords": ["python", "kafka"],
  "github_topics": ["fintech", "api"],
  "github_user_queries": ["language:python location:London fintech"],
  "hn_queries": ["risk modeling", "agent based modeling"],
  "google_search_patterns": [
    "site:linkedin.com/in \\"CTO\\" \\"fintech\\"",
    "site:linkedin.com/in \\"head of engineering\\" \\"startup\\""
  ],
  "twitter_bio_keywords": ["founder", "engineer"],
  "indeed_job_queries": ["software engineer startup"],
  "exclude_keywords": ["course", "tutorial", "intern", "student"]
}}"""

    try:
        parsed = llm_json(prompt, high_quality=True, max_tokens=1200)
        strategy.target_industries = parsed.get("industries", [])
        strategy.target_roles = parsed.get("target_roles", [])
        strategy.raw_icp_params = parsed
        db.commit()
        log.info(f"ICP translated for strategy {strategy.id}: {len(strategy.target_roles)} roles, {len(strategy.target_industries)} industries")
        return parsed
    except Exception as e:
        log.error(f"ICP translation failed for strategy {strategy.id}: {e}")
        return {}

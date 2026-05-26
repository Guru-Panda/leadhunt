from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from backend.llm import llm_json

log = logging.getLogger(__name__)


def translate_icp(strategy, db: Session) -> dict:
    """Convert freeform strategy into structured ICP search params.

    Critical field: `buyer_intent_keywords`. These describe WHAT THE LEAD DOES
    that makes them a buyer — not just industry/role. E.g.
      "I sell sponsorship packages"        -> ["sponsor", "sponsorship", "sponsored event", "partner"]
      "I sell cold-outreach tools"         -> ["cold email", "outbound", "lead gen", "sdr"]
      "I sell hiring software"             -> ["hiring", "we're hiring", "open roles", "recruiting"]
      "I sell tools to fundraisers"        -> ["just raised", "seed round", "series a", "fundraising"]
    Every source filters on these keywords + the scorer re-checks them on the
    lead's actual bio / post / company one-liner.
    """
    prompt = f"""You are an expert at converting business strategies into structured lead-search parameters.

BUSINESS STRATEGY:
- Problem we solve: {strategy.main_problem}
- Ideal customer: {strategy.ideal_customer}
- User-provided keywords: {strategy.keywords}
- Target locations: {strategy.target_locations}

Extract:
- `industries`: 3-5 industry tags the lead's company would be in
- `target_roles`: 3-5 job titles the buyer typically holds (decision-makers)
- `buyer_intent_keywords`: CRITICAL — the specific verbs/nouns that indicate this person/company is ACTIVELY a buyer. NOT just "they're in fintech" — but what action/signal shows they need our solution RIGHT NOW. Look at the business problem to figure out what signal the buyer would emit.

  Examples:
   * "sells to companies that sponsor conferences" → ["sponsor", "sponsorship", "sponsored event", "partnership opportunity", "we sponsor"]
   * "sells cold-outreach automation" → ["cold email", "outbound sales", "lead gen", "sdr", "prospecting", "sales pipeline"]
   * "sells hiring software" → ["hiring", "we're hiring", "open roles", "recruiting", "join our team"]
   * "sells to recently-funded startups" → ["just raised", "seed round", "series a", "fundraising", "announcing our funding"]
   * "sells KYC automation" → ["kyc", "compliance burden", "manual onboarding", "regulatory headache"]

- `tech_keywords`, `github_topics`, `github_user_queries`, `hn_queries`, `google_search_patterns`, `twitter_bio_keywords`, `indeed_job_queries`: as before
- `exclude_keywords`: terms that mean the result is irrelevant (course, tutorial, intern, student, etc.)

Return ONLY valid JSON (no markdown):
{{
  "industries": ["..."],
  "target_roles": ["..."],
  "buyer_intent_keywords": ["...", "..."],
  "company_size_min": 10,
  "company_size_max": 5000,
  "tech_keywords": ["..."],
  "github_topics": ["..."],
  "github_user_queries": ["..."],
  "hn_queries": ["..."],
  "google_search_patterns": [
    "site:linkedin.com/in \\"role\\" \\"industry\\""
  ],
  "twitter_bio_keywords": ["..."],
  "indeed_job_queries": ["..."],
  "exclude_keywords": ["course", "tutorial", "intern", "student"]
}}"""

    try:
        parsed = llm_json(prompt, high_quality=True, max_tokens=1400)
        strategy.target_industries = parsed.get("industries", [])
        strategy.target_roles = parsed.get("target_roles", [])
        strategy.raw_icp_params = parsed
        db.commit()
        log.info(
            f"ICP translated for strategy {strategy.id}: "
            f"{len(strategy.target_roles)} roles, {len(strategy.target_industries)} industries, "
            f"{len(parsed.get('buyer_intent_keywords', []))} intent keywords"
        )
        return parsed
    except Exception as e:
        log.error(f"ICP translation failed for strategy {strategy.id}: {e}")
        return {}

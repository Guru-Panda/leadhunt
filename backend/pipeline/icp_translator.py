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

- `buyer_phrases`: THE MOST IMPORTANT FIELD. 10-15 realistic phrases a prospect would actually TYPE/POST online when they need what we offer. These are how we find people EXPRESSING the need — not just industry matches. Write them as natural search/forum language, first-person where natural.

  Examples for "we sell website load-testing tools":
   ["looking for a load testing tool", "how do I simulate website traffic", "recommendations for stress testing my site", "best tool to test server under load", "my site crashes under traffic help", "alternatives to loadrunner", "anyone use a good performance testing service"]

  Examples for "we help R&B/Hip-hop radio hosts find sponsors":
   ["looking for sponsors for my podcast", "how to get brand deals for my radio show", "where to find music sponsorship", "brands that sponsor hip hop content", "need a sponsor for my show", "how do indie radio hosts get sponsorships"]

- `tech_keywords`, `github_topics`, `github_user_queries`, `hn_queries`, `google_search_patterns`, `twitter_bio_keywords`, `indeed_job_queries`: as before
- `exclude_keywords`: terms that mean the result is irrelevant (course, tutorial, intern, student, etc.)

Return ONLY valid JSON (no markdown):
{{
  "industries": ["..."],
  "target_roles": ["..."],
  "buyer_intent_keywords": ["...", "..."],
  "buyer_phrases": ["looking for ...", "how do I ...", "recommendations for ...", "..."],
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
        parsed = llm_json(prompt, high_quality=True, max_tokens=1600)
        # Carry the raw strategy text into raw_icp_params so sources (esp. the
        # general web-search extractor) can use it without the strategy object.
        parsed["_main_problem"] = strategy.main_problem
        parsed["_ideal_customer"] = strategy.ideal_customer
        # Merge any user-entered buyer phrases with the LLM-generated ones (user first)
        user_phrases = list(strategy.buyer_phrases or [])
        gen_phrases = list(parsed.get("buyer_phrases", []) or [])
        merged = list(dict.fromkeys([p for p in (user_phrases + gen_phrases) if p and p.strip()]))
        parsed["buyer_phrases"] = merged
        strategy.target_industries = parsed.get("industries", [])
        strategy.target_roles = parsed.get("target_roles", [])
        strategy.raw_icp_params = parsed
        db.commit()
        log.info(f"ICP for strategy {strategy.id}: {len(merged)} buyer phrases generated")
        log.info(
            f"ICP translated for strategy {strategy.id}: "
            f"{len(strategy.target_roles)} roles, {len(strategy.target_industries)} industries, "
            f"{len(parsed.get('buyer_intent_keywords', []))} intent keywords"
        )
        return parsed
    except Exception as e:
        log.error(f"ICP translation failed for strategy {strategy.id}: {e}")
        return {}

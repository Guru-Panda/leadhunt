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

- `buyer_phrases`: THE MOST IMPORTANT FIELD. 10-15 realistic phrases a prospect would actually TYPE/POST online when they need what we offer. These are FIRST-PERSON expressions of an active need — not industry jargon. Write as natural forum/social language.

  Examples for "we sell website load-testing tools":
   ["looking for a load testing tool", "how do I simulate website traffic", "recommendations for stress testing my site", "best tool to test server under load", "my site crashes under traffic", "alternatives to loadrunner"]

  Examples for "we help R&B/Hip-hop radio hosts find sponsors":
   ["looking for sponsors for my podcast", "how to get brand deals for my radio show", "where to find music sponsorship", "need a sponsor for my show", "brands that sponsor hip hop content"]

  Examples for "we book wedding DJs in Albany NY":
   ["looking for wedding DJ recommendations", "need a DJ for my wedding in Albany", "can anyone recommend a good wedding DJ", "best wedding DJ in upstate NY", "how much does a wedding DJ cost", "DJ recommendations for reception", "wedding entertainment ideas"]

- `target_subreddits`: 3-6 specific subreddit names (without r/) WHERE your ideal buyers congregate and post. Think: where would someone go to ask for what you sell?

  Examples:
  - Wedding DJ → ["weddingplanning", "weddingadvice", "Brides", "wedding", "upstateNY"]
  - HR software → ["humanresources", "smallbusiness", "entrepreneur", "startups"]
  - Dev tools → ["webdev", "devops", "programming", "ExperiencedDevs"]
  - Podcast sponsors → ["podcasting", "podcasters", "mildlyinfluential"]

- `tech_keywords`, `github_topics`, `github_user_queries`, `google_search_patterns`, `twitter_bio_keywords`, `indeed_job_queries`: as before
- `exclude_keywords`: terms that mean the result is irrelevant (course, tutorial, intern, student, etc.)
- `recommended_sources`: CRITICAL — pick 3-6 source names from this exact list that will find the most leads for this specific strategy. Choose based on WHERE the ideal customer actually spends time online.

  Available sources and when to use them:
  - `apollo`       — ALWAYS include for B2B; 275M contact database with verified emails + LinkedIn URLs; best data quality
  - `linkedin`     — include for B2B; professionals with job titles; decision-makers
  - `google_cse`   — include for B2B; finds LinkedIn profiles via Google (more reliable than Mojeek)
  - `reddit`       — include when the ICP has active subreddits (devs, marketers, founders, consumers, any hobbyist niche); GREAT for local services and consumer products
  - `github`       — include for developer tools, APIs, open-source, technical B2B SaaS
  - `stackoverflow`— include for developer tools, DevOps, data engineering, anything a programmer would search
  - `devto`        — include for developer tools, engineering culture, technical content
  - `indiehackers` — include for indie SaaS, bootstrapped founders, productized services, solopreneurs
  - `bing`         — include as a catch-all web search fallback for any strategy; especially useful for niche/non-tech ICPs

  Examples:
  - B2B HR software → ["apollo", "linkedin", "google_cse", "reddit", "indiehackers"]
  - Developer API tool → ["apollo", "github", "stackoverflow", "devto", "reddit"]
  - Local consumer service (wedding, events) → ["reddit", "bing", "google_cse"]
  - SaaS for indie founders → ["apollo", "indiehackers", "reddit", "linkedin"]

Return ONLY valid JSON (no markdown):
{{
  "industries": ["..."],
  "target_roles": ["..."],
  "buyer_intent_keywords": ["...", "..."],
  "buyer_phrases": ["looking for ...", "how do I ...", "recommendations for ...", "..."],
  "target_subreddits": ["subreddit1", "subreddit2"],
  "company_size_min": 10,
  "company_size_max": 5000,
  "tech_keywords": ["..."],
  "github_topics": ["..."],
  "github_user_queries": ["..."],
  "google_search_patterns": [
    "site:linkedin.com/in \\"role\\" \\"industry\\""
  ],
  "twitter_bio_keywords": ["..."],
  "indeed_job_queries": ["..."],
  "exclude_keywords": ["course", "tutorial", "intern", "student"],
  "recommended_sources": ["linkedin", "google_cse", "reddit"]
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

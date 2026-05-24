from __future__ import annotations

import logging

from backend.llm import llm_call

log = logging.getLogger(__name__)


def generate_outreach(lead, strategy) -> str:
    """Generate a personalized cold outreach email.

    The MOST important input is the source_snippet — that's the actual text the
    person wrote (HN comment, Reddit post, YC company one-liner, etc.). Referencing
    it specifically dramatically lifts reply rates over generic templates.
    """
    snippet = (lead.source_snippet or "")[:1000]
    context = str((lead.raw_data or {}).get("context", ""))[:300]
    source_url = lead.source_url or ""
    intent_signals = ", ".join(lead.intent_signals or [])

    prompt = f"""Write a short, personalized cold outreach email.

OUR BUSINESS:
- We solve: {strategy.main_problem}
- Ideal customer: {strategy.ideal_customer}

THE LEAD:
- Name: {lead.person_name}
- Title: {lead.person_title or "unknown"}
- Company: {lead.company_name or "unknown"}
- Found via: {lead.source}
- Intent signals: {intent_signals}
- Original context: {context}

THEIR ACTUAL POST / PROFILE (use this for specific personalization — paraphrase, never copy verbatim):
\"\"\"
{snippet}
\"\"\"

WRITE A SHORT EMAIL (max 110 words):
1. Subject line: specific, NOT clickbait — reference something from their post or company
2. Opening line: reference something CONCRETE from the snippet above (their post, role, company, tech they mentioned). NEVER use "I came across your profile" or "I noticed you" or any generic opener.
3. One sentence bridging their problem to ours
4. Low-pressure CTA ("worth a 15-min chat?" / "happy to share more if useful")
5. Sign off with a single first name (e.g. "— Alex")
6. Sound HUMAN, not templated. Match the energy of their post.

OUTPUT FORMAT (exactly this, nothing else):
SUBJECT: <subject>

<body>
"""

    return llm_call(prompt, high_quality=True, max_tokens=400)

from __future__ import annotations

import json
import logging
import re
import time

from groq import Groq

from backend.config import settings

log = logging.getLogger(__name__)

_client: Groq | None = Groq(api_key=settings.GROQ_API_KEY) if settings.GROQ_API_KEY else None

FAST_MODEL = "llama-3.1-8b-instant"
HQ_MODEL = "llama-3.3-70b-versatile"
FALLBACK_MODEL = "llama-3.1-8b-instant"


def llm_call(
    prompt: str,
    high_quality: bool = False,
    max_tokens: int = 1000,
    retries: int = 3,
) -> str:
    if _client is None:
        raise RuntimeError("GROQ_API_KEY is not configured")
    model = HQ_MODEL if high_quality else FAST_MODEL
    models_to_try = [model, FALLBACK_MODEL] if model != FALLBACK_MODEL else [FALLBACK_MODEL]

    for attempt, m in enumerate(models_to_try):
        for retry in range(retries):
            try:
                response = _client.chat.completions.create(
                    model=m,
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=max_tokens,
                    temperature=0.3,
                )
                return response.choices[0].message.content.strip()
            except Exception as e:
                wait = 2 ** retry
                log.warning(f"LLM call failed (model={m}, retry={retry}): {e}. Waiting {wait}s")
                if retry < retries - 1:
                    time.sleep(wait)

    raise RuntimeError("All LLM models and retries exhausted")


def llm_json(prompt: str, high_quality: bool = False, max_tokens: int = 1500) -> dict | list:
    raw = llm_call(prompt, high_quality=high_quality, max_tokens=max_tokens)
    # Strip markdown code fences if present
    raw = re.sub(r"^```(?:json)?\s*", "", raw.strip())
    raw = re.sub(r"\s*```$", "", raw.strip())
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    # LLM often wraps JSON in prose ("Here's the result: [...]"). Extract the
    # outermost [...] or {...} region and try that.
    start_array = raw.find("[")
    start_object = raw.find("{")
    if start_array == -1 and start_object == -1:
        raise ValueError(f"llm_json: no JSON found in response: {raw[:200]}")
    starts = [s for s in (start_array, start_object) if s != -1]
    start = min(starts)
    open_char = raw[start]
    close_char = "]" if open_char == "[" else "}"
    end = raw.rfind(close_char)
    if end > start:
        candidate = raw[start: end + 1]
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            # Truncation repair: cut back to last "}," then close the array
            if open_char == "[":
                last_obj_end = candidate.rfind("},")
                if last_obj_end > 0:
                    repaired = candidate[: last_obj_end + 1] + "]"
                    try:
                        return json.loads(repaired)
                    except Exception:
                        pass
    log.error(f"llm_json: could not parse or repair. Raw (first 400): {raw[:400]}")
    raise ValueError(f"llm_json: parse failed for response: {raw[:200]}")

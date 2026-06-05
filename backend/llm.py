"""LLM entry points used across the pipeline.

Thin layer over the multi-provider failover pool in `llm_providers`. Keeps the
historical `llm_call` / `llm_json` / `llm_status` interface so callers (scorer,
icp_translator, discoverer, universal_extractor, bing) are unchanged.
"""
from __future__ import annotations

import json
import logging
import re

from backend.llm_providers import chat, pool_status

log = logging.getLogger(__name__)


def llm_call(prompt: str, high_quality: bool = False, max_tokens: int = 1000,
             retries: int = 2) -> str:
    """Call the LLM pool. The pool already fails over across providers; `retries`
    only guards against transient network blips (it re-runs the whole pool)."""
    last_err: Exception | None = None
    for _ in range(max(1, retries)):
        try:
            return chat(prompt, high_quality=high_quality, max_tokens=max_tokens)
        except Exception as e:
            last_err = e
    raise RuntimeError(f"LLM call failed: {last_err}")


def llm_status() -> dict:
    """Pool health. `rate_limited` is True only when EVERY provider is unavailable,
    so the pipeline only enters degraded/heuristic mode when there's truly no LLM."""
    return pool_status()


def llm_json(prompt: str, high_quality: bool = False, max_tokens: int = 1500) -> dict | list:
    raw = llm_call(prompt, high_quality=high_quality, max_tokens=max_tokens)
    # Strip markdown code fences if present
    raw = re.sub(r"^```(?:json)?\s*", "", raw.strip())
    raw = re.sub(r"\s*```$", "", raw.strip())
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    # LLMs often wrap JSON in prose ("Here's the result: [...]"). Extract the
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
            # Truncation repair: cut back to the last "}," then close the array
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

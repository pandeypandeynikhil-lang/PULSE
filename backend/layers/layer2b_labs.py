"""Layer 2b - LLM-based evaluation of uploaded laboratory results."""
from __future__ import annotations

import json
import os
from typing import Any

from .nlp_llm import _call_llm, _parse_json

_LAB_SYSTEM = (
    "You are a clinical AI. Review these labs. If there are critical "
    "abnormalities indicating an acute, life-threatening condition (e.g., "
    "severe infection, critical anemia, high lactate), return a JSON object "
    "with 'multiplier' (float between 1.1 and 1.5) and 'reason' (short "
    "string). If mostly normal, return multiplier 1.0. Output ONLY valid JSON."
)
_DEFAULT = {"multiplier": 1.0, "reason": "evaluation failed"}


def evaluate_labs(lab_results: list[dict]) -> dict:
    if not lab_results:
        return {"multiplier": 1.0, "reason": None}
    if not (os.environ.get("GEMINI_API_KEY") or os.environ.get("GROQ_API_KEY")):
        return dict(_DEFAULT)

    user_prompt = json.dumps(lab_results, ensure_ascii=True)
    parsed, _provider = _call_llm(_LAB_SYSTEM, user_prompt)
    if isinstance(parsed, dict) and "multiplier" in parsed:
        return parsed
    return dict(_DEFAULT)
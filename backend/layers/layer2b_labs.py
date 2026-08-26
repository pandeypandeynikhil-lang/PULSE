"""Layer 2b - LLM-based evaluation of uploaded laboratory results."""
from __future__ import annotations

import json
from typing import Any

from . import nlp_llm

_LAB_SYSTEM = (
    "You are a clinical AI agent. Review these lab results. If there are "
    "critical abnormalities indicating an acute, life-threatening condition "
    "(e.g., severe infection, critical anemia), return a JSON object with a "
    "'multiplier' between 1.1 and 1.5, and a short string 'reason'. If the "
    "labs are mostly normal or chronically abnormal but not immediately "
    "critical, return a 'multiplier' of 1.0. Output ONLY valid JSON."
)
_DEFAULT = {"multiplier": 1.0, "reason": "evaluation failed"}


def evaluate_labs(lab_results: list[dict]) -> dict:
    if not lab_results:
        return {"multiplier": 1.0, "reason": None}
    if not nlp_llm.any_provider_configured():
        return dict(_DEFAULT)

    try:
        parsed, _provider = nlp_llm._call_llm(  # noqa: SLF001
            _LAB_SYSTEM, json.dumps(lab_results, ensure_ascii=True))
        if not isinstance(parsed, dict):
            return dict(_DEFAULT)
        multiplier = float(parsed.get("multiplier", 1.0))
        if not 1.0 <= multiplier <= 1.5:
            return dict(_DEFAULT)
        reason = parsed.get("reason")
        if reason is not None and not isinstance(reason, str):
            return dict(_DEFAULT)
        return {"multiplier": multiplier, "reason": reason}
    except (TypeError, ValueError, json.JSONDecodeError):
        return dict(_DEFAULT)
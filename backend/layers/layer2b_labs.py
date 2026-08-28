"""Layer 2b - evaluation of uploaded laboratory results.

Two tiers, same pattern as every other LLM-backed layer in this codebase:
an LLM read of the full panel first (catches things a fixed rule can't —
"critical anaemia," "severe infection" are judgment calls, not a single
threshold), and a deterministic fallback under it. Before this fallback
existed, an LLM outage meant a critically abnormal panel scored identically
to a normal one — silently, with no signal anywhere that anything had been
skipped. This tier no longer has that gap.
"""
from __future__ import annotations

import json
import re
from typing import Any

from .nlp_llm import any_provider_configured, call_llm_json

_LAB_SYSTEM = (
    "You are a clinical AI. Review these labs. If there are critical "
    "abnormalities indicating an acute, life-threatening condition (e.g., "
    "severe infection, critical anemia, high lactate), return a JSON object "
    "with 'multiplier' (float between 1.1 and 1.5) and 'reason' (short "
    "string). If mostly normal, return multiplier 1.0. Output ONLY valid JSON."
)

_RANGE_RE = re.compile(r"(-?\d+\.?\d*)\s*(?:-|to)\s*(-?\d+\.?\d*)", re.I)
_NUMBER_RE = re.compile(r"-?\d+\.?\d*")


def evaluate_labs(lab_results: list[dict]) -> dict:
    if not lab_results:
        return {"multiplier": 1.0, "reason": None}

    fallback = _deterministic_fallback(lab_results)
    if not any_provider_configured():
        return fallback

    parsed, _provider = call_llm_json(
        _LAB_SYSTEM, json.dumps(lab_results, ensure_ascii=True))
    multiplier = _valid_multiplier(parsed)
    if multiplier is None:
        return fallback
    reason = parsed.get("reason") if isinstance(parsed, dict) else None
    return {"multiplier": multiplier, "reason": reason if isinstance(reason, str) else None}


def _valid_multiplier(parsed: Any) -> float | None:
    """Never trust the shape of an LLM response without checking it — same
    rule as everywhere else that parses one. A multiplier outside its
    documented 1.0-1.5 range, or one that isn't actually a number (a model
    occasionally returns "1.5" as a string), is treated as a failed
    evaluation, not silently coerced or clamped into range."""
    if not isinstance(parsed, dict):
        return None
    raw = parsed.get("multiplier")
    if isinstance(raw, bool) or not isinstance(raw, (int, float, str)):
        return None
    try:
        multiplier = float(raw)
    except (TypeError, ValueError):
        return None
    return multiplier if 1.0 <= multiplier <= 1.5 else None


def _deterministic_fallback(lab_results: list[dict]) -> dict:
    """The offline floor: trust a nurse-confirmed abnormality_flag first
    (it is, if anything, a stronger signal than an LLM's own read of the
    number), then fall back to comparing the reported value against the
    lab's own reference range. Not as clinically nuanced as the LLM tier —
    it can't tell "critical" from "mildly abnormal" the way a read of the
    whole panel can — but it means an LLM outage degrades to *reduced
    sensitivity to severity*, not to *zero signal from labs at all*.
    """
    abnormal, reasons = 0, []
    for result in lab_results:
        if not isinstance(result, dict):
            continue
        name = str(result.get("test_name") or "result").strip()
        flagged = result.get("abnormality_flag") in ("H", "L", "A")
        out_of_range = _outside_reference_range(
            result.get("value"), result.get("reference_range"))
        if flagged or out_of_range:
            abnormal += 1
            reasons.append(f"{name} outside reference range")

    if abnormal == 0:
        return {"multiplier": 1.0, "reason": None}
    # Two independent judgment calls (multiple abnormal results) carry more
    # weight than one — same "corroboration raises confidence" idea Layer 3
    # already applies via its synergy multiplier, kept modest because this
    # tier has no way to judge clinical severity, only "in range or not."
    multiplier = 1.25 if abnormal >= 2 else 1.1
    return {"multiplier": multiplier, "reason": "; ".join(reasons[:3])}


def _outside_reference_range(value: Any, reference_range: Any) -> bool:
    """False whenever either field can't be parsed as a numeric range —
    most lab values are, but qualitative results ("Positive", "Trace") and
    freeform ranges are common enough that "can't tell" must mean "don't
    flag," not "assume abnormal.\""""
    if not isinstance(reference_range, str):
        return False
    range_match = _RANGE_RE.search(reference_range)
    value_match = _NUMBER_RE.search(str(value)) if value is not None else None
    if not range_match or not value_match:
        return False
    try:
        low, high = float(range_match.group(1)), float(range_match.group(2))
        numeric_value = float(value_match.group())
    except ValueError:
        return False
    return not (low <= numeric_value <= high)

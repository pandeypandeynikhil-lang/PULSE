"""Layer 1b - deterministic clinical safety heuristics."""
from __future__ import annotations

from typing import Any


def _number(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def evaluate_sirs(vitals: dict, lab_results: list[dict] | None = None) -> dict:
    criteria_count = 0
    met_conditions: list[str] = []

    temperature = _number(vitals.get("temperature"))
    if temperature is not None and (temperature > 38.0 or temperature < 36.0):
        criteria_count += 1
        met_conditions.append("Abnormal Temp")

    heart_rate = _number(vitals.get("heart_rate"))
    if heart_rate is not None and heart_rate > 90:
        criteria_count += 1
        met_conditions.append("Tachycardia")

    resp_rate = _number(vitals.get("resp_rate"))
    if resp_rate is not None and resp_rate > 20:
        criteria_count += 1
        met_conditions.append("Tachypnea")

    for result in lab_results or []:
        if not isinstance(result, dict):
            continue
        test_name = str(result.get("test_name") or "").upper()
        if "LEUKOCYTE" not in test_name and "WBC" not in test_name:
            continue
        value = _number(str(result.get("value") or "").replace(",", ""))
        if value is not None and (value > 12000 or value < 4000):
            criteria_count += 1
            met_conditions.append("Abnormal WBC")

    return {
        "sirs_positive": criteria_count >= 2,
        "criteria_count": criteria_count,
        "reasons": met_conditions,
    }
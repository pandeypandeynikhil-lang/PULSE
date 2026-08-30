"""Layer 1b - deterministic clinical safety heuristics.

SIRS (Systemic Inflammatory Response Syndrome) criteria, age-banded — not
one adult-calibrated threshold applied to every patient. A healthy
3-year-old's resting heart rate sits well above 90 and their respiratory
rate well above 20; scored against the adult thresholds below, every
toddler in the department would trigger a false SIRS positive and get
force-escalated by Layer 3's SIRS floor regardless of how well they
actually are. That is exactly the "silent safety risk" a single
adult-calibrated model creates. The bands below are published pediatric
vital-sign reference ranges (the shape of criteria used in the Goldstein
2005 pediatric sepsis consensus definitions, simplified to the two signals
this layer already checks), applied up to age 12; from 12 up this
collapses back to the original adult thresholds, which were never wrong,
only silently mis-applied to patients they were never calibrated for.
"""
from __future__ import annotations

from typing import Any

# age < N years -> (heart-rate-high threshold, resp-rate-high threshold).
# Ordered youngest-first; the first band whose upper bound exceeds the
# patient's age wins. 12+ falls through to the adult thresholds below.
_PEDIATRIC_BANDS = [
    (1, 180, 50),   # infant
    (3, 140, 40),   # toddler
    (6, 130, 34),   # preschool / early school-age
    (12, 120, 30),  # school-age / pre-adolescent
]
_ADULT_HR_HIGH = 90
_ADULT_RR_HIGH = 20


def _age_thresholds(age: float | None) -> tuple[float, float]:
    """Returns (heart_rate_high, resp_rate_high) for this patient's age.
    None or 12+ gets the adult thresholds this layer always used."""
    if age is None:
        return _ADULT_HR_HIGH, _ADULT_RR_HIGH
    for max_age, hr_high, rr_high in _PEDIATRIC_BANDS:
        if age < max_age:
            return hr_high, rr_high
    return _ADULT_HR_HIGH, _ADULT_RR_HIGH


def _number(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def evaluate_sirs(vitals: dict, lab_results: list[dict] | None = None) -> dict:
    criteria_count = 0
    met_conditions: list[str] = []
    age = _number(vitals.get("age"))
    hr_high, rr_high = _age_thresholds(age)

    temperature = _number(vitals.get("temperature"))
    if temperature is not None and (temperature > 38.0 or temperature < 36.0):
        criteria_count += 1
        met_conditions.append("Abnormal Temp")

    heart_rate = _number(vitals.get("heart_rate"))
    if heart_rate is not None and heart_rate > hr_high:
        criteria_count += 1
        met_conditions.append(
            "Tachycardia" if age is None or age >= 12
            else f"Tachycardia (>{hr_high} bpm for age {int(age)})")

    resp_rate = _number(vitals.get("resp_rate"))
    if resp_rate is not None and resp_rate > rr_high:
        criteria_count += 1
        met_conditions.append(
            "Tachypnea" if age is None or age >= 12
            else f"Tachypnea (>{rr_high}/min for age {int(age)})")

    for result in lab_results or []:
        if not isinstance(result, dict):
            continue
        test_name = str(result.get("test_name") or "").upper()
        if "LEUKOCYTE" not in test_name and "WBC" not in test_name:
            continue
        value = _number(str(result.get("value") or "").replace(",", ""))
        # Trust a nurse-confirmed H/L flag even if the numeric parse fails
        # or the lab's own units differ from the 4,000-12,000 assumption
        # baked into the threshold check below — a human already read this
        # result as abnormal, which is at least as reliable as our parser.
        flagged = result.get("abnormality_flag") in ("H", "L")
        out_of_range = value is not None and (value > 12000 or value < 4000)
        if flagged or out_of_range:
            criteria_count += 1
            met_conditions.append("Abnormal WBC")

    return {
        "sirs_positive": criteria_count >= 2,
        "criteria_count": criteria_count,
        "reasons": met_conditions,
    }

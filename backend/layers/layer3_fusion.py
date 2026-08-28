"""Layer 3 — Fusion into the Arrival Risk Index.

A transparent weighted combination, not a learned meta-model. In a clinical
safety context an auditable formula that a nurse can be talked through beats a
marginally more accurate black box, and this is the number the whole console is
built around.
"""
from __future__ import annotations

from typing import Any

W_VITALS, W_SYMPTOM, W_AGE = 0.46, 0.34, 0.08
SYNERGY_MAP = {
    "respiratory": {"resp_rate", "spo2"},
    "cardiac": {"heart_rate", "systolic_bp", "diastolic_bp", "shock_index"},
    "vascular": {"heart_rate", "systolic_bp", "diastolic_bp", "shock_index"},
    "infection": {"temperature", "heart_rate"},
    "neuro": {"systolic_bp"},
}

# ESI runs I (most urgent) to V. We map onto it rather than inventing our own
# scale, so the output lands in the vocabulary the department already uses.
ESI_BANDS = [(82, "I"), (68, "II"), (40, "III"), (18, "IV"), (0, "V")]


def _band(ari: int) -> str:
    for threshold, level in ESI_BANDS:
        if ari >= threshold:
            return level
    return "V"


def fuse(vitals_out: dict[str, Any] | None,
         symptom_out: dict[str, Any] | None,
         age: int | None,
         lab_out: dict[str, Any] | None = None,
         sirs_data: dict[str, Any] | None = None) -> dict[str, Any]:
    parts, weights = [], []

    if vitals_out:
        parts.append(vitals_out["risk"] * 100)
        weights.append(W_VITALS)
    # A complaint with no red flags is ABSENCE OF EVIDENCE, not evidence of
    # safety. Scoring it as zero risk would drag down exactly the patients whose
    # words never reveal the problem — the silent decompensators. We drop the
    # component instead, and let the measured signals carry the score.
    if symptom_out and symptom_out.get("flags"):
        parts.append(symptom_out["severity"] * 100)
        weights.append(W_SYMPTOM)
    if age is not None:
        parts.append(min(max((age - 40) * 1.5, 0), 100))
        weights.append(W_AGE)

    synergy_multiplier = 1.0
    synergy_matches: list[str] = []
    if vitals_out and symptom_out:
        elevated_vitals = {
            driver["feature"] for driver in vitals_out.get("drivers", [])
            if driver.get("direction") == "raises"
        }
        for system in symptom_out.get("systems", []):
            matches = elevated_vitals.intersection(SYNERGY_MAP.get(system, set()))
            if matches and system not in synergy_matches:
                synergy_matches.append(system)
    if synergy_matches:
        # Graduated rather than a flat step: a single corroborating system
        # (tachycardia alongside a chest-pain flag) keeps the original 1.2x.
        # A second independently-corroborating system is more than twice as
        # reassuring that the vitals and the complaint describe the same
        # event, not a coincidence of two marginal signals — so it earns
        # more, capped well short of the SIRS floor or lab multiplier so
        # synergy alone can never substitute for either as the primary
        # escalation path.
        synergy_multiplier = min(1.1 + 0.1 * len(synergy_matches), 1.3)

    if parts:
        total = sum(weights)
        ari = int(round(sum(p * w for p, w in zip(parts, weights)) / total))
    else:
        ari = 0
    lab_mult = lab_out.get("multiplier", 1.0) if lab_out else 1.0
    ari = int(round(ari * lab_mult))
    ari = int(round(ari * synergy_multiplier))
    if sirs_data and sirs_data.get("sirs_positive"):
        # ESI II starts at 68; floor at 70 to guarantee ESI II triage for SIRS.
        ari = max(ari, 70)
    ari = max(0, min(100, ari))

    if vitals_out and symptom_out and vitals_out["sufficient"]:
        conf = "high"
    elif vitals_out and vitals_out["sufficient"]:
        conf = "moderate"
    else:
        conf = "low"

    return {
        "ari": ari,
        "esi": _band(ari),
        "confidence": conf,
        "components": {
            "vitals": round(vitals_out["risk"] * 100, 1) if vitals_out else None,
            "symptoms": round(symptom_out["severity"] * 100, 1) if symptom_out else None,
            "age": age,
            "labs": lab_out,
            "sirs": sirs_data.get("reasons") if sirs_data and sirs_data.get("sirs_positive") else None,
            "synergy_matched": synergy_matches if synergy_matches else None,
        },
    }

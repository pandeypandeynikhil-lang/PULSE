"""Layer 3 — Fusion into the Arrival Risk Index.

A transparent weighted combination, not a learned meta-model. In a clinical
safety context an auditable formula that a nurse can be talked through beats a
marginally more accurate black box, and this is the number the whole console is
built around.
"""
from __future__ import annotations

from typing import Any

W_VITALS, W_SYMPTOM, W_PRIOR, W_AGE = 0.46, 0.34, 0.12, 0.08

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
         prior: int | None,
         age: int | None) -> dict[str, Any]:
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
    if prior is not None:
        # The prior decays as soon as real data lands. It opened the door; it
        # does not get to stay in the room.
        decay = 0.35 if vitals_out else 1.0
        parts.append(prior * decay)
        weights.append(W_PRIOR)
    if age is not None:
        parts.append(min(max((age - 40) * 1.5, 0), 100))
        weights.append(W_AGE)

    if not parts:
        return {"ari": 0, "esi": "V", "confidence": "none", "components": {}}

    total = sum(weights)
    ari = int(round(sum(p * w for p, w in zip(parts, weights)) / total))
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
            "prior": prior,
            "age": age,
        },
    }

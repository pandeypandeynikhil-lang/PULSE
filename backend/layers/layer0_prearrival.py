"""Layer 0 — Pre-Arrival Signal.

Scores the ambulance handover or helpline call before the patient reaches the
door. The output is a PRIOR, not an acuity level: it is allowed to move
resources and nothing else, and it is superseded the moment real vitals exist.

This is the layer that answers "what data is realistically available in the
first few minutes" with: more than we assumed, for the subset of patients who
arrive by ambulance or call ahead.
"""
from __future__ import annotations

from typing import Any

from .nlp_core import extract

# Hard ceiling. A call-only signal can never justify a top-tier acuity, however
# alarming the words are, so we cap the prior below the ESI-II equivalent and
# force the real decision to wait for real data.
PRIOR_CEILING = 68


def score(transcript: str, arrival_mode: str = "ambulance") -> dict[str, Any]:
    nlp = extract(transcript)

    base = nlp["severity"] * 100.0
    if arrival_mode == "ambulance":
        base *= 1.08  # crews call ahead about the patients that worry them

    if nlp["age"] and nlp["age"] >= 65:
        base *= 1.06

    prior = min(round(base), PRIOR_CEILING)

    # Confidence is low by construction. A frightened relative is not a
    # paramedic, and the model must not pretend otherwise.
    n = len(nlp["flags"])
    confidence = "low" if n < 3 else "moderate"

    return {
        "prior": prior,
        "confidence": confidence,
        "provisional": True,
        "flags": nlp["flags"],
        "spans": nlp["spans"],
        "age_extracted": nlp["age"],
        "systems": nlp["systems"],
        "actions": _actions(prior, nlp["systems"]),
    }


def _actions(prior: int, systems: list[str]) -> list[str]:
    """Logistics only. Every item here is reversible and costs a bay, not a life."""
    if prior < 35:
        return []
    out = ["Resus bay placed on standby"]
    if prior >= 55:
        out.append("Triage nurse notified of inbound")
    if "cardiac" in systems:
        out.append("12-lead ECG staged at the door")
        out.append("Cardiology on-call paged")
    if "neuro" in systems:
        out.append("CT scanner slot held")
        out.append("Stroke team pre-alerted")
    if "trauma" in systems:
        out.append("Trauma bay cleared")
    if "vascular" in systems:
        out.append("Contrast CT slot held")
    return out

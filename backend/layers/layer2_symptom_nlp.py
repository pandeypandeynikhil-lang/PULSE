"""Layer 2 — Symptom NLP on the in-person chief complaint."""
from __future__ import annotations

from typing import Any

from .nlp_core import extract


def score(complaint: str, nursing_assessment: str = "") -> dict[str, Any]:
    comp_nlp = extract(complaint)
    nurse_nlp = (extract(nursing_assessment) if nursing_assessment else {
        "severity": 0.0, "flags": [], "spans": [], "systems": [],
        "source": "lexicon",
    })
    intervention_keywords = [
        "iv access", "iv fluid", "oxygen", "o2 applied", "ecg", "ekg",
        "cpr", "resuscitation",
    ]
    gestalt_intervention = any(
        keyword in nursing_assessment.lower() for keyword in intervention_keywords
    )
    combined_flags = comp_nlp.get("flags", []) + nurse_nlp.get("flags", [])
    combined_spans = comp_nlp.get("spans", []) + nurse_nlp.get("spans", [])
    combined_systems = list(dict.fromkeys(
        comp_nlp.get("systems", []) + nurse_nlp.get("systems", [])
    ))
    base_severity = max(comp_nlp.get("severity", 0.0) * 0.7,
                        nurse_nlp.get("severity", 0.0))
    final_severity = (max(base_severity, 0.85)
                      if gestalt_intervention else base_severity)
    return {
        "severity": final_severity,
        "flags": combined_flags,
        "spans": combined_spans,
        "systems": combined_systems,
        "nlp_source": comp_nlp.get("source", "lexicon"),
    }

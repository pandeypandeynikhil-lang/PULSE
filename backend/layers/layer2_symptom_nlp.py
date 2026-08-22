"""Layer 2 — Symptom NLP on the in-person chief complaint."""
from __future__ import annotations

from typing import Any

from .nlp_core import extract


def score(complaint: str) -> dict[str, Any]:
    nlp = extract(complaint)
    return {
        "severity": nlp["severity"],
        "flags": nlp["flags"],
        "spans": nlp["spans"],
        "systems": nlp["systems"],
    }

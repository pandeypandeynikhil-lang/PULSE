"""Layer 5 — Capacity-Aware Routing.

Scores the patient against the department as it actually is right now, not
against an idealised one. A greedy assignment is the right call here: it is
explainable in one sentence, it runs in microseconds, and nobody in an
emergency department is going to trust a route they cannot follow.
"""
from __future__ import annotations

from typing import Any

# system -> (pathway, specialty)
PATHWAYS = {
    "cardiac":     ("Resus / cardiac", "Cardiology"),
    "neuro":       ("Resus / stroke", "Neurology"),
    "vascular":    ("Resus / vascular", "Vascular surgery"),
    "trauma":      ("Trauma bay", "Trauma surgery"),
    "respiratory": ("Acute majors", "Respiratory"),
    "infection":   ("Acute majors", "Acute medicine"),
    "abdominal":   ("Acute majors", "General surgery"),
    "allergy":     ("Resus / airway", "Acute medicine"),
}
DEFAULT = ("Acute majors", "Emergency medicine")
FAST_TRACK = ("Fast track", "Emergency nurse practitioner")


def route(esi: str, systems: list[str], capacity: dict[str, Any]) -> dict[str, Any]:
    if esi in ("IV", "V"):
        pathway, specialty = FAST_TRACK
    else:
        pathway, specialty = DEFAULT
        for s in systems:
            if s in PATHWAYS:
                pathway, specialty = PATHWAYS[s]
                break

    beds = capacity.get("beds", {})
    free = beds.get(pathway, 0)
    specialists = capacity.get("specialists", {})
    spec_free = specialists.get(specialty, 0)

    notes, blocked = [], False
    if free <= 0:
        blocked = True
        notes.append(f"No {pathway.lower()} bed free")
        alt = next((p for p, n in beds.items() if n > 0 and p != pathway), None)
        if alt:
            notes.append(f"{alt} available as holding")
    if spec_free <= 0:
        notes.append(f"{specialty} not currently free — page required")

    return {
        "pathway": pathway,
        "specialty": specialty,
        "beds_free": free,
        "specialist_available": spec_free > 0,
        "blocked": blocked,
        "notes": notes,
    }

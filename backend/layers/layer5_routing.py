"""Layer 5 — Capacity-Aware Routing.

Scores the patient against the department as it actually is right now, not
against an idealised one. A greedy assignment is the right call here: it is
explainable in one sentence, it runs in microseconds, and nobody in an
emergency department is going to trust a route they cannot follow.

As of the ward roster (`backend/ward.py`), "capacity-aware" means something
more specific than a bed count: this layer names the exact bed and the exact
clinician it would assign, so the nurse console's accept/override gate has
something concrete to act on — and so accepting a recommendation can mark
that one bed occupied, not just decrement a total.
"""
from __future__ import annotations

from typing import Any

try:
    from .. import ward
except ImportError:
    # Supports `uvicorn main:app` from inside backend/, where `layers` is
    # imported as a top-level package with no parent for `..` to climb to —
    # same fallback main.py already uses for db/simulation/ward itself.
    import ward  # type: ignore[no-redef]

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


def route(esi: str, systems: list[str],
          beds: list[ward.Bed], clinicians: list[ward.Clinician]) -> dict[str, Any]:
    if esi in ("IV", "V"):
        pathway, specialty = FAST_TRACK
    else:
        pathway, specialty = DEFAULT
        for s in systems:
            if s in PATHWAYS:
                pathway, specialty = PATHWAYS[s]
                break

    free_beds = ward.free_beds(beds, pathway)
    free_clinicians = ward.free_clinicians(clinicians, specialty)
    bed = free_beds[0] if free_beds else None
    clinician = free_clinicians[0] if free_clinicians else None

    notes, blocked = [], False
    if bed is None:
        blocked = True
        notes.append(f"No {pathway.lower()} bed free")
        alt = next((b for b in beds if b.status == "available" and b.ward != pathway), None)
        if alt:
            notes.append(f"{alt.ward} available as holding")
    if clinician is None:
        notes.append(f"{specialty} not currently free — page required")

    return {
        "pathway": pathway,
        "specialty": specialty,
        "beds_free": len(free_beds),
        "specialist_available": clinician is not None,
        "blocked": blocked,
        "notes": notes,
        # The concrete assignment a nurse's ACCEPT actually commits to —
        # None when nothing is free, which the console renders as "page
        # required" / "holding" rather than silently assigning nothing.
        "suggested_bed": bed.id if bed else None,
        "suggested_clinician": clinician.id if clinician else None,
        "suggested_clinician_name": clinician.name if clinician else None,
    }

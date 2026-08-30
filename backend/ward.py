"""The department as a roster of named things, not a bag of counts.

Everything downstream — Layer 5's suggestion, the accept/override gate, the
Ward Map page — needs to point at a *specific* bed and a *specific*
clinician, not just decrement a number. So the roster here is the one source
of truth: a bed or clinician has an id, a status, and (when occupied) the
patient it belongs to. The old aggregate view the dashboard's "Department
state" panel already renders (`{ward: free_count}`) is a projection of this
roster, computed on demand — never a second copy of the truth that could
drift from it.

Four bed states, not two, because a real ward isn't binary:
  available   — ready for the next patient
  occupied    — a specific patient is in it (see `patient_id`)
  cleaning    — just vacated, not yet ready — a real intermediate state,
                and modelling it is what makes "mark clean" a real action on
                the Ward Map rather than set dressing
  unavailable — out of service (maintenance, staffing gap, closed bay)
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any

BED_STATUSES = ("available", "occupied", "cleaning", "unavailable")
CLINICIAN_STATUSES = ("available", "busy", "off_shift")

_HERE = os.path.dirname(os.path.abspath(__file__))
_PROFILES_PATH = os.path.join(_HERE, "..", "data", "hospital_profiles.json")
DEFAULT_PROFILE = "community_hospital"
STAFF_ON = 6  # last-resort fallback if a profile omits its own staff_on

# Fallback if data/hospital_profiles.json is ever missing — the original
# hardcoded numbers, so a corrupted or deleted config degrades to "the
# default scenario" rather than an empty department. Never used when the
# file is present; see _load_profile().
_FALLBACK_PROFILE = {
    "beds": {
        "Resus / cardiac": 1, "Resus / stroke": 1, "Resus / vascular": 1,
        "Resus / airway": 1, "Trauma bay": 1, "Acute majors": 3, "Fast track": 4,
    },
    "specialists": {
        "Cardiology": ["Dr. Adeyemi"], "Neurology": ["Dr. Whitfield"],
        "Respiratory": ["Dr. Okoye"], "Acute medicine": ["Dr. Larsen", "Dr. Mbeki"],
        "General surgery": ["Dr. Petrova"], "Vascular surgery": [],
        "Trauma surgery": ["Dr. Hassan"],
        "Emergency medicine": ["Dr. Reyes", "Dr. Lindqvist"],
        "Emergency nurse practitioner": ["ENP Cole", "ENP Dubois"],
    },
    "staff_on": 6,
}


def available_profiles() -> list[str]:
    return sorted(_load_all_profiles().keys())


def _load_all_profiles() -> dict[str, Any]:
    try:
        with open(_PROFILES_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {DEFAULT_PROFILE: _FALLBACK_PROFILE}
    return {k: v for k, v in data.items() if not k.startswith("_")}


def _load_profile(name: str) -> dict[str, Any]:
    """Never network, never raise — a missing file, a missing profile name,
    or a malformed one all degrade to the built-in default rather than
    taking the department down. This is the same "degrade, don't die"
    contract every other data-loading path in this project holds to."""
    profiles = _load_all_profiles()
    return profiles.get(name) or profiles.get(DEFAULT_PROFILE) or _FALLBACK_PROFILE


@dataclass
class Bed:
    id: str
    ward: str
    status: str = "available"
    patient_id: str | None = None


@dataclass
class Clinician:
    id: str
    name: str
    specialty: str
    status: str = "available"
    patient_id: str | None = None


def build_roster(profile_name: str = DEFAULT_PROFILE) -> tuple[list[Bed], list[Clinician]]:
    profile = _load_profile(profile_name)
    beds = [
        Bed(id=f"{_abbr(ward)}-{i + 1}", ward=ward)
        for ward, n in profile.get("beds", {}).items()
        for i in range(n)
    ]
    clinicians = [
        Clinician(id=f"{_abbr(specialty)}-{i + 1}", name=name, specialty=specialty)
        for specialty, names in profile.get("specialists", {}).items()
        for i, name in enumerate(names)
    ]
    return beds, clinicians


def _abbr(label: str) -> str:
    """'Resus / cardiac' -> 'RC', 'Acute majors' -> 'AM'. Used only to build
    short, stable bed/clinician ids — never shown as the ward name itself."""
    words = [w for w in label.replace("/", " ").split() if w[:1].isalpha()]
    return "".join(w[0] for w in words).upper()


# ------------------------------------------------------------------ queries
def free_beds(beds: list[Bed], ward: str) -> list[Bed]:
    return [b for b in beds if b.ward == ward and b.status == "available"]


def free_clinicians(clinicians: list[Clinician], specialty: str) -> list[Clinician]:
    return [c for c in clinicians if c.specialty == specialty and c.status == "available"]


def capacity_summary(beds: list[Bed], clinicians: list[Clinician],
                     profile_name: str = DEFAULT_PROFILE) -> dict:
    """The old aggregate shape (`{"beds": {ward: free_count}, ...}`) that the
    dashboard's Department State panel already renders. Derived fresh from
    the roster every time — this is a view, not a stored value, so it can
    never disagree with the roster it's read from.

    `profile_name` is only consulted for the union below — a ward or
    specialty the active profile deliberately staffs at zero (rural_ed has
    no vascular surgery at all) still needs to show up as "0 available",
    the same reasoning that already applied to `_ROSTER`'s empty lists;
    since there's no Bed/Clinician object for a zero-count entry, the
    profile's own key list is what keeps it visible.
    """
    profile = _load_profile(profile_name)
    bed_wards = {b.ward for b in beds} | set(profile.get("beds", {}))
    spec_names = {c.specialty for c in clinicians} | set(profile.get("specialists", {}))
    return {
        "beds": {w: sum(1 for b in beds if b.ward == w and b.status == "available")
                for w in bed_wards},
        "specialists": {s: sum(1 for c in clinicians if c.specialty == s and c.status == "available")
                        for s in spec_names},
        "staff_on": profile.get("staff_on", STAFF_ON),
    }


# ----------------------------------------------------------------- mutation
def assign_bed(beds: list[Bed], bed_id: str, patient_id: str) -> bool:
    bed = next((b for b in beds if b.id == bed_id), None)
    if bed is None or bed.status != "available":
        return False
    bed.status, bed.patient_id = "occupied", patient_id
    return True


def assign_clinician(clinicians: list[Clinician], clinician_id: str, patient_id: str) -> bool:
    c = next((c for c in clinicians if c.id == clinician_id), None)
    if c is None or c.status != "available":
        return False
    c.status, c.patient_id = "busy", patient_id
    return True


def set_bed_status(beds: list[Bed], bed_id: str, status: str) -> bool:
    """Manual staff action from the Ward Map — never used to set 'occupied'
    directly, only via `assign_bed`, so a bed can't be marked occupied
    without a patient it actually belongs to."""
    if status not in ("available", "cleaning", "unavailable"):
        return False
    bed = next((b for b in beds if b.id == bed_id), None)
    if bed is None:
        return False
    bed.status, bed.patient_id = status, None
    return True


def set_clinician_status(clinicians: list[Clinician], clinician_id: str, status: str) -> bool:
    if status not in ("available", "off_shift"):
        return False
    c = next((c for c in clinicians if c.id == clinician_id), None)
    if c is None:
        return False
    c.status, c.patient_id = status, None
    return True


def release_bed_for(beds: list[Bed], patient_id: str) -> None:
    """A patient re-escalating out of a bed they already occupy (Layer 4
    caught them getting worse after admission) frees it first — to
    'cleaning', not straight back to 'available', because that is what
    actually happens to a bed a deteriorating patient is moved out of."""
    for b in beds:
        if b.patient_id == patient_id:
            b.status, b.patient_id = "cleaning", None


def release_clinician_for(clinicians: list[Clinician], patient_id: str) -> None:
    for c in clinicians:
        if c.patient_id == patient_id:
            c.status, c.patient_id = "available", None

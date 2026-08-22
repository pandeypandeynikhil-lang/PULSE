"""Simulated emergency department.

PULSE's central claim is that time passes and risk changes. A static demo
cannot show that, so the whole prototype is built around a running clock.

Important: the escalations are NOT scripted. The deterioration engine computes
from the vitals stream like it would in production. What we authored is the
*physiology* — patient 11's observations genuinely worsen over the shift — and
the engine finds it on its own. That distinction is the difference between a
demo and a puppet show, and it is the first thing to say if anyone asks.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any

SPEEDS = {"1x": 1, "10x": 10, "60x": 60, "180x": 180}


@dataclass
class VitalsPoint:
    at_min: float
    vitals: dict[str, Any]


@dataclass
class SimPatient:
    id: str
    display_id: str
    age: int
    arrival_mode: str
    complaint: str
    arrive_min: float
    timeline: list[VitalsPoint]
    transcript: str | None = None
    prearrival_min: float | None = None
    status: str = "inbound"
    assigned_esi: str | None = None
    pathway: str | None = None
    specialty: str | None = None
    arrived_at_min: float | None = None
    last_recommendation: int | None = None
    escalated: bool = False
    seen_at_min: float | None = None
    prior: dict[str, Any] | None = None
    seed_esi: str | None = None   # acuity already assigned before the shift

    def vitals_at(self, t: float) -> dict[str, Any] | None:
        if self.arrived_at_min is None:
            return None
        # Patients already in the room when the shift starts have their
        # observation timeline anchored to t=0, not to their arrival 46 minutes
        # ago — otherwise their whole trajectory would have played out before
        # anyone was watching, which is the opposite of the point.
        anchor = max(self.arrived_at_min, 0.0)
        rel = t - anchor
        if rel < self.timeline[0].at_min:
            return None

        # Interpolate between observation sets. Physiology does not step between
        # discrete readings, and a step function would make the risk trajectory
        # jump in a way no monitor ever shows. Layer 4 reasons over slope, so a
        # smooth series is not cosmetic — it is what makes the slope meaningful.
        prev = self.timeline[0]
        nxt = None
        for p in self.timeline:
            if p.at_min <= rel:
                prev = p
            else:
                nxt = p
                break

        if nxt is None:
            v = dict(prev.vitals)
        else:
            span = max(nxt.at_min - prev.at_min, 1e-6)
            f = min(max((rel - prev.at_min) / span, 0.0), 1.0)
            v = {}
            for k, a in prev.vitals.items():
                b = nxt.vitals.get(k, a)
                val = a + (b - a) * f
                v[k] = round(val, 1) if k == "temperature" else round(val)

        v["age"] = self.age
        v["arrival_mode"] = self.arrival_mode
        return v


def _steady(hr, sbp, dbp, rr, spo2, temp, n=6, step=8.0, drift=0.0, rng=None):
    """A patient whose observations stay broadly where they started."""
    rng = rng or random.Random(0)
    out = []
    for i in range(n):
        out.append(VitalsPoint(i * step, {
            "heart_rate": round(hr + rng.gauss(0, 2.5) + drift * i),
            "systolic_bp": round(sbp + rng.gauss(0, 3)),
            "diastolic_bp": round(dbp + rng.gauss(0, 2)),
            "resp_rate": round(rr + rng.gauss(0, 0.8)),
            "spo2": round(min(100, spo2 + rng.gauss(0, 0.7))),
            "temperature": round(temp + rng.gauss(0, 0.15), 1),
        }))
    return out


def _deteriorating(rng=None):
    """Patient 11. Arrives genuinely low-acuity and genuinely gets worse.

    Nothing about the first two observation sets would justify escalation, which
    is the point: this is what a silent decompensator looks like on paper.
    """
    rng = rng or random.Random(11)
    frames = [
        (0.0,  {"heart_rate": 84, "systolic_bp": 134, "diastolic_bp": 84, "resp_rate": 16, "spo2": 98, "temperature": 36.8}),
        (14.0, {"heart_rate": 91, "systolic_bp": 130, "diastolic_bp": 82, "resp_rate": 17, "spo2": 97, "temperature": 36.9}),
        (26.0, {"heart_rate": 103, "systolic_bp": 121, "diastolic_bp": 76, "resp_rate": 20, "spo2": 95, "temperature": 37.1}),
        (36.0, {"heart_rate": 114, "systolic_bp": 109, "diastolic_bp": 68, "resp_rate": 23, "spo2": 93, "temperature": 37.3}),
        (44.0, {"heart_rate": 122, "systolic_bp": 99,  "diastolic_bp": 62, "resp_rate": 26, "spo2": 91, "temperature": 37.4}),
        (52.0, {"heart_rate": 128, "systolic_bp": 94,  "diastolic_bp": 59, "resp_rate": 28, "spo2": 90, "temperature": 37.6}),
    ]
    return [VitalsPoint(t, v) for t, v in frames]


def _partial_first(points: list[VitalsPoint]) -> list[VitalsPoint]:
    """Strip fields from the first observation set.

    Real triage does not capture a full set in minute one, and a prototype that
    pretends otherwise is answering an easier question than the brief asked.
    """
    if points:
        v = dict(points[0].vitals)
        for k in ("temperature", "diastolic_bp"):
            v.pop(k, None)
        points[0] = VitalsPoint(points[0].at_min, v)
    return points


CARDIAC_TRANSCRIPT = (
    "He's 58 - he's clutching his chest, he's grey and he's sweating through "
    "his shirt. He can't get a full breath. It started about twenty minutes ago."
)


def build_scenario() -> list[SimPatient]:
    rng = random.Random(2026)
    P: list[SimPatient] = []

    waiting = [
        ("PT 01", 34, "twisted ankle on the stairs, swollen",              (88, 128, 80, 15, 99, 36.7)),
        ("PT 02", 71, "productive cough and high fever since yesterday",   (98, 118, 70, 21, 94, 38.4)),
        ("PT 03", 26, "sore throat, no fever",                             (76, 122, 78, 14, 99, 36.8)),
        ("PT 04", 63, "abdominal pain, can't straighten up",               (96, 126, 76, 18, 97, 37.2)),
        ("PT 05", 45, "small cut to the hand needing stitches",            (78, 124, 79, 14, 99, 36.6)),
        ("PT 06", 82, "confused since this morning, family worried",       (92, 112, 66, 19, 95, 37.0)),
        ("PT 07", 19, "rash on both arms, itchy",                          (74, 118, 74, 15, 99, 36.7)),
        ("PT 08", 55, "back pain radiating, came on fast",                 (94, 138, 86, 17, 97, 36.9)),
        ("PT 09", 38, "migraine, photophobia",                             (80, 120, 76, 15, 98, 36.8)),
        ("PT 10", 67, "prescription refill and blood pressure check",      (82, 142, 88, 15, 98, 36.7)),
    ]
    seed = ["IV", "II", "V", "III", "V", "II", "V", "III", "IV", "V"]
    for i, (disp, age, complaint, v) in enumerate(waiting):
        P.append(SimPatient(
            id=f"p{i+1:02d}", display_id=disp, age=age, arrival_mode="walk-in",
            complaint=complaint, arrive_min=-(46 - i * 3.5),
            timeline=_partial_first(_steady(*v, rng=rng)), seed_esi=seed[i],
        ))

    # PT 11 — the deterioration case. Low-acuity complaint, ordinary first obs.
    P.append(SimPatient(
        id="p11", display_id="PT 11", age=61, arrival_mode="walk-in",
        complaint="feeling tired and off-colour since this morning",
        arrive_min=-46.0, timeline=_partial_first(_deteriorating(rng)),
        seed_esi="IV",
    ))

    P.append(SimPatient(
        id="p12", display_id="PT 12", age=58, arrival_mode="ambulance",
        complaint="crushing central chest pain, sweating, breathless",
        arrive_min=9.0, prearrival_min=0.5, transcript=CARDIAC_TRANSCRIPT,
        timeline=_partial_first(_steady(118, 96, 62, 24, 91, 37.1, n=5, step=6, rng=rng)),
    ))

    P.append(SimPatient(
        id="p13", display_id="PT 13", age=29, arrival_mode="walk-in",
        complaint="ankle sprain playing football",
        arrive_min=22.0, timeline=_partial_first(_steady(80, 126, 80, 15, 99, 36.7, rng=rng)),
    ))
    return P


BASE_CAPACITY = {
    "beds": {"Resus / cardiac": 1, "Resus / stroke": 1, "Resus / vascular": 1,
             "Resus / airway": 1, "Trauma bay": 1, "Acute majors": 3, "Fast track": 4},
    "specialists": {"Cardiology": 1, "Neurology": 1, "Respiratory": 1,
                    "Acute medicine": 2, "General surgery": 1,
                    "Vascular surgery": 0, "Trauma surgery": 1,
                    "Emergency medicine": 2, "Emergency nurse practitioner": 2},
    "staff_on": 6,
}

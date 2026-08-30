"""Layer 4 — Deterioration Engine.

The layer nobody else builds. Every patient still waiting is re-scored on a
loop, and their scores are treated as a time series rather than a snapshot. A
patient can be escalated on trajectory alone: absolute risk still moderate, but
rising consistently, which is exactly the signature of the presentations that
kill people in waiting rooms.

Two independent triggers, not one. A rising score trend is the first — a
patient whose numbers are visibly getting worse. The second is a patient
whose numbers are *not* getting worse but who has simply been waiting
longer than is safe for their acuity: a flat trend is not the same claim as
"nothing is wrong," it can just as easily mean nobody has looked. Real
triage protocols (the Canadian Triage and Acuity Scale's five reassessment
windows are the most-cited example) treat wait time past a level-specific
threshold as its own trigger for exactly this reason, independent of
whether a trend line agrees.
"""
from __future__ import annotations

from typing import Any

MIN_SCORES = 4          # a trend needs several points before it is a trend
RISING_DELTA = 6        # ARI points per score step that counts as "rising"
ESCALATE_TOTAL = 22     # cumulative rise that forces a recommendation
STALE_MINUTES = 25      # a patient nobody has re-measured is its own risk

# ESI level -> minutes a patient at that acuity may safely wait before a
# reassessment is due, absent any other trigger. Modelled on published
# triage reassessment intervals (CTAS 1-5) adapted to ESI's five levels;
# ESI I is "continuous," represented here as effectively zero tolerance.
MAX_SAFE_WAIT_MIN = {"I": 0, "II": 15, "III": 30, "IV": 60, "V": 120}


def _wait_breach(waited_minutes: float, current_esi: str | None) -> tuple[bool, str | None]:
    if current_esi is None:
        return False, None
    safe_wait = MAX_SAFE_WAIT_MIN.get(current_esi, MAX_SAFE_WAIT_MIN["V"])
    if waited_minutes <= safe_wait:
        return False, None
    return True, (f"waited {int(waited_minutes)} min — past the {safe_wait} min "
                  f"safe reassessment window for ESI {current_esi}")


def assess(history: list[dict[str, Any]], waited_minutes: float,
          current_esi: str | None = None) -> dict[str, Any]:
    """history: oldest-first list of {ari, at} score records.

    `current_esi` is the acuity already assigned to this patient (if any) —
    the wait-time trigger is evaluated against *their* level's safe window,
    not a flat number, so an ESI II patient and an ESI V patient are held
    to genuinely different standards, the same way a real department would.
    """
    wait_breach, wait_reason = _wait_breach(waited_minutes, current_esi)

    # Collapse consecutive identical scores first. The scheduler re-scores on a
    # loop, so an unchanged patient produces repeated reads of the same value —
    # analysing those as separate observations would mask every real trend
    # behind a run of zero deltas. We reason over distinct observations.
    distinct: list[dict[str, Any]] = []
    for h in history:
        if not distinct or distinct[-1]["ari"] != h["ari"]:
            distinct.append(h)

    if len(distinct) < MIN_SCORES:
        return {"rising": False, "slope": 0.0, "delta": 0, "reason": wait_reason,
                "escalate": False, "wait_breach": wait_breach,
                "trace": [h["ari"] for h in distinct]}

    recent = distinct[-MIN_SCORES:]
    aris = [h["ari"] for h in recent]
    deltas = [aris[i + 1] - aris[i] for i in range(len(aris) - 1)]
    delta = aris[-1] - aris[0]
    slope = delta / max(len(aris) - 1, 1)

    monotonic = all(d > 0 for d in deltas)
    rising = monotonic and slope >= RISING_DELTA / MIN_SCORES

    reasons = []
    if monotonic:
        reasons.append(f"{len(aris)} consecutive rising scores")
    if delta >= ESCALATE_TOTAL:
        reasons.append(f"risk up {delta} points since triage")
    if waited_minutes >= STALE_MINUTES and rising:
        reasons.append(f"waiting {int(waited_minutes)} min without reassessment")
    if wait_reason:
        reasons.append(wait_reason)

    escalate = rising and delta >= ESCALATE_TOTAL

    return {
        "rising": rising,
        "slope": round(slope, 2),
        "delta": int(delta),
        "reason": "; ".join(reasons) if reasons else None,
        "escalate": escalate,
        "wait_breach": wait_breach,
        "trace": aris,
    }

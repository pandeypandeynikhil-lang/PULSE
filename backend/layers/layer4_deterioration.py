"""Layer 4 — Deterioration Engine.

The layer nobody else builds. Every patient still waiting is re-scored on a
loop, and their scores are treated as a time series rather than a snapshot. A
patient can be escalated on trajectory alone: absolute risk still moderate, but
rising consistently, which is exactly the signature of the presentations that
kill people in waiting rooms.
"""
from __future__ import annotations

from typing import Any

MIN_SCORES = 4          # a trend needs several points before it is a trend
RISING_DELTA = 6        # ARI points per score step that counts as "rising"
ESCALATE_TOTAL = 22     # cumulative rise that forces a recommendation
STALE_MINUTES = 25      # a patient nobody has re-measured is its own risk


def assess(history: list[dict[str, Any]], waited_minutes: float) -> dict[str, Any]:
    """history: oldest-first list of {ari, at} score records."""
    # Collapse consecutive identical scores first. The scheduler re-scores on a
    # loop, so an unchanged patient produces repeated reads of the same value —
    # analysing those as separate observations would mask every real trend
    # behind a run of zero deltas. We reason over distinct observations.
    distinct: list[dict[str, Any]] = []
    for h in history:
        if not distinct or distinct[-1]["ari"] != h["ari"]:
            distinct.append(h)

    if len(distinct) < MIN_SCORES:
        return {"rising": False, "slope": 0.0, "delta": 0, "reason": None,
                "escalate": False, "trace": [h["ari"] for h in distinct]}

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

    escalate = rising and delta >= ESCALATE_TOTAL

    return {
        "rising": rising,
        "slope": round(slope, 2),
        "delta": int(delta),
        "reason": "; ".join(reasons) if reasons else None,
        "escalate": escalate,
        "trace": aris,
    }

# PULSE — Architecture Notes

Companion to the README. This file covers the decisions a reviewer is most likely
to interrogate, and how to swap the synthetic cohort for real data.

## Why the scheduler loop is the architecture

Most triage tools are request/response: a patient arrives, you POST their data, you
get a score. That shape cannot express PULSE's central claim, which is that risk
moves while the patient waits.

So the service is built the other way round. `Engine.tick()` in `backend/main.py`
runs on a fixed cadence, pulls every waiting patient, runs the full pipeline, and
pushes the result. Layer 4 is not a feature attached to a triage tool — it is the
reason the loop exists. Everything else hangs off it.

Consequence worth noting: the API is almost stateless from the client's point of
view. The console never asks for a score; it receives them.

## Score persistence, and why it is throttled

Scores are append-only (`db.append_score`). They are also not written every tick:
`Engine.score_patient` persists when the ARI actually changes or when four simulated
minutes have passed.

Writing one row per tick would bury a real trajectory under a high-frequency log of
identical values, and Layer 4 would see a run of zero deltas where a rise was
happening. Layer 4 additionally collapses consecutive identical scores before
analysing, so trend detection reasons over *distinct observations* rather than
repeated reads of the same value. Both mechanisms exist for the same reason and
either one alone is insufficient.

## Fusion weights

```
ARI = (0.46·vitals + 0.34·symptoms + 0.12·prior + 0.08·age) / Σ(active weights)
```

Weights are clinically motivated rather than learned, and the denominator is the sum
of *active* components — so a missing input reweights the rest instead of being
treated as a zero.

That last detail carries real clinical meaning for the symptom component. A complaint
with no red flags is absence of evidence, not evidence of safety. Scoring it as zero
risk would drag down precisely the patients whose words never reveal the problem —
the silent decompensators the whole system exists to catch. PT 11 in the demo is
exactly this case: "feeling tired and off-colour" contains no flag at all, and PULSE
finds him anyway, on measured signal alone.

The prior decays to 35% of its value the moment real vitals exist. It opened the
door; it does not get to stay in the room.

## The guardrail, in code

| PULSE decides | Where |
|---|---|
| Pre-positioning bays, imaging, on-call staff | `layer0_prearrival._actions()` |
| Queue ordering within a nurse-set tier | `Engine.board()` sort |
| Bed accounting, audit logging | `Engine.decide()`, `db` |

| Only the nurse decides | Where |
|---|---|
| Acuity level | `Engine.decide()` — nothing else writes `assigned_esi` |
| Pathway and specialty commitment | same |
| Whether an escalation is acted on | same |

`assigned_esi` is written in exactly one place in the codebase, and that place is
reached only from the `/api/decide` endpoint. That is the guardrail as an
architectural property rather than a promise.

## Swapping in MIMIC-IV-ED

`backend/ml/train.py` is the only file that needs to change.

1. Obtain credentialed access and download `edstays`, `triage`, `vitalsign`.
2. Replace `generate_cohort()` with a loader producing the same `(X, y)` contract —
   the ten features in `FEATURES`, in order, with `NaN` for genuinely missing vitals.
3. Define the label: encounters receiving a life-stabilising intervention. Sax et al.
   (JAMA Netw Open 2023) publish operational definitions worth following so the
   sensitivity figure stays comparable to the 65.9% ESI baseline.
4. Retrain. Nothing downstream changes — `layer1_vitals.py` loads the pickle and reads
   SHAP contributions through `pred_contribs`, both of which are source-agnostic.

Expect AUC to move. Real cohorts are messier than any synthetic one, and a drop is
information rather than failure.

## Known limits

- **Layer 0 covers a minority of arrivals.** Most walk-ins generate no pre-arrival
  signal at all. It is an enhancement layer, never a replacement for door-time triage,
  and the console says so when no ambulance is inbound.
- **The routing solver is greedy**, not optimal. Deliberate: it is explainable in one
  sentence, and no one in an emergency department will follow a route they cannot
  reason about.
- **Fairness is monitored, not solved.** The audit trail makes disparate override
  patterns *visible*; correcting them needs real cohort data and clinical governance.
- **Anchoring risk is real.** Showing a nurse a score before she assesses can bias her.
  The provisional flag, the confidence band and the one-tap override are mitigations,
  not proof — measuring this is what shadow mode is for.

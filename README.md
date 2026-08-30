# PULSE — Patient Urgency & Load Sequencing Engine

**Accenture Innovation Challenge 2026 · Problem Statement 2 — PatientTriage.ai**

A triage co-pilot that sits beside the nurse, not in her place. It ingests a patient
the moment they're spoken for, written up, or diagnostically tested — voice, a
structured intake form, a lab PDF — fuses vitals, symptom narrative and live
department state into one explainable priority signal, and keeps updating that
signal, and the bed it points to, for as long as the patient is waiting.

**PULSE never assigns an acuity level. A nurse does. Every time.**

---

## Run it

Start the backend and frontend in separate terminals.

**Terminal 1 - backend (Windows):**

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r backend/requirements.txt
if (!(Test-Path backend/ml/artifacts/vitals_model.pkl)) { python -m backend.ml.train }
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

**Terminal 1 - backend (macOS/Linux):**

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
[ -f backend/ml/artifacts/vitals_model.pkl ] || python -m backend.ml.train
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

**Terminal 2 - frontend:**

```bash
cd frontend
npm install
npm run dev
```

Then open **http://localhost:3000**. First run trains the Layer 1 model
(~20 seconds); after that it starts immediately.

Three pages, one live board underneath all of them: **Patient Intake** (`/intake`)
enters demographics, vitals, dictated clinical notes, and sequentially uploaded PDF
lab reports, and submitting puts a real patient on the board. **Triage Dashboard**
(`/dashboard`) is the live operational board, department state, shadow-mode
agreement, and audit log. **Ward Map** (`/ward`) is the colour-coded bed and
clinician roster Layer 5 actually routes against, editable in real time.

Runs fully offline by default. To turn on the LLM NLP tier (and the Voice Intake
panel, which needs it): `cp .env.example .env`, fill in `GEMINI_API_KEY` and/or
`GROQ_API_KEY` (both have a free tier), set `PULSE_NLP_MODE=llm`.

The department is simulated continuously. Reset the simulation from the header
when needed.

### What to watch for

| Time | What happens |
|---|---|
| ~17:51 | PT 12 arrives. Vitals stream in, the ARI resolves, the console asks the nurse to confirm |
| ~18:12 | **PT 11 escalates on trajectory alone** — triaged ESI IV over an hour ago, complaint never revealed anything, but the risk curve crossed a tier boundary |

That second escalation is the point of the whole system. Nothing about PT 11's
words or first observations justified attention. The trajectory did.

---

## The escalation is not scripted

This matters more than anything else in the repo, so it is worth being blunt:
**we authored the physiology, not the alert.**

`backend/simulation.py` defines PT 11's observations genuinely worsening across the
shift. `backend/layers/layer4_deterioration.py` computes slope over persisted score
history and decides on its own. Delete the escalation logic and nothing fires; change
the vitals and it fires at a different time. There is no `if patient == "p11"`
anywhere in the codebase.

---

## Architecture

```
  SIGNALS IN                 PERCEPTION              REASONING            ACTION · HUMAN GATE
  ──────────                 ──────────              ─────────            ───────────────────
  voice complaint       ──┐
  intake form vitals    ──┼─▶ L2 symptom NLP    ──┐
  lab PDF vitals        ──┘   L1 vitals model   ──┼──▶ L3 fusion → ARI ──▶ nurse console
                                                          │    ▼                  │
  live bed/clinician roster ───────────────────▶ L4 deterioration       L5 routing → named
                             (ward.py)              (re-score loop)      bed + clinician
  ─────────────────────────────  GOVERNANCE RAIL  ─────────────────────────────────────────
  append-only score history · SHAP on every score · audit log · shadow-mode agreement
```

| Layer | File | What it does |
|---|---|---|
| **1** | `layers/layer1_vitals.py` | XGBoost on whatever vitals exist. Missing fields stay `NaN` — never imputed and passed off as measured |
| **1b** | `layers/layer1b_heuristics.py` | Deterministic SIRS check, age-banded — a pediatric-safe floor the ML model alone can't provide (below) |
| **2** | `layers/layer2_symptom_nlp.py` | Red-flag extraction from the chief complaint, returning the **exact spans** that matched |
| **2b** | `layers/layer2b_labs.py` | LLM evaluation of an uploaded lab panel against reference ranges, with a deterministic fallback |
| **3** | `layers/layer3_fusion.py` | Transparent weighted fusion into the Arrival Risk Index, mapped to ESI I–V with a confidence band |
| **4** | `layers/layer4_deterioration.py` | Re-scores every waiting patient as a time series and escalates on slope **or** an overdue reassessment |
| **5** | `layers/layer5_routing.py` | Suggests a *named* bed and clinician from a hospital-scale-specific `ward.py` roster, not just a pathway and a count |

### Three decisions worth defending

**Scores are append-only.** `backend/db.py` never updates a score in place. The
sequence of scores *is* the trajectory Layer 4 reasons over — overwrite it and PULSE
becomes the one-shot triage it was built to replace.

**Absent red flags are not evidence of safety.** If Layer 2 finds no flags, its
component is *dropped* from the fusion rather than contributing zero. Scoring silence
as zero risk would systematically bury exactly the patients whose words never reveal
the problem.

**The threshold is set by fixing sensitivity, not by picking whatever flatters the
model.** Under-triage is the error direction that kills people, so we fix sensitivity
at 85% and report the over-triage cost that buys.

---

## Layer 1 model performance

Held-out test set, 12,000 encounters:

| Metric | PULSE | ESI (real-world, Sax 2023) |
|---|---|---|
| ROC-AUC | **0.861** | — |
| Sensitivity for patients needing life-stabilising intervention | **85.0%** | 65.9% |
| Under-triage rate | **1.9%** | 3.3% |
| Alert rate (over-triage cost) | 42% | 28.9% |

Regenerate with `python -m backend.ml.train`.

### Data honesty

MIMIC-IV-ED requires credentialed PhysioNet access, which we do not have at hackathon
time. `backend/ml/train.py` therefore generates a **synthetic cohort** whose vital-sign
distributions and risk relationships are drawn from published emergency-medicine
literature, deliberately including a 20% subgroup of critical patients who present with
near-normal vitals, plus realistic missingness and label noise.

The pipeline, feature contract, calibration and explanation path are exactly what we
would run against MIMIC-IV-ED — only the source table changes. **The numbers above
are real measurements on held-out synthetic data, not real measurements on real
patients**, and we would not claim otherwise to a judge.

---

## Round 2 guidelines — what changed and why

The organisers' Round 2 guidelines were checked against this build line by line;
six gaps were real, and all six are now closed and independently verified rather
than merely claimed. Each is a load-bearing behaviour change, not a cosmetic one.

**1. Pediatric-safe scoring.** Layer 1's XGBoost model is trained on an
adult-calibrated synthetic cohort (NEWS2/qSOFA/shock-index literature — all adult
frameworks). Fed a genuinely healthy 3-year-old's normal vitals (HR 128, RR 28 —
alarming by adult thresholds, unremarkable for a toddler), it scored 97% risk. Two
independent fixes, not one: `layer1b_heuristics.py`'s SIRS check now uses age-banded
HR/RR thresholds (Goldstein 2005 pediatric-SIRS-consensus shape) instead of one
adult cutoff for every age, and `layer3_fusion.py` discounts Layer 1's *vitals*
weight by age band — 0.6× age 12–17, 0.25× age 6–11, **0×** under 6, where the raw
model has no calibrated signal at all. A flat discount was tried first and measured
insufficient (a 0.5× cut on a 97%-risk input still landed ESI II); the graduated,
zero-at-the-floor version is what actually corrects it. Verified: PT 14 (age 3,
elevated-for-adult vitals) now resolves ARI 0 / ESI V; a 45-year-old with the same
raw numbers still resolves at the original adult-accurate score — the fix is
age-scoped, not a global desensitisation.

**2. Wait-time-triggered re-assessment.** Layer 4 previously escalated only on a
*rising* score trend — a patient who arrived low-acuity and stayed flat, however
long they waited, was invisible to it. `layer4_deterioration.py` now carries a
second, independent trigger: CTAS-derived maximum safe wait windows per ESI tier
(II: 15 min, III: 30 min, IV: 60 min, V: 120 min; ESI I is zero — always immediate).
Breaching the window for a patient's own current tier raises a `reassessment_due`
recommendation through the same nurse decision gate as every other escalation, even
with an empty or entirely flat score history — the old trend-only path required at
least two distinct scores to reason over at all.

**3. Surge-mode demonstration.** `Engine.trigger_surge()` in `main.py` injects a
burst of new patients — a deliberately heterogeneous mix of acuities, not N copies
of the same complaint — staggered over a short window, so bed contention, routing
pressure and queue reordering under 3× normal volume are things a judge can trigger
and watch happen live, not something asserted in a slide. Reachable via
`POST /api/control/surge?value=<multiplier>`.

**4. A regulatory basis and real access control** — see the dedicated section
below.

**5. Hospital-scale configurability.** Ward capacity used to be four module-level
constants — one fixed department shape, full stop. `data/hospital_profiles.json`
now holds three named presets (`community_hospital`, the original default;
`rural_ed`, six beds and a single generalist covering every specialty;
`urban_trauma_center`, 28 beds and a deep on-call roster) that `ward.py` loads at
runtime, with the original hardcoded numbers kept as an in-code fallback if the
file is ever missing. `Engine.set_hospital_profile()` rebuilds the roster from any
profile without a restart, rejecting an unknown name outright rather than falling
over. Reachable via `POST /api/control/profile?value=rural_ed`.

**6. Scenario depth.** The scripted demo grew from 13 to 16 patients: two
pediatric cases (ages 3 and 8) that exercise gap #1 directly, and one adult case,
each with physiology authored the same way as every other scripted patient — real
vitals a real pipeline reasons over, nothing hand-scored.

---

## Regulatory basis and access control

PULSE's own ambulance-tracking layer anchors this deployment to India — a
Bengaluru-based fleet, real OSRM road-network routing (`backend/ambulance.py`) — so
the assumed regulatory jurisdiction is India's **Digital Personal Data Protection
Act, 2023**. Section 8(5) puts a "reasonable security safeguards" duty on anyone
processing personal data; an emergency department's patient names, ages,
complaints and vitals are squarely that, and an unauthenticated API where anyone on
the network can create, edit or discharge a patient record fails that duty
regardless of how good the triage logic behind it is.

`backend/auth.py` + a blanket FastAPI middleware in `main.py` close that gap:
**every write under `/api/*`** — intake, voice intake, translation, decide, admit,
discharge, medications, clinical notes, ward status, lab upload, and the control
endpoints above — requires an `X-PULSE-Token` header matching `PULSE_API_TOKEN`
(`.env`; defaults to a fixed demo value so the app still runs out of the box, but
never on an *unknown* value). Reads — the board, audit log, model metrics — stay
open, matching how the console is actually used: a display surface meant to be
visible department-wide, the same way a physical whiteboard would be. The frontend
sends the header automatically on every mutating call (`frontend/lib/api.ts`); a
request without it gets a `401` before any handler runs. A single shared token
rather than per-user accounts is a deliberate scope decision for a prototype — real
deployment sits behind hospital SSO/RBAC, and the `actor` column already in
`db.py`'s decisions table is where per-clinician identity would attach; what this
layer proves is that the write surface is gated at all, which is the DPDP-relevant
claim.

The Act's storage-limitation duty (s.8(7): erase personal data once its purpose is
served) is likewise a real code path, not a policy statement: `db.purge_stale_records()`
removes a patient and everything that references them — scores, medications,
notes, recommendations, decisions — once their most recent score is older than a
configurable retention window (90 days by default), cascading through every table
so nothing is left orphaned. Reachable via `POST /api/control/purge?value=<days>`;
a real deployment would run it on a schedule rather than on demand.

---

## What is real and what is stubbed

**Real:** the XGBoost model and its SHAP attributions · the full six-layer scoring
pipeline · the scheduler loop · SQLite persistence with append-only scores · the audit
trail · the override flow · shadow-mode agreement tracking · WebSocket push with
polling fallback.

**Stubbed, deliberately:** the scripted scenario's patient arrivals and vitals come
from `simulation.py` rather than live monitors, and the bed/clinician roster (below)
starts from a fixed initial headcount rather than a hospital's staffing system —
everything downstream of that roster (occupancy, routing, the Ward Map) is real.

**Red-flag extraction (Layer 2) is a genuine three-tier failover**, in
`layers/nlp_core.py`: Gemini (`layers/nlp_llm.py`), grounded on
`data/clinical_lexicon.json`'s closed vocabulary, is tried first; if it's
unconfigured or fails, Groq — a second vendor, so one provider's outage doesn't
sink the demo — is tried next; the deterministic lexicon matcher underneath both is
the guaranteed fallback, the same path that keeps PULSE working fully offline. Both
LLM tiers are off by default (`PULSE_NLP_MODE=lexicon`); set `PULSE_NLP_MODE=llm`
and at least one of `GEMINI_API_KEY` / `GROQ_API_KEY` to turn them on. Whichever
tier actually answered is stamped on the result (`llm-gemini` / `llm-groq` /
`lexicon`) and shown on the console as a small badge, so the failover is something
you can watch happen rather than a line in this README. Regenerate the agreement
numbers with `python -m backend.ml.eval_nlp`.

**Voice Intake** is the demoable form of "the nurse and the patient (or the person who
brought them) don't share a language." A mic panel on the console records speech in
the browser (Web Speech API — audio never leaves the machine), and the recognised
text, in whatever language, goes to `POST /api/voice-intake`. The LLM translates it
into a chart-style English chief complaint, pulls out age and any vital-sign *numbers
actually spoken aloud* (never inferred from a description), and a new patient appears
on the board, already through Layer 2, fusion and routing, waiting on the same human
decision gate as everyone else. It needs the LLM tier — there's no lexicon fallback
for translation — and says so plainly if it isn't configured, rather than silently
extracting nothing useful from non-English text.

**The Ward Map turns capacity from a count into a roster.** `backend/ward.py`
generates individually-identified beds (`RC-1`, `AM-2`, ...) and clinicians, each
with its own status — `available` / `occupied` / `cleaning` / `unavailable` for a
bed, `available` / `busy` / `off_shift` for a clinician. Layer 5 no longer just
counts free beds in a pathway; it names the specific bed and clinician it would
assign (`suggested_bed`, `suggested_clinician`), and the nurse's own console shows
that same name on the decision gate. Accepting or overriding a recommendation is the
one place `assigned_esi` is written *and* the one place a bed goes from available to
occupied — the acuity decision and the resource commitment happen in the same click,
not as two things that can drift apart. If a patient already admitted deteriorates
further, Layer 4's re-triage now fires for in-treatment patients too (previously
waiting-room only): accepting that escalation releases their current bed (to
`cleaning`, not straight back to `available` — that's what actually happens to a bed
someone is moved out of) and assigns the new one. The Ward Map page
(`frontend/app/ward`) is the live, colour-coded view of all of it, and the only page
where staff can directly mark a bed clean or a clinician back on shift — never
"occupied" or "busy" by hand, since those only mean anything tied to an actual
patient.

**Patient Intake creates a live patient, not a preview.** `POST /api/intake` used to
return an ARI number and nothing else. It now runs the exact same path Voice Intake
does — `Engine.create_intake_patient` — so submitting the reviewed form (personal
details, dictated complaint, manually entered vitals, PDF-extracted lab results)
puts a real, queued patient on the Triage Dashboard, scored before the response even
returns. A lab PDF's extracted test panel is also scanned for vital-sign-shaped
entries (`backend/lab/pipeline.py:infer_vitals`) — pulse, blood pressure, SpO₂,
temperature, respiratory rate — and used to pre-fill the vitals fields, so a report
that happens to carry a physical-exam block doesn't need those numbers retyped by
hand.

---

## API

Every endpoint below except the `GET`s and `WS /ws` requires an `X-PULSE-Token`
header (see **Regulatory basis and access control** above) — the frontend sends it
automatically; a `curl`/Postman call needs it added by hand.

| Endpoint | Purpose |
|---|---|
| `GET /api/board` | Full board state — patients, ward roster, capacity, surge status, audit feed |
| `WS /ws` | Live push, ~1s cadence |
| `POST /api/decide/{id}/accept` | Nurse accepts the recommendation — commits the suggested bed & clinician |
| `POST /api/decide/{id}/override?esi=III` | Nurse overrides — recomputes routing for the overridden ESI, logged |
| `POST /api/admit/{id}` | Move patient to their bed |
| `POST /api/voice-intake` | Voice Intake — `{transcript, lang}` in, a new patient scored and queued out. Requires the LLM tier |
| `POST /api/translate` | Translates dictated text into English for the intake form — same LLM tier as Voice Intake |
| `POST /api/intake` | Structured intake form — creates a live, queued patient from reviewed details/vitals/labs |
| `POST /api/extract-lab` | PDF lab report upload — structured demographics, `test_results`, and inferred `vitals`; requires Docling and Ollama |
| `POST /api/ari` | Stateless ARI preview from an unreviewed snapshot — no patient created |
| `POST /api/ward/beds/{id}/status` | Staff sets a bed to available / cleaning / unavailable |
| `POST /api/ward/clinicians/{id}/status` | Staff sets a clinician to available / off_shift |
| `POST /api/control/reset` | Reset the simulation |
| `POST /api/control/surge?value=<multiplier>` | Inject a heterogeneous burst of patients (default 3×) — see **Surge-mode demonstration** above |
| `POST /api/control/profile?value=<name>` | Switch hospital-capacity preset live — `community_hospital` / `rural_ed` / `urban_trauma_center` |
| `POST /api/control/purge?value=<days>` | Purge patients past their data-retention window (default 90 days) — see **Regulatory basis** above |
| `GET /api/audit` | Decision log and agreement rate |
| `GET /api/model` | Layer 1 metrics |

---

## Layout

```
backend/
  main.py            FastAPI app, scheduler loop, WebSocket, surge/profile/purge control
  auth.py            Access control — X-PULSE-Token bearer gate on every write
  db.py              SQLite — append-only scores, audit trail, data-retention purge
  simulation.py      Simulated department and patient physiology (16 scripted patients)
  ward.py            Bed/clinician roster, loaded from a named hospital-scale profile —
                      the one source of truth Layer 5 routes against and the Ward Map renders
  layers/            The scoring pipeline, one file per layer (1, 1b, 2, 2b, 3, 4, 5)
  lab/               PDF lab report extraction — Docling + local Ollama
  ml/train.py        Model training
frontend/            Next.js + TypeScript nurse console
  app/               App Router entry point — dashboard, intake, ward routes
  components/        Navigation, dashboard, board, intake, ward map, drawer
  lib/               Typed API client (sends the auth header) and shared domain models
data/
  clinical_lexicon.json     Red-flag rubric for Layer 2
  hospital_profiles.json    Named capacity presets ward.py loads at runtime
docs/ARCHITECTURE.md
```

Backend runs fully offline by default (the LLM tier is opt-in). The frontend is a
standard Next.js app — it does have a build step now, `npm install && npm run dev`.

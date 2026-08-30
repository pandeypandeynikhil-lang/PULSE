# PULSE — Patient Urgency & Load Sequencing Engine

**Accenture Innovation Challenge 2026 · Problem Statement 2 — PatientTriage.ai**

A triage co-pilot that sits beside the nurse, not in her place. It ingests a patient
the moment they're spoken for, written up, or diagnostically tested — voice, a
structured intake form, a lab PDF — fuses vitals, symptom narrative and live
department state into one explainable priority signal, and keeps updating that
signal, and the bed it points to, for as long as the patient is waiting.

**PULSE never assigns an acuity level. A nurse does. Every time.**

---

## Contents

[Setup](#setup) · [What to watch for](#what-to-watch-for) ·
[The escalation is not scripted](#the-escalation-is-not-scripted) ·
[Architecture](#architecture) · [Layer 1 model performance](#layer-1-model-performance) ·
[Round 2 guidelines — what changed and why](#round-2-guidelines--what-changed-and-why) ·
[Regulatory basis and access control](#regulatory-basis-and-access-control) ·
[What is real and what is stubbed](#what-is-real-and-what-is-stubbed) ·
[API](#api) · [Layout](#layout)

---

## Setup

Every step below, in order, on Windows, macOS, or Linux — two terminals, nothing
skipped. The **core app needs only steps 1–4**; everything after that is optional
and adds one specific feature.

### 1. Prerequisites

Python 3.10+, Node.js 18+ with npm, and git. `python --version` / `node --version`
to check what you already have.

### 2. Backend — install and train

**Windows (PowerShell):**

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r backend/requirements.txt
python -m backend.ml.train
```

**macOS / Linux:**

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
python -m backend.ml.train
```

`pip install` pulls in FastAPI, XGBoost, the Gemini/Groq SDKs, and Docling +
langchain-ollama for lab-PDF parsing (step 6) — nothing here needs a paid key,
an API call, or a GPU to *install*. `python -m backend.ml.train` trains Layer 1's
XGBoost model on the synthetic cohort (~20 seconds) and writes
`backend/ml/artifacts/vitals_model.pkl`; skip it and the backend trains the same
model itself the first time it boots, so this step only saves you that first-run
wait.

### 3. Start the backend

```bash
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

Leave this terminal running — it's the scheduler loop, re-scoring every waiting
patient once a second for as long as it's up.

### 4. Frontend

```bash
cd frontend
npm install
npm run dev
```

Open **http://localhost:3000**. That's the whole app, running fully offline —
symptom extraction on the deterministic lexicon matcher, everything else at full
strength: the six-layer scoring pipeline, the deterioration engine, Ward Map,
ambulance tracking, medications/notes/discharge, surge mode, hospital-profile
switching, access control. Only two things need anything past this point: richer
LLM-based extraction (step 5) and lab-PDF upload (step 6) — both fail closed and
say so plainly if skipped, never silently.

Six routes, one live board underneath all of them: **`/`** is the landing page —
what the product argues, before you touch it. **Triage Dashboard** (`/dashboard`)
is the live operational board, department state, shadow-mode agreement, and audit
log. **Patient Intake** (`/intake`) enters demographics, vitals, dictated clinical
notes, and sequentially uploaded PDF lab reports, and submitting puts a real
patient on the board. **Ward Map** (`/ward`) is the colour-coded bed and clinician
roster Layer 5 actually routes against, editable in real time. **Patient Directory**
(`/patients`) searches every patient on record; each one opens onto a full chart
(`/patients/[id]`) — medications, clinical notes, and discharge, detailed below.
**Ambulance Tracking** (`/ambulances`) is a live radar of the inbound fleet, road
routes and all. The department is simulated continuously; reset it from the
header when needed.

### 5. Optional — the LLM NLP tier (Voice Intake, richer red-flag extraction)

Off by default (`PULSE_NLP_MODE=lexicon`); Layer 2's red-flag extraction runs on
the deterministic lexicon matcher and Voice Intake is disabled until this is on.

1. `cp .env.example .env`
2. Get a free key from **Gemini** (https://aistudio.google.com) and/or **Groq**
   (https://console.groq.com) — either is enough to turn the tier on; both is
   better, since PULSE tries Gemini first and only falls to Groq if it fails, so
   the second key is what makes that failover real rather than theoretical.
3. Fill in `GEMINI_API_KEY` and/or `GROQ_API_KEY` in `.env`
4. Set `PULSE_NLP_MODE=llm`
5. Restart the backend (Ctrl+C, re-run the step 3 command)

The console stamps every score with which tier actually answered
(`llm-gemini` / `llm-groq` / `lexicon`) so the failover is something you watch
happen, not a line in this file.

### 6. Optional — lab report PDF parsing (Ollama + Llama 3.1)

Patient Intake's PDF upload and the patient chart's "Upload lab report" panel go
through `backend/lab/pipeline.py`: **Docling** turns the PDF into structured
markdown, then a **locally-running Llama 3.1** (via **Ollama**) turns that
markdown into structured test results — name, value, unit, reference range,
abnormality flag — which Layer 2b then evaluates and Layer 1 scans for
vital-sign-shaped entries. This is the one feature in PULSE that depends on a
*local* LLM rather than Gemini/Groq or the offline lexicon, deliberately: parsing
a layout-heavy pathology-report table is a job a small local model handles just
as well as a cloud one, and this way no lab data — someone's actual blood work —
ever has to leave the machine to be read.

1. **Install Ollama** — https://ollama.com/download (Windows, macOS, Linux). The
   installer starts the Ollama server as a background service automatically; you
   don't run anything to keep it alive.
2. **Pull the model:**
   ```bash
   ollama pull llama3.1
   ```
   ~4.7 GB, one-time download. Confirm it landed with `ollama list`.
3. That's it — **no `.env` entry required.** `POST /api/extract-lab` talks to
   Ollama on its default `localhost:11434` the next time a PDF is uploaded.
4. To point this at a different local model instead (a smaller one on a slower
   machine, say — anything `ollama pull`-able works, since `langchain-ollama`
   only needs a model name), set `PULSE_LAB_OLLAMA_MODEL=<model name>` in `.env`
   and pull that model instead of `llama3.1`.

If Ollama isn't running, or the model was never pulled, PDF upload fails with a
plain `422` naming the actual problem — never silently. Nothing else in PULSE
needs Ollama: every other feature, including the full scoring pipeline, works
with it never installed at all.

### 7. Optional — refresh the live ambulance routes

`data/ambulance_routes.json` ships pre-fetched and committed, so this step is
**never required** to run the app — `Engine.reset()` only ever reads that file.
To regenerate it against OSRM's live routing service instead of the cached one:

```bash
python -m backend.ambulance
```

### 8. Optional — change the access-control token before any real deployment

`PULSE_API_TOKEN` / `NEXT_PUBLIC_API_TOKEN` in `.env` default to a fixed demo
value (`pulse-demo-2026`) so every write endpoint is protected out of the box
with zero setup — see [Regulatory basis and access control](#regulatory-basis-and-access-control).
Change both (they must match) before deploying anywhere real; leave them alone
for local development and demoing.

---

## What to watch for

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
polling fallback · live ambulance tracking on real, cached OSRM road routes · the
medication, clinical-notes and discharge workflow on a patient's chart.

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

**Live ambulance tracking is real road routing, not a straight line on a map.**
`backend/ambulance.py` fetches each inbound vehicle's route from OSRM
(project-osrm.org) — a real Bengaluru road-network polyline — exactly once, at
`python -m backend.ambulance` time, and caches it to `data/ambulance_routes.json`,
committed with the project. `Engine.reset()` only ever reads that cached file; it
never calls OSRM live, so a demo's Reset button can never depend on the venue's
wifi or a third-party service being up, and a route that was never fetched falls
back to a straight line rather than breaking. Every tick, `position_at()`
interpolates each ambulance's live bearing and distance from the hospital along
its real route — the same "author the ground truth once, let the engine compute
the live state" pattern `simulation.py` uses for physiology, applied to geography.
The Ambulance Tracking page (`frontend/app/ambulances`, `components/AmbulanceRadar`)
renders it as a radar: click a marker for that vehicle's crew, unit number, and
live ETA. This is also Layer 0's actual pre-arrival signal source in the running
app — an inbound ambulance's distance and ETA feed the board before the patient
is ever at the door.

**A patient's chart doesn't end at triage.** `/patients` searches every patient on
record; opening one (`/patients/[id]`) reaches a full medication and notes
workflow that exists independently of the scoring pipeline. Medications can be
scheduled ahead (`POST /api/medications/schedule`) or given immediately in an
emergency (`POST /api/medications/emergency`, which schedules and records the
administration in one call); every administration is a `given` / `held` /
`refused` / `not_available` / `cancelled` record, and the API rejects a `held` or
`refused` entry with no reason — the record can't silently go quiet on why a dose
wasn't given. Each administration carries an actor (`X-Actor-Id` header, default
`demo-nurse`) — a real per-action identity already threading through the
medication trail, ahead of where the rest of the audit rail (`db.py`'s decisions
table) currently only records a fixed `"triage nurse"`. Clinical notes
(`POST /api/patients/{id}/notes`, typed `surgical` / `follow_up`) and discharge
(`POST /api/discharge/{id}`) round it out: discharging writes the discharge
summary and any follow-up instructions as clinical notes, moves the patient to
`discharged`, and releases their bed and clinician back to the Ward Map roster.

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
| `PATCH /api/patients/{id}/profile` | Edits a patient's chart — demographics, vitals, labs, bed/clinician assignment |
| `POST /api/patients/{id}/medications` | Adds a medication order to a patient's chart |
| `PATCH /api/patients/{id}/medications/{med_id}/order` | Edits a medication order (dosage, frequency, route, ...) |
| `POST /api/medications/schedule` | Schedules a medication ahead of time |
| `POST /api/medications/emergency` | Orders and immediately records an emergency (given-now) medication |
| `PATCH /api/patients/{id}/medications/{med_id}` | Records an administration — given / held / refused / not_available / cancelled |
| `PATCH /api/patients/{id}/medications/{med_id}/given` | Shortcut to mark a dose given |
| `POST /api/patients/{id}/notes` | Adds a clinical note (`surgical` / `follow_up`) |
| `POST /api/discharge/{id}` | Discharges a patient — logs the summary, releases their bed and clinician |
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
  db.py              SQLite — append-only scores, audit trail, meds/notes, data-retention purge
  simulation.py      Simulated department and patient physiology (16 scripted patients)
  ambulance.py       Live fleet tracking on cached, real OSRM road routes
  ward.py            Bed/clinician roster, loaded from a named hospital-scale profile —
                      the one source of truth Layer 5 routes against and the Ward Map renders
  layers/            The scoring pipeline, one file per layer (1, 1b, 2, 2b, 3, 4, 5)
  lab/               PDF lab report extraction — Docling + local Ollama
  ml/train.py        Model training
frontend/            Next.js + TypeScript nurse console
  app/               App Router entry point — landing, dashboard, intake, ward,
                      patients (directory + chart), ambulances routes
  components/        Navigation, dashboard, board, intake, ward map, ambulance
                      radar, patient chart, drawer
  lib/               Typed API client (sends the auth header) and shared domain models
data/
  clinical_lexicon.json     Red-flag rubric for Layer 2
  hospital_profiles.json    Named capacity presets ward.py loads at runtime
  ambulance_routes.json     Cached real OSRM road routes for the live fleet
docs/ARCHITECTURE.md
```

Backend runs fully offline by default (the LLM tier is opt-in). The frontend is a
standard Next.js app — it does have a build step now, `npm install && npm run dev`.

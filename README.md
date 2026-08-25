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
| **2** | `layers/layer2_symptom_nlp.py` | Red-flag extraction from the chief complaint, returning the **exact spans** that matched |
| **3** | `layers/layer3_fusion.py` | Transparent weighted fusion into the Arrival Risk Index, mapped to ESI I–V with a confidence band |
| **4** | `layers/layer4_deterioration.py` | Re-scores every waiting patient as a time series and escalates on slope |
| **5** | `layers/layer5_routing.py` | Suggests a *named* bed and clinician from the live `ward.py` roster, not just a pathway and a count |

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

| Endpoint | Purpose |
|---|---|
| `GET /api/board` | Full board state — patients, ward roster, capacity, audit feed |
| `WS /ws` | Live push, ~1s cadence |
| `POST /api/decide/{id}/accept` | Nurse accepts the recommendation — commits the suggested bed & clinician |
| `POST /api/decide/{id}/override?esi=III` | Nurse overrides — recomputes routing for the overridden ESI, logged |
| `POST /api/admit/{id}` | Move patient to their bed |
| `POST /api/voice-intake` | Voice Intake — `{transcript, lang}` in, a new patient scored and queued out. Requires the LLM tier |
| `POST /api/intake` | Structured intake form — creates a live, queued patient from reviewed details/vitals/labs |
| `POST /api/extract-lab` | PDF lab report upload — structured demographics, `test_results`, and inferred `vitals`; requires Docling and Ollama |
| `POST /api/ari` | Stateless ARI preview from an unreviewed snapshot — no patient created |
| `POST /api/ward/beds/{id}/status` | Staff sets a bed to available / cleaning / unavailable |
| `POST /api/ward/clinicians/{id}/status` | Staff sets a clinician to available / off_shift |
| `POST /api/control/reset` | Reset the simulation |
| `GET /api/audit` | Decision log and agreement rate |
| `GET /api/model` | Layer 1 metrics |

---

## Layout

```
backend/
  main.py            FastAPI app, scheduler loop, WebSocket
  db.py              SQLite — append-only scores, audit trail
  simulation.py      Simulated department and patient physiology
  ward.py            Bed/clinician roster — the one source of truth Layer 5
                      routes against and the Ward Map renders
  layers/            The five layers, one file each
  lab/               PDF lab report extraction — Docling + local Ollama
  ml/train.py        Model training
frontend/            Next.js + TypeScript nurse console
  app/               App Router entry point — dashboard, intake, ward routes
  components/        Navigation, dashboard, board, intake, ward map, drawer
  lib/               Typed API client and shared domain models
data/
  clinical_lexicon.json   Red-flag rubric for Layer 2
docs/ARCHITECTURE.md
```

Backend runs fully offline by default (the LLM tier is opt-in). The frontend is a
standard Next.js app — it does have a build step now, `npm install && npm run dev`.

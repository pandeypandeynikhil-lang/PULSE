# PULSE — Patient Urgency & Load Sequencing Engine

**Accenture Innovation Challenge 2026 · Problem Statement 2 — PatientTriage.ai**

A triage co-pilot that sits beside the nurse, not in her place. It listens from the
ambulance call onward, fuses vitals, symptom narrative and live department state into
one explainable priority signal — and keeps updating that signal for as long as the
patient is waiting.

**PULSE never assigns an acuity level. A nurse does. Every time.**

---

## Run it

```bash
git clone <this repo> && cd pulse
./run.sh          # Windows: run.bat
```

Then open **http://127.0.0.1:8000**. First run trains the Layer 1 model
(~20 seconds); after that it starts immediately.

Runs fully offline by default. To turn on the LLM NLP tier (and the Voice Intake
panel, which needs it): `cp .env.example .env`, fill in `GEMINI_API_KEY` and/or
`GROQ_API_KEY` (both have a free tier), set `PULSE_NLP_MODE=llm`.

The department is simulated and the clock runs on its own. Use the speed control
in the header — **60×** is right for watching, **180×** for a quick pass.

### What to watch for

| Time | What happens |
|---|---|
| ~17:43 | **Layer 0** scores the inbound ambulance call before the patient arrives, and pre-positions a bay, an ECG and cardiology |
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
  SIGNALS IN            PERCEPTION              REASONING            ACTION · HUMAN GATE
  ──────────            ──────────              ─────────            ───────────────────
  ambulance audio  ──▶  L0 pre-arrival NLP ──┐
  chief complaint  ──▶  L2 symptom NLP     ──┼──▶  L3 fusion → ARI ──▶  nurse console
  vitals stream    ──▶  L1 vitals model    ──┘         ▲    │           (accept / override)
  prior records    ──▶                                 │    ▼                  │
  live ED state    ──────────────────────────▶  L4 deterioration        L5 routing → bed
                                                    (re-score loop)      + specialist
  ─────────────────────────  GOVERNANCE RAIL  ─────────────────────────────────────────
  append-only score history · SHAP on every score · audit log · shadow-mode agreement
```

| Layer | File | What it does |
|---|---|---|
| **0** | `layers/layer0_prearrival.py` | Scores the ambulance/helpline call. Emits a **provisional prior**, capped below ESI-II equivalence, that may move resources and nothing else |
| **1** | `layers/layer1_vitals.py` | XGBoost on whatever vitals exist. Missing fields stay `NaN` — never imputed and passed off as measured |
| **2** | `layers/layer2_symptom_nlp.py` | Red-flag extraction from the chief complaint, returning the **exact spans** that matched |
| **3** | `layers/layer3_fusion.py` | Transparent weighted fusion into the Arrival Risk Index, mapped to ESI I–V with a confidence band |
| **4** | `layers/layer4_deterioration.py` | Re-scores every waiting patient as a time series and escalates on slope |
| **5** | `layers/layer5_routing.py` | Matches pathway and specialty against live beds and staffing |

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

**Stubbed, deliberately:** bed and staffing data are simulated in-process (a real
deployment reads these from the hospital's system) · patient arrivals and vitals come
from `simulation.py` rather than live monitors · the scripted ambulance call's
speech-to-text is pre-transcribed, so Layer 0 starts from text for that scenario
patient specifically — Voice Intake (below) does real, live browser speech-to-text.

**Red-flag extraction (Layers 0 and 2) is a genuine three-tier failover**, in
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

---

## API

| Endpoint | Purpose |
|---|---|
| `GET /api/board` | Full board state |
| `WS /ws` | Live push, ~1s cadence |
| `POST /api/decide/{id}/accept` | Nurse accepts the recommendation |
| `POST /api/decide/{id}/override?esi=III` | Nurse overrides — logged |
| `POST /api/admit/{id}` | Move patient to their bed |
| `POST /api/voice-intake` | Voice Intake — `{transcript, lang}` in, a new patient scored and queued out. Requires the LLM tier |
| `POST /api/control/speed?value=60x` | Simulation speed |
| `POST /api/control/pause` · `/reset` | Clock control |
| `GET /api/audit` | Decision log and agreement rate |
| `GET /api/model` | Layer 1 metrics |

---

## Layout

```
backend/
  main.py            FastAPI app, scheduler loop, WebSocket
  db.py              SQLite — append-only scores, audit trail
  simulation.py      Simulated department and patient physiology
  layers/            The six layers, one file each
  ml/train.py        Model training
frontend/            Single-screen nurse console (no build step)
data/
  clinical_lexicon.json   Red-flag rubric shared by Layers 0 and 2
docs/ARCHITECTURE.md
```

No build step, no bundler, no cloud dependency. It runs offline.

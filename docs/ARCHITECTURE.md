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

## The NLP failover chain

`layers/nlp_core.py:extract()` is the single entry point both Layer 0 (pre-arrival
transcript) and Layer 2 (chief complaint) call — deliberately the same code path,
because the clinical meaning of a phrase does not change with who said it. It tries,
in order:

1. **Gemini** (`layers/nlp_llm.py`), only when `PULSE_NLP_MODE=llm` and at least one
   provider key is set. Asked for a bare JSON object naming only flag ids that exist
   in `clinical_lexicon.json`, plus a verbatim quote as evidence for each. Any
   failure — missing key, timeout, malformed JSON — returns `None` and falls through.
2. **Groq**, tried automatically if Gemini is unconfigured or fails — a second vendor
   with a different outage surface, not just a retry of the same one. Same JSON
   contract, different provider SDK underneath (`_call_llm()` tries both in order and
   reports which one actually answered).
3. **The deterministic lexicon matcher** — always available, needs no network, and is
   what runs by default (`PULSE_NLP_MODE=lexicon`). This is what makes PULSE degrade
   rather than die if both LLM vendors are unreachable or the venue's wifi fails
   mid-demo.

Neither LLM tier is trusted blindly: whichever one answers, `nlp_core.py` validates
the response itself — a flag id has to be one from the lexicon, and its quote has to
be found verbatim in the source text (case-insensitive substring search) or the flag
is dropped entirely. A model-reported span offset is never used. Severity is never
asked of either model either; it's computed from the lexicon's own weights, same as
tier 3. This validation is provider-agnostic by design — it doesn't matter which
vendor answered, the same Python code decides whether to trust what came back.

Extraction is memoised per input text, because the scheduler re-scores every waiting
patient roughly once a second and a patient's complaint doesn't change between ticks —
without the cache, enabling the LLM tier would mean one API call per patient per
second, which is neither affordable nor necessary.

Whichever tier answers stamps `source: "llm-gemini" | "llm-groq" | "lexicon"` on the
result. That field is threaded through to the board payload and shown as a small
badge on the console (`PRESENTING COMPLAINT` header, and the pre-arrival prior box) —
so which tier served a given score, including a live Gemini→Groq failover, is visible
to the nurse, not just to someone reading this file.

`python -m backend.ml.eval_nlp` runs a small hand-labelled set of complaint/transcript
strings through both tiers and reports agreement. It is not a clinical validation —
we don't have clinician-reviewed ground truth for that, the same honesty constraint
that applies to the Layer 1 cohort — but it catches regressions and demonstrates the
actual reason to add an LLM tier: phrasing the lexicon's fixed patterns don't
anticipate ("it feels like an elephant on my chest" vs. the lexicon's `chest pain`
patterns).

## Voice Intake

`Engine.create_voice_patient()` in `backend/main.py` is a live, console-triggered
entry point for a patient or companion who doesn't share a language with the nurse.
It deliberately does *not* duplicate the flag-extraction logic above: it calls a
separate function, `nlp_llm.extract_voice_intake()`, whose only job is translation and
light structuring — a short English `complaint_summary`, an optional `age`, and any
vital-sign numbers actually spoken aloud. That summary is then set as the new
patient's `complaint` and re-enters the ordinary Layer 2 pipeline on the very next
scheduler tick, through the exact same `extract()` tiering described above. Nothing
about fusion, severity or ESI mapping has a second code path for a voice-intake
patient — the only thing this feature adds is a translation step in front of the
pipeline everyone else already goes through.

Practical details:
- Speech-to-text happens in the browser (Web Speech API); only recognised text is
  ever sent to the backend, never audio.
- The extraction call runs in a thread executor (`loop.run_in_executor`), not on the
  asyncio event loop directly — a blocking ~1-3s network call would otherwise stall
  the scheduler tick for every other patient on the board while it's in flight.
- A voice-intake patient gets a single-point vitals "timeline" built from whatever
  numbers were actually spoken (often none, sometimes one or two) — it is not a
  physiological curve like the scripted patients in `simulation.py`, and Layer 1 scores
  it exactly as it would score any door-time patient with sparse vitals: on whatever
  exists, NaN for the rest, flagged as low-confidence below three measurements.
- Requires `PULSE_NLP_MODE=llm` plus `GEMINI_API_KEY` and/or `GROQ_API_KEY` — same
  Gemini-then-Groq failover as the red-flag tier above. There is deliberately no
  lexicon fallback for this feature specifically — translation isn't something regex
  can do, and running the English-only matcher against foreign text would silently
  produce an empty, misleadingly clean-looking result instead of an honest failure.

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

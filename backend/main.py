"""PULSE API and scheduler.

The scheduler loop is the heart of this service, not a background chore. Every
tick it re-scores every waiting patient through the full pipeline and pushes the
result to any connected console. Layer 4 is not a feature bolted onto a triage
tool — it is the shape of the whole backend.
"""
from __future__ import annotations

import asyncio
import copy
import json
import logging
import os
import time
from datetime import datetime
from typing import Any

from dotenv import load_dotenv

load_dotenv()  # reads .env into os.environ, if present — before anything
               # below reads GEMINI_API_KEY / GROQ_API_KEY / PULSE_NLP_MODE.
               # Safe no-op if there is no .env: PULSE runs offline by default.

from fastapi import FastAPI, File, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

try:
    from . import db, simulation
    from .layers import (layer1_vitals, layer2_symptom_nlp,
                         layer3_fusion, layer4_deterioration, layer5_routing)
except ImportError:
    # Supports `uvicorn main:app` when the working directory is backend/.
    import db  # type: ignore[no-redef]
    import simulation  # type: ignore[no-redef]
    from layers import (layer1_vitals, layer2_symptom_nlp,
                        layer3_fusion, layer4_deterioration, layer5_routing)

TICK_SECONDS = 1.0          # wall-clock cadence of the scheduler
app = FastAPI(title="PULSE", version="0.1.0")
logger = logging.getLogger(__name__)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class Engine:
    """Owns simulation state, the scoring pipeline and connected clients."""

    def __init__(self) -> None:
        self.conn = db.init(reset=True)
        self.patients: list[simulation.SimPatient] = []
        self.sim_minutes = 0.0
        self.clients: set[WebSocket] = set()
        self.capacity = copy.deepcopy(simulation.BASE_CAPACITY)
        self.events: list[dict[str, Any]] = []
        self.reset()

    # ---------------------------------------------------------------- state
    def reset(self) -> None:
        self.conn = db.init(reset=True)
        self.patients = simulation.build_scenario()
        self.sim_minutes = 0.0
        self.capacity = copy.deepcopy(simulation.BASE_CAPACITY)
        self.events = []
        self.voice_seq = 0  # counts Voice Intake patients created this shift
        for p in self.patients:
            if p.arrive_min <= 0:
                p.status = "waiting"
                p.arrived_at_min = p.arrive_min
            if p.seed_esi:
                p.assigned_esi = p.seed_esi
            db.add_patient(self.conn, {
                "id": p.id, "display_id": p.display_id, "age": p.age,
                "arrival_mode": p.arrival_mode, "complaint": p.complaint,
                "transcript": p.transcript, "arrived_at": p.arrive_min,
                "status": p.status, "assigned_esi": p.assigned_esi})

    def log(self, kind: str, text: str, patient: str | None = None) -> None:
        self.events.insert(0, {"at": datetime.now().strftime("%H:%M:%S"), "kind": kind,
                               "text": text, "patient": patient})
        del self.events[40:]

    # ------------------------------------------------------------- pipeline
    def score_patient(self, p: simulation.SimPatient) -> dict[str, Any] | None:
        symptom = layer2_symptom_nlp.score(p.complaint or "")
        vitals_raw = p.vitals_at(self.sim_minutes)
        vitals_out = layer1_vitals.score(vitals_raw) if vitals_raw else None
        fused = layer3_fusion.fuse(vitals_out, symptom, p.age)

        # Persist a score when it actually says something new, or every few
        # simulated minutes. Writing one row per tick would bury the trajectory
        # in noise; Layer 4 needs spaced observations, not a high-frequency log.
        prev = db.last_score(self.conn, p.id)
        if (prev is None or prev["ari"] != fused["ari"]
                or self.sim_minutes - prev["at"] >= 4.0):
            db.append_score(self.conn, p.id, self.sim_minutes, fused,
                            {"vitals": vitals_raw, "vitals_out": vitals_out,
                             "symptom": symptom})

        history = db.score_history(self.conn, p.id)
        waited = (self.sim_minutes - (p.arrived_at_min or 0))
        trend = layer4_deterioration.assess(history, waited)
        systems = symptom["systems"]
        routing = layer5_routing.route(fused["esi"], systems, self.capacity)

        return {"fused": fused, "vitals": vitals_raw, "vitals_out": vitals_out,
                "symptom": symptom, "trend": trend, "routing": routing,
                "history": history, "waited": waited}

    # ----------------------------------------------------------------- tick
    async def tick(self) -> None:
        self.sim_minutes += (60 * TICK_SECONDS) / 60.0
        t = self.sim_minutes

        for p in self.patients:
            if p.status == "inbound" and t >= p.arrive_min:
                p.status = "waiting"
                p.arrived_at_min = p.arrive_min
                self.log("arrival", f"{p.display_id} arrived by {p.arrival_mode}",
                         p.display_id)

        for p in self.patients:
            if p.status not in ("waiting", "in-treatment"):
                continue
            res = self.score_patient(p)
            if res is None:
                continue
            p._last = res  # noqa: SLF001  cached for the board payload

            if p.status != "waiting":
                continue

            # New patient with no acuity yet -> initial recommendation.
            if p.assigned_esi is None and p.last_recommendation is None:
                rid = db.add_recommendation(
                    self.conn, p.id, t, "initial", res["fused"]["esi"],
                    res["routing"]["pathway"], res["routing"]["specialty"],
                    _rationale(res))
                p.last_recommendation = rid
                self.log("recommend",
                         f"{p.display_id}: recommend ESI {res['fused']['esi']} "
                         f"→ {res['routing']['pathway']}", p.display_id)

            # Already triaged, but trajectory says otherwise -> re-triage.
            elif (p.assigned_esi and not p.escalated
                    and res["trend"]["escalate"]
                    and _rank(res["fused"]["esi"]) < _rank(p.assigned_esi)):
                rid = db.add_recommendation(
                    self.conn, p.id, t, "re-triage", res["fused"]["esi"],
                    res["routing"]["pathway"], res["routing"]["specialty"],
                    res["trend"]["reason"] or _rationale(res))
                p.last_recommendation = rid
                p.escalated = True
                self.log("deterioration",
                         f"{p.display_id}: rising trajectory — "
                         f"ESI {p.assigned_esi} → {res['fused']['esi']} "
                         f"({res['trend']['reason']})", p.display_id)

        await self.broadcast()

    # ------------------------------------------------------------ decisions
    def decide(self, patient_id: str, action: str,
               override_esi: str | None = None) -> dict[str, Any]:
        p = next((x for x in self.patients if x.id == patient_id), None)
        if p is None or p.last_recommendation is None:
            return {"ok": False, "error": "no open recommendation"}

        res = getattr(p, "_last", None)
        rec_esi = res["fused"]["esi"] if res else "III"
        final = rec_esi if action == "accept" else (override_esi or "III")

        db.resolve(self.conn, p.last_recommendation, p.id, self.sim_minutes,
                   action, final)
        p.assigned_esi = final
        p.last_recommendation = None
        if res:
            p.pathway = res["routing"]["pathway"]
            p.specialty = res["routing"]["specialty"]
            beds = self.capacity["beds"]
            if beds.get(p.pathway, 0) > 0:
                beds[p.pathway] -= 1
        verb = "accepted" if action == "accept" else f"overrode to ESI {final}"
        self.log("decision", f"Nurse {verb} for {p.display_id}", p.display_id)
        return {"ok": True, "final_esi": final}

    def admit(self, patient_id: str) -> dict[str, Any]:
        p = next((x for x in self.patients if x.id == patient_id), None)
        if p is None:
            return {"ok": False}
        p.status = "in-treatment"
        p.seen_at_min = self.sim_minutes
        self.log("treatment",
                 f"{p.display_id} moved to {p.pathway or 'treatment'} "
                 f"— door-to-provider {int(self.sim_minutes - (p.arrived_at_min or 0))} min",
                 p.display_id)
        return {"ok": True}

    # ------------------------------------------------------------- voice intake
    async def create_voice_patient(self, transcript: str, lang: str) -> dict[str, Any]:
        """A spoken account from a patient or companion who doesn't share a
        language with the nurse becomes a new patient on the board — the same
        triggered live from the console instead of from the scripted scenario.

        Requires the LLM tier: the deterministic lexicon can't translate, and
        limping along on an English-only regex match against foreign text
        would silently extract nothing while looking like it worked. We fail
        honestly instead.
        """
        transcript = (transcript or "").strip()[:2000]
        if not transcript:
            return {"ok": False, "error": "Nothing to send yet."}

        try:
            from .layers import nlp_llm  # local import: optional LLM SDKs
        except ImportError:
            from layers import nlp_llm  # type: ignore[no-redef]
        if (os.environ.get("PULSE_NLP_MODE") != "llm"
                or not nlp_llm.any_provider_configured()):
            return {"ok": False, "error": ("Voice intake needs the LLM tier — "
                    "set PULSE_NLP_MODE=llm and GEMINI_API_KEY and/or "
                    "GROQ_API_KEY (see .env.example) and restart PULSE.")}

        loop = asyncio.get_running_loop()
        # The extraction call is a blocking network request; running it off
        # the event loop keeps the scheduler tick (and every other patient's
        # live board update) moving while this one call is in flight.
        raw = await loop.run_in_executor(
            None, nlp_llm.extract_voice_intake, transcript, lang)
        if raw is None:
            return {"ok": False, "error": ("Translation/extraction failed or "
                    "timed out — try again.")}

        provider = raw.get("_provider")
        self.voice_seq += 1
        pid, display_id = f"voice{self.voice_seq:02d}", f"PT V{self.voice_seq}"

        age = raw.get("age")
        age = age if isinstance(age, int) and 0 < age < 120 else None

        vitals = {k: v for k, v in (raw.get("vitals") or {}).items()
                 if isinstance(v, (int, float))}

        complaint = (raw.get("complaint_summary") or transcript[:80]).strip()

        p = simulation.SimPatient(
            id=pid, display_id=display_id, age=age, arrival_mode="voice intake",
            complaint=complaint, arrive_min=self.sim_minutes,
            timeline=[simulation.VitalsPoint(0.0, vitals)], transcript=transcript)
        p.status = "waiting"
        p.arrived_at_min = self.sim_minutes
        self.patients.append(p)

        db.add_patient(self.conn, {
            "id": p.id, "display_id": p.display_id, "age": p.age,
            "arrival_mode": p.arrival_mode, "complaint": p.complaint,
            "transcript": p.transcript, "arrived_at": p.arrived_at_min,
            "status": p.status, "assigned_esi": p.assigned_esi})

        self.log("voice", f"{display_id}: voice intake ({lang} via "
                 f"{provider or 'llm'}) — “{complaint}”", display_id)
        return {"ok": True, "id": pid, "display_id": display_id,
                "complaint": complaint, "age": age, "vitals": vitals,
                "provider": provider}

    # --------------------------------------------------------------- output
    def board(self) -> dict[str, Any]:
        rows = []
        for p in self.patients:
            res = getattr(p, "_last", None)
            if p.status == "inbound":
                continue
            if res is None:
                continue
            rows.append({
                "id": p.id, "display_id": p.display_id, "age": p.age,
                "complaint": p.complaint, "transcript": p.transcript,
                "arrival_mode": p.arrival_mode,
                "status": p.status, "assigned_esi": p.assigned_esi,
                "ari": res["fused"]["ari"], "esi": res["fused"]["esi"],
                "confidence": res["fused"]["confidence"],
                "waited": round(res["waited"], 1),
                "trace": [h["ari"] for h in res["history"]][-10:],
                "trend": res["trend"],
                "pending": p.last_recommendation is not None,
                "pathway": p.pathway or res["routing"]["pathway"],
                "specialty": p.specialty or res["routing"]["specialty"],
                "routing": res["routing"],
                "vitals": res["vitals"],
                "drivers": res["vitals_out"]["drivers"] if res["vitals_out"] else [],
                "vitals_present": res["vitals_out"]["vitals_present"] if res["vitals_out"] else 0,
                "spans": res["symptom"]["spans"],
                "nlp_source": res["symptom"].get("nlp_source", "lexicon"),
            })

        order = {"I": 0, "II": 1, "III": 2, "IV": 3, "V": 4, None: 5}
        rows.sort(key=lambda r: (order.get(r["assigned_esi"] or r["esi"], 5), -r["ari"]))
        return {
            "sim_minutes": round(self.sim_minutes, 1),
            "rows": rows, "capacity": self.capacity,
            "events": self.events[:14],
            "agreement": db.agreement_rate(self.conn),
            "model": layer1_vitals.model_metrics(),
        }

    async def broadcast(self) -> None:
        if not self.clients:
            return
        msg = json.dumps(self.board())
        dead = set()
        for ws in self.clients:
            try:
                await ws.send_text(msg)
            except Exception:
                dead.add(ws)
        self.clients -= dead

    # ---------------------------------------------------------- nlp warm-up
    async def prewarm_nlp(self) -> None:
        """Warms `nlp_core`'s per-text cache for every patient's
        complaint/transcript, concurrently, before the scheduler starts
        ticking (or right after a reset). `score_patient()` runs synchronously
        inside `tick()`, so without this the LLM tier's first, uncached call
        for each of a dozen-odd patients would happen one at a time inside the
        tick loop — each up to PULSE_NLP_TIMEOUT seconds — which could
        visibly freeze the whole board for the better part of a minute right
        when a demo starts. No-op if the LLM tier is off."""
        if os.environ.get("PULSE_NLP_MODE") != "llm":
            return
        try:
            from .layers import nlp_core
        except ImportError:
            from layers import nlp_core  # type: ignore[no-redef]
        texts = {p.complaint for p in self.patients if p.complaint}
        texts |= {p.transcript for p in self.patients if p.transcript}
        loop = asyncio.get_running_loop()
        await asyncio.gather(
            *(loop.run_in_executor(None, nlp_core.extract, t) for t in texts),
            return_exceptions=True)


def _rank(esi: str | None) -> int:
    return {"I": 1, "II": 2, "III": 3, "IV": 4, "V": 5}.get(esi or "V", 5)


def _rationale(res: dict[str, Any]) -> str:
    bits = []
    for d in res["drivers"] if "drivers" in res else res.get("vitals_out", {}).get("drivers", []):
        if d["direction"] == "raises":
            bits.append(f"{d['label']} {d['value']}")
    flags = [f["label"] for f in res["symptom"]["flags"][:3]]
    parts = []
    if flags:
        parts.append("reported " + ", ".join(flags))
    if bits:
        parts.append("vitals: " + ", ".join(bits[:3]))
    return "; ".join(parts) or "insufficient data — clinical assessment required"


engine = Engine()


@app.on_event("startup")
async def _startup() -> None:
    await engine.prewarm_nlp()

    async def loop() -> None:
        while True:
            try:
                await engine.tick()
            except Exception as exc:  # keep the shift running
                print("tick error:", exc)
            await asyncio.sleep(TICK_SECONDS)
    asyncio.create_task(loop())


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket) -> None:
    await ws.accept()
    engine.clients.add(ws)
    await ws.send_text(json.dumps(engine.board()))
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        engine.clients.discard(ws)


@app.get("/api/board")
async def api_board():
    return JSONResponse(engine.board())


@app.post("/api/decide/{patient_id}/{action}")
async def api_decide(patient_id: str, action: str, esi: str | None = None):
    out = engine.decide(patient_id, action, esi)
    await engine.broadcast()
    return JSONResponse(out)


class VoiceIntakeIn(BaseModel):
    transcript: str
    lang: str = "en-US"


class ARIIn(BaseModel):
    age_years: int | None = None
    complaint: str = ""
    nursing_assessment: str = ""
    vitals: dict[str, Any] = Field(default_factory=dict)
    test_results: list[dict[str, Any]] = Field(default_factory=list)


class PersonalDetailsIn(BaseModel):
    name: str = ""
    age_years: int | None = Field(default=None, ge=0, le=150)
    sex: str = ""
    referred_by: str = ""
    registration_no: str = ""
    report_date: str = ""


class PresentationIn(BaseModel):
    complaint: str = ""
    nursing_assessment: str = ""


class LaboratoryIn(BaseModel):
    test_results: list[dict[str, Any]] = Field(default_factory=list)


class IntakeIn(BaseModel):
    personal_details: PersonalDetailsIn = Field(default_factory=PersonalDetailsIn)
    presentation: PresentationIn = Field(default_factory=PresentationIn)
    vitals: dict[str, Any] = Field(default_factory=dict)
    laboratory: LaboratoryIn = Field(default_factory=LaboratoryIn)


@app.post("/api/voice-intake")
async def api_voice_intake(body: VoiceIntakeIn):
    out = await engine.create_voice_patient(body.transcript, body.lang)
    print("voice intake:", out)
    if out.get("ok"):
        await engine.broadcast()
    return JSONResponse(out)


@app.post("/api/ari")
async def api_ari(body: ARIIn):
    """Calculate an ARI preview for a reviewed intake payload."""
    complaint = " ".join(filter(None, (body.complaint, body.nursing_assessment)))
    symptom = layer2_symptom_nlp.score(complaint)
    vitals = dict(body.vitals)
    vitals["age"] = body.age_years
    vitals["arrival_mode"] = "walk-in"
    vitals_out = layer1_vitals.score(vitals)
    fused = layer3_fusion.fuse(vitals_out, symptom, body.age_years)
    return JSONResponse({"ari": fused["ari"], "esi": fused["esi"], "confidence": fused["confidence"]})


@app.post("/api/intake")
async def api_intake(body: IntakeIn):
    """Accept the complete, organised patient intake and calculate its ARI."""
    print("intake payload:", body)
    complaint = " ".join(filter(None, (
        body.presentation.complaint, body.presentation.nursing_assessment)))
    symptom = layer2_symptom_nlp.score(complaint)
    vitals = dict(body.vitals)
    vitals["age"] = body.personal_details.age_years
    vitals["arrival_mode"] = "walk-in"
    vitals_out = layer1_vitals.score(vitals)
    fused = layer3_fusion.fuse(
        vitals_out, symptom, body.personal_details.age_years)
    return JSONResponse({
        "ari": fused["ari"], "esi": fused["esi"],
        "confidence": fused["confidence"],
    })


@app.post("/api/extract-lab")
async def api_extract_lab(file: UploadFile = File(...)):
    """Extract structured demographics and test results from a PDF report."""
    if file.content_type != "application/pdf":
        raise HTTPException(status_code=415, detail="Only PDF files are supported.")

    contents = await file.read()
    if not contents:
        raise HTTPException(status_code=400, detail="The uploaded PDF is empty.")

    try:
        try:
            from .lab.pipeline import extract_lab_report
        except ImportError:
            from lab.pipeline import extract_lab_report  # type: ignore[no-redef]

        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, extract_lab_report, contents)
    except Exception as error:
        logger.exception("Lab report extraction failed")
        raise HTTPException(
            status_code=422,
            detail=f"Unable to extract the lab report ({type(error).__name__}): {error}",
        ) from error

    return JSONResponse(result.model_dump(mode="json"))


@app.post("/api/admit/{patient_id}")
async def api_admit(patient_id: str):
    out = engine.admit(patient_id)
    await engine.broadcast()
    return JSONResponse(out)


@app.post("/api/control/{what}")
async def api_control(what: str, value: str | None = None):
    if what == "reset":
        engine.reset()
        await engine.prewarm_nlp()
    await engine.broadcast()
    return JSONResponse({"ok": True})


@app.get("/api/audit")
async def api_audit():
    return JSONResponse({"decisions": db.audit(engine.conn),
                         "agreement": db.agreement_rate(engine.conn)})


@app.get("/api/model")
async def api_model():
    return JSONResponse(layer1_vitals.model_metrics())



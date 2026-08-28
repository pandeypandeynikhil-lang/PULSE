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
from typing import Any, Literal

from dotenv import load_dotenv

load_dotenv()  # reads .env into os.environ, if present — before anything
               # below reads GEMINI_API_KEY / GROQ_API_KEY / PULSE_NLP_MODE.
               # Safe no-op if there is no .env: PULSE runs offline by default.

from fastapi import FastAPI, File, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

try:
    from . import db, simulation, ward
    from .layers import (layer1_vitals, layer1b_heuristics, layer2_symptom_nlp, layer2b_labs,
                         layer3_fusion, layer4_deterioration, layer5_routing)
except ImportError:
    # Supports `uvicorn main:app` when the working directory is backend/.
    import db  # type: ignore[no-redef]
    import simulation  # type: ignore[no-redef]
    import ward  # type: ignore[no-redef]
    from layers import (layer1_vitals, layer1b_heuristics, layer2_symptom_nlp, layer2b_labs,
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
        self.beds: list[ward.Bed] = []
        self.clinicians: list[ward.Clinician] = []
        self.events: list[dict[str, Any]] = []
        self.reset()

    # ---------------------------------------------------------------- state
    def reset(self) -> None:
        self.conn = db.init(reset=True)
        self.patients = simulation.build_scenario()
        self.sim_minutes = 0.0
        self.beds, self.clinicians = ward.build_roster()
        self.events = []
        self.voice_seq = 0    # counts Voice Intake patients created this shift
        self.intake_seq = 0   # counts structured-intake patients this shift
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
                "nursing_assessment": p.nursing_assessment,
                "status": p.status, "assigned_esi": p.assigned_esi})

    def log(self, kind: str, text: str, patient: str | None = None) -> None:
        self.events.insert(0, {"at": datetime.now().strftime("%H:%M:%S"), "kind": kind,
                               "text": text, "patient": patient})
        del self.events[40:]

    # ------------------------------------------------------------- pipeline
    def score_patient(self, p: simulation.SimPatient) -> dict[str, Any] | None:
        symptom = layer2_symptom_nlp.score(
            p.complaint or "", p.nursing_assessment or "")
        vitals_raw = p.vitals_at(self.sim_minutes)
        sirs_data = layer1b_heuristics.evaluate_sirs(vitals_raw or {}, p.lab_results)
        vitals_out = layer1_vitals.score(vitals_raw) if vitals_raw else None
        fused = layer3_fusion.fuse(vitals_out, symptom, p.age, p.lab_out, sirs_data)

        # Persist a score when it actually says something new, or every few
        # simulated minutes. Writing one row per tick would bury the trajectory
        # in noise; Layer 4 needs spaced observations, not a high-frequency log.
        prev = db.last_score(self.conn, p.id)
        if (prev is None or prev["ari"] != fused["ari"]
                or self.sim_minutes - prev["at"] >= 4.0):
            db.append_score(self.conn, p.id, self.sim_minutes, fused,
                            {"vitals": vitals_raw, "vitals_out": vitals_out,
                             "symptom": symptom, "labs": p.lab_out,
                             "sirs": sirs_data})

        history = db.score_history(self.conn, p.id)
        waited = (self.sim_minutes - (p.arrived_at_min or 0))
        trend = layer4_deterioration.assess(history, waited)
        systems = symptom["systems"]
        routing = layer5_routing.route(fused["esi"], systems, self.beds, self.clinicians)

        return {"fused": fused, "vitals": vitals_raw, "vitals_out": vitals_out,
                "symptom": symptom, "sirs": sirs_data, "trend": trend, "routing": routing,
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

            # New patient with no acuity yet -> initial recommendation.
            # Waiting-room only: an in-treatment patient already has one.
            if (p.status == "waiting" and p.assigned_esi is None
                    and p.last_recommendation is None):
                rid = db.add_recommendation(
                    self.conn, p.id, t, "initial", res["fused"]["esi"],
                    res["routing"]["pathway"], res["routing"]["specialty"],
                    _rationale(res))
                p.last_recommendation = rid
                self.log("recommend",
                         f"{p.display_id}: recommend ESI {res['fused']['esi']} "
                         f"→ {res['routing']['pathway']}", p.display_id)

            # Already triaged, but trajectory says otherwise -> re-triage.
            # Deliberately not gated to "waiting": Layer 4 re-scores admitted
            # patients too, and a patient crashing on the ward after being
            # placed is the case that matters more, not less, than one still
            # in the waiting room. Accepting this recommendation reassigns
            # them to a new bed — see Engine.decide().
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
        """Accept or override a recommendation — and, per the same action,
        commit to the specific bed and clinician Layer 5 suggested for it.
        This is the one place `assigned_esi` is written, and now also the
        one place a bed goes from 'available' to 'occupied': the human
        decision gate and the resource commitment are the same click.
        """
        p = next((x for x in self.patients if x.id == patient_id), None)
        if p is None or p.last_recommendation is None:
            return {"ok": False, "error": "no open recommendation"}

        res = getattr(p, "_last", None)
        rec_esi = res["fused"]["esi"] if res else "III"
        final = rec_esi if action == "accept" else (override_esi or "III")

        db.resolve(self.conn, p.last_recommendation, p.id, self.sim_minutes,
                   action, final)
        p.assigned_esi = final

        # An override to a different acuity can change the pathway (a nurse
        # downgrading to ESI IV should route to fast track, not resus), so
        # the routing used for accept isn't automatically valid for
        # override — recompute it against the ESI actually being committed
        # to rather than reusing the one Layer 3 recommended.
        if res and action == "accept":
            routing = res["routing"]
        elif res:
            routing = layer5_routing.route(
                final, res["symptom"]["systems"], self.beds, self.clinicians)
        else:
            routing = None

        p.last_recommendation = None
        bed_note = "no bed currently free"
        if routing:
            p.pathway, p.specialty = routing["pathway"], routing["specialty"]
            # Re-escalating an already-admitted patient: free whatever they
            # occupy before claiming the new assignment, not after — a
            # patient is never double-booked mid-transition.
            ward.release_bed_for(self.beds, p.id)
            ward.release_clinician_for(self.clinicians, p.id)
            if routing["suggested_bed"]:
                ward.assign_bed(self.beds, routing["suggested_bed"], p.id)
                bed_note = f"bed {routing['suggested_bed']} assigned"
            if routing["suggested_clinician"]:
                ward.assign_clinician(self.clinicians, routing["suggested_clinician"], p.id)

        verb = "accepted" if action == "accept" else f"overrode to ESI {final}"
        self.log("decision", f"Nurse {verb} for {p.display_id} — {bed_note}",
                 p.display_id)
        return {"ok": True, "final_esi": final, "pathway": p.pathway,
                "bed": routing["suggested_bed"] if routing else None}

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

        # nlp_llm.extract_voice_intake() already refuses to return a result
        # with no complaint_summary, so this is never the original-language
        # transcript falling through untranslated — see its docstring for
        # why that distinction is the whole point of this code path.
        complaint = raw["complaint_summary"]

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
            "nursing_assessment": p.nursing_assessment,
            "status": p.status, "assigned_esi": p.assigned_esi})

        self.log("voice", f"{display_id}: voice intake ({lang} via "
                 f"{provider or 'llm'}) — “{complaint}”", display_id)
        return {"ok": True, "id": pid, "display_id": display_id,
                "complaint": complaint, "age": age, "vitals": vitals,
                "provider": provider}

    # ------------------------------------------------------------ intake form
    def create_intake_patient(self, body: "IntakeIn",
                              lab_out: dict[str, Any] | None = None) -> dict[str, Any]:
        """The reviewed intake form — personal details, dictated complaint,
        manually entered vitals, and any lab results pulled from a PDF —
        becomes a live, queued patient the instant a nurse submits it, not a
        one-off number handed back to a form. Same Engine, same board, same
        Layer 4 re-scoring loop as every other arrival: this is what "triage
        decided simultaneously, ARI calculated, queue precedence decided"
        means in code, not just in the sentence describing the feature.
        """
        complaint = body.presentation.complaint.strip()
        nursing_assessment = body.presentation.nursing_assessment.strip()
        vitals = {k: v for k, v in body.vitals.items() if isinstance(v, (int, float))}
        labs = body.laboratory.test_results if body.laboratory else []
        if not complaint and not nursing_assessment and not vitals and not labs:
            return {"ok": False, "error": ("Nothing to submit — enter a complaint, "
                    "vitals, or lab results first.")}

        self.intake_seq += 1
        pid, display_id = f"intake{self.intake_seq:02d}", f"PT I{self.intake_seq}"
        age = body.personal_details.age_years
        name = body.personal_details.name if body.personal_details.name else display_id
        sex = body.personal_details.sex or None
        reg_no = body.personal_details.registration_no or None
        ref_by = body.personal_details.referred_by or None
        rep_date = body.personal_details.report_date or None
        raw_json = body.model_dump_json() if hasattr(body, "model_dump_json") else None

        p = simulation.SimPatient(
            id=pid, display_id=display_id, age=age, arrival_mode="walk-in",
            name=name, sex=sex, registration_no=reg_no, referred_by=ref_by,
            report_date=rep_date, raw_intake=raw_json, complaint=complaint,
            nursing_assessment=nursing_assessment,
            arrive_min=self.sim_minutes,
            timeline=[simulation.VitalsPoint(0.0, vitals)], lab_out=lab_out,
            lab_results=labs)
        p.status = "waiting"
        p.arrived_at_min = self.sim_minutes
        self.patients.append(p)

        db.add_patient(self.conn, {
            "id": p.id, "display_id": p.display_id, "age": p.age,
            "arrival_mode": p.arrival_mode, "complaint": p.complaint,
            "transcript": p.transcript, "arrived_at": p.arrived_at_min,
            "status": p.status, "assigned_esi": p.assigned_esi,
            "name": p.name, "sex": p.sex, "registration_no": p.registration_no,
            "referred_by": p.referred_by, "report_date": p.report_date,
            "raw_intake": p.raw_intake, "lab_results": p.lab_results})

        # Score immediately rather than waiting for the next tick, so the
        # nurse who just submitted the form sees the real ARI/queue position
        # in the same response instead of a blank row for up to a second.
        res = self.score_patient(p)
        p._last = res  # noqa: SLF001

        self.log("intake", f"{display_id}: structured intake submitted"
                 + (f" — ARI {res['fused']['ari']}" if res else ""), display_id)
        return {"ok": True, "id": pid, "display_id": display_id,
                "ari": res["fused"]["ari"] if res else None,
                "esi": res["fused"]["esi"] if res else None,
                "confidence": res["fused"]["confidence"] if res else None,
                "lab_evaluation": lab_out}

    # --------------------------------------------------------------- output
    def board(self) -> dict[str, Any]:
        rows = []
        for p in self.patients:
            res = getattr(p, "_last", None)
            if p.status in ("inbound", "discharged"):
                continue
            if res is None:
                continue
            rows.append({
                "id": p.id, "display_id": p.display_id, "age": p.age,
                "name": getattr(p, "name", None), "sex": getattr(p, "sex", None),
                "registration_no": getattr(p, "registration_no", None),
                "lab_results": getattr(p, "lab_results", []),
                "medications": db.get_medications(self.conn, p.id),
                "clinical_notes": db.get_clinical_notes(self.conn, p.id),
                "complaint": p.complaint, "transcript": p.transcript,
                "nursing_assessment": p.nursing_assessment,
                "arrival_mode": p.arrival_mode,
                "status": p.status, "assigned_esi": p.assigned_esi,
                "ari": res["fused"]["ari"], "esi": res["fused"]["esi"],
                "lab_evaluation": res["fused"]["components"].get("labs"),
                "sirs": res["fused"]["components"].get("sirs"),
                "synergy_matched": res["fused"]["components"].get("synergy_matched"),
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
            "rows": rows,
            "capacity": ward.capacity_summary(self.beds, self.clinicians),
            # Full roster, not just the aggregate above — the Ward Map page
            # needs individual identities and statuses to draw its
            # colour-coded boxes; the dashboard's Department State panel
            # keeps reading the aggregate, so nothing there has to change.
            "beds": [{"id": b.id, "ward": b.ward, "status": b.status,
                      "patient_id": b.patient_id} for b in self.beds],
            "clinicians": [{"id": c.id, "name": c.name, "specialty": c.specialty,
                            "status": c.status, "patient_id": c.patient_id}
                           for c in self.clinicians],
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


class MedicationIn(BaseModel):
    medication_name: str
    dosage: str = ""
    scheduled_time: str = ""
    notes: str = ""


class MedicationUpdateIn(BaseModel):
    status: Literal["scheduled", "given", "held", "cancelled"]
    given_at: str | None = None


class ClinicalNoteIn(BaseModel):
    note_type: Literal["surgical", "follow_up"]
    content: str


class DischargeIn(BaseModel):
    discharge_summary: str
    follow_up_instructions: str = ""
    discharge_date_time: str | None = None


class ProfileUpdateIn(BaseModel):
    name: str | None = None
    age: int | None = None
    sex: str | None = None
    registration_no: str | None = None
    referred_by: str | None = None
    report_date: str | None = None
    complaint: str | None = None
    nursing_assessment: str | None = None
    raw_intake: str | None = None
    lab_results: list[dict[str, Any]] | None = None
    labs: list[dict[str, Any]] | None = None
    medications: list[dict[str, Any]] | None = None
    vitals: dict[str, Any] | None = None
    ari: int | None = Field(default=None, ge=0, le=100)
    esi: str | None = None
    pathway: str | None = None
    bed_id: str | None = None
    clinician_id: str | None = None


class MedicationScheduleIn(BaseModel):
    patient_id: str
    name: str
    schedule_time: str = ""
    frequency: str = ""
    instructions: str = ""


class EmergencyMedicationIn(BaseModel):
    patient_id: str
    name: str
    given_date: str = ""
    given_time: str = ""
    remarks: str = ""


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
    symptom = layer2_symptom_nlp.score(body.complaint, body.nursing_assessment)
    vitals = dict(body.vitals)
    vitals["age"] = body.age_years
    vitals["arrival_mode"] = "walk-in"
    vitals_out = layer1_vitals.score(vitals)
    lab_out = await asyncio.to_thread(layer2b_labs.evaluate_labs, body.test_results)
    sirs_data = layer1b_heuristics.evaluate_sirs(vitals, body.test_results)
    fused = layer3_fusion.fuse(vitals_out, symptom, body.age_years, lab_out, sirs_data)
    return JSONResponse({"ari": fused["ari"], "esi": fused["esi"],
                         "confidence": fused["confidence"],
                         "lab_evaluation": lab_out,
                         "sirs": fused["components"].get("sirs")})


@app.post("/api/intake")
async def api_intake(body: IntakeIn):
    """Submit the complete, reviewed patient intake — creates a live,
    queued patient on the board (see Engine.create_intake_patient) rather
    than only returning a preview number."""
    labs = body.laboratory.test_results if body.laboratory else []
    lab_out = await asyncio.to_thread(layer2b_labs.evaluate_labs, labs)
    out = engine.create_intake_patient(body, lab_out)
    if out.get("ok"):
        await engine.broadcast()
    return JSONResponse(out)


@app.get("/api/patients/search")
async def api_search_patients(q: str = ""):
    return JSONResponse(db.search_patients(engine.conn, q.strip()) if q.strip() else [])


def _profile_payload(patient_id: str) -> dict[str, Any]:
    patient = _patient_or_404(patient_id)
    stored = db.get_patient(engine.conn, patient_id) or {}
    score = db.latest_score(engine.conn, patient_id) or {}
    score_payload = score.get("payload") or {}
    assigned_bed = next((b for b in engine.beds if b.patient_id == patient_id), None)
    assigned_clinician = next((c for c in engine.clinicians if c.patient_id == patient_id), None)
    try:
        stored_labs = json.loads(stored.get("lab_results") or "[]")
    except (TypeError, json.JSONDecodeError):
        stored_labs = []
    return {
        **stored,
        "id": patient.id,
        "display_id": patient.display_id,
        "age": patient.age,
        "name": patient.name or stored.get("name") or patient.display_id,
        "status": patient.status,
        "nursing_assessment": patient.nursing_assessment or stored.get("nursing_assessment"),
        "lab_results": patient.lab_results or stored_labs,
        "vitals": score_payload.get("vitals") or {},
        "ari": score.get("ari"), "esi": score.get("esi"),
        "confidence": score.get("confidence"),
        "ward": {"bed": assigned_bed.id if assigned_bed else None,
                 "bed_ward": assigned_bed.ward if assigned_bed else None,
                 "clinician": assigned_clinician.id if assigned_clinician else None,
                 "clinician_name": assigned_clinician.name if assigned_clinician else None},
        "medications": db.get_medications(engine.conn, patient_id),
        "clinical_notes": db.get_clinical_notes(engine.conn, patient_id),
    }


@app.get("/api/patients/{patient_id}/profile")
async def api_patient_profile(patient_id: str):
    return JSONResponse(_profile_payload(patient_id))


@app.patch("/api/patients/{patient_id}/profile")
async def api_update_patient_profile(patient_id: str, body: ProfileUpdateIn):
    patient = _patient_or_404(patient_id)
    data = body.model_dump(exclude_unset=True)
    if "labs" in data and "lab_results" not in data:
        data["lab_results"] = data["labs"]
    db.update_patient_profile(engine.conn, patient_id, data)
    if "medications" in data:
        db.replace_medications(engine.conn, patient_id, data["medications"] or [])
    for field in ("name", "age", "sex", "registration_no", "referred_by", "report_date",
                  "complaint", "nursing_assessment", "raw_intake", "lab_results", "pathway"):
        if field in data:
            setattr(patient, field if field != "age" else "age", data[field])
    if "lab_results" in data:
        patient.lab_results = data["lab_results"] or []
    if "ari" in data or "esi" in data:
        current = db.latest_score(engine.conn, patient_id) or {}
        current_payload = current.get("payload") or {}
        db.add_score_override(engine.conn, patient_id, data.get("ari", current.get("ari", 0)),
                      data.get("esi", current.get("esi", "V")),
                      {"vitals": data.get("vitals", current_payload.get("vitals", {}))})
    if "bed_id" in data:
        ward.release_bed_for(engine.beds, patient_id)
        if data["bed_id"]:
            ward.assign_bed(engine.beds, data["bed_id"], patient_id)
    if "clinician_id" in data:
        ward.release_clinician_for(engine.clinicians, patient_id)
        if data["clinician_id"]:
            ward.assign_clinician(engine.clinicians, data["clinician_id"], patient_id)
    await engine.broadcast()
    return JSONResponse({"ok": True, "profile": _profile_payload(patient_id)})


def _patient_or_404(patient_id: str) -> simulation.SimPatient:
    patient = next((item for item in engine.patients if item.id == patient_id), None)
    if patient is None:
        raise HTTPException(status_code=404, detail="Patient not found")
    return patient


@app.post("/api/patients/{patient_id}/medications")
async def api_add_medication(patient_id: str, body: MedicationIn):
    _patient_or_404(patient_id)
    if not body.medication_name.strip():
        raise HTTPException(status_code=422, detail="Medication name is required")
    medication_id = db.add_medication(engine.conn, {
        "patient_id": patient_id,
        "medication_name": body.medication_name.strip(),
        "dosage": body.dosage.strip(),
        "scheduled_time": body.scheduled_time.strip(),
        "notes": body.notes.strip(),
    })
    await engine.broadcast()
    return JSONResponse({"ok": True, "id": medication_id})


@app.post("/api/medications/schedule")
async def api_schedule_medication(body: MedicationScheduleIn):
    _patient_or_404(body.patient_id)
    medication_id = db.add_medication(engine.conn, {
        "patient_id": body.patient_id, "medication_name": body.name,
        "dosage": body.frequency, "scheduled_time": body.schedule_time,
        "notes": body.instructions,
    })
    return JSONResponse({"ok": True, "id": medication_id})


@app.post("/api/medications/emergency")
async def api_emergency_medication(body: EmergencyMedicationIn):
    _patient_or_404(body.patient_id)
    medication_id = db.add_medication(engine.conn, {
        "patient_id": body.patient_id, "medication_name": body.name,
        "status": "given", "given_at": f"{body.given_date} {body.given_time}".strip(),
        "notes": body.remarks,
    })
    return JSONResponse({"ok": True, "id": medication_id})


@app.patch("/api/medications/{med_id}")
async def api_update_medication(med_id: int, body: MedicationUpdateIn):
    given_at = body.given_at or (datetime.now().isoformat() if body.status == "given" else None)
    if not db.update_medication_status(engine.conn, med_id, body.status, given_at):
        raise HTTPException(status_code=404, detail="Medication not found")
    await engine.broadcast()
    return JSONResponse({"ok": True})


@app.patch("/api/medications/{med_id}/given")
async def api_mark_medication_given(med_id: int):
    if not db.update_medication_status(engine.conn, med_id, "given", datetime.now().isoformat()):
        raise HTTPException(status_code=404, detail="Medication not found")
    await engine.broadcast()
    return JSONResponse({"ok": True})


@app.post("/api/patients/{patient_id}/notes")
async def api_add_clinical_note(patient_id: str, body: ClinicalNoteIn):
    _patient_or_404(patient_id)
    if not body.content.strip():
        raise HTTPException(status_code=422, detail="Note content is required")
    note_id = db.add_clinical_note(engine.conn, {
        "patient_id": patient_id,
        "note_type": body.note_type,
        "content": body.content.strip(),
        "created_at": datetime.now().isoformat(),
    })
    await engine.broadcast()
    return JSONResponse({"ok": True, "id": note_id})


@app.post("/api/discharge/{patient_id}")
async def api_discharge(patient_id: str, body: DischargeIn):
    patient = _patient_or_404(patient_id)
    if not body.discharge_summary.strip():
        raise HTTPException(status_code=422, detail="Discharge summary is required")
    now = datetime.now().isoformat()
    db.add_clinical_note(engine.conn, {
        "patient_id": patient_id, "note_type": "discharge_summary",
        "content": body.discharge_summary.strip(), "created_at": now,
    })
    if body.follow_up_instructions.strip():
        db.add_clinical_note(engine.conn, {
            "patient_id": patient_id, "note_type": "follow_up",
            "content": body.follow_up_instructions.strip(), "created_at": now,
        })
    patient.status = "discharged"
    ward.release_bed_for(engine.beds, patient_id)
    ward.release_clinician_for(engine.clinicians, patient_id)
    await engine.broadcast()
    return JSONResponse({"ok": True, "patient_id": patient_id, "status": patient.status})


class WardStatusIn(BaseModel):
    status: str


@app.post("/api/ward/beds/{bed_id}/status")
async def api_bed_status(bed_id: str, body: WardStatusIn):
    """Direct staff update to a bed's status — the real-time bedding feed
    requirement. Deliberately can't set 'occupied' this way: that only ever
    happens through Engine.decide(), tied to the patient it belongs to, so a
    bed can never show occupied without a patient record behind it."""
    ok = ward.set_bed_status(engine.beds, bed_id, body.status)
    if ok:
        await engine.broadcast()
    return JSONResponse({"ok": ok})


@app.post("/api/ward/clinicians/{clinician_id}/status")
async def api_clinician_status(clinician_id: str, body: WardStatusIn):
    ok = ward.set_clinician_status(engine.clinicians, clinician_id, body.status)
    if ok:
        await engine.broadcast()
    return JSONResponse({"ok": ok})


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



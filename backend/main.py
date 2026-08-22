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
import os
import time
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import db, simulation
from .layers import (layer0_prearrival, layer1_vitals, layer2_symptom_nlp,
                     layer3_fusion, layer4_deterioration, layer5_routing)

HERE = os.path.dirname(os.path.abspath(__file__))
FRONTEND = os.path.join(HERE, "..", "frontend")

TICK_SECONDS = 1.0          # wall-clock cadence of the scheduler
START_CLOCK = 17 * 60 + 42  # the shift starts at 17:42, as in the film

app = FastAPI(title="PULSE", version="0.1.0")


class Engine:
    """Owns simulation state, the scoring pipeline and connected clients."""

    def __init__(self) -> None:
        self.conn = db.init(reset=True)
        self.patients: list[simulation.SimPatient] = []
        self.sim_minutes = 0.0
        self.speed = 60
        self.running = True
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
        self.events.insert(0, {"at": self.clock(), "kind": kind,
                               "text": text, "patient": patient})
        del self.events[40:]

    def clock(self) -> str:
        total = int(START_CLOCK + self.sim_minutes)
        return f"{(total // 60) % 24:02d}:{total % 60:02d}"

    # ------------------------------------------------------------- pipeline
    def score_patient(self, p: simulation.SimPatient) -> dict[str, Any] | None:
        symptom = layer2_symptom_nlp.score(p.complaint or "")
        vitals_raw = p.vitals_at(self.sim_minutes)
        vitals_out = layer1_vitals.score(vitals_raw) if vitals_raw else None
        prior = p.prior["prior"] if p.prior else None

        fused = layer3_fusion.fuse(vitals_out, symptom, prior, p.age)

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
        systems = sorted(set(symptom["systems"]) |
                         set(p.prior["systems"] if p.prior else []))
        routing = layer5_routing.route(fused["esi"], systems, self.capacity)

        return {"fused": fused, "vitals": vitals_raw, "vitals_out": vitals_out,
                "symptom": symptom, "trend": trend, "routing": routing,
                "history": history, "waited": waited}

    # ----------------------------------------------------------------- tick
    async def tick(self) -> None:
        if not self.running:
            return
        self.sim_minutes += (self.speed * TICK_SECONDS) / 60.0
        t = self.sim_minutes

        for p in self.patients:
            # Layer 0 fires before arrival for anyone who called ahead.
            if (p.transcript and p.prior is None
                    and p.prearrival_min is not None and t >= p.prearrival_min):
                p.prior = layer0_prearrival.score(p.transcript, p.arrival_mode)
                self.log("layer0",
                         f"Pre-arrival prior {p.prior['prior']} "
                         f"({p.prior['confidence']} confidence) — "
                         f"{len(p.prior['actions'])} resources pre-positioned",
                         p.display_id)

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

    # --------------------------------------------------------------- output
    def board(self) -> dict[str, Any]:
        rows, inbound = [], []
        for p in self.patients:
            res = getattr(p, "_last", None)
            if p.status == "inbound":
                inbound.append({
                    "id": p.id, "display_id": p.display_id, "age": p.age,
                    "eta_min": round(max(0.0, p.arrive_min - self.sim_minutes), 1),
                    "complaint": p.complaint, "transcript": p.transcript,
                    "prior": p.prior})
                continue
            if res is None:
                continue
            rows.append({
                "id": p.id, "display_id": p.display_id, "age": p.age,
                "complaint": p.complaint, "arrival_mode": p.arrival_mode,
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
                "prior": p.prior,
            })

        order = {"I": 0, "II": 1, "III": 2, "IV": 3, "V": 4, None: 5}
        rows.sort(key=lambda r: (order.get(r["assigned_esi"] or r["esi"], 5), -r["ari"]))
        inbound.sort(key=lambda r: r["eta_min"])

        return {
            "clock": self.clock(), "sim_minutes": round(self.sim_minutes, 1),
            "speed": self.speed, "running": self.running,
            "rows": rows, "inbound": inbound, "capacity": self.capacity,
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


@app.post("/api/admit/{patient_id}")
async def api_admit(patient_id: str):
    out = engine.admit(patient_id)
    await engine.broadcast()
    return JSONResponse(out)


@app.post("/api/control/{what}")
async def api_control(what: str, value: str | None = None):
    if what == "speed" and value:
        engine.speed = simulation.SPEEDS.get(value, 60)
    elif what == "pause":
        engine.running = not engine.running
    elif what == "reset":
        engine.reset()
    await engine.broadcast()
    return JSONResponse({"ok": True, "speed": engine.speed,
                         "running": engine.running})


@app.get("/api/audit")
async def api_audit():
    return JSONResponse({"decisions": db.audit(engine.conn),
                         "agreement": db.agreement_rate(engine.conn)})


@app.get("/api/model")
async def api_model():
    return JSONResponse(layer1_vitals.model_metrics())


app.mount("/static", StaticFiles(directory=FRONTEND), name="static")


@app.get("/")
async def index():
    return FileResponse(os.path.join(FRONTEND, "index.html"))

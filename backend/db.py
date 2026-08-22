"""SQLite persistence.

One design decision matters more than the rest: the scores table is
APPEND-ONLY. A score is never updated in place, because the sequence of scores
IS the trajectory Layer 4 reasons over. Overwrite a score and you have thrown
away the thing that makes PULSE different from one-shot triage.

The overrides table is the other half of the governance story: every time the
nurse disagrees with a recommendation, that disagreement is recorded — as a
legal audit trail, and as the training signal that keeps the model honest.
"""
from __future__ import annotations

import json
import os
import sqlite3
from typing import Any

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "pulse.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS patients (
    id TEXT PRIMARY KEY,
    display_id TEXT NOT NULL,
    age INTEGER,
    arrival_mode TEXT,
    complaint TEXT,
    transcript TEXT,
    arrived_at REAL,
    status TEXT DEFAULT 'waiting',
    assigned_esi TEXT,
    pathway TEXT,
    specialty TEXT
);
CREATE TABLE IF NOT EXISTS scores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id TEXT NOT NULL,
    at REAL NOT NULL,
    ari INTEGER NOT NULL,
    esi TEXT,
    confidence TEXT,
    payload TEXT,
    FOREIGN KEY (patient_id) REFERENCES patients(id)
);
CREATE TABLE IF NOT EXISTS recommendations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id TEXT NOT NULL,
    at REAL NOT NULL,
    kind TEXT NOT NULL,
    recommended_esi TEXT,
    pathway TEXT,
    specialty TEXT,
    rationale TEXT,
    resolved TEXT
);
CREATE TABLE IF NOT EXISTS decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    recommendation_id INTEGER,
    patient_id TEXT NOT NULL,
    at REAL NOT NULL,
    action TEXT NOT NULL,
    final_esi TEXT,
    actor TEXT DEFAULT 'triage nurse'
);
CREATE INDEX IF NOT EXISTS idx_scores_patient ON scores(patient_id, at);
"""


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init(reset: bool = False) -> sqlite3.Connection:
    conn = connect()
    if reset:
        for table in ("decisions", "recommendations", "scores", "patients"):
            conn.execute(f"DROP TABLE IF EXISTS {table}")
        conn.commit()
    conn.executescript(SCHEMA)
    conn.commit()
    return conn

def add_patient(conn, p: dict[str, Any]) -> None:
    conn.execute(
        """INSERT OR REPLACE INTO patients
           (id, display_id, age, arrival_mode, complaint, transcript, arrived_at,
            status, assigned_esi, pathway, specialty)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (p["id"], p["display_id"], p.get("age"), p.get("arrival_mode"),
         p.get("complaint"), p.get("transcript"), p.get("arrived_at"),
         p.get("status", "waiting"), p.get("assigned_esi"),
         p.get("pathway"), p.get("specialty")))
    conn.commit()


def append_score(conn, patient_id: str, at: float, fused: dict, payload: dict) -> None:
    conn.execute(
        "INSERT INTO scores (patient_id, at, ari, esi, confidence, payload) VALUES (?,?,?,?,?,?)",
        (patient_id, at, fused["ari"], fused["esi"], fused["confidence"],
         json.dumps(payload)))
    conn.commit()


def last_score(conn, patient_id: str) -> dict | None:
    row = conn.execute(
        "SELECT at, ari FROM scores WHERE patient_id=? ORDER BY at DESC LIMIT 1",
        (patient_id,)).fetchone()
    return dict(row) if row else None


def score_history(conn, patient_id: str, limit: int = 12) -> list[dict]:
    rows = conn.execute(
        "SELECT at, ari, esi, confidence FROM scores WHERE patient_id=? ORDER BY at ASC",
        (patient_id,)).fetchall()
    return [dict(r) for r in rows][-limit:]


def add_recommendation(conn, patient_id: str, at: float, kind: str,
                       esi: str, pathway: str, specialty: str, rationale: str) -> int:
    cur = conn.execute(
        """INSERT INTO recommendations
           (patient_id, at, kind, recommended_esi, pathway, specialty, rationale, resolved)
           VALUES (?,?,?,?,?,?,?,NULL)""",
        (patient_id, at, kind, esi, pathway, specialty, rationale))
    conn.commit()
    return int(cur.lastrowid)


def resolve(conn, rec_id: int, patient_id: str, at: float,
            action: str, final_esi: str) -> None:
    conn.execute("UPDATE recommendations SET resolved=? WHERE id=?", (action, rec_id))
    conn.execute(
        "INSERT INTO decisions (recommendation_id, patient_id, at, action, final_esi) VALUES (?,?,?,?,?)",
        (rec_id, patient_id, at, action, final_esi))
    conn.commit()


def audit(conn, limit: int = 60) -> list[dict]:
    rows = conn.execute(
        """SELECT d.at, d.action, d.final_esi, d.actor, r.kind, r.recommended_esi,
                  r.rationale, p.display_id
           FROM decisions d
           JOIN recommendations r ON r.id = d.recommendation_id
           JOIN patients p ON p.id = d.patient_id
           ORDER BY d.at DESC LIMIT ?""", (limit,)).fetchall()
    return [dict(r) for r in rows]


def agreement_rate(conn) -> dict[str, Any]:
    """Shadow-mode metric: how often does the nurse agree with PULSE?

    This is the number that decides whether a tool like this is ever allowed to
    go live, so we surface it from day one rather than bolting it on later.
    """
    rows = conn.execute("SELECT action FROM decisions").fetchall()
    total = len(rows)
    accepted = sum(1 for r in rows if r["action"] == "accept")
    return {"total": total, "accepted": accepted,
            "rate": round(accepted / total, 3) if total else None}

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
import time
from typing import Any

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "pulse.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS patients (
    id TEXT PRIMARY KEY,
    display_id TEXT NOT NULL,
    age INTEGER,
    arrival_mode TEXT,
    complaint TEXT,
    nursing_assessment TEXT,
    transcript TEXT,
    arrived_at REAL,
    status TEXT DEFAULT 'waiting',
    assigned_esi TEXT,
    pathway TEXT,
    specialty TEXT,
    name TEXT,
    sex TEXT,
    registration_no TEXT,
    referred_by TEXT,
    report_date TEXT,
    raw_intake TEXT,
    lab_results TEXT
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
CREATE TABLE IF NOT EXISTS medications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id TEXT,
    medication_name TEXT,
    dosage TEXT,
    scheduled_time TEXT,
    status TEXT DEFAULT 'scheduled',
    given_at TEXT,
    notes TEXT
);
CREATE TABLE IF NOT EXISTS clinical_notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id TEXT,
    note_type TEXT,
    content TEXT,
    created_at TEXT
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
        for table in ("clinical_notes", "medications", "decisions", "recommendations", "scores", "patients"):
            conn.execute(f"DROP TABLE IF EXISTS {table}")
        conn.commit()
    conn.executescript(SCHEMA)
    conn.commit()
    return conn

def add_patient(conn, p: dict[str, Any]) -> None:
    conn.execute(
        """INSERT OR REPLACE INTO patients
           (id, display_id, age, arrival_mode, complaint, transcript, arrived_at,
                                nursing_assessment, status, assigned_esi, pathway, specialty, name, sex, registration_no,
                referred_by, report_date, raw_intake, lab_results)
                            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
          (p.get("id"), p.get("display_id"), p.get("age"), p.get("arrival_mode"),
                 p.get("complaint"), p.get("transcript"), p.get("arrived_at"), p.get("nursing_assessment"),
         p.get("status", "waiting"), p.get("assigned_esi"),
            p.get("pathway"), p.get("specialty"), p.get("name"), p.get("sex"),
            p.get("registration_no"), p.get("referred_by"), p.get("report_date"),
            p.get("raw_intake"),
            json.dumps(p.get("lab_results")) if p.get("lab_results") else None))
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


def add_medication(conn, data: dict[str, Any]) -> int:
    cur = conn.execute(
        """INSERT INTO medications
           (patient_id, medication_name, dosage, scheduled_time, status, given_at, notes)
           VALUES (?,?,?,?,?,?,?)""",
        (data.get("patient_id"), data.get("medication_name"), data.get("dosage"),
         data.get("scheduled_time"), data.get("status", "scheduled"),
         data.get("given_at"), data.get("notes")),
    )
    conn.commit()
    return int(cur.lastrowid)


def update_medication_status(conn, med_id: int, status: str,
                             given_at: str | None) -> bool:
    cur = conn.execute(
        "UPDATE medications SET status=?, given_at=? WHERE id=?",
        (status, given_at, med_id),
    )
    conn.commit()
    return cur.rowcount > 0


def get_medications(conn, patient_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT id, patient_id, medication_name, dosage, scheduled_time, status, given_at, notes "
        "FROM medications WHERE patient_id=? ORDER BY scheduled_time, id",
        (patient_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def replace_medications(conn, patient_id: str, medications: list[dict[str, Any]]) -> None:
    """Replace a patient's medication draft while preserving existing rows when possible."""
    existing = {row["id"] for row in conn.execute(
        "SELECT id FROM medications WHERE patient_id=?", (patient_id,)
    ).fetchall()}
    kept: set[int] = set()
    for medication in medications:
        medication_id = medication.get("id")
        values = (medication.get("medication_name") or medication.get("name"),
                  medication.get("dosage") or medication.get("frequency"),
                  medication.get("scheduled_time") or medication.get("schedule_time"),
                  medication.get("status", "scheduled"), medication.get("given_at"),
                  medication.get("notes") or medication.get("instructions"))
        if medication_id in existing:
            conn.execute(
                "UPDATE medications SET medication_name=?, dosage=?, scheduled_time=?, status=?, given_at=?, notes=? WHERE id=? AND patient_id=?",
                (*values, medication_id, patient_id),
            )
            kept.add(medication_id)
        else:
            conn.execute(
                "INSERT INTO medications (patient_id, medication_name, dosage, scheduled_time, status, given_at, notes) VALUES (?,?,?,?,?,?,?)",
                (patient_id, *values),
            )
    stale = existing - kept
    if stale:
        conn.executemany("DELETE FROM medications WHERE id=? AND patient_id=?",
                         [(medication_id, patient_id) for medication_id in stale])
    conn.commit()


def add_clinical_note(conn, data: dict[str, Any]) -> int:
    cur = conn.execute(
        "INSERT INTO clinical_notes (patient_id, note_type, content, created_at) VALUES (?,?,?,?)",
        (data.get("patient_id"), data.get("note_type"), data.get("content"),
         data.get("created_at")),
    )
    conn.commit()
    return int(cur.lastrowid)


def get_clinical_notes(conn, patient_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT id, patient_id, note_type, content, created_at "
        "FROM clinical_notes WHERE patient_id=? ORDER BY created_at DESC, id DESC",
        (patient_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def get_patient(conn, patient_id: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM patients WHERE id=?", (patient_id,)).fetchone()
    return dict(row) if row else None


def search_patients(conn, query: str) -> list[dict[str, Any]]:
    term = f"%{query}%"
    rows = conn.execute(
        "SELECT id, display_id, name, age, sex, registration_no, status, complaint "
        "FROM patients WHERE display_id LIKE ? OR name LIKE ? ORDER BY display_id",
        (term, term),
    ).fetchall()
    return [dict(row) for row in rows]


def update_patient_profile(conn, patient_id: str, data: dict[str, Any]) -> bool:
    allowed = {"name", "age", "sex", "registration_no", "referred_by",
               "report_date", "complaint", "nursing_assessment", "raw_intake",
               "lab_results", "pathway", "specialty"}
    values = {key: value for key, value in data.items() if key in allowed}
    if not values:
        return get_patient(conn, patient_id) is not None
    if "lab_results" in values:
        values["lab_results"] = json.dumps(values["lab_results"]) if values["lab_results"] else None
    assignments = ", ".join(f"{key}=?" for key in values)
    cur = conn.execute(
        f"UPDATE patients SET {assignments} WHERE id=?",
        (*values.values(), patient_id),
    )
    conn.commit()
    return cur.rowcount > 0


def latest_score(conn, patient_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT at, ari, esi, confidence, payload FROM scores "
        "WHERE patient_id=? ORDER BY at DESC, id DESC LIMIT 1", (patient_id,)
    ).fetchone()
    if not row:
        return None
    result = dict(row)
    try:
        result["payload"] = json.loads(result["payload"] or "{}")
    except (TypeError, json.JSONDecodeError):
        result["payload"] = {}
    return result


def add_score_override(conn, patient_id: str, ari: int, esi: str,
                       payload: dict[str, Any] | None = None) -> None:
    conn.execute(
        "INSERT INTO scores (patient_id, at, ari, esi, confidence, payload) VALUES (?,?,?,?,?,?)",
        (patient_id, time.time(), ari, esi, "manual", json.dumps(payload or {})),
    )
    conn.commit()


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

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
CREATE TABLE IF NOT EXISTS medication_orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id TEXT NOT NULL,
    medication_name TEXT NOT NULL,
    dosage TEXT DEFAULT '',
    frequency TEXT DEFAULT '',
    route TEXT DEFAULT '',
    prescriber TEXT DEFAULT '',
    scheduled_time TEXT DEFAULT '',
    start_time TEXT,
    stop_time TEXT,
    notes TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS medication_administrations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER NOT NULL,
    administered_at TEXT NOT NULL,
    scheduled_slot TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('given', 'held', 'refused', 'not_available', 'cancelled')),
    dose_given TEXT DEFAULT '',
    route TEXT DEFAULT '',
    reason TEXT,
    FOREIGN KEY (order_id) REFERENCES medication_orders(id),
    UNIQUE(order_id, scheduled_slot)
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
        for table in ("clinical_notes", "medication_administrations", "medication_orders", "medications", "decisions", "recommendations", "scores", "patients"):
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


def first_score(conn, patient_id: str) -> dict[str, Any] | None:
    """Get the initial/triage score (first score recorded for a patient)."""
    row = conn.execute(
        "SELECT at, ari, esi, confidence, payload FROM scores WHERE patient_id=? ORDER BY at ASC LIMIT 1",
        (patient_id,)).fetchone()
    if not row:
        return None
    data = dict(row)
    try:
        data["payload"] = json.loads(data.get("payload") or "{}")
    except (TypeError, json.JSONDecodeError):
        data["payload"] = {}
    return data


def add_medication(conn, data: dict[str, Any]) -> int:
    cur = conn.execute(
          """INSERT INTO medication_orders
              (patient_id, medication_name, dosage, frequency, route, prescriber,
                scheduled_time, start_time, stop_time, notes)
              VALUES (?,?,?,?,?,?,?,?,?,?)""",
          (data.get("patient_id"), data.get("medication_name"), data.get("dosage", ""),
            data.get("frequency", ""), data.get("route", ""), data.get("prescriber", ""),
            data.get("scheduled_time", ""), data.get("start_time"), data.get("stop_time"),
            data.get("notes", "")),
    )
    conn.commit()
    return int(cur.lastrowid)


def medication_belongs_to_patient(conn, med_id: int, patient_id: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM medication_orders WHERE id=? AND patient_id=?",
        (med_id, patient_id),
    ).fetchone() is not None


def update_medication_order(conn, med_id: int, patient_id: str,
                                     data: dict[str, Any]) -> bool:
     cur = conn.execute(
          """UPDATE medication_orders SET medication_name=?, dosage=?, frequency=?,
              route=?, prescriber=?, scheduled_time=?, start_time=?, stop_time=?, notes=?
              WHERE id=? AND patient_id=?""",
          (data.get("medication_name", ""), data.get("dosage", ""), data.get("frequency", ""),
            data.get("route", ""), data.get("prescriber", ""), data.get("scheduled_time", ""),
            data.get("start_time"), data.get("stop_time"), data.get("notes", ""), med_id, patient_id),
     )
     conn.commit()
     return cur.rowcount > 0


def add_medication_administration(conn, order_id: int, data: dict[str, Any]) -> int | None:
    cur = conn.execute(
        """INSERT OR IGNORE INTO medication_administrations
              (order_id, administered_at, scheduled_slot, actor_id, status, dose_given, route, reason)
              VALUES (?,?,?,?,?,?,?,?)""",
          (order_id, data["administered_at"], data["scheduled_slot"], data["actor_id"], data["status"],
         data.get("dose_given", ""), data.get("route", ""), data.get("reason")),
    )
    conn.commit()
    return int(cur.lastrowid) if cur.rowcount else None


def get_medications(conn, patient_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
                """SELECT o.id, o.patient_id, o.medication_name, o.dosage, o.frequency,
                                    o.route, o.prescriber, o.scheduled_time, o.start_time,
                                    o.stop_time, o.notes,
                                    COALESCE(a.status, 'scheduled') AS status,
                                    a.administered_at AS given_at, a.actor_id, a.dose_given,
                                    a.reason AS administration_reason
                     FROM medication_orders o
                     LEFT JOIN medication_administrations a ON a.id = (
                         SELECT a2.id FROM medication_administrations a2
                         WHERE a2.order_id=o.id ORDER BY a2.administered_at DESC, a2.id DESC LIMIT 1
                     )
                     WHERE o.patient_id=? ORDER BY o.scheduled_time, o.id""",
        (patient_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def replace_medications(conn, patient_id: str, medications: list[dict[str, Any]]) -> None:
    """Replace medication orders without changing their administration history."""
    existing = {row["id"] for row in conn.execute(
        "SELECT id FROM medication_orders WHERE patient_id=?", (patient_id,)
    ).fetchall()}
    kept: set[int] = set()
    for medication in medications:
        medication_id = medication.get("id")
        values = (medication.get("medication_name") or medication.get("name"),
              medication.get("dosage", ""), medication.get("frequency", ""),
              medication.get("route", ""), medication.get("prescriber", ""),
              medication.get("scheduled_time") or medication.get("schedule_time"),
              medication.get("start_time"), medication.get("stop_time"),
              medication.get("notes") or medication.get("instructions", ""))
        if medication_id in existing:
            conn.execute(
                                """UPDATE medication_orders SET medication_name=?, dosage=?, frequency=?,
                                     route=?, prescriber=?, scheduled_time=?, start_time=?, stop_time=?, notes=?
                                     WHERE id=? AND patient_id=?""",
                                (*values, medication_id, patient_id),
            )
            kept.add(medication_id)
        else:
            conn.execute(
                """INSERT INTO medication_orders
                   (patient_id, medication_name, dosage, frequency, route, prescriber,
                    scheduled_time, start_time, stop_time, notes)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (patient_id, *values),
            )
    stale = existing - kept
    if stale:
        conn.executemany("DELETE FROM medication_orders WHERE id=? AND patient_id=?",
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


def purge_stale_records(conn, retention_days: float = 90.0, now: float | None = None) -> dict[str, int]:
    """Data-minimisation pass — the DPDP Act 2023's storage-limitation duty
    (s.8(7): erase personal data once its purpose is served, absent a
    longer legal-retention requirement) made concrete rather than asserted
    in a policy document nobody runs. Purges any patient whose most recent
    score is older than `retention_days`, cascading through every table
    that references that patient id.

    Deliberately keyed off the *scores* table, not the retention window
    naively deleting straight from `patients`: a patient's last score is
    the closest thing this schema has to "case closed", so a patient still
    inside their retention window keeps every table's rows, and one past
    it loses all of them together rather than leaving orphaned medication
    or note rows behind (foreign keys here are documentation, not
    enforced ON DELETE CASCADE, since SQLite needs that pragma on and this
    project doesn't turn it on elsewhere).

    Returns a per-table count so a caller (a scheduled job, or a manual
    admin action) can log what was actually removed — silent deletion of
    patient data is its own compliance problem.
    """
    now = now if now is not None else time.time()
    cutoff = now - retention_days * 86400.0
    stale_ids = [row["patient_id"] for row in conn.execute(
        """SELECT patient_id FROM scores GROUP BY patient_id
           HAVING MAX(at) < ?""", (cutoff,)).fetchall()]
    if not stale_ids:
        return {"patients": 0}

    counts: dict[str, int] = {"patients": 0}
    placeholders = ",".join("?" for _ in stale_ids)
    order_ids = [row["id"] for row in conn.execute(
        f"SELECT id FROM medication_orders WHERE patient_id IN ({placeholders})",
        stale_ids).fetchall()]
    if order_ids:
        order_placeholders = ",".join("?" for _ in order_ids)
        cur = conn.execute(
            f"DELETE FROM medication_administrations WHERE order_id IN ({order_placeholders})",
            order_ids)
        counts["medication_administrations"] = cur.rowcount
        cur = conn.execute(
            f"DELETE FROM medication_orders WHERE id IN ({order_placeholders})", order_ids)
        counts["medication_orders"] = cur.rowcount
    for table in ("clinical_notes", "decisions", "recommendations", "scores"):
        cur = conn.execute(f"DELETE FROM {table} WHERE patient_id IN ({placeholders})", stale_ids)
        counts[table] = cur.rowcount
    cur = conn.execute(f"DELETE FROM patients WHERE id IN ({placeholders})", stale_ids)
    counts["patients"] = cur.rowcount
    conn.commit()
    return counts


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

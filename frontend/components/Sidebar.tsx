"use client";

import { useState } from "react";
import { administerMedication } from "@/lib/api";
import type { BoardState, Medication, Patient } from "@/lib/types";

function formatSchedule(value?: string) {
  if (!value) return "Time not set";
  const parsed = new Date(value.includes("T") ? value : `${new Date().toISOString().slice(0, 10)}T${value}`);
  return Number.isNaN(parsed.getTime()) ? value : new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(parsed);
}

export default function Sidebar({ state, onRefresh }: { state: BoardState; onRefresh: () => void }) {
  const [target, setTarget] = useState<{ patient: Patient; med: Medication } | null>(null);
  const [busy, setBusy] = useState(false);
  const medications = state.rows.flatMap((patient) =>
    (patient.medications || [])
      .filter((med) => med.status === "scheduled")
      .map((med) => ({ patient, med })),
  );
  return (
    <aside className="col">
      <section className="panel">
        <div className="ph">
          <b>Medication schedule</b>
          <span className="sub">scheduled for this shift</span>
        </div>
        <div className="medication-sidebar-list">
          {medications.length === 0 ? <p className="sidebar-empty">No scheduled medications.</p> : medications.map(({ patient, med }) => (
            <div className="sidebar-medication" key={`${patient.id}-${med.id}`}>
              <div><b>{med.medication_name}</b><span>{patient.name || patient.display_id}</span></div>
              <div className="medication-sidebar-action"><strong>{formatSchedule(med.scheduled_time)}</strong><button type="button" onClick={() => setTarget({ patient, med })}>Mark given</button></div>
            </div>
          ))}
        </div>
      </section>
      {target && (
        <div className="modal-backdrop" role="presentation" onClick={() => setTarget(null)}>
          <section className="verification-modal" role="dialog" aria-modal="true" aria-labelledby="dashboard-medication-title" onClick={(event) => event.stopPropagation()}>
            <h2 id="dashboard-medication-title">Verify medication administration</h2>
            <p>Confirm the patient, medication, dose, and route before recording this dose.</p>
            <dl className="verification-list">
              <div><dt>Patient</dt><dd>{target.patient.display_id} · {target.patient.name || "Name not recorded"}</dd></div>
              <div><dt>Medication</dt><dd>{target.med.medication_name}</dd></div>
              <div><dt>Dose</dt><dd>{target.med.dosage || "Dose not specified"}</dd></div>
              <div><dt>Route</dt><dd>{target.med.route || "Route not specified"}</dd></div>
            </dl>
            <div className="modal-actions"><button type="button" onClick={() => setTarget(null)}>Cancel</button><button type="button" disabled={busy} onClick={async () => { try { setBusy(true); await administerMedication(target.patient.id, target.med.id, "given"); setTarget(null); onRefresh(); } finally { setBusy(false); } }}>{busy ? "Recording..." : "Confirm and record"}</button></div>
          </section>
        </div>
      )}
      <section className="panel">
        <div className="ph">
          <b>Shadow mode</b>
          <span className="sub">nurse agreement</span>
        </div>
        <div className="agree">
          <div className="big">
            {state.agreement.rate == null
              ? "-"
              : `${Math.round(state.agreement.rate * 100)}%`}
          </div>
          <div className="agree-txt">
            {state.agreement.total === 0
              ? "No decisions yet this shift."
              : `${state.agreement.accepted} accepted of ${state.agreement.total} recommendations this shift.`}
          </div>
        </div>
      </section>
      <section className="panel grow">
        <div className="ph">
          <b>Audit log</b>
          <span className="sub">every recommendation &amp; override</span>
        </div>
        <div className="events">
          {state.events.map((event) => (
            <div
              className={`ev ${event.kind}`}
              key={`${event.at}-${event.text}`}
            >
              <span className="t">{event.at}</span>
              <span className="x">{event.text}</span>
            </div>
          ))}
        </div>
      </section>
      <section className="panel">
        <div className="ph">
          <b>Layer 1 model</b>
          <span className="sub">held-out test set</span>
        </div>
        <div className="model">
          {[
            [state.model.roc_auc, "ROC-AUC"],
            [`${(state.model.sensitivity * 100).toFixed(1)}%`, "sensitivity"],
            [
              `${(state.model.undertriage_rate * 100).toFixed(1)}%`,
              "under-triage",
            ],
            [state.model.n_test.toLocaleString(), "held-out encounters"],
          ].map(([value, label]) => (
            <div className="mstat" key={label}>
              <div className="v">{value}</div>
              <div className="k">{label}</div>
            </div>
          ))}
        </div>
      </section>
    </aside>
  );
}

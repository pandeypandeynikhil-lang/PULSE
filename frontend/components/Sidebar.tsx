import type { BoardState } from "@/lib/types";

export default function Sidebar({ state }: { state: BoardState }) {
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
              <strong>{med.scheduled_time || "Time not set"}</strong>
            </div>
          ))}
        </div>
      </section>
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

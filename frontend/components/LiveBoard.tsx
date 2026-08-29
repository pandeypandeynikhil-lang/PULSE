import type { Patient } from "@/lib/types";

function Sparkline({ values, alert }: { values: number[]; alert: boolean }) {
  if (values.length < 2) return <span className="pill">-</span>;
  const points = values
    .map(
      (value, index) =>
        `${(index / (values.length - 1)) * 86},${24 - (value / 100) * 24}`,
    )
    .join(" ");
  return (
    <svg className="spark" viewBox="0 0 86 24">
      <polyline
        points={points}
        fill="none"
        stroke={alert ? "#FF93A6" : "#B9A6FF"}
        strokeWidth="1.8"
      />
    </svg>
  );
}

// A pending recommendation always wins the action slot, even for an
// already-admitted patient — Layer 4 re-scores in-treatment patients too
// (see main.py's tick()), and a re-triage on someone already in a bed is
// the case that most needs to stay visible, not the one most likely to get
// buried under a static "In treatment" pill.
function actionFor(patient: Patient, onOpen: (id: string) => void) {
  if (patient.pending)
    return (
      <button
        className="mini act"
        onClick={(event) => {
          event.stopPropagation();
          onOpen(patient.id);
        }}
      >
        Review
      </button>
    );
  if (patient.status === "in-treatment")
    return <span className="pill">In treatment</span>;
  return (
    <button
      className="mini ok"
      onClick={(event) => {
        event.stopPropagation();
        onOpen(patient.id);
      }}
    >
      Move to bed
    </button>
  );
}

export default function LiveBoard({
  patients,
  onOpen,
  simMinutes,
}: {
  patients: Patient[];
  onOpen: (id: string) => void;
  simMinutes?: number;
}) {
  return (
    <section className="panel board">
      <div className="ph">
        <b>Live board</b>
        <span className="sub">
          {patients.filter((p) => p.status === "waiting").length} waiting ·{" "}
          {patients.filter((p) => p.status === "in-treatment").length} in
          treatment
        </span>
      </div>
      <div className="thead">
        <span>Patient</span>
        <span>Presenting</span>
        <span>ESI</span>
        <span>ARI</span>
        <span>Trend</span>
        <span>Wait</span>
        <span />
      </div>
      <div className="rows">
        {patients.map((patient) => {
          const alert = patient.pending && Boolean(patient.assigned_esi);
          return (
            <div
              className={`row ${alert ? "alert" : ""} ${patient.status === "in-treatment" ? "treat" : ""}`}
              key={patient.id}
              onClick={() => onOpen(patient.id)}
            >
              <div>
                <div className="pid">{patient.display_id}</div>
                <div className="page">
                  {patient.age == null ? "age unknown" : `age ${patient.age}`} ·{" "}
                  {patient.arrival_mode}
                </div>
              </div>
              <div className="comp">{patient.complaint}</div>
              <div className={`esi ${patient.assigned_esi || "none"}`}>
                {patient.assigned_esi || "-"}
              </div>
              <div className="ari">{patient.ari}</div>
              <div>
                <Sparkline
                  values={patient.trace}
                  alert={Boolean(patient.trend?.rising)}
                />
              </div>
              <div className="wait">{Math.round(patient.waited)}m</div>
              <div className="rowact">{actionFor(patient, onOpen)}</div>
            </div>
          );
        })}
      </div>
    </section>
  );
}

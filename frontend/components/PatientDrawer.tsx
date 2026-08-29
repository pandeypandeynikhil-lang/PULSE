"use client";

import type { Medication, Patient } from "@/lib/types";
import { administerMedication, post } from "@/lib/api";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { IconClose } from "./Icons";

function formatMedicationDate(value?: string | null) {
  if (!value) return "Time not specified";
  const parsed = new Date(value.includes("T") ? value : `${new Date().toISOString().slice(0, 10)}T${value}`);
  return Number.isNaN(parsed.getTime()) ? value : new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(parsed);
}

export default function PatientDrawer({
  patient,
  onClose,
  onAction,
  engineTime,
}: {
  patient: Patient | null;
  onClose: () => void;
  onAction: () => void;
  engineTime: number;
}) {
  const router = useRouter();
  const [medicationTarget, setMedicationTarget] = useState<Medication | null>(null);
  const [administering, setAdministering] = useState(false);
  if (!patient) return null;
  const activePatient = patient;
  const waitMinutes = Math.max(0, (engineTime - patient.arrival_time) / 60);
  async function acceptRecommendation() {
    await post(`/api/decide/${activePatient.id}/accept`);
    onAction();
  }
  async function markMedicationGiven() {
    if (!medicationTarget) return;
    try {
      setAdministering(true);
      await administerMedication(activePatient.id, medicationTarget.id, "given");
      setMedicationTarget(null);
      onAction();
    } catch (error) {
      window.alert(error instanceof Error ? error.message : "Unable to record medication administration.");
    } finally {
      setAdministering(false);
    }
  }
  
  const vitals = patient.vitals || {};
  const systolic = vitals.systolic_bp;
  const diastolic = vitals.diastolic_bp;
  const vitalCards = [
    ["Heart Rate", "heart_rate", "bpm"],
    ["Resp Rate", "resp_rate", "/min"],
    ["SpO2", "spo2", "%"],
    ["Temp", "temperature", "°C"],
  ] as const;
  return (
    <>
      <div className="scrim on" onClick={onClose} />
      <aside className="drawer on">
        <div className="dhead">
          <div>
            <h2>{patient.display_id}</h2>
          </div>
          <button onClick={onClose}>
            <IconClose width={15} height={15} />
          </button>
        </div>
        <div className="dbody">
          <div className="sec identity">
            <h4>Patient Identity</h4>
            <div className="identity-name">{patient.name || patient.display_id}</div>
            <div className="identity-meta">Age: {patient.age ?? "N/A"} | Sex: {patient.sex || "N/A"} | Reg No: {patient.registration_no || "N/A"} | Mode: {patient.arrival_mode || "N/A"} | Wait: {`${Math.round(waitMinutes)} min`}</div>
            <div className="drawer-actions">
              <button className="accept-recommendation" type="button" onClick={acceptRecommendation}>Accept Recommendation</button>
              <button className="edit-patient-button" type="button" onClick={() => router.push(`/patients/${patient.id}`)}>Edit Patient Info</button>
            </div>
            <div className="recommendation-banner">
              <div className="recommendation-label">PULSE Recommendation</div>
              <div className="recommendation-main"><strong>ESI {patient.esi}</strong><span>{patient.confidence} confidence</span></div>
              {patient.escalation_reason && (
                <div className="recommendation-reason" style={{ fontSize: "0.85em", color: "#666", marginTop: "4px" }}>
                  {patient.escalation_reason}
                </div>
              )}
              <div className="recommendation-route">{patient.routing.pathway} · {patient.routing.suggested_bed ? `bed ${patient.routing.suggested_bed}` : "bed unassigned"}</div>
            </div>
          </div>
          {patient.transcript && patient.arrival_mode === "voice intake" && (
            <div className="sec">
              <h4>Original account · as spoken</h4>
              <div className="quote">{patient.transcript}</div>
            </div>
          )}
          <div className="sec">
            <h4>Presenting complaint · Layer 2 extraction</h4>
            <div className="quote">{patient.complaint}</div>
          </div>
          {patient.lab_evaluation && patient.lab_evaluation.multiplier > 1 && (
            <div className="sec">
              <h4>Laboratory evaluation</h4>
              <div className="quote">
                ARI multiplier {patient.lab_evaluation.multiplier} ·{" "}
                {patient.lab_evaluation.reason ||
                  "critical abnormality detected"}
              </div>
            </div>
          )}
          {patient.lab_results && patient.lab_results.length > 0 && (
            <div className="sec">
              <h4>Raw laboratory results</h4>
              <table className="lab-table">
                <thead>
                  <tr><th>Test</th><th>Value</th><th>Unit</th></tr>
                </thead>
                <tbody>
                  {patient.lab_results.map((lab, index) => {
                    const abnormal = lab.abnormality_flag === "H" || lab.abnormality_flag === "L";
                    return (
                      <tr key={`${lab.test_name || "lab"}-${index}`}>
                        <td>{lab.test_name || "N/A"}</td>
                        <td className={abnormal ? "lab-abnormal" : undefined}>{lab.value ?? "N/A"}</td>
                        <td>{lab.unit || "N/A"}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
          <div className="sec">
            <h4>Vitals · {patient.vitals_present} of 6 recorded</h4>
            <div className="vgrid">
              {systolic != null && diastolic != null && (
                <div className="vc">
                  <div className="k">Blood Pressure</div>
                  <div className="v" style={{ display: "flex", gap: "8px", alignItems: "center" }}>
                    <span>{systolic}/{diastolic} <small>mmHg</small></span>
                    {(patient.vital_deltas?.systolic_bp != null || patient.vital_deltas?.diastolic_bp != null) && (
                      <span style={{ fontSize: "0.9em" }}>
                        {(["systolic_bp", "diastolic_bp"] as const).map((key, index) => {
                          const delta = patient.vital_deltas?.[key];
                          if (delta == null) return null;
                          return <span key={key} style={{ color: delta > 0 ? "#ef5350" : delta < 0 ? "#42a5f5" : "#9ca3af" }}>{index > 0 ? " / " : ""}{delta > 0 ? "↑ +" : delta < 0 ? "↓ -" : "→ "}{Math.abs(delta)}</span>;
                        })}
                      </span>
                    )}
                  </div>
                </div>
              )}
              {vitalCards.map(([label, key, unit]) => vitals[key] != null && (
                <div className="vc" key={key}>
                  <div className="k">{label}</div>
                  <div className="v" style={{ display: "flex", gap: "8px", alignItems: "center" }}>
                    <span>{vitals[key]} <small>{unit}</small></span>
                    {patient.vital_deltas?.[key] != null && (
                      <span style={{ color: patient.vital_deltas[key]! > 0 ? "#ef5350" : patient.vital_deltas[key]! < 0 ? "#42a5f5" : "#9ca3af", fontSize: "0.9em" }}>
                        {patient.vital_deltas[key]! > 0 ? "↑ +" : patient.vital_deltas[key]! < 0 ? "↓ -" : "→ "}{Math.abs(patient.vital_deltas[key]!)}
                      </span>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </div>
          <div className="sec care-section">
            <h4>Care &amp; Disposition</h4>
            <div className="care-block">
              <strong>Medication schedule</strong>
              {(patient.medications || []).length > 0 ? (
                <div className="med-list">
                  {patient.medications?.map((med) => (
                    <div className="med-row" key={med.id}>
                      <div><b>{med.medication_name}</b><span>{med.dosage || "Dose not specified"} · {med.route || "Route not specified"} · {med.status === "scheduled" ? formatMedicationDate(med.scheduled_time) : formatMedicationDate(med.given_at)}</span></div>
                      {med.status === "scheduled" && <button type="button" className="med-given-button" onClick={() => setMedicationTarget(med)}>Mark given</button>}
                      <span className={`med-status ${med.status}`}>{med.status.replace("_", " ")}</span>
                    </div>
                  ))}
                </div>
              ) : <p className="care-empty">No medications scheduled.</p>}
            </div>
            <div className="care-block">
              <strong>Clinical notes</strong>
              {(patient.clinical_notes || []).length > 0 ? patient.clinical_notes?.map((note) => (
                <div className="saved-note" key={note.id}>
                  <span className="note-type">{note.note_type.replace("_", " ")}</span>
                  <div>{note.content}</div>
                </div>
              )) : <p className="care-empty">No clinical notes recorded.</p>}
            </div>
          </div>
        </div>
      </aside>
      {medicationTarget && (
        <div className="modal-backdrop" role="presentation" onClick={() => setMedicationTarget(null)}>
          <section className="verification-modal" role="dialog" aria-modal="true" aria-labelledby="drawer-medication-title" onClick={(event) => event.stopPropagation()}>
            <h2 id="drawer-medication-title">Verify medication administration</h2>
            <p>Confirm the patient, medication, dose, route, and scheduled time before recording this dose.</p>
            <dl className="verification-list">
              <div><dt>Patient</dt><dd>{patient.display_id} · {patient.name || "Name not recorded"}</dd></div>
              <div><dt>Medication</dt><dd>{medicationTarget.medication_name}</dd></div>
              <div><dt>Dose</dt><dd>{medicationTarget.dosage || "Dose not specified"}</dd></div>
              <div><dt>Route</dt><dd>{medicationTarget.route || "Route not specified"}</dd></div>
              <div><dt>Scheduled</dt><dd>{formatMedicationDate(medicationTarget.scheduled_time)}</dd></div>
            </dl>
            <div className="modal-actions"><button type="button" onClick={() => setMedicationTarget(null)}>Cancel</button><button type="button" disabled={administering} onClick={markMedicationGiven}>{administering ? "Recording..." : "Confirm and record"}</button></div>
          </section>
        </div>
      )}
    </>
  );
}

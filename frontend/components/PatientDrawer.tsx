"use client";

import type { Patient } from "@/lib/types";
import { post } from "@/lib/api";
import { useRouter } from "next/navigation";
import { IconClose } from "./Icons";

export default function PatientDrawer({
  patient,
  onClose,
  onAction,
}: {
  patient: Patient | null;
  onClose: () => void;
  onAction: () => void;
}) {
  const router = useRouter();
  if (!patient) return null;
  const activePatient = patient;
  async function acceptRecommendation() {
    await post(`/api/decide/${activePatient.id}/accept`);
    onAction();
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
            <div className="identity-meta">Age: {patient.age ?? "N/A"} | Sex: {patient.sex || "N/A"} | Reg No: {patient.registration_no || "N/A"} | Mode: {patient.arrival_mode || "N/A"} | Wait: {patient.waited != null ? `${Math.round(patient.waited)} min` : "N/A"}</div>
            <div className="drawer-actions">
              <button className="accept-recommendation" type="button" onClick={acceptRecommendation}>Accept Recommendation</button>
              <button className="edit-patient-button" type="button" onClick={() => router.push(`/patients/${patient.id}`)}>Edit Patient Info</button>
            </div>
            <div className="recommendation-banner">
              <div className="recommendation-label">PULSE Recommendation</div>
              <div className="recommendation-main"><strong>ESI {patient.esi}</strong><span>{patient.confidence} confidence</span></div>
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
              {systolic != null && diastolic != null && <div className="vc"><div className="k">Blood Pressure</div><div className="v">{systolic}/{diastolic} <small>mmHg</small></div></div>}
              {vitalCards.map(([label, key, unit]) => vitals[key] != null && <div className="vc" key={key}><div className="k">{label}</div><div className="v">{vitals[key]} <small>{unit}</small></div></div>)}
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
                      <div><b>{med.medication_name}</b><span>{med.dosage || "Dose not specified"} · {med.scheduled_time || "Time not specified"}</span></div>
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
    </>
  );
}

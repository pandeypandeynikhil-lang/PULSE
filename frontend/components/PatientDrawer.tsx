"use client";

import type { Patient } from "@/lib/types";
import { post } from "@/lib/api";
import { IconClose } from "./Icons";

function ResourceLine({ routing }: { routing: Patient["routing"] }) {
  // What ACCEPT actually commits to — a named bed and clinician, not just a
  // pathway label — so the nurse sees the same resource Engine.decide() is
  // about to mark occupied, not a category that gets resolved after the fact.
  const bedText = routing.suggested_bed
    ? `bed ${routing.suggested_bed}`
    : "no bed free — holding elsewhere";
  const clinicianText =
    routing.suggested_clinician_name || `${routing.specialty} — page required`;
  return (
    <>
      <b>{routing.pathway}</b> · {bedText}
      <br />
      <b>{routing.specialty}</b> · {clinicianText}
    </>
  );
}

export default function PatientDrawer({
  patient,
  onClose,
  onAction,
}: {
  patient: Patient | null;
  onClose: () => void;
  onAction: () => void;
}) {
  if (!patient) return null;
  const activePatient = patient;
  async function decide(action: string) {
    await post(
      `/api/decide/${activePatient.id}/${action}${action === "override" ? "?esi=III" : ""}`,
    );
    onAction();
  }
  return (
    <>
      <div className="scrim on" onClick={onClose} />
      <aside className="drawer on">
        <div className="dhead">
          <div>
            <div className="tag">
              {patient.arrival_mode} · waiting {Math.round(patient.waited)} min
            </div>
            <h2>
              {patient.display_id} ·{" "}
              {patient.age != null ? `age ${patient.age}` : "age unknown"}
            </h2>
          </div>
          <button onClick={onClose}>
            <IconClose width={15} height={15} />
          </button>
        </div>
        <div className="dbody">
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
          <div className="sec">
            <h4>Vitals · {patient.vitals_present} of 6 recorded</h4>
            <div className="vgrid">
              {Object.entries(patient.vitals || {}).map(
                ([key, value]) =>
                  value != null && (
                    <div className="vc" key={key}>
                      <div className="k">{key}</div>
                      <div className="v">{value}</div>
                    </div>
                  ),
              )}
            </div>
          </div>
          <div className="sec">
            <div className="gate">
              <div className="g">● Human decision gate</div>
              <div className="rec">
                PULSE recommends
                <br />
                <b>ESI {patient.esi}</b> - {patient.confidence} confidence
                <br />
                <ResourceLine routing={patient.routing} />
              </div>
              <div className="gbtns">
                <button className="acc" onClick={() => decide("accept")}>
                  Accept
                </button>
                <button className="ovr" onClick={() => decide("override")}>
                  Override
                </button>
              </div>
            </div>
          </div>
        </div>
      </aside>
    </>
  );
}

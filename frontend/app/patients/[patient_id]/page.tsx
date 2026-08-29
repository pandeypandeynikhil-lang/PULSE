"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { API_ORIGIN, administerMedication, scheduleMedication } from "@/lib/api";
import type { ClinicalNote, Medication, TestResult } from "@/lib/types";

type Profile = {
  id: string;
  display_id: string;
  name?: string;
  age?: number | null;
  sex?: string;
  registration_no?: string;
  complaint?: string;
  nursing_assessment?: string;
  referred_by?: string;
  report_date?: string;
  raw_intake?: string;
  status?: string;
  lab_results?: TestResult[];
  vitals?: Record<string, string | number | null>;
  ari?: number;
  esi?: string;
  pathway?: string;
  ward?: { bed?: string; clinician?: string };
  medications?: Medication[];
  clinical_notes?: ClinicalNote[];
};

type DraftMedication = Medication & { isNew?: boolean };

type Roster = {
  beds: { id: string; ward: string; status: string }[];
  clinicians: { id: string; name: string; specialty: string; status: string }[];
};
const pathways = [
  "Resus",
  "Acute medicine",
  "Fast track",
  "Trauma",
  "General surgery",
  "Observation",
];
const vitalKeys = [
  "heart_rate",
  "systolic_bp",
  "diastolic_bp",
  "resp_rate",
  "spo2",
  "temperature",
];

function toDateTimeLocal(value?: string | null) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  const pad = (part: number) => String(part).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

function formatDateTime(value?: string | null) {
  if (!value) return "Date not recorded";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

function toScheduledDateTimeLocal(value?: string | null) {
  if (!value) return "";
  const parsed = value.includes("T")
    ? new Date(value)
    : new Date(`${new Date().toISOString().slice(0, 10)}T${value}`);
  if (Number.isNaN(parsed.getTime())) return "";
  const pad = (part: number) => String(part).padStart(2, "0");
  return `${parsed.getFullYear()}-${pad(parsed.getMonth() + 1)}-${pad(parsed.getDate())}T${pad(parsed.getHours())}:${pad(parsed.getMinutes())}`;
}

function medicationDueState(value: string): "overdue" | "due-now" | "upcoming" {
  if (!value) return "upcoming";
  const scheduled = new Date(value.includes("T") ? value : `${new Date().toISOString().slice(0, 10)}T${value}`);
  if (Number.isNaN(scheduled.getTime())) return "upcoming";
  const difference = scheduled.getTime() - Date.now();
  if (difference < -30 * 60 * 1000) return "overdue";
  if (difference <= 30 * 60 * 1000) return "due-now";
  return "upcoming";
}

export default function PatientProfilePage() {
  const { patient_id } = useParams<{ patient_id: string }>();
  const router = useRouter();
  const [profile, setProfile] = useState<Profile | null>(null);
  const [roster, setRoster] = useState<Roster>({ beds: [], clinicians: [] });
  const [labs, setLabs] = useState<TestResult[]>([]);
  const [medications, setMedications] = useState<DraftMedication[]>([]);
  const [status, setStatus] = useState("");
  const [uploading, setUploading] = useState(false);
  const [dischargeSummary, setDischargeSummary] = useState("");
  const [followUp, setFollowUp] = useState("");
  const [administrationTarget, setAdministrationTarget] = useState<DraftMedication | null>(null);
  const [administrationStatus, setAdministrationStatus] = useState<"given" | "held" | "refused">("given");
  const [administrationReason, setAdministrationReason] = useState("");
  const [administering, setAdministering] = useState(false);

  async function load() {
    const [profileResponse, boardResponse] = await Promise.all([
      fetch(`${API_ORIGIN}/api/patients/${patient_id}/profile`),
      fetch(`${API_ORIGIN}/api/board`),
    ]);
    if (!profileResponse.ok) {
      setStatus("Patient profile not found.");
      return;
    }
    const next = (await profileResponse.json()) as Profile;
    const board = await boardResponse.json();
    setProfile(next);
    setLabs(next.lab_results || []);
    setRoster({ beds: board.beds || [], clinicians: board.clinicians || [] });
    setMedications(next.medications || []);
  }
  useEffect(() => {
    load().catch(() => setStatus("Unable to load patient profile."));
  }, [patient_id]);
  if (!profile)
    return (
      <main className="page-wrap">
        <p>{status || "Loading patient profile..."}</p>
      </main>
    );

  function setField(field: keyof Profile, value: unknown) {
    setProfile((current) =>
      current ? { ...current, [field]: value } : current,
    );
  }
  function setVital(key: string, value: string) {
    setProfile((current) =>
      current
        ? {
            ...current,
            vitals: {
              ...current.vitals,
              [key]: value === "" ? null : Number(value),
            },
          }
        : current,
    );
  }
  function addLab() {
    setLabs((current) => [
      ...current,
      {
        test_name: "",
        value: "",
        unit: "",
        reference_range: "",
        abnormality_flag: null,
      },
    ]);
  }
  function updateLab(index: number, key: keyof TestResult, value: string) {
    setLabs((current) =>
      current.map((lab, i) =>
        i === index ? { ...lab, [key]: value || null } : lab,
      ),
    );
  }
  async function save() {
    if (!profile) return;
    setStatus("Saving changes...");
    const response = await fetch(
      `${API_ORIGIN}/api/patients/${patient_id}/profile`,
      {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ...profile,
          lab_results: labs,
          labs,
          medications,
          vitals: profile.vitals,
          ari: profile.ari,
          esi: profile.esi,
          pathway: profile.pathway,
          bed_id: profile.ward?.bed || null,
          clinician_id: profile.ward?.clinician || null,
        }),
      },
    );
    setStatus(response.ok ? "All changes saved." : "Unable to save changes.");
    if (response.ok) await load();
  }
  async function uploadLab(file?: File) {
    if (!file) return;
    setUploading(true);
    const form = new FormData();
    form.append("file", file);
    const response = await fetch(`${API_ORIGIN}/api/extract-lab`, {
      method: "POST",
      body: form,
    });
    if (response.ok) {
      const report = await response.json();
      setLabs((current) => [...current, ...(report.test_results || [])]);
      setStatus("Lab results appended. Save all changes to store them.");
    }
    setUploading(false);
  }
  function addScheduledMedication() {
    setMedications((current) => [...current, {
      id: -Date.now(), medication_name: "", dosage: "", scheduled_time: "",
      status: "scheduled", notes: "", isNew: true,
    }]);
  }
  function updateMedication(id: number, changes: Partial<DraftMedication>) {
    setMedications((current) => current.map((med) => med.id === id ? { ...med, ...changes } : med));
  }
  function confirmMedication(id: number) {
    const medication = medications.find((item) => item.id === id);
    if (!medication?.medication_name.trim()) {
      setStatus("Medication name is required.");
      return;
    }
    updateMedication(id, { isNew: false });
    setStatus("Medication ready to save. Click Save All Changes to apply it.");
  }
  function removeMedication(id: number) {
    setMedications((current) => current.filter((med) => med.id !== id));
    setStatus("Medication removed from the draft. Click Save All Changes to apply it.");
  }
  async function confirmHistoryMedication(id: number) {
    const medication = medications.find((item) => item.id === id);
    if (!medication?.medication_name.trim()) {
      setStatus("Medication name is required.");
      return;
    }
    try {
      setStatus("Recording medication history...");
      const order = await scheduleMedication(patient_id, medication);
      await administerMedication(patient_id, order.id, "given");
      await load();
      setStatus("Medication administration recorded.");
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Unable to record medication history.");
    }
  }
  function addHistoryMedication() {
    setMedications((current) => [...current, {
      id: -Date.now(), medication_name: "", dosage: "", scheduled_time: "",
      status: "given", given_at: new Date().toISOString(), notes: "", isNew: true,
    }]);
  }
  async function confirmAdministration() {
    if (!administrationTarget) return;
    if (administrationStatus !== "given" && !administrationReason.trim()) {
      setStatus("A reason is required for a held or refused dose.");
      return;
    }
    try {
      setAdministering(true);
      await administerMedication(patient_id, administrationTarget.id, administrationStatus, administrationReason);
      setAdministrationTarget(null);
      setAdministrationReason("");
      await load();
      setStatus("Medication administration recorded.");
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Unable to record administration.");
    } finally {
      setAdministering(false);
    }
  }
  async function discharge() {
    if (!profile) return;
    if (!dischargeSummary.trim()) {
      alert("Discharge Summary is required.");
      return;
    }
      const saved = await fetch(`${API_ORIGIN}/api/patients/${patient_id}/profile`, {
        method: "PATCH", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...profile, lab_results: labs, labs,
        vitals: profile.vitals, ari: profile.ari, esi: profile.esi,
        pathway: profile.pathway, bed_id: profile.ward?.bed || null,
        clinician_id: profile.ward?.clinician || null }),
    });
    if (!saved.ok) { setStatus("Unable to save changes before discharge."); return; }
    const response = await fetch(`${API_ORIGIN}/api/discharge/${patient_id}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        discharge_summary: dischargeSummary,
        follow_up_instructions: followUp,
      }),
    });
    if (response.ok) router.push("/dashboard");
    else setStatus("Discharge failed.");
  }
  return (
    <main className="page-wrap profile-page">
      <div className="profile-toolbar">
        <button type="button" onClick={() => router.push("/patients")}>
          Back to search
        </button>
        <div>
          <p className="eyebrow">Patient profile</p>
          <h1>{profile.name || profile.display_id}</h1>
          <p>
            {profile.display_id} · {profile.status}
          </p>
        </div>
        <button className="save-all" type="button" onClick={save}>
          Save All Changes
        </button>
      </div>
      {status && <div className="profile-status">{status}</div>}
      <section className="profile-grid">
        <div className="profile-card">
          <h2>Personal details &amp; presentation</h2>
          <div className="profile-fields">
            <label>
              Name
              <input
                value={profile.name || ""}
                onChange={(e) => setField("name", e.target.value)}
              />
            </label>
            <label>
              Age
              <input
                type="number"
                value={profile.age ?? ""}
                onChange={(e) => setField("age", Number(e.target.value))}
              />
            </label>
            <label>
              Sex
              <input
                value={profile.sex || ""}
                onChange={(e) => setField("sex", e.target.value)}
              />
            </label>
            <label>
              Registration No
              <input
                value={profile.registration_no || ""}
                onChange={(e) => setField("registration_no", e.target.value)}
              />
            </label>
            <label>
              Presenting Complaint
              <textarea
                value={profile.complaint || ""}
                onChange={(e) => setField("complaint", e.target.value)}
              />
            </label>
            <label>
              Nursing Assessment
              <textarea
                value={profile.nursing_assessment || ""}
                onChange={(e) => setField("nursing_assessment", e.target.value)}
              />
            </label>
          </div>
        </div>
        <div className="profile-card">
          <h2>Triage &amp; ward map</h2>
          <div className="profile-fields">
            <label>
              ARI (0-100)
              <input
                type="number"
                min="0"
                max="100"
                value={profile.ari ?? ""}
                onChange={(e) => setField("ari", Number(e.target.value))}
              />
            </label>
            <label>
              ESI
              <select
                value={profile.esi || "V"}
                onChange={(e) => setField("esi", e.target.value)}
              >
                {["I", "II", "III", "IV", "V"].map((v) => (
                  <option key={v}>{v}</option>
                ))}
              </select>
            </label>
            <label>
              Pathway
              <select
                value={profile.pathway || ""}
                onChange={(e) => setField("pathway", e.target.value)}
              >
                <option value="">Unassigned</option>
                {pathways.map((v) => (
                  <option key={v}>{v}</option>
                ))}
              </select>
            </label>
            <label>
              Bed
              <select
                value={profile.ward?.bed || ""}
                onChange={(e) =>
                  setField("ward", { ...profile.ward, bed: e.target.value })
                }
              >
                <option value="">Unassigned</option>
                {roster.beds.map((bed) => (
                  <option key={bed.id} value={bed.id}>
                    {bed.id} · {bed.ward} ({bed.status})
                  </option>
                ))}
              </select>
            </label>
            <label>
              Clinician
              <select
                value={profile.ward?.clinician || ""}
                onChange={(e) =>
                  setField("ward", {
                    ...profile.ward,
                    clinician: e.target.value,
                  })
                }
              >
                <option value="">Unassigned</option>
                {roster.clinicians.map((clinician) => (
                  <option key={clinician.id} value={clinician.id}>
                    {clinician.name} · {clinician.specialty} ({clinician.status}
                    )
                  </option>
                ))}
              </select>
            </label>
          </div>
        </div>
      </section>
      <section className="profile-card">
        <h2>Vitals</h2>
        <div className="profile-vitals">
          {vitalKeys.map((key) => (
            <label key={key}>
              {key.replaceAll("_", " ")}
              <input
                type="number"
                value={profile.vitals?.[key] ?? ""}
                onChange={(e) => setVital(key, e.target.value)}
              />
            </label>
          ))}
        </div>
      </section>
      <section className="profile-card">
        <div className="section-heading">
          <h2>Laboratory records</h2>
          <div>
            <label className="upload-button">
              {uploading ? "Uploading..." : "Upload PDF"}
              <input
                hidden
                type="file"
                accept="application/pdf"
                onChange={(e) => uploadLab(e.target.files?.[0])}
              />
            </label>
            <button type="button" onClick={addLab}>
              + Add Lab Row
            </button>
          </div>
        </div>
        <div className="editable-table lab-editor">
          <div className="table-head">
            <span>Test Name</span>
            <span>Value</span>
            <span>Unit</span>
            <span>Reference Range</span>
            <span>Flag</span>
          </div>
          {labs.map((lab, index) => (
            <div className="table-row" key={`${index}-${lab.test_name}`}>
              <input
                value={lab.test_name}
                onChange={(e) => updateLab(index, "test_name", e.target.value)}
              />
              <input
                value={lab.value}
                onChange={(e) => updateLab(index, "value", e.target.value)}
              />
              <input
                value={lab.unit || ""}
                onChange={(e) => updateLab(index, "unit", e.target.value)}
              />
              <input
                value={lab.reference_range || ""}
                onChange={(e) =>
                  updateLab(index, "reference_range", e.target.value)
                }
              />
              <select
                value={lab.abnormality_flag || ""}
                onChange={(e) =>
                  updateLab(index, "abnormality_flag", e.target.value)
                }
              >
                <option value="">Normal</option>
                <option value="H">H</option>
                <option value="L">L</option>
              </select>
            </div>
          ))}
        </div>
      </section>
      <section className="profile-grid">
        <div className="profile-card">
          <div className="section-heading">
            <h2>Medication schedule</h2>
            <button
              type="button"
              onClick={addScheduledMedication}
            >
              + Add Scheduled Med
            </button>
          </div>
          <table className="profile-table medication-table">
            <thead><tr><th>Name</th><th>Dose</th><th>Route</th><th>Date &amp; time</th><th>Instructions</th><th>Action</th></tr></thead>
            <tbody>{medications.filter((med) => med.status === "scheduled").sort((a, b) => {
              const order = { overdue: 0, "due-now": 1, upcoming: 2 };
              return order[medicationDueState(a.scheduled_time)] - order[medicationDueState(b.scheduled_time)];
            }).map((med) => (
              <tr key={med.id}>
                {med.isNew ? <>
                  <td><input value={med.medication_name} onChange={(e) => updateMedication(med.id, { medication_name: e.target.value })} placeholder="Name" /></td>
                  <td><input value={med.dosage} onChange={(e) => updateMedication(med.id, { dosage: e.target.value })} placeholder="Dose" /></td>
                  <td><input value={med.route || ""} onChange={(e) => updateMedication(med.id, { route: e.target.value })} placeholder="Route" /></td>
                  <td><input type="datetime-local" value={toScheduledDateTimeLocal(med.scheduled_time)} onChange={(e) => updateMedication(med.id, { scheduled_time: e.target.value ? new Date(e.target.value).toISOString() : "" })} /></td>
                  <td><input value={med.notes || ""} onChange={(e) => updateMedication(med.id, { notes: e.target.value })} placeholder="Instructions" /></td>
                  <td><button type="button" className="med-confirm-button" onClick={() => confirmMedication(med.id)}>Confirm</button></td>
                </> : <>
                  <td><input value={med.medication_name} onChange={(e) => updateMedication(med.id, { medication_name: e.target.value })} /></td>
                  <td><input value={med.dosage} onChange={(e) => updateMedication(med.id, { dosage: e.target.value })} placeholder="Dose" /></td>
                  <td><input value={med.route || ""} onChange={(e) => updateMedication(med.id, { route: e.target.value })} placeholder="Route" /></td>
                  <td><input type="datetime-local" value={toScheduledDateTimeLocal(med.scheduled_time)} onChange={(e) => updateMedication(med.id, { scheduled_time: e.target.value ? new Date(e.target.value).toISOString() : "" })} /></td>
                  <td>{med.notes || "No instructions"}</td>
                  <td>{med.id < 0 ? <button type="button" className="med-remove-button" onClick={() => removeMedication(med.id)}>Remove</button> : <button type="button" className="med-given-button" onClick={() => { setAdministrationTarget(med); setAdministrationStatus("given"); }}>Mark Given</button>}</td>
                </>}
              </tr>
            ))}</tbody>
          </table>
        </div>
        <div className="profile-card">
          <div className="section-heading">
            <h2>Medicine history</h2>
            <button type="button" onClick={addHistoryMedication}>
              + Add Medication History
            </button>
          </div>
          <table className="profile-table medication-table">
            <thead><tr><th>Name</th><th>Given At</th><th>Instructions</th></tr></thead>
            <tbody>{medications.filter((med) => med.status !== "scheduled").map((med) => (
              <tr key={med.id}>
                {med.isNew ? <>
                  <td><input value={med.medication_name} onChange={(e) => updateMedication(med.id, { medication_name: e.target.value })} placeholder="Name" /></td>
                  <td><input type="datetime-local" value={toDateTimeLocal(med.given_at)} onChange={(e) => updateMedication(med.id, { given_at: e.target.value ? new Date(e.target.value).toISOString() : "" })} /></td>
                  <td><input value={med.notes || ""} onChange={(e) => updateMedication(med.id, { notes: e.target.value })} placeholder="Instructions" /><button type="button" onClick={() => confirmHistoryMedication(med.id)}>Confirm</button></td>
                </> : <>
                  <td>{med.medication_name || "Unnamed medication"}</td><td><strong>{med.status.replace("_", " ")}</strong> · {formatDateTime(med.given_at)}</td><td>{med.notes || med.administration_reason || "No instructions"}</td>
                </>}
              </tr>
            ))}</tbody>
          </table>
        </div>
      </section>
      {administrationTarget && (
        <div className="modal-backdrop" role="presentation" onClick={() => setAdministrationTarget(null)}>
          <section className="verification-modal" role="dialog" aria-modal="true" aria-labelledby="verify-medication-title" onClick={(event) => event.stopPropagation()}>
            <h2 id="verify-medication-title">Verify medication administration</h2>
            <p>Confirm the patient identifier, medication, dose, and route before recording this event.</p>
            <dl className="verification-list">
              <div><dt>Patient</dt><dd>{profile.display_id} · {profile.name || "Name not recorded"}</dd></div>
              <div><dt>Medication</dt><dd>{administrationTarget.medication_name || "Unnamed medication"}</dd></div>
              <div><dt>Dose</dt><dd>{administrationTarget.dosage || "Dose not specified"}</dd></div>
              <div><dt>Route</dt><dd>{administrationTarget.route || "Route not specified"}</dd></div>
            </dl>
            <label>Status<select value={administrationStatus} onChange={(event) => setAdministrationStatus(event.target.value as typeof administrationStatus)}><option value="given">Given</option><option value="held">Held</option><option value="refused">Refused</option></select></label>
            {administrationStatus !== "given" && <label>Reason<textarea value={administrationReason} onChange={(event) => setAdministrationReason(event.target.value)} placeholder="Required justification" /></label>}
            <div className="modal-actions"><button type="button" onClick={() => setAdministrationTarget(null)}>Cancel</button><button type="button" disabled={administering} onClick={confirmAdministration}>{administering ? "Recording..." : "Confirm and record"}</button></div>
          </section>
        </div>
      )}
      <section className="profile-card discharge-card">
        <h2>Discharge</h2>
        <div className="profile-fields">
          <label>
            Discharge Date/Time
            <input type="datetime-local" />
          </label>
          <label>
            Discharge Summary
            <textarea
              value={dischargeSummary}
              onChange={(e) => setDischargeSummary(e.target.value)}
            />
          </label>
          <label>
            Follow-up Instructions
            <textarea
              value={followUp}
              onChange={(e) => setFollowUp(e.target.value)}
            />
          </label>
        </div>
        <button className="discharge-action" type="button" onClick={discharge}>
          Save &amp; Discharge
        </button>
      </section>
    </main>
  );
}

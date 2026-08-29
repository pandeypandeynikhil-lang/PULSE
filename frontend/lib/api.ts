import type { BoardState, IntakePayload, LabReport, Medication } from "./types";

export const API_ORIGIN = process.env.NEXT_PUBLIC_API_ORIGIN || "http://127.0.0.1:8000";

export async function getBoard(): Promise<BoardState> {
  const response = await fetch(`${API_ORIGIN}/api/board`, { cache: "no-store" });
  if (!response.ok) throw new Error("Unable to load the board");
  return response.json();
}

export async function post(path: string): Promise<void> {
  await fetch(`${API_ORIGIN}${path}`, { method: "POST" });
}

export async function scheduleMedication(patientId: string, medication: Omit<Medication, "id" | "status" | "given_at">) {
  const response = await fetch(`${API_ORIGIN}/api/patients/${patientId}/medications`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(medication),
  });
  if (!response.ok) {
    throw new Error("Unable to schedule medication.");
  }
  return response.json() as Promise<{ ok: boolean; id: number }>;
}

export async function administerMedication(patientId: string, medicationId: number, status: "given" | "held" | "refused" | "not_available" | "cancelled", reason?: string) {
  const isGiven = status === "given";
  const response = await fetch(`${API_ORIGIN}/api/patients/${patientId}/medications/${medicationId}${isGiven ? "/given" : ""}`, {
    method: "PATCH", headers: { "Content-Type": "application/json" },
    body: isGiven ? undefined : JSON.stringify({ status, reason }),
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || "Unable to record medication administration.");
  }
}

export async function updateMedicationOrder(patientId: string, medicationId: number, medication: Omit<Medication, "id" | "status" | "given_at">) {
  const response = await fetch(`${API_ORIGIN}/api/patients/${patientId}/medications/${medicationId}/order`, {
    method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(medication),
  });
  if (!response.ok) throw new Error("Unable to update medication order.");
}

export async function addClinicalNote(patientId: string, noteType: "surgical" | "follow_up", content: string) {
  const response = await fetch(`${API_ORIGIN}/api/patients/${patientId}/notes`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ note_type: noteType, content }),
  });
  if (!response.ok) throw new Error("Unable to save clinical note.");
}

export async function dischargePatient(patientId: string, dischargeSummary: string, followUpInstructions: string) {
  const response = await fetch(`${API_ORIGIN}/api/discharge/${patientId}`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ discharge_summary: dischargeSummary, follow_up_instructions: followUpInstructions }),
  });
  if (!response.ok) throw new Error("Unable to discharge patient.");
}

export async function getModel() {
  const response = await fetch(`${API_ORIGIN}/api/model`, { cache: "no-store" });
  if (!response.ok) throw new Error("Unable to load model metrics");
  return response.json() as Promise<{
    roc_auc: number; sensitivity: number; undertriage_rate: number; n_test: number;
  }>;
}

export async function sendVoice(transcript: string, lang: string) {
  const response = await fetch(`${API_ORIGIN}/api/voice-intake`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ transcript, lang }),
  });
  return response.json() as Promise<{ ok: boolean; error?: string; display_id?: string; complaint?: string; age?: number; provider?: string }>;
}

export async function translateDictation(text: string, lang: string) {
  const response = await fetch(`${API_ORIGIN}/api/translate`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text, lang }),
  });
  return response.json() as Promise<{ ok: boolean; error?: string; translation?: string }>;
}

export async function extractLab(file: File): Promise<LabReport> {
  const form = new FormData();
  form.append("file", file);
  const response = await fetch(`${API_ORIGIN}/api/extract-lab`, { method: "POST", body: form });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.detail || "Unable to extract the lab report.");
  return body as LabReport;
}

export async function calculateARI(patientData: unknown): Promise<{ ari: number; esi: string; confidence: string; lab_evaluation?: { multiplier: number; reason: string | null } }> {
  const response = await fetch(`${API_ORIGIN}/api/ari`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patientData),
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.detail || "Unable to calculate the Arrival Risk Index.");
  return body;
}

export async function submitIntake(payload: IntakePayload) {
  const response = await fetch(`${API_ORIGIN}/api/intake`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.detail || "Unable to submit the patient intake.");
  // Submitting now creates a live, queued patient (see backend/main.py
  // Engine.create_intake_patient) — `ok`/`error` come back the same way
  // every other patient-creating endpoint reports failure, rather than a
  // bare HTTP error being the only signal something went wrong.
  return body as { ok: boolean; error?: string; id?: string; display_id?: string;
    ari?: number; esi?: string; confidence?: string;
    lab_evaluation?: { multiplier: number; reason: string | null } };
}

export async function setBedStatus(bedId: string, status: string) {
  const response = await fetch(`${API_ORIGIN}/api/ward/beds/${bedId}/status`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ status }),
  });
  return response.json() as Promise<{ ok: boolean }>;
}

export async function setClinicianStatus(clinicianId: string, status: string) {
  const response = await fetch(`${API_ORIGIN}/api/ward/clinicians/${clinicianId}/status`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ status }),
  });
  return response.json() as Promise<{ ok: boolean }>;
}

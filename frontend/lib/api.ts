import type { BoardState, IntakePayload, LabReport, Medication } from "./types";

export const API_ORIGIN = process.env.NEXT_PUBLIC_API_ORIGIN || "http://127.0.0.1:8000";

// Sent as X-PULSE-Token on every write — backend/auth.py rejects a mutating
// /api/* request without it (the DPDP Act 2023 access-control gate; reads
// like getBoard() above stay open). NEXT_PUBLIC_* is baked into the client
// bundle at build time, so this is only ever the same demo-scoped value
// that ships in .env.example, never a real secret — a production
// deployment would put write access behind hospital SSO instead of a
// bundled token, which is exactly the "out of scope for a triage-logic
// prototype" boundary auth.py's docstring calls out.
const API_TOKEN = process.env.NEXT_PUBLIC_API_TOKEN || "pulse-demo-2026";

export function authHeaders(json: boolean): HeadersInit {
  return json
    ? { "Content-Type": "application/json", "X-PULSE-Token": API_TOKEN }
    : { "X-PULSE-Token": API_TOKEN };
}

export async function getBoard(): Promise<BoardState> {
  const response = await fetch(`${API_ORIGIN}/api/board`, { cache: "no-store" });
  if (!response.ok) throw new Error("Unable to load the board");
  return response.json();
}

export async function post(path: string): Promise<void> {
  await fetch(`${API_ORIGIN}${path}`, { method: "POST", headers: authHeaders(false) });
}

export async function scheduleMedication(patientId: string, medication: Omit<Medication, "id" | "status" | "given_at">) {
  const response = await fetch(`${API_ORIGIN}/api/patients/${patientId}/medications`, {
    method: "POST", headers: authHeaders(true),
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
    method: "PATCH", headers: authHeaders(true),
    body: isGiven ? undefined : JSON.stringify({ status, reason }),
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || "Unable to record medication administration.");
  }
}

export async function updateMedicationOrder(patientId: string, medicationId: number, medication: Omit<Medication, "id" | "status" | "given_at">) {
  const response = await fetch(`${API_ORIGIN}/api/patients/${patientId}/medications/${medicationId}/order`, {
    method: "PATCH", headers: authHeaders(true), body: JSON.stringify(medication),
  });
  if (!response.ok) throw new Error("Unable to update medication order.");
}

export async function addClinicalNote(patientId: string, noteType: "surgical" | "follow_up", content: string) {
  const response = await fetch(`${API_ORIGIN}/api/patients/${patientId}/notes`, {
    method: "POST", headers: authHeaders(true),
    body: JSON.stringify({ note_type: noteType, content }),
  });
  if (!response.ok) throw new Error("Unable to save clinical note.");
}

export async function dischargePatient(patientId: string, dischargeSummary: string, followUpInstructions: string) {
  const response = await fetch(`${API_ORIGIN}/api/discharge/${patientId}`, {
    method: "POST", headers: authHeaders(true),
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
    method: "POST", headers: authHeaders(true),
    body: JSON.stringify({ transcript, lang }),
  });
  return response.json() as Promise<{ ok: boolean; error?: string; display_id?: string; complaint?: string; age?: number; provider?: string }>;
}

export async function translateDictation(text: string, lang: string) {
  const response = await fetch(`${API_ORIGIN}/api/translate`, {
    method: "POST", headers: authHeaders(true),
    body: JSON.stringify({ text, lang }),
  });
  return response.json() as Promise<{ ok: boolean; error?: string; translation?: string }>;
}

export async function extractLab(file: File): Promise<LabReport> {
  const form = new FormData();
  form.append("file", file);
  const response = await fetch(`${API_ORIGIN}/api/extract-lab`, { method: "POST", headers: authHeaders(false), body: form });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.detail || "Unable to extract the lab report.");
  return body as LabReport;
}

export async function calculateARI(patientData: unknown): Promise<{ ari: number; esi: string; confidence: string; lab_evaluation?: { multiplier: number; reason: string | null } }> {
  const response = await fetch(`${API_ORIGIN}/api/ari`, {
    method: "POST", headers: authHeaders(true),
    body: JSON.stringify(patientData),
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.detail || "Unable to calculate the Arrival Risk Index.");
  return body;
}

export async function submitIntake(payload: IntakePayload) {
  const response = await fetch(`${API_ORIGIN}/api/intake`, {
    method: "POST",
    headers: authHeaders(true),
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
    method: "POST", headers: authHeaders(true),
    body: JSON.stringify({ status }),
  });
  return response.json() as Promise<{ ok: boolean }>;
}

export async function setClinicianStatus(clinicianId: string, status: string) {
  const response = await fetch(`${API_ORIGIN}/api/ward/clinicians/${clinicianId}/status`, {
    method: "POST", headers: authHeaders(true),
    body: JSON.stringify({ status }),
  });
  return response.json() as Promise<{ ok: boolean }>;
}

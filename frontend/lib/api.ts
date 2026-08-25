import type { BoardState, IntakePayload, LabReport } from "./types";

export const API_ORIGIN = process.env.NEXT_PUBLIC_API_ORIGIN || "http://127.0.0.1:8000";

export async function getBoard(): Promise<BoardState> {
  const response = await fetch(`${API_ORIGIN}/api/board`, { cache: "no-store" });
  if (!response.ok) throw new Error("Unable to load the board");
  return response.json();
}

export async function post(path: string): Promise<void> {
  await fetch(`${API_ORIGIN}${path}`, { method: "POST" });
}

export async function sendVoice(transcript: string, lang: string) {
  const response = await fetch(`${API_ORIGIN}/api/voice-intake`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ transcript, lang }),
  });
  return response.json() as Promise<{ ok: boolean; error?: string; display_id?: string; complaint?: string; age?: number; provider?: string }>;
}

export async function extractLab(file: File): Promise<LabReport> {
  const form = new FormData();
  form.append("file", file);
  const response = await fetch(`${API_ORIGIN}/api/extract-lab`, { method: "POST", body: form });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.detail || "Unable to extract the lab report.");
  return body as LabReport;
}

export async function calculateARI(patientData: unknown): Promise<{ ari: number; esi: string; confidence: string }> {
  const response = await fetch(`${API_ORIGIN}/api/ari`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patientData),
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.detail || "Unable to calculate the Arrival Risk Index.");
  return body;
}

export async function submitIntake(payload: IntakePayload): Promise<{ ari: number; esi: string; confidence: string }> {
  const response = await fetch(`${API_ORIGIN}/api/intake`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.detail || "Unable to submit the patient intake.");
  return body;
}

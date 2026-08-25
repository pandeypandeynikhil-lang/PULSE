"use client";

import { useRef, useState } from "react";
import VoiceIntake from "./VoiceIntake";
import { extractLab, submitIntake } from "@/lib/api";
import type { IntakePayload, LabReport, TestResult } from "@/lib/types";

type PatientData = {
  name: string; age_years: string; sex: string; referred_by: string; registration_no: string;
  report_date: string; complaint: string; nursing_assessment: string;
  vitals: { heart_rate: string; systolic_bp: string; diastolic_bp: string; resp_rate: string; spo2: string; temperature: string };
  test_results: TestResult[];
};

const initialData: PatientData = { name: "", age_years: "", sex: "", referred_by: "", registration_no: "", report_date: "", complaint: "", nursing_assessment: "", vitals: { heart_rate: "", systolic_bp: "", diastolic_bp: "", resp_rate: "", spo2: "", temperature: "" }, test_results: [] };

function Field({ label, value, onChange, type = "text", placeholder = "" }: { label: string; value: string; onChange: (value: string) => void; type?: string; placeholder?: string }) { return <label className="intake-field"><span>{label}</span><input type={type} value={value} placeholder={placeholder} onChange={event => onChange(event.target.value)} /></label>; }

export default function IntakePage() {
  const [patientData, setPatientData] = useState<PatientData>(initialData);
  const [parsing, setParsing] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [message, setMessage] = useState("");
  const [risk, setRisk] = useState<{ ari: number; esi: string; confidence: string } | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const update = <K extends keyof PatientData>(key: K, value: PatientData[K]) => setPatientData(current => ({ ...current, [key]: value }));

  function applyReport(report: LabReport) { setPatientData(current => ({ ...current, name: report.name || current.name, age_years: report.age_years == null ? current.age_years : String(report.age_years), sex: report.sex || current.sex, referred_by: report.referred_by || current.referred_by, registration_no: report.registration_no || current.registration_no, report_date: report.report_date || current.report_date, test_results: [...current.test_results, ...report.test_results], vitals: { ...current.vitals, ...Object.fromEntries(Object.entries(report.vitals || {}).filter(([key, value]) => value != null && !current.vitals[key as keyof typeof current.vitals]).map(([key, value]) => [key, String(value)])) } })); }
  async function handleFile(file?: File) { if (!file) return; if (file.type !== "application/pdf") { setMessage("Please select a PDF lab report."); return; } setParsing(true); setMessage("Extracting report with Docling and Ollama..."); try { const report = await extractLab(file); applyReport(report); setMessage(`${report.test_results.length} result${report.test_results.length === 1 ? "" : "s"} added from ${file.name}.`); } catch (error) { setMessage(error instanceof Error ? error.message : "Lab extraction failed."); } finally { setParsing(false); } }
  function updateResult(index: number, key: keyof TestResult, value: string) { setPatientData(current => ({ ...current, test_results: current.test_results.map((result, resultIndex) => resultIndex === index ? { ...result, [key]: value } : result) })); }
  async function submit() {
    setMessage("Submitting patient intake...");
    try {
      const payload: IntakePayload = { personal_details: { name: patientData.name.trim(), age_years: patientData.age_years ? Number(patientData.age_years) : null, sex: patientData.sex.trim(), referred_by: patientData.referred_by.trim(), registration_no: patientData.registration_no.trim(), report_date: patientData.report_date.trim() }, presentation: { complaint: patientData.complaint.trim(), nursing_assessment: patientData.nursing_assessment.trim() }, vitals: Object.fromEntries(Object.entries(patientData.vitals).map(([key, value]) => [key, value === "" ? null : Number(value)])), laboratory: { test_results: patientData.test_results } };
      // Submitting doesn't just calculate a number any more — it creates a
      // live, queued patient on the same board Voice Intake and the
      // scripted scenario feed. `ok: false` (e.g. an empty form) is a real
      // outcome to show, not just an HTTP failure.
      const result = await submitIntake(payload);
      if (!result.ok) { setMessage(result.error || "Patient intake submission failed."); return; }
      setRisk({ ari: result.ari!, esi: result.esi!, confidence: result.confidence! });
      setMessage(`${result.display_id} added to the live board — ARI ${result.ari}, ESI ${result.esi}. Review it on the Triage Dashboard.`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Patient intake submission failed.");
    }
  }
  const setVital = (key: keyof PatientData["vitals"], value: string) => setPatientData(current => ({ ...current, vitals: { ...current.vitals, [key]: value } }));

  return <main className="page-wrap intake-page"><div className="page-heading"><div><p className="eyebrow">New patient assessment</p><h1>Patient intake</h1><p>Combine patient context, live dictation, vital signs, and verified laboratory evidence.</p></div>{risk && <div className="risk-result"><span>Arrival Risk Index</span><strong>{risk.ari}</strong><small>ESI {risk.esi} · {risk.confidence} confidence</small></div>}</div>
    <section className="intake-section"><div className="section-title"><span>01</span><div><h2>Personal details</h2><p>Demographics and identifiers from the patient or report.</p></div></div><div className="field-grid four"><Field label="Patient name" value={patientData.name} onChange={value => update("name", value)} placeholder="Full name" /><Field label="Age" value={patientData.age_years} onChange={value => update("age_years", value)} type="number" placeholder="Years" /><Field label="Sex" value={patientData.sex} onChange={value => update("sex", value)} placeholder="Sex" /><Field label="Registration number" value={patientData.registration_no} onChange={value => update("registration_no", value)} placeholder="MRN" /><Field label="Referred by" value={patientData.referred_by} onChange={value => update("referred_by", value)} placeholder="Clinician or service" /><Field label="Report date" value={patientData.report_date} onChange={value => update("report_date", value)} placeholder="DD/MM/YYYY" /></div></section>
    <section className="intake-section"><div className="section-title"><span>02</span><div><h2>Presentation and vitals</h2><p>Capture the reason for arrival and observations at intake.</p></div></div><div className="field-grid six">{([['Heart rate','heart_rate','bpm'],['Systolic BP','systolic_bp','mmHg'],['Diastolic BP','diastolic_bp','mmHg'],['Respiratory rate','resp_rate','/min'],['Oxygen saturation','spo2','%'],['Temperature','temperature','°C']] as const).map(([label, key, unit]) => <label className="intake-field" key={key}><span>{label} <em>{unit}</em></span><input type="number" value={patientData.vitals[key]} onChange={event => setVital(key, event.target.value)} /></label>)}</div><div className="notes-grid"><div><label className="textarea-label">Chief complaint</label><textarea value={patientData.complaint} onChange={event => update("complaint", event.target.value)} placeholder="Primary reason for presentation" /><VoiceIntake submitToBackend={false} onTranscript={text => update("complaint", patientData.complaint ? `${patientData.complaint} ${text}` : text)} /></div><div><label className="textarea-label">Nursing assessment</label><textarea value={patientData.nursing_assessment} onChange={event => update("nursing_assessment", event.target.value)} placeholder="Observations, symptoms, and relevant context" /><VoiceIntake submitToBackend={false} onTranscript={text => update("nursing_assessment", patientData.nursing_assessment ? `${patientData.nursing_assessment} ${text}` : text)} /></div></div></section>
    <section className="intake-section"><div className="section-title"><span>03</span><div><h2>Diagnostic results</h2><p>Upload reports sequentially, then review every extracted value.</p></div></div><div className={`intake-dropzone ${dragging ? "dragging" : ""}`} onClick={() => fileInput.current?.click()} onDragOver={event => { event.preventDefault(); setDragging(true); }} onDragLeave={() => setDragging(false)} onDrop={event => { event.preventDefault(); setDragging(false); void handleFile(event.dataTransfer.files[0]); }}><input ref={fileInput} hidden type="file" accept="application/pdf,.pdf" onChange={event => { void handleFile(event.target.files?.[0]); event.currentTarget.value = ""; }} /><strong>{parsing ? "Parsing laboratory report..." : "Drop a PDF report here"}</strong><span>or click to browse · PDF files only</span></div>{patientData.test_results.length > 0 && <div className="editable-results">{patientData.test_results.map((result, index) => <div className="editable-result" key={`${result.test_name}-${index}`}><input aria-label="Test name" value={result.test_name} onChange={event => updateResult(index, "test_name", event.target.value)} /><input aria-label="Test value" value={result.value} onChange={event => updateResult(index, "value", event.target.value)} /><input aria-label="Test unit" value={result.unit || ""} onChange={event => updateResult(index, "unit", event.target.value)} placeholder="Unit" /><input aria-label="Reference range" value={result.reference_range || ""} onChange={event => updateResult(index, "reference_range", event.target.value)} placeholder="Reference range" /><button type="button" onClick={() => setPatientData(current => ({ ...current, test_results: current.test_results.filter((_, resultIndex) => resultIndex !== index) }))}>Remove</button></div>)}</div>}{patientData.test_results.length > 0 && <button className="secondary-action" type="button" onClick={() => fileInput.current?.click()}>+ Upload another report</button>}<div className="intake-status">{message}</div></section>
    <div className="intake-submit"><div><strong>Ready for clinical review?</strong><span>The full reviewed payload will be sent to the ARI assessment endpoint.</span></div><button className="primary-action" type="button" onClick={submit}>Calculate Arrival Risk Index</button></div>
  </main>;
}

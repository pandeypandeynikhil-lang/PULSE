"use client";

import { useRef, useState } from "react";
import { extractLab } from "@/lib/api";
import type { LabReport } from "@/lib/types";

export default function LabUpload({ onExtracted }: { onExtracted?: (report: LabReport) => void }) {
  const input = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState("");
  const [report, setReport] = useState<LabReport | null>(null);

  async function upload(file?: File) {
    if (!file) return;
    if (file.type !== "application/pdf") { setMessage("Please choose a PDF lab report."); return; }
    setLoading(true); setMessage("Reading lab report with Docling and Ollama...");
    try {
      const result = await extractLab(file);
      setReport(result);
      setMessage(`Extracted ${result.test_results.length} test result${result.test_results.length === 1 ? "" : "s"}.`);
      onExtracted?.(result);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Lab report extraction failed.");
    } finally { setLoading(false); }
  }

  return <section className="lab-upload panel">
    <div className="ph"><b>Lab report</b><span className="sub">PDF extraction · Docling + Ollama</span></div>
    <div className={`lab-dropzone ${dragging ? "dragging" : ""}`} onClick={() => input.current?.click()}
      onDragOver={event => { event.preventDefault(); setDragging(true); }}
      onDragLeave={() => setDragging(false)}
      onDrop={event => { event.preventDefault(); setDragging(false); void upload(event.dataTransfer.files[0]); }}>
      <input ref={input} type="file" accept="application/pdf,.pdf" hidden onChange={event => { void upload(event.target.files?.[0]); event.currentTarget.value = ""; }} />
      <span className="upload-icon">PDF</span>
      <strong>{loading ? "Extracting report..." : "Drop a lab PDF here"}</strong>
      <span>or click to browse your computer</span>
    </div>
    <div className="lab-status">{message}</div>
    {report && <div className="lab-preview">
      <div className="lab-meta"><span><b>Patient</b>{report.name || "Not found"}</span><span><b>Age</b>{report.age_years ?? "Not found"}</span><span><b>Sex</b>{report.sex || "Not found"}</span><span><b>Date</b>{report.report_date || "Not found"}</span></div>
      <div className="lab-results">{report.test_results.slice(0, 6).map(test => <div className="lab-result" key={`${test.test_name}-${test.value}`}><b>{test.test_name}</b><span className={test.abnormality_flag ? "abnormal" : ""}>{test.value} {test.unit || ""}</span></div>)}{report.test_results.length > 6 && <span className="lab-more">+ {report.test_results.length - 6} more results</span>}</div>
    </div>}
  </section>;
}

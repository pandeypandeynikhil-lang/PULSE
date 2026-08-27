"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { getModel } from "@/lib/api";
import {
  IconArrow, IconEye, IconGlobe, IconLayers, IconMic, IconShield, IconTrend, PulseMark,
} from "./Icons";

const FEATURES = [
  { Icon: IconMic, title: "Voice intake, any language", body: "A companion who doesn't share the nurse's language speaks; PULSE translates, extracts red flags, and queues a scored patient in the same pipeline as everyone else." },
  { Icon: IconLayers, title: "Six layers, one explainable score", body: "Vitals, symptom narrative, SIRS criteria, and lab findings fuse into one Arrival Risk Index — a weighted formula a nurse can be talked through, not a black box." },
  { Icon: IconTrend, title: "Deterioration doesn't wait for rounds", body: "Every waiting — and every admitted — patient is re-scored continuously. A trajectory crossing a tier boundary raises a fresh recommendation on its own." },
  { Icon: IconEye, title: "Every number shows its work", body: "SHAP contributions on the vitals model, matched phrase spans on the complaint, SIRS criteria met — the reasoning is on screen, not just the result." },
  { Icon: IconShield, title: "A human gate on every acuity", body: "PULSE suggests a bed, a specialist, an ESI level. A nurse accepts or overrides — every time, logged either way." },
  { Icon: IconGlobe, title: "Degrades, never dies", body: "LLM extraction tries two independent providers, then falls back to a deterministic offline matcher. The board keeps scoring even with no network at all." },
];

export default function Landing() {
  const [model, setModel] = useState<{ roc_auc: number; sensitivity: number; undertriage_rate: number; n_test: number } | null>(null);
  useEffect(() => { getModel().then(setModel).catch(() => undefined); }, []);

  return (
    <main className="landing">
      <div className="landing-glow" aria-hidden />

      <header className="landing-top">
        <span className="landing-brand"><PulseMark width={20} height={20} />PULSE</span>
        <Link href="/dashboard" className="landing-enter">Enter workspace<IconArrow width={15} height={15} /></Link>
      </header>

      <section className="landing-hero">
        <span className="landing-badge">Accenture Innovation Challenge 2026 · PatientTriage.ai</span>
        <h1>The Triage Co-pilot<br />Beside Every Nurse</h1>
        <p className="landing-sub">
          PULSE fuses vitals, symptom narrative, lab findings, and live department
          state into one explainable priority signal — and keeps updating it for
          as long as the patient is waiting.
        </p>
        <p className="landing-tagline">PULSE never assigns an acuity level. A nurse does. Every time.</p>
        <div className="landing-cta">
          <Link href="/dashboard" className="primary-action landing-pill">Enter the dashboard<IconArrow width={16} height={16} /></Link>
          <Link href="/intake" className="landing-secondary">Start a patient intake</Link>
        </div>
      </section>

      <p className="landing-eyebrow-line">A glimpse into the six-layer scoring engine</p>

      <section className="landing-features">
        {FEATURES.map(({ Icon, title, body }) => (
          <div className="landing-card" key={title}>
            <span className="landing-card-icon"><Icon width={20} height={20} /></span>
            <h3>{title}</h3>
            <p>{body}</p>
          </div>
        ))}
      </section>

      <section className="landing-stats">
        <div className="landing-stats-hd">
          <h2>Measured, not asserted</h2>
          <p>Held-out test set — every number below is a real measurement, regenerated with <code>python -m backend.ml.train</code>.</p>
        </div>
        <div className="landing-stats-grid">
          <div className="landing-stat"><strong>{model ? model.roc_auc : "—"}</strong><span>ROC-AUC</span></div>
          <div className="landing-stat"><strong>{model ? `${(model.sensitivity * 100).toFixed(1)}%` : "—"}</strong><span>sensitivity <em>ESI: 65.9%</em></span></div>
          <div className="landing-stat"><strong>{model ? `${(model.undertriage_rate * 100).toFixed(1)}%` : "—"}</strong><span>under-triage <em>ESI: 3.3%</em></span></div>
          <div className="landing-stat"><strong>{model ? model.n_test.toLocaleString() : "—"}</strong><span>held-out encounters</span></div>
        </div>
      </section>

      <footer className="landing-footer">
        <div>
          <strong>Ready to see it live?</strong>
          <span>The department is simulated and the clock runs on its own — open the dashboard and watch it work.</span>
        </div>
        <Link href="/dashboard" className="primary-action landing-pill">Enter the dashboard<IconArrow width={16} height={16} /></Link>
      </footer>
    </main>
  );
}

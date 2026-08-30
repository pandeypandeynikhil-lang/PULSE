"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { getModel } from "@/lib/api";
import {
  IconArrow,
  IconEye,
  IconGlobe,
  IconLayers,
  IconMic,
  IconShield,
  IconTrend,
  PulseMark,
} from "./Icons";

// Three bespoke illustrations for the showcase strip below the hero — the
// same "hand-authored SVG, no stock imagery" convention Icons.tsx already
// holds to, just scaled up into art rather than a 24×24 glyph. Each reads as
// the thing it represents (a trajectory crossing a tier line, a spoken
// phrase resolving into English, three signals converging on one score)
// rather than generic medical decoration, so the panel is doing real work,
// not just filling space the way a stock photo would.
function ArtDeterioration() {
  return (
    <svg viewBox="0 0 400 240" fill="none" aria-hidden>
      <defs>
        <radialGradient id="sc-g1" cx="78%" cy="24%" r="65%">
          <stop offset="0%" stopColor="rgba(255,147,166,0.32)" />
          <stop offset="100%" stopColor="rgba(255,147,166,0)" />
        </radialGradient>
        <linearGradient id="sc-line1" x1="0" y1="1" x2="1" y2="0">
          <stop offset="0%" stopColor="#8fb8ff" />
          <stop offset="100%" stopColor="#ff93a6" />
        </linearGradient>
      </defs>
      <rect width="400" height="240" fill="url(#sc-g1)" />
      <line x1="20" y1="150" x2="380" y2="150" stroke="#2b2240" strokeWidth="1.5" strokeDasharray="5 6" />
      <line x1="20" y1="92" x2="380" y2="92" stroke="#2b2240" strokeWidth="1.5" strokeDasharray="5 6" />
      <text x="30" y="145" fontFamily="var(--mono)" fontSize="10" fill="#8779a3">ESI IV</text>
      <text x="30" y="87" fontFamily="var(--mono)" fontSize="10" fill="#8779a3">ESI II</text>
      <path
        d="M30 168 L84 164 L138 152 L192 130 L246 100 L300 68 L340 46"
        stroke="url(#sc-line1)"
        strokeWidth="3"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <circle cx="340" cy="46" r="6" fill="#ff93a6" />
      <circle cx="340" cy="46" r="12" fill="none" stroke="#ff93a6" strokeWidth="1.4" opacity="0.55" />
      <circle cx="340" cy="46" r="19" fill="none" stroke="#ff93a6" strokeWidth="1" opacity="0.3" />
    </svg>
  );
}

function ArtVoice() {
  return (
    <svg viewBox="0 0 400 240" fill="none" aria-hidden>
      <defs>
        <radialGradient id="sc-g2" cx="50%" cy="42%" r="60%">
          <stop offset="0%" stopColor="rgba(143,227,184,0.3)" />
          <stop offset="100%" stopColor="rgba(143,227,184,0)" />
        </radialGradient>
      </defs>
      <rect width="400" height="240" fill="url(#sc-g2)" />
      {[26, 42, 58].map((r) => (
        <circle key={r} cx="200" cy="110" r={r} stroke="#4fbe8c" strokeWidth="1.3" opacity={0.5 - r / 140} />
      ))}
      <rect x="188" y="78" width="24" height="44" rx="12" fill="none" stroke="#8fe3b8" strokeWidth="2" />
      <path d="M172 108a28 28 0 0 0 56 0" stroke="#8fe3b8" strokeWidth="2" strokeLinecap="round" fill="none" />
      <path d="M200 136v14M188 150h24" stroke="#8fe3b8" strokeWidth="2" strokeLinecap="round" />
      <rect x="46" y="168" width="88" height="30" rx="8" fill="#171123" stroke="#2b2240" />
      <text x="90" y="187" textAnchor="middle" fontFamily="var(--mono)" fontSize="11" fill="#b6a8d3">कोई भाषा</text>
      <path d="M140 183h56" stroke="#4fbe8c" strokeWidth="1.6" strokeLinecap="round" strokeDasharray="1 7" />
      <path d="M188 176l10 7-10 7" stroke="#4fbe8c" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" fill="none" />
      <rect x="266" y="168" width="88" height="30" rx="8" fill="#171123" stroke="#4fbe8c" />
      <text x="310" y="187" textAnchor="middle" fontFamily="var(--mono)" fontSize="11" fill="#8fe3b8">chest pain</text>
    </svg>
  );
}

function ArtFusion() {
  const nodes = [
    { x: 44, y: 46, c: "#8fb8ff", label: "vitals" },
    { x: 44, y: 120, c: "#ffce85", label: "symptoms" },
    { x: 44, y: 194, c: "#b9a6ff", label: "labs" },
  ];
  return (
    <svg viewBox="0 0 400 240" fill="none" aria-hidden>
      <defs>
        <radialGradient id="sc-g3" cx="82%" cy="50%" r="55%">
          <stop offset="0%" stopColor="rgba(185,166,255,0.3)" />
          <stop offset="100%" stopColor="rgba(185,166,255,0)" />
        </radialGradient>
      </defs>
      <rect width="400" height="240" fill="url(#sc-g3)" />
      {nodes.map((n) => (
        <g key={n.label}>
          <path d={`M${n.x + 8} ${n.y} C 170 ${n.y}, 230 120, 300 120`} stroke={n.c} strokeWidth="1.6" opacity="0.55" fill="none" />
          <circle cx={n.x} cy={n.y} r="7" fill={n.c} />
          <text x={n.x} y={n.y + 24} textAnchor="middle" fontFamily="var(--mono)" fontSize="10" fill="#8779a3">{n.label}</text>
        </g>
      ))}
      <circle cx="300" cy="120" r="17" fill="none" stroke="#b9a6ff" strokeWidth="1.4" opacity="0.5" />
      <circle cx="300" cy="120" r="10" fill="#b9a6ff" />
      <text x="300" y="164" textAnchor="middle" fontFamily="var(--mono)" fontWeight={700} fontSize="12" fill="#f2eefa">ARI</text>
    </svg>
  );
}

const SHOWCASE = [
  {
    art: ArtDeterioration,
    title: "Deterioration Engine",
    body: "PT 11 arrived low-acuity — nothing in the words or the first vitals said otherwise. PULSE re-scores every waiting patient on a loop and caught the trajectory crossing a tier boundary anyway, without anyone asking it to.",
  },
  {
    art: ArtVoice,
    title: "Voice Intake, Any Language",
    body: "A patient or companion who doesn't share the nurse's language speaks. PULSE translates, extracts the red flags, and a scored patient joins the same queue as everyone else — seconds later.",
  },
  {
    art: ArtFusion,
    title: "Six Signals, One Explainable Score",
    body: "Vitals, symptom narrative, SIRS criteria and lab findings fuse into one Arrival Risk Index — a transparent, SHAP-explained formula a nurse can be talked through, never a black box.",
  },
];

const FEATURES = [
  {
    Icon: IconMic,
    title: "Voice intake, any language",
    body: "A companion who doesn't share the nurse's language speaks; PULSE translates, extracts red flags, and queues a scored patient in the same pipeline as everyone else.",
  },
  {
    Icon: IconLayers,
    title: "Six layers, one explainable score",
    body: "Vitals, symptom narrative, SIRS criteria, and lab findings fuse into one Arrival Risk Index — a weighted formula a nurse can be talked through, not a black box.",
  },
  {
    Icon: IconTrend,
    title: "Deterioration doesn't wait for rounds",
    body: "Every waiting — and every admitted — patient is re-scored continuously. A trajectory crossing a tier boundary raises a fresh recommendation on its own.",
  },
  {
    Icon: IconEye,
    title: "Every number shows its work",
    body: "SHAP contributions on the vitals model, matched phrase spans on the complaint, SIRS criteria met — the reasoning is on screen, not just the result.",
  },
  {
    Icon: IconShield,
    title: "A human gate on every acuity",
    body: "PULSE suggests a bed, a specialist, an ESI level. A nurse accepts or overrides — every time, logged either way.",
  },
  {
    Icon: IconGlobe,
    title: "Degrades, never dies",
    body: "LLM extraction tries two independent providers, then falls back to a deterministic offline matcher. The board keeps scoring even with no network at all.",
  },
];

export default function Landing() {
  const [model, setModel] = useState<{
    roc_auc: number;
    sensitivity: number;
    undertriage_rate: number;
    n_test: number;
  } | null>(null);
  useEffect(() => {
    getModel()
      .then(setModel)
      .catch(() => undefined);
  }, []);

  return (
    <main className="landing">
      <div className="landing-glow" aria-hidden />

      <header className="landing-top">
        <span className="landing-brand">
          <PulseMark width={20} height={20} />
          PULSE
        </span>
        <Link href="/dashboard" className="landing-enter">
          Enter workspace
          <IconArrow width={15} height={15} />
        </Link>
      </header>

      <section className="landing-hero">
        <span className="landing-badge">
          Accenture Innovation Challenge 2026 · PatientTriage.ai
        </span>
        <h1>
          The Triage Co-pilot
          <br />
          Beside Every Nurse
        </h1>
        <p className="landing-sub">
          PULSE fuses vitals, symptom narrative, lab findings, and live
          department state into one explainable priority signal — and keeps
          updating it for as long as the patient is waiting.
        </p>
        <p className="landing-tagline">
          PULSE never assigns an acuity level. A nurse does. Every time.
        </p>
        <div className="landing-cta">
          <Link href="/dashboard" className="primary-action landing-pill">
            Enter the dashboard
            <IconArrow width={16} height={16} />
          </Link>
          <Link href="/intake" className="landing-secondary">
            Start a patient intake
          </Link>
        </div>
      </section>

      <p className="landing-eyebrow-line landing-eyebrow-line--first">
        Helping a nurse see risk before a chart does
      </p>

      <section className="landing-showcase">
        {SHOWCASE.map(({ art: Art, title, body }) => (
          <div className="showcase-card" key={title}>
            <div className="showcase-art">
              <Art />
            </div>
            <h3>{title}</h3>
            <p>{body}</p>
          </div>
        ))}
      </section>

      <p className="landing-eyebrow-line">
        A glimpse into the six-layer scoring engine
      </p>

      <section className="landing-features">
        {FEATURES.map(({ Icon, title, body }) => (
          <div className="landing-card" key={title}>
            <span className="landing-card-icon">
              <Icon width={20} height={20} />
            </span>
            <h3>{title}</h3>
            <p>{body}</p>
          </div>
        ))}
      </section>

      <section className="landing-stats">
        <div className="landing-stats-hd">
          <h2>Measured, not asserted</h2>
          <p>
            Held-out test set — every number below is a real measurement, go to your virtual environment, regenerate with <code>python -m ml.train</code>.
          </p>
        </div>
        <div className="landing-stats-grid">
          <div className="landing-stat">
            <strong>{model ? model.roc_auc : "—"}</strong>
            <span>ROC-AUC</span>
          </div>
          <div className="landing-stat">
            <strong>
              {model ? `${(model.sensitivity * 100).toFixed(1)}%` : "—"}
            </strong>
            <span>
              sensitivity <em>ESI: 65.9%</em>
            </span>
          </div>
          <div className="landing-stat">
            <strong>
              {model ? `${(model.undertriage_rate * 100).toFixed(1)}%` : "—"}
            </strong>
            <span>
              under-triage <em>ESI: 3.3%</em>
            </span>
          </div>
          <div className="landing-stat">
            <strong>{model ? model.n_test.toLocaleString() : "—"}</strong>
            <span>held-out encounters</span>
          </div>
        </div>
      </section>

      <footer className="landing-footer">
        <div>
          <strong>Ready to see it live?</strong>
          <span>
            The department is simulated and the clock runs on its own — open the
            dashboard and watch it work.
          </span>
        </div>
        <Link href="/dashboard" className="primary-action landing-pill">
          Enter the dashboard
          <IconArrow width={16} height={16} />
        </Link>
      </footer>
    </main>
  );
}

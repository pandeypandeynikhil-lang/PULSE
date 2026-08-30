"use client";

import { useEffect, useState } from "react";
import { API_ORIGIN, getBoard } from "@/lib/api";
import type { AmbulancePosition, AmbulanceStatus, BoardState } from "@/lib/types";
import { IconClose } from "./Icons";

// No map tiles, no external SDK, no API key — a bearing/distance radar
// can never fail from venue wifi or a routing service being down, which
// matters more for a live demo than road-accurate rendering does. The
// underlying data (ambulance.py) still tracks real road distance; this
// view just doesn't need literal lat/lng to show it.
const MAX_KM = 22;
const SIZE = 560;
const RADIUS = SIZE / 2 - 56;
const CENTER = SIZE / 2;

function toneOf(status: AmbulanceStatus) {
  return status === "arrived" ? "arrived" : status === "dispatched" ? "dispatched" : "en-route";
}

function polar(bearing: number, distanceKm: number) {
  const r = Math.min(distanceKm / MAX_KM, 1) * RADIUS;
  const rad = (bearing * Math.PI) / 180;
  return { x: Math.sin(rad) * r, y: -Math.cos(rad) * r };
}

// A professional emergency-marker glyph, not a plain dot: a red badge with
// a white cross, the same visual language real map products use for EMS —
// instantly readable as "ambulance" at a glance, and legible against the
// dark radar at a size that would turn a literal vehicle silhouette to mush.
function AmbulanceMarker({ amb, selected, onSelect }: { amb: AmbulancePosition; selected: boolean; onSelect: () => void }) {
  const { x, y } = polar(amb.bearing, amb.distance_km);
  const tone = toneOf(amb.status);
  return (
    <g
      className={`radar-marker ${tone} ${selected ? "selected" : ""}`}
      transform={`translate(${CENTER + x}, ${CENTER + y})`}
      onClick={onSelect}
      role="button"
      aria-label={`${amb.display_id}, ${amb.status.replace("_", " ")}, ${amb.distance_km} km out`}
    >
      {tone === "en-route" && <circle className="radar-marker-pulse" r={11} />}
      <circle className="radar-marker-badge" r={11} />
      <path className="radar-marker-cross" d="M0 -5.5v11M-5.5 0h11" />
      <text className="radar-marker-label" y={-17}>{amb.display_id}</text>
    </g>
  );
}

function DetailRow({ label, value }: { label: string; value: string }) {
  return <div className="radar-detail-row"><span>{label}</span><b>{value}</b></div>;
}

function AmbulanceDetail({ amb, onClose }: { amb: AmbulancePosition; onClose: () => void }) {
  const tone = toneOf(amb.status);
  return (
    <>
      <div className="scrim on" onClick={onClose} />
      <aside className="drawer on">
        <div className="dhead">
          <div>
            <div className="tag">{amb.callsign} · {amb.vehicle_type}</div>
            <h2>{amb.display_id}</h2>
          </div>
          <button onClick={onClose}><IconClose width={15} height={15} /></button>
        </div>
        <div className="dbody">
          <div className="sec">
            <h4>Status</h4>
            <div className="quote" style={{ borderLeftColor: tone === "en-route" ? "var(--green)" : tone === "dispatched" ? "var(--amber)" : "var(--dim)" }}>
              <b>{amb.status.replace("_", " ")}</b> · {amb.distance_km.toFixed(1)} km out ·{" "}
              {amb.status === "arrived" ? "at the ED" : `ETA ${Math.round(amb.eta_min)} min`}
            </div>
          </div>
          <div className="sec">
            <h4>Vehicle &amp; crew</h4>
            <div className="radar-details">
              <DetailRow label="Vehicle number" value={amb.vehicle_number} />
              <DetailRow label="Callsign" value={amb.callsign} />
              <DetailRow label="Vehicle type" value={amb.vehicle_type} />
              <DetailRow label="Driver" value={amb.driver} />
              <DetailRow label="Paramedic" value={amb.paramedic} />
            </div>
          </div>
          <div className="sec">
            <h4>Dispatch</h4>
            <p className="radar-origin">From {amb.origin}</p>
            <div className="quote">{amb.note}</div>
          </div>
          <div className="sec">
            <h4>Route</h4>
            <div className="radar-details">
              <DetailRow label="Total route distance" value={`${amb.total_distance_km.toFixed(1)} km`} />
              <DetailRow label="Remaining" value={`${amb.distance_km.toFixed(1)} km`} />
              <DetailRow label="Progress" value={`${Math.round(amb.progress * 100)}%`} />
            </div>
            <div className="radar-progress" style={{ marginTop: 11 }}><i style={{ width: `${amb.progress * 100}%` }} /></div>
          </div>
        </div>
      </aside>
    </>
  );
}

export default function AmbulanceRadar() {
  const [state, setState] = useState<BoardState | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  // Same pattern as every other live page: interval as the baseline,
  // WebSocket overwriting state the moment a broadcast arrives.
  useEffect(() => {
    const refresh = () => getBoard().then(setState).catch(() => undefined);
    refresh();
    const timer = window.setInterval(refresh, 1000);
    return () => window.clearInterval(timer);
  }, []);
  useEffect(() => {
    const socket = new WebSocket(`${API_ORIGIN.replace(/^http/, "ws")}/ws`);
    socket.onmessage = (event) => setState(JSON.parse(event.data));
    return () => socket.close();
  }, []);

  if (!state) return <main className="page-wrap"><p className="loading">Connecting to PULSE...</p></main>;

  const ambulances = state.ambulances || [];
  const inbound = ambulances.filter((a) => a.status !== "arrived");
  const selected = ambulances.find((a) => a.id === selectedId) || null;
  const rings = [0.25, 0.5, 0.75, 1];

  return (
    <main className="page-wrap">
      <div className="page-heading">
        <div>
          <p className="eyebrow">Live inbound fleet</p>
          <h1>Ambulance tracking</h1>
          <p>Real road distance and ETA for every ambulance en route, interpolated along its actual route every second. Click a marker for vehicle and crew details.</p>
        </div>
        <div className="risk-result">
          <span>Inbound now</span>
          <strong>{inbound.length}</strong>
          <small>of {ambulances.length} tracked this shift</small>
        </div>
      </div>

      <div className="radar-layout">
        <div className="radar-wrap">
          <svg viewBox={`0 0 ${SIZE} ${SIZE}`} className="radar-svg" role="img" aria-label="Ambulance positions relative to the hospital">
            <defs>
              <radialGradient id="radarFace" cx="50%" cy="50%" r="65%">
                <stop offset="0%" stopColor="rgba(122,90,230,.10)" />
                <stop offset="100%" stopColor="rgba(122,90,230,0)" />
              </radialGradient>
            </defs>
            <circle cx={CENTER} cy={CENTER} r={RADIUS} fill="url(#radarFace)" />
            {rings.map((f) => (
              <circle key={f} cx={CENTER} cy={CENTER} r={RADIUS * f} className="radar-ring" />
            ))}
            {rings.slice(0, -1).map((f) => (
              <text key={f} x={CENTER + 6} y={CENTER - RADIUS * f - 6} className="radar-ring-label">
                {Math.round(MAX_KM * f)} km
              </text>
            ))}
            <line x1={CENTER} y1={CENTER - RADIUS} x2={CENTER} y2={CENTER + RADIUS} className="radar-axis" />
            <line x1={CENTER - RADIUS} y1={CENTER} x2={CENTER + RADIUS} y2={CENTER} className="radar-axis" />
            <g className="radar-sweep-group" style={{ transformOrigin: `${CENTER}px ${CENTER}px` }}>
              <path d={`M ${CENTER} ${CENTER} L ${CENTER} ${CENTER - RADIUS} A ${RADIUS} ${RADIUS} 0 0 1 ${CENTER + RADIUS * Math.sin(Math.PI / 6)} ${CENTER - RADIUS * Math.cos(Math.PI / 6)} Z`} className="radar-sweep" />
            </g>
            {ambulances.map((amb) => (
              <AmbulanceMarker key={amb.id} amb={amb} selected={amb.id === selectedId}
                onSelect={() => setSelectedId(amb.id === selectedId ? null : amb.id)} />
            ))}
            <circle cx={CENTER} cy={CENTER} r={13} className="radar-hospital" />
            <circle cx={CENTER} cy={CENTER} r={13} className="radar-hospital-pulse" />
          </svg>
          <span className="radar-center-label">ED</span>
          <div className="radar-legend">
            <span><i className="dot en-route" />En route</span>
            <span><i className="dot dispatched" />Dispatched</span>
            <span><i className="dot arrived" />Arrived</span>
          </div>
        </div>

        <div className="radar-list">
          {ambulances.length === 0 && <p className="note">No ambulances currently tracked.</p>}
          {ambulances.map((amb) => {
            const tone = toneOf(amb.status);
            return (
              <button className={`radar-card ${tone} ${amb.id === selectedId ? "selected" : ""}`} key={amb.id}
                onClick={() => setSelectedId(amb.id === selectedId ? null : amb.id)}>
                <div className="radar-card-hd">
                  <strong>{amb.display_id}</strong>
                  <span className={`radar-status ${tone}`}>{amb.status.replace("_", " ")}</span>
                </div>
                <p className="radar-origin">From {amb.origin} · {amb.callsign}</p>
                <p className="radar-note">{amb.note}</p>
                <div className="radar-metrics">
                  <span><b>{amb.distance_km.toFixed(1)}</b> km out</span>
                  <span><b>{Math.round(amb.eta_min)}</b> min ETA</span>
                </div>
                <div className="radar-progress"><i style={{ width: `${amb.progress * 100}%` }} /></div>
              </button>
            );
          })}
        </div>
      </div>

      {selected && <AmbulanceDetail amb={selected} onClose={() => setSelectedId(null)} />}
    </main>
  );
}

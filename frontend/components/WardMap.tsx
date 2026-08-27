"use client";

import { useEffect, useState } from "react";
import { API_ORIGIN, getBoard, setBedStatus, setClinicianStatus } from "@/lib/api";
import type { Bed, BedStatus, BoardState, Clinician, ClinicianStatus } from "@/lib/types";
import { IconBed, IconClinician } from "./Icons";

// Only these transitions are a staff member's to make by clicking a box.
// "occupied" / "busy" are never in this cycle — they only ever happen
// through Engine.decide() committing an actual patient to the resource, so
// a box can't be clicked into looking occupied without one behind it.
const BED_CYCLE: Record<BedStatus, BedStatus> = {
  available: "cleaning", cleaning: "unavailable", unavailable: "available",
  occupied: "occupied",
};
const CLINICIAN_CYCLE: Record<ClinicianStatus, ClinicianStatus> = {
  available: "off_shift", off_shift: "available", busy: "busy",
};

const BED_LABEL: Record<BedStatus, string> = {
  available: "Available", occupied: "Occupied", cleaning: "Cleaning", unavailable: "Unavailable",
};
const CLINICIAN_LABEL: Record<ClinicianStatus, string> = {
  available: "Available", busy: "With patient", off_shift: "Off shift",
};

function groupBy<T>(items: T[], key: (item: T) => string): [string, T[]][] {
  const groups = new Map<string, T[]>();
  for (const item of items) {
    const k = key(item);
    groups.set(k, [...(groups.get(k) || []), item]);
  }
  return [...groups.entries()];
}

function count<T>(items: T[], pred: (item: T) => boolean) {
  return items.filter(pred).length;
}

function BedBox({ bed, patientLabel, onCycle }: { bed: Bed; patientLabel?: string; onCycle: () => void }) {
  const clickable = bed.status !== "occupied";
  return (
    <button
      className={`ward-box bed ${bed.status}`}
      onClick={clickable ? onCycle : undefined}
      disabled={!clickable}
      title={clickable ? `Click to mark ${BED_LABEL[BED_CYCLE[bed.status]].toLowerCase()}` : `Occupied by ${patientLabel ?? bed.patient_id}`}
    >
      <span className="ward-box-icon"><IconBed width={15} height={15} /></span>
      <span className="ward-box-body">
        <span className="ward-box-id">{bed.id}</span>
        <span className="ward-box-status">{bed.status === "occupied" ? (patientLabel ?? bed.patient_id) : BED_LABEL[bed.status]}</span>
      </span>
    </button>
  );
}

function ClinicianBox({ clinician, patientLabel, onCycle }: { clinician: Clinician; patientLabel?: string; onCycle: () => void }) {
  const clickable = clinician.status !== "busy";
  return (
    <button
      className={`ward-box clinician ${clinician.status}`}
      onClick={clickable ? onCycle : undefined}
      disabled={!clickable}
      title={clickable ? `Click to mark ${CLINICIAN_LABEL[CLINICIAN_CYCLE[clinician.status]].toLowerCase()}` : `With ${patientLabel ?? clinician.patient_id}`}
    >
      <span className="ward-box-icon"><IconClinician width={15} height={15} /></span>
      <span className="ward-box-body">
        <span className="ward-box-id">{clinician.name}</span>
        <span className="ward-box-status">{clinician.status === "busy" ? (patientLabel ?? clinician.patient_id) : CLINICIAN_LABEL[clinician.status]}</span>
      </span>
    </button>
  );
}

function StatTile({ n, label, tone }: { n: number; label: string; tone: string }) {
  return <div className={`ward-stat ${tone}`}><strong>{n}</strong><span>{label}</span></div>;
}

function WardCard({ name, beds, displayFor, onCycle }: {
  name: string; beds: Bed[];
  displayFor: (id: string | null) => string | undefined;
  onCycle: (bed: Bed) => void;
}) {
  const free = count(beds, (b) => b.status === "available");
  const pct = beds.length ? Math.round((free / beds.length) * 100) : 0;
  const tightness = free === 0 ? "none" : pct <= 34 ? "low" : "";
  return (
    <div className="ward-card">
      <div className="ward-card-hd">
        <h3>{name}</h3>
        <span className="ward-frac">{free}/{beds.length} free</span>
      </div>
      <span className="ward-capbar"><i className={tightness} style={{ width: `${pct}%` }} /></span>
      <div className="ward-grid">
        {beds.map((bed) => (
          <BedBox key={bed.id} bed={bed} patientLabel={displayFor(bed.patient_id)} onCycle={() => onCycle(bed)} />
        ))}
      </div>
    </div>
  );
}

function ClinicianCard({ specialty, clinicians, displayFor, onCycle }: {
  specialty: string; clinicians: Clinician[];
  displayFor: (id: string | null) => string | undefined;
  onCycle: (c: Clinician) => void;
}) {
  const free = count(clinicians, (c) => c.status === "available");
  return (
    <div className="ward-card">
      <div className="ward-card-hd">
        <h3>{specialty}</h3>
        <span className="ward-frac">{clinicians.length ? `${free}/${clinicians.length} free` : "0 on roster"}</span>
      </div>
      {clinicians.length === 0
        ? <p className="note">Always pages out — see Layer 5&apos;s notes on the patient drawer.</p>
        : <div className="ward-grid">
            {clinicians.map((c) => (
              <ClinicianBox key={c.id} clinician={c} patientLabel={displayFor(c.patient_id)} onCycle={() => onCycle(c)} />
            ))}
          </div>}
    </div>
  );
}

export default function WardMap() {
  const [state, setState] = useState<BoardState | null>(null);

  // Same pattern as Dashboard: an interval as the baseline (works even if
  // the WebSocket never connects) plus a live socket overwriting state the
  // moment a broadcast arrives, so a bed a nurse just accepted doesn't wait
  // up to a second to show occupied here.
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

  const displayFor = (patientId: string | null) =>
    patientId ? state.rows.find((r) => r.id === patientId)?.display_id : undefined;

  const bedGroups = groupBy(state.beds, (b) => b.ward);
  // Grouped from the full specialty roster (capacity.specialists), not just
  // from clinicians present — a specialty with zero staff (vascular
  // surgery, in the base scenario) is exactly the case Layer 5 flags as
  // "page required", and it should show up here as an empty card rather
  // than silently disappear because there was no one to group.
  const clinicianGroups: [string, Clinician[]][] = Object.keys(state.capacity.specialists)
    .sort()
    .map((specialty) => [specialty, state.clinicians.filter((c) => c.specialty === specialty)]);

  async function cycleBed(bed: Bed) {
    const next = BED_CYCLE[bed.status];
    if (next === bed.status) return;
    await setBedStatus(bed.id, next);
  }
  async function cycleClinician(clinician: Clinician) {
    const next = CLINICIAN_CYCLE[clinician.status];
    if (next === clinician.status) return;
    await setClinicianStatus(clinician.id, next);
  }

  const beds = state.beds, clinicians = state.clinicians;

  return (
    <main className="page-wrap ward-page">
      <div className="page-heading">
        <div>
          <p className="eyebrow">Live department state</p>
          <h1>Ward map</h1>
          <p>Every bed and clinician Layer 5 routes against, updated the moment a nurse accepts a recommendation or marks a bed clean.</p>
        </div>
      </div>

      <div className="ward-stats">
        <StatTile n={count(beds, b => b.status === "available")} label="beds free" tone="available" />
        <StatTile n={count(beds, b => b.status === "occupied")} label="beds occupied" tone="occupied" />
        <StatTile n={count(beds, b => b.status === "cleaning")} label="beds cleaning" tone="cleaning" />
        <StatTile n={count(beds, b => b.status === "unavailable")} label="beds out of service" tone="unavailable" />
        <StatTile n={count(clinicians, c => c.status === "available")} label="clinicians free" tone="available" />
        <StatTile n={count(clinicians, c => c.status === "busy")} label="clinicians with patients" tone="occupied" />
      </div>

      <section>
        <div className="section-title"><span>Beds</span>
          <div><h2>Bed status by ward</h2><p>Green is free to route to. Click any box that isn&apos;t occupied to change it — occupied beds only clear when a patient is reassigned or discharged.</p></div>
        </div>
        <div className="ward-cards">
          {bedGroups.map(([wardName, wardBeds]) => (
            <WardCard key={wardName} name={wardName} beds={wardBeds} displayFor={displayFor} onCycle={cycleBed} />
          ))}
        </div>
      </section>

      <section>
        <div className="section-title"><span>Staff</span>
          <div><h2>Clinician availability by specialty</h2><p>A specialty with no one listed pages out rather than routing silently.</p></div>
        </div>
        <div className="ward-cards">
          {clinicianGroups.map(([specialty, specialtyClinicians]) => (
            <ClinicianCard key={specialty} specialty={specialty} clinicians={specialtyClinicians} displayFor={displayFor} onCycle={cycleClinician} />
          ))}
        </div>
      </section>
    </main>
  );
}

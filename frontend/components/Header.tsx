"use client";

import type { BoardState } from "@/lib/types";
import { post } from "@/lib/api";

export default function Header({ onAction }: { onAction: () => void }) {
  async function control(path: string) { await post(path); onAction(); }
  return <header className="top">
    <div className="brand"><b>PULSE</b><span>Triage co-pilot</span></div>
    <div className="legend"><span className="dot green" />PULSE decides<span className="dot red" />Nurse decides</div>
    <div className="ctrl"><button className="wide" onClick={() => control("/api/control/reset")}>Reset</button></div>
  </header>;
}

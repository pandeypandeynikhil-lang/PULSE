"use client";

import type { BoardState } from "@/lib/types";
import { post } from "@/lib/api";
import { IconReset } from "./Icons";

export default function Header({ onAction }: { onAction: () => void }) {
  async function control(path: string) {
    await post(path);
    onAction();
  }
  return (
    <header className="top">
      <div className="brand">
        <b>PULSE</b>
        <span>Triage co-pilot</span>
      </div>
      <div className="legend">
        <span className="dot green" />
        PULSE decides
        <span className="dot red" />
        Nurse decides
      </div>
      <div className="ctrl">
        <button className="wide" onClick={() => control("/api/control/reset")}>
          <IconReset width={14} height={14} />
          Reset
        </button>
      </div>
    </header>
  );
}

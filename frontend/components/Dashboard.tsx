"use client";

import { useEffect, useState } from "react";
import Header from "./Header";
import LiveBoard from "./LiveBoard";
import Sidebar from "./Sidebar";
import PatientDrawer from "./PatientDrawer";
import { API_ORIGIN, getBoard } from "@/lib/api";
import type { BoardState } from "@/lib/types";

export default function Dashboard() {
  const [state, setState] = useState<BoardState | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const refresh = () =>
    getBoard()
      .then(setState)
      .catch(() => undefined);
  useEffect(() => {
    refresh();
    const timer = window.setInterval(refresh, 1000);
    return () => window.clearInterval(timer);
  }, []);
  useEffect(() => {
    if (!state) return;
    const socket = new WebSocket(`${API_ORIGIN.replace(/^http/, "ws")}/ws`);
    socket.onmessage = (event) => setState(JSON.parse(event.data));
    return () => socket.close();
  }, []);
  if (!state) return <main className="loading">Connecting to PULSE...</main>;
  const patient = state.rows.find((row) => row.id === open) || null;
  return (
    <>
      <Header onAction={refresh} />
      <main className="grid">
        <LiveBoard patients={state.rows} onOpen={setOpen} engineTime={state.engine.current_time} />
        <Sidebar state={state} onRefresh={refresh} />
      </main>
      <PatientDrawer
        patient={patient}
        engineTime={state.engine.current_time}
        onClose={() => setOpen(null)}
        onAction={refresh}
      />
    </>
  );
}

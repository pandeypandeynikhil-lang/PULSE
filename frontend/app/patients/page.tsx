"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { API_ORIGIN } from "@/lib/api";

export default function PatientsPage() {
  const router = useRouter();
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<
    {
      id: string;
      display_id: string;
      name?: string;
      complaint?: string;
      status?: string;
    }[]
  >([]);
  async function search(value: string) {
    setQuery(value);
    if (!value.trim()) {
      setResults([]);
      return;
    }
    const response = await fetch(
      `${API_ORIGIN}/api/patients/search?q=${encodeURIComponent(value)}`,
    );
    setResults(await response.json());
  }
  return (
    <main className="page-wrap patient-search-page">
      <div className="page-heading">
        <div>
          <p className="eyebrow">Patient records</p>
          <h1>Search &amp; edit patient</h1>
          <p>Find a patient profile by name or registration ID.</p>
        </div>
      </div>
      <section className="patient-search-panel">
        <input
          autoFocus
          value={query}
          onChange={(event) => search(event.target.value)}
          placeholder="Search by patient name or display ID"
        />
        <div className="patient-search-results">
          {results.map((patient) => (
            <button
              type="button"
              key={patient.id}
              onClick={() => router.push(`/patients/${patient.id}`)}
            >
              <span>
                <b>{patient.name || patient.display_id}</b>
                <small>
                  {patient.display_id} ·{" "}
                  {patient.complaint || "No complaint recorded"}
                </small>
              </span>
              <em>{patient.status}</em>
            </button>
          ))}
        </div>
      </section>
    </main>
  );
}

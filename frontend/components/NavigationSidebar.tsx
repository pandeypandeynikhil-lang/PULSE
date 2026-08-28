"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { getBoard } from "@/lib/api";
import type { BoardState } from "@/lib/types";
import { IconDashboard, IconIntake, IconWard, PulseMark } from "./Icons";

const links = [
  { href: "/intake", label: "Patient Intake", Icon: IconIntake },
  { href: "/dashboard", label: "Triage Dashboard", Icon: IconDashboard },
  { href: "/patients", label: "Search/Edit Patient", Icon: IconDashboard },
  { href: "/ward", label: "Ward Map", Icon: IconWard },
];

export default function NavigationSidebar() {
  const pathname = usePathname();
  const [state, setState] = useState<BoardState | null>(null);
  useEffect(() => {
    const refresh = () => getBoard().then(setState).catch(() => undefined);
    refresh();
    const timer = window.setInterval(refresh, 1000);
    return () => window.clearInterval(timer);
  }, []);
  return <aside className="navigation-sidebar">
    <Link href="/" className="nav-brand">
      <span className="nav-mark"><PulseMark width={18} height={18} /></span>
      <div><strong>PULSE</strong><small>Clinical workspace</small></div>
    </Link>
    <div className="nav-section-label">Workspace</div>
    <nav aria-label="Primary navigation">
      {links.map(({ href, label, Icon }) => (
        <Link key={href} href={href} className={`nav-link ${pathname === href ? "active" : ""}`}>
          <span className="nav-icon"><Icon width={17} height={17} /></span>{label}
        </Link>
      ))}
    </nav>
    {state && <section className="nav-department-state">
      <div className="nav-section-label">Department state</div>
      <div className="nav-capacity">
        {Object.entries(state.capacity.beds).map(([name, count]) => <div key={name}><span>{name}</span><b>{count}</b></div>)}
        <div><span>Staff on shift</span><b>{state.capacity.staff_on}</b></div>
      </div>
    </section>}
    <div className="nav-footer"><span className="status-dot" />Local services connected</div>
  </aside>;
}

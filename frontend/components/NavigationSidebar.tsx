"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { IconDashboard, IconIntake, IconWard, PulseMark } from "./Icons";

const links = [
  { href: "/intake", label: "Patient Intake", Icon: IconIntake },
  { href: "/dashboard", label: "Triage Dashboard", Icon: IconDashboard },
  { href: "/ward", label: "Ward Map", Icon: IconWard },
];

export default function NavigationSidebar() {
  const pathname = usePathname();
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
    <div className="nav-footer"><span className="status-dot" />Local services connected</div>
  </aside>;
}

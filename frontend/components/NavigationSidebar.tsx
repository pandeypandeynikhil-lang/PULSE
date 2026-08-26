"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const links = [
  { href: "/intake", label: "Patient Intake", icon: "+" },
  { href: "/dashboard", label: "Triage Dashboard", icon: "~" },
  { href: "/ward", label: "Ward Map", icon: "#" },
];

export default function NavigationSidebar() {
  const pathname = usePathname();
  return <aside className="navigation-sidebar">
    <div className="nav-brand"><span className="nav-mark">P</span><div><strong>PULSE</strong><small>Clinical workspace</small></div></div>
    <div className="nav-section-label">Workspace</div>
    <nav aria-label="Primary navigation">{links.map(link => <Link key={link.href} href={link.href} className={`nav-link ${pathname === link.href ? "active" : ""}`}><span className="nav-icon">{link.icon}</span>{link.label}</Link>)}</nav>
    <div className="nav-footer"><span className="status-dot" />Local services connected</div>
  </aside>;
}

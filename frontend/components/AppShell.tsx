"use client";

import { usePathname } from "next/navigation";
import NavigationSidebar from "./NavigationSidebar";

export default function AppShell({ children }: Readonly<{ children: React.ReactNode }>) {
  // The landing page is the one place PULSE gets to look like a product
  // page rather than a clinical workspace — full-bleed, no workspace
  // chrome. Every route past it is the actual tool, and keeps the sidebar.
  const isLanding = usePathname() === "/";
  if (isLanding) return <>{children}</>;
  return <div className="app-shell"><NavigationSidebar /><div className="app-content">{children}</div></div>;
}

import type { Metadata } from "next";
import { Baloo_2, JetBrains_Mono, Manrope } from "next/font/google";
import "./globals.css";
import AppShell from "@/components/AppShell";

// Self-hosted at build time by next/font — no runtime request to Google's
// CDN, so this doesn't cost PULSE its offline-capable backend story; it's
// the same "ship the asset" principle the rest of the project applies to
// everything else. Baloo 2 for headlines (the confident, rounded, soothing
// display voice the redesign is built around); Manrope for everything you
// actually have to read at speed on a clinical screen; JetBrains Mono for
// the handful of places that are genuinely numeric readouts, not labels.
const display = Baloo_2({ subsets: ["latin"], weight: ["600", "700", "800"], variable: "--font-display" });
const sans = Manrope({ subsets: ["latin"], weight: ["400", "500", "600", "700", "800"], variable: "--font-sans" });
const mono = JetBrains_Mono({ subsets: ["latin"], weight: ["400", "500", "600", "700"], variable: "--font-mono" });

export const metadata: Metadata = {
  title: "PULSE - Triage co-pilot",
  description: "Patient Urgency & Load Sequencing Engine",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" className={`${display.variable} ${sans.variable} ${mono.variable}`}>
      <body><AppShell>{children}</AppShell></body>
    </html>
  );
}

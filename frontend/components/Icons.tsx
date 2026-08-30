// Small, stroke-based, hand-authored icons — no icon library dependency.
// Every path uses currentColor so an icon inherits whatever the surrounding
// text color is (active nav state, status tint, etc.) instead of carrying
// its own hardcoded fill, and every one shares the same 1.6 stroke weight
// and rounded caps so the set reads as one family rather than a grab-bag.
import type { SVGProps } from "react";

type IconProps = SVGProps<SVGSVGElement>;
const base = { width: 20, height: 20, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: 1.6, strokeLinecap: "round" as const, strokeLinejoin: "round" as const };

export function PulseMark(props: IconProps) {
  // The brand mark: a heartbeat trace inside a rounded square, standing in
  // for the wordmark's dot in small spaces (tab favicon-style, nav badge).
  return <svg {...base} {...props}><path d="M3 12h4l2-7 4 14 2-7h6" /></svg>;
}
export function IconIntake(props: IconProps) {
  return <svg {...base} {...props}><rect x="5" y="4" width="14" height="17" rx="2.5" /><path d="M9 3.5h6v2.5H9z" /><path d="M9 12.5h4M9 16h6" /></svg>;
}
export function IconDashboard(props: IconProps) {
  return <svg {...base} {...props}><path d="M3 13h4l2-8 4 15 2-9 2 2h4" /></svg>;
}
export function IconWard(props: IconProps) {
  return <svg {...base} {...props}><rect x="3" y="5" width="8" height="8" rx="1.6" /><rect x="13" y="5" width="8" height="8" rx="1.6" /><rect x="3" y="15" width="8" height="6" rx="1.6" /><rect x="13" y="15" width="8" height="6" rx="1.6" /></svg>;
}
export function IconBed(props: IconProps) {
  return <svg {...base} {...props}><path d="M3 19v-8a2 2 0 0 1 2-2h6" /><path d="M3 15h18v4" /><path d="M13 9h6a2 2 0 0 1 2 2v4" /><circle cx="7" cy="7" r="1.6" /></svg>;
}
export function IconClinician(props: IconProps) {
  return <svg {...base} {...props}><path d="M6 4v4a3 3 0 0 0 6 0V4" /><path d="M6 4H4.5M12 4h1.5" /><path d="M9 11v3a5 5 0 0 0 5 5h1" /><circle cx="18.5" cy="18.5" r="2.5" /></svg>;
}
export function IconMic(props: IconProps) {
  return <svg {...base} {...props}><rect x="9" y="3" width="6" height="11" rx="3" /><path d="M5 11a7 7 0 0 0 14 0" /><path d="M12 18v3M9 21h6" /></svg>;
}
export function IconArrow(props: IconProps) {
  return <svg {...base} {...props}><path d="M5 12h14M13 6l6 6-6 6" /></svg>;
}
export function IconEye(props: IconProps) {
  return <svg {...base} {...props}><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7Z" /><circle cx="12" cy="12" r="2.6" /></svg>;
}
export function IconTrend(props: IconProps) {
  return <svg {...base} {...props}><path d="M4 16l5-6 4 3 7-9" /><path d="M15 4h5v5" /></svg>;
}
export function IconShield(props: IconProps) {
  return <svg {...base} {...props}><path d="M12 3l7 3v6c0 4.5-3 7.5-7 9-4-1.5-7-4.5-7-9V6l7-3Z" /><path d="M9 12l2 2 4-4" /></svg>;
}
export function IconLayers(props: IconProps) {
  return <svg {...base} {...props}><path d="M12 3l9 5-9 5-9-5 9-5Z" /><path d="M3 13l9 5 9-5" /><path d="M3 17.5l9 5 9-5" /></svg>;
}
export function IconGlobe(props: IconProps) {
  return <svg {...base} {...props}><circle cx="12" cy="12" r="9" /><path d="M3 12h18M12 3c2.8 2.6 4.2 5.7 4.2 9S14.8 18.4 12 21c-2.8-2.6-4.2-5.7-4.2-9S9.2 5.6 12 3Z" /></svg>;
}
export function IconClose(props: IconProps) {
  return <svg {...base} {...props}><path d="M6 6l12 12M18 6L6 18" /></svg>;
}
export function IconReset(props: IconProps) {
  return <svg {...base} {...props}><path d="M20 12a8 8 0 1 1-2.6-5.9" /><path d="M20 4v5h-5" /></svg>;
}
export function IconAmbulance(props: IconProps) {
  return <svg {...base} {...props}><rect x="2" y="9" width="13" height="8" rx="1.5" /><path d="M15 12h4l3 3v2h-7z" /><path d="M7 6.5v5M4.5 9h5" /><circle cx="7" cy="19" r="1.8" /><circle cx="17" cy="19" r="1.8" /></svg>;
}

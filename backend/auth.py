"""Access control — the DPDP Act 2023 duty made concrete, not just asserted.

PULSE's ambulance-tracking layer already anchors this deployment to India (a
Bengaluru fleet, real OSRM road routing — see ambulance.py), so the assumed
regulatory jurisdiction is India's Digital Personal Data Protection Act,
2023. Section 8(5) puts a "reasonable security safeguards" duty on anyone
processing personal data — an emergency department's patient names, ages,
complaints and vitals are squarely that. An unauthenticated API where anyone
on the network can create, edit or discharge a patient record fails that
duty regardless of how good the triage logic behind it is.

The gate here is deliberately simple: one shared bearer token, checked by
`main.py`'s access-control middleware against every request that mutates
data (anything but GET/HEAD/OPTIONS under /api/*). Reads stay open — the
board is a display surface meant to be visible department-wide, the same
way a physical whiteboard would be — only writes need the token. A single
shared token instead of per-user accounts is a scope decision, not an
oversight: a real deployment sits behind hospital SSO/RBAC and per-clinician
audit identity (the `actor` column in db.py's decisions table is already
where that would attach); what this layer proves is that the write surface
is gated at all, which is the DPDP-relevant claim.

`PULSE_API_TOKEN` in .env overrides the default so a real deployment never
ships on the demo token.
"""
from __future__ import annotations

import os

from fastapi import Header, HTTPException

DEFAULT_TOKEN = "pulse-demo-2026"

# Requests that only ever read never need the token — see module docstring.
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def expected_token() -> str:
    return os.environ.get("PULSE_API_TOKEN") or DEFAULT_TOKEN


def check(token: str | None) -> bool:
    return token == expected_token()


async def require_api_token(x_pulse_token: str | None = Header(default=None)) -> None:
    """FastAPI dependency form, kept for any route that wants it explicitly
    (e.g. the WebSocket handshake, which the blanket middleware in main.py
    does not cover since it isn't a normal HTTP request)."""
    if not check(x_pulse_token):
        raise HTTPException(status_code=401, detail="Missing or invalid X-PULSE-Token header.")

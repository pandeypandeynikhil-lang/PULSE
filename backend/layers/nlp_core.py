"""Shared red-flag extraction. Used by Layer 0 (pre-arrival audio) and Layer 2
(in-person chief complaint) — deliberately the same code path, because the
clinical meaning of "crushing chest pain" does not change with who said it.

In production the primary extractor is an LLM call grounded on this lexicon,
with a second provider as failover. This deterministic matcher is the third
rung: it needs no network, so PULSE degrades rather than dies.
"""
from __future__ import annotations

import json
import os
import re
from typing import Any

_HERE = os.path.dirname(os.path.abspath(__file__))
_LEX_PATH = os.path.join(_HERE, "..", "..", "data", "clinical_lexicon.json")

with open(_LEX_PATH, "r", encoding="utf-8") as _f:
    LEXICON: dict[str, Any] = json.load(_f)

_COMPILED = [
    (flag, [re.compile(r"\b" + p + r"\b", re.I) for p in flag["patterns"]])
    for flag in LEXICON["flags"]
]
_AGE = [re.compile(p, re.I) for p in LEXICON["age_extractors"]]


def extract(text: str) -> dict[str, Any]:
    """Return matched red flags, the exact spans that matched, and a 0-1 score.

    The spans matter as much as the score: the nurse sees her patient's own
    words highlighted, not a number with no provenance.
    """
    if not text:
        return {"flags": [], "spans": [], "severity": 0.0, "age": None, "systems": []}

    hits, spans = [], []
    for flag, patterns in _COMPILED:
        for rx in patterns:
            m = rx.search(text)
            if m:
                hits.append(flag)
                spans.append({"start": m.start(), "end": m.end(),
                              "text": m.group(0), "flag": flag["id"],
                              "label": flag["label"], "weight": flag["weight"]})
                break

    age = None
    for rx in _AGE:
        m = rx.search(text)
        if m:
            try:
                v = int(m.group(1))
                if 0 < v < 120:
                    age = v
                    break
            except (ValueError, IndexError):
                pass

    # Severity is a saturating combination, not a sum: three cardiac red flags
    # is not three times one. We take the strongest signal and let the rest add
    # diminishing weight on top.
    weights = sorted((f["weight"] for f in hits), reverse=True)
    severity = 0.0
    for i, w in enumerate(weights):
        severity += w * (0.45 ** i)
    severity = min(severity, 1.0)

    return {
        "flags": [{"id": f["id"], "label": f["label"], "weight": f["weight"],
                   "system": f["system"]} for f in hits],
        "spans": sorted(spans, key=lambda s: s["start"]),
        "severity": round(severity, 4),
        "age": age,
        "systems": sorted({f["system"] for f in hits}),
    }

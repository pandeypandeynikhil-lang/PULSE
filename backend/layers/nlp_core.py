"""Shared red-flag extraction for the in-person chief complaint.

Three tiers, tried in order by `extract()`:
  1. LLM extraction (`nlp_llm.py`), grounded on this lexicon's closed
     vocabulary — only active when PULSE_NLP_MODE=llm and at least one of
     GEMINI_API_KEY / GROQ_API_KEY is set. Catches phrasing the fixed
     patterns below don't anticipate.
  2. A second LLM provider, tried automatically if the first fails — see
     nlp_llm.py. Two vendors, not one, so a single provider's outage doesn't
     drop straight to tier 3 mid-demo.
  3. This deterministic matcher. It needs no network, so PULSE degrades
     rather than dies — and it is what runs by default, so a demo never
     depends on wifi at the venue.

Whichever tier answers, the contract returned is identical. The one visible
difference is `source`, stamped on the result for the audit trail and the
nurse console's "extracted by" badge — the failover is meant to be seen, not
hidden.
"""
from __future__ import annotations

import json
import os
import re
from typing import Any

from dotenv import load_dotenv

# Loaded here, not only in main.py: this module is the one that actually
# reads PULSE_NLP_MODE (in extract(), below), and it has other entry points
# — backend/ml/eval_nlp.py in particular — that never import main.py and so
# would otherwise never see .env at all. Idempotent and a safe no-op if
# there's no .env file, or if the process environment already has these set.
load_dotenv()

_HERE = os.path.dirname(os.path.abspath(__file__))
_LEX_PATH = os.path.join(_HERE, "..", "..", "data", "clinical_lexicon.json")

with open(_LEX_PATH, "r", encoding="utf-8") as _f:
    LEXICON: dict[str, Any] = json.load(_f)

_COMPILED = [
    (flag, [re.compile(r"\b" + p + r"\b", re.I) for p in flag["patterns"]])
    for flag in LEXICON["flags"]
]
_AGE = [re.compile(p, re.I) for p in LEXICON["age_extractors"]]
_BY_ID = {f["id"]: f for f in LEXICON["flags"]}

# Extraction is deterministic per input text (the sim never mutates a
# patient's complaint/transcript mid-shift), so memoising on the text itself
# is safe — and it is what keeps the once-a-second scheduler tick from
# re-calling an LLM for a sentence it has already scored.
_CACHE: dict[str, dict[str, Any]] = {}


def extract(text: str) -> dict[str, Any]:
    """Return matched red flags, the exact spans that matched, and a 0-1 score.

    The spans matter as much as the score: the nurse sees her patient's own
    words highlighted, not a number with no provenance.
    """
    if not text:
        return {"flags": [], "spans": [], "severity": 0.0, "age": None,
                "systems": [], "source": "lexicon"}

    cached = _CACHE.get(text)
    if cached is not None:
        return cached

    result = None
    if os.environ.get("PULSE_NLP_MODE", "lexicon") == "llm":
        result = _extract_via_llm(text)
    if result is None:
        result = _extract_lexicon(text)

    _CACHE[text] = result
    return result


def _extract_age(text: str) -> int | None:
    for rx in _AGE:
        m = rx.search(text)
        if m:
            try:
                v = int(m.group(1))
                if 0 < v < 120:
                    return v
            except (ValueError, IndexError):
                pass
    return None


def _severity(hits: list[dict[str, Any]]) -> float:
    # Severity is a saturating combination, not a sum: three cardiac red flags
    # is not three times one. We take the strongest signal and let the rest
    # add diminishing weight on top.
    weights = sorted((f["weight"] for f in hits), reverse=True)
    severity = 0.0
    for i, w in enumerate(weights):
        severity += w * (0.45 ** i)
    return round(min(severity, 1.0), 4)


def _extract_lexicon(text: str) -> dict[str, Any]:
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

    return {
        "flags": [{"id": f["id"], "label": f["label"], "weight": f["weight"],
                   "system": f["system"]} for f in hits],
        "spans": sorted(spans, key=lambda s: s["start"]),
        "severity": _severity(hits),
        "age": _extract_age(text),
        "systems": sorted({f["system"] for f in hits}),
        "source": "lexicon",
    }


def _extract_via_llm(text: str) -> dict[str, Any] | None:
    """Returns None on any failure — the caller falls through to the lexicon
    tier. Never raises past this boundary."""
    from . import nlp_llm  # local import: keeps the gemini/groq SDKs optional
                            # unless PULSE_NLP_MODE=llm is actually set
    raw = nlp_llm.extract_llm(text, LEXICON)
    if raw is None:
        return None

    hits, spans = [], []
    lower = text.lower()
    for item in raw.get("flags", []):
        meta = _BY_ID.get(item.get("id"))
        quote = (item.get("quote") or "").strip()
        if not meta or not quote:
            continue
        # Never trust a model-reported offset — locate the quote ourselves in
        # the source text, and drop the flag entirely if it can't be found
        # verbatim. A flag with no provenance in the patient's own words is
        # not a flag PULSE will show a nurse.
        idx = lower.find(quote.lower())
        if idx < 0:
            continue
        hits.append(meta)
        spans.append({"start": idx, "end": idx + len(quote),
                      "text": text[idx:idx + len(quote)], "flag": meta["id"],
                      "label": meta["label"], "weight": meta["weight"]})

    age = raw.get("age")
    if not (isinstance(age, int) and 0 < age < 120):
        age = _extract_age(text)

    provider = raw.get("_provider")
    return {
        "flags": [{"id": f["id"], "label": f["label"], "weight": f["weight"],
                   "system": f["system"]} for f in hits],
        "spans": sorted(spans, key=lambda s: s["start"]),
        "severity": _severity(hits),
        "age": age,
        "systems": sorted({f["system"] for f in hits}),
        "source": f"llm-{provider}" if provider else "llm",
    }

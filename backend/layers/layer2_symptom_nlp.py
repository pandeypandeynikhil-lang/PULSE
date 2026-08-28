"""Layer 2 — Symptom NLP on the in-person chief complaint."""
from __future__ import annotations

import re
from typing import Any

from .nlp_core import extract

# A nurse's own note that an intervention is already under way ("IV access
# obtained", "oxygen applied") is a stronger severity signal than any
# pattern match on the complaint — clinical gestalt the red-flag lexicon
# can't see. But a bare substring match can't tell "oxygen applied" from
# "oxygen not required": the same word appears in both. These are checked
# for a negation word within a short window on either side of the match
# before counting — the standard, cheap way clinical NLP handles this
# (not full negation scope parsing, but enough to stop "not", "no",
# "denies", "without" right next to the keyword from flipping the meaning).
_INTERVENTION_KEYWORDS = [
    "iv access", "iv fluid", "oxygen", "o2 applied", "ecg", "ekg",
    "cpr", "resuscitation",
]
_NEGATIONS = {
    "not", "no", "without", "denies", "denied", "declined", "refused",
    "isn't", "wasn't", "didn't", "doesn't", "don't", "never", "n't",
}
_WORD_STRIP = ".,;:!?()\"'"


def _negated_near(text_lower: str, start: int, end: int, window: int = 4) -> bool:
    before = text_lower[:start].split()[-window:]
    after = text_lower[end:].split()[:window]
    return any(w.strip(_WORD_STRIP) in _NEGATIONS for w in before + after)


def _gestalt_intervention(text: str) -> bool:
    lowered = text.lower()
    for keyword in _INTERVENTION_KEYWORDS:
        for match in re.finditer(re.escape(keyword), lowered):
            if not _negated_near(lowered, match.start(), match.end()):
                return True
    return False


def score(complaint: str, nursing_assessment: str = "") -> dict[str, Any]:
    comp_nlp = extract(complaint)
    nurse_nlp = (extract(nursing_assessment) if nursing_assessment else {
        "severity": 0.0, "flags": [], "spans": [], "systems": [],
        "source": "lexicon",
    })
    gestalt_intervention = _gestalt_intervention(nursing_assessment)
    combined_flags = comp_nlp.get("flags", []) + nurse_nlp.get("flags", [])
    combined_spans = comp_nlp.get("spans", []) + nurse_nlp.get("spans", [])
    combined_systems = list(dict.fromkeys(
        comp_nlp.get("systems", []) + nurse_nlp.get("systems", [])
    ))
    base_severity = max(comp_nlp.get("severity", 0.0) * 0.7,
                        nurse_nlp.get("severity", 0.0))
    final_severity = (max(base_severity, 0.85)
                      if gestalt_intervention else base_severity)
    return {
        "severity": final_severity,
        "flags": combined_flags,
        "spans": combined_spans,
        "systems": combined_systems,
        "nlp_source": comp_nlp.get("source", "lexicon"),
    }

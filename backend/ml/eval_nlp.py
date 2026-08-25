"""Evaluate the LLM extraction tier against the deterministic lexicon tier on
a small hand-labelled set of complaint/transcript strings.

This does not "grade" the LLM against clinician-reviewed ground truth — we
don't have that data, and pretending otherwise would violate the same data
honesty this project applies to the vitals model. What it checks is narrower
and defensible: does the LLM tier at least recover what the lexicon already
catches (regression), and does it catch phrasing the lexicon's fixed patterns
were never going to match (the actual reason to add it)?

Requires PULSE_NLP_MODE=llm and at least one of GEMINI_API_KEY / GROQ_API_KEY
to exercise the LLM path; without that, only the lexicon tier is reported.

Run: python -m backend.ml.eval_nlp
"""
from __future__ import annotations

import os

from ..layers import nlp_llm
from ..layers.nlp_core import _extract_lexicon, _extract_via_llm  # noqa: SLF001  eval-only

# (text, expected_flag_ids) — hand-labelled by reading the sentence the way a
# clinician would. Small and meant to be extended, not exhaustive. The last
# few rows are phrased deliberately outside the lexicon's fixed patterns —
# that's the gap the LLM tier exists to close.
CASES: list[tuple[str, set[str]]] = [
    ("He's 58, clutching his chest, grey and sweating through his shirt. Can't get a full breath.",
     {"chest_pain", "diaphoresis", "pallor", "dyspnoea"}),
    ("Feeling tired and off-colour since this morning.", set()),
    ("Sudden worst headache of my life, room's spinning.", {"thunderclap"}),
    ("Her face is drooping on the left and her speech is slurred, started twenty minutes ago.",
     {"focal_deficit", "sudden_onset"}),
    ("Twisted my ankle on the stairs, it's swollen.", {"minor_injury"}),
    ("Threw up blood twice in the last hour, feels faint.", {"haemorrhage", "syncope"}),
    ("Shivering and burning up, hasn't passed urine since yesterday.", {"sepsis_signs"}),
    # Outside the lexicon's exact wording — a real recall test for the LLM tier.
    ("It feels like an elephant is sitting on my chest and I've gone cold and clammy.",
     {"chest_pain", "diaphoresis"}),
    ("One side of her mouth just stopped working and she can't get her words out right.",
     {"focal_deficit"}),
    ("He went down like a sack of potatoes and was out cold for a bit.",
     {"syncope"}),
]


def _ids(flags: list[dict]) -> set[str]:
    return {f["id"] for f in flags}


def main() -> None:
    llm_enabled = (os.environ.get("PULSE_NLP_MODE") == "llm"
                   and nlp_llm.any_provider_configured())
    print("LLM tier:", "enabled" if llm_enabled else
          "DISABLED — set PULSE_NLP_MODE=llm and GEMINI_API_KEY/GROQ_API_KEY to exercise it")
    print()

    lex_correct = llm_correct = 0
    for text, expected in CASES:
        lex_ids = _ids(_extract_lexicon(text)["flags"])
        lex_ok = lex_ids == expected
        lex_correct += lex_ok
        print(f"{text!r}")
        print(f"  lexicon {'OK  ' if lex_ok else 'MISS'} got={sorted(lex_ids)} want={sorted(expected)}")

        if llm_enabled:
            raw = _extract_via_llm(text)
            llm_ids = _ids(raw["flags"]) if raw else set()
            llm_ok = llm_ids == expected
            llm_correct += llm_ok
            provider = raw["source"] if raw else "unavailable"
            tag = "OK  " if llm_ok else ("MISS" if raw else "MISS (tier unavailable)")
            print(f"  llm     {tag} ({provider}) got={sorted(llm_ids)} want={sorted(expected)}")
        print()

    n = len(CASES)
    print(f"lexicon agreement: {lex_correct}/{n}")
    if llm_enabled:
        print(f"llm agreement:     {llm_correct}/{n}")


if __name__ == "__main__":
    main()

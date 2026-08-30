"""Layer 2c — Probable Presentation.

Not a diagnosis, and it never claims to be one. This is a deterministic
pattern-matcher over evidence the rest of the pipeline already computed —
Layer 2's matched red flags, Layer 1b's SIRS verdict, Layer 1's directional
SHAP drivers — mapped against a small, curated table of clinical
presentation patterns. It names the working hypotheses a clinician would
reasonably consider given the same evidence already on screen, each with a
transparent, capped confidence built from how many independent signals
corroborate it — the same "drop what you can't trust, show your work"
principle layer3_fusion.py already applies to the Arrival Risk Index,
applied here to a differential instead of a single risk number.

No LLM call, no network dependency: everything this reads (flags, systems,
SIRS, SHAP direction) is already sitting in memory by the time fuse() runs,
so this is nearly free and works fully offline, same as the rest of the
pipeline's deterministic floor.
"""
from __future__ import annotations

from typing import Any

# A real differential is never one name — it's a ranked set of competing
# explanations for the same evidence. So most flags here nominate MORE than
# one pattern: a primary reading (higher base, usually the one a corroborating
# vital or SIRS also supports) and at least one lower-confidence alternative
# that the same words are also consistent with. `base` is the starting
# confidence for a single matched flag; `step` is the (diminishing) credit
# for each additional flag from this pattern's own set that also matched.
# `drivers` are the vitals-model SHAP features that corroborate it if also
# elevated/depressed; `sirs_weight` is how much a positive SIRS check adds —
# non-zero for infective/systemic patterns, smaller for the milder
# alternative reading of the same signs, zero where SIRS is irrelevant.
# Deliberately small and conservative — well-known ED presentation clusters
# tied directly to clinical_lexicon.json's own flag ids, not an attempt at
# exhaustive differential diagnosis.
PATTERNS: list[dict[str, Any]] = [
    # Chest pain cluster
    {"name": "Acute Coronary Syndrome", "system": "cardiac",
     "flags": {"chest_pain", "diaphoresis"}, "drivers": {"heart_rate", "shock_index", "systolic_bp"},
     "base": 42, "step": 14, "sirs_weight": 0},
    {"name": "Musculoskeletal / Non-Cardiac Chest Pain", "system": "cardiac",
     "flags": {"chest_pain"}, "drivers": set(),
     "base": 26, "step": 6, "sirs_weight": 0},

    # Vascular
    {"name": "Aortic Dissection", "system": "vascular",
     "flags": {"tearing_back"}, "drivers": {"systolic_bp", "diastolic_bp"},
     "base": 44, "step": 12, "sirs_weight": 0},
    {"name": "Musculoskeletal Back Pain", "system": "vascular",
     "flags": {"tearing_back"}, "drivers": set(),
     "base": 24, "step": 6, "sirs_weight": 0},

    # Neuro — focal / thunderclap cluster
    {"name": "Acute Ischaemic Stroke / TIA", "system": "neuro",
     "flags": {"focal_deficit", "thunderclap"}, "drivers": {"systolic_bp"},
     "base": 44, "step": 14, "sirs_weight": 0},
    {"name": "Intracranial Haemorrhage", "system": "neuro",
     "flags": {"thunderclap", "focal_deficit", "altered_mental"}, "drivers": {"systolic_bp"},
     "base": 32, "step": 10, "sirs_weight": 0},
    {"name": "Complex Migraine", "system": "neuro",
     "flags": {"thunderclap"}, "drivers": set(),
     "base": 22, "step": 4, "sirs_weight": 0},

    # Altered mental status without a focal/thunderclap flag
    {"name": "Delirium / Metabolic Encephalopathy", "system": "neuro",
     "flags": {"altered_mental"}, "drivers": {"temperature"},
     "base": 34, "step": 10, "sirs_weight": 6},

    # Infection / sepsis cluster — the same signs read two ways
    {"name": "Sepsis / Systemic Infection", "system": "infection",
     "flags": {"sepsis_signs"}, "drivers": {"heart_rate", "temperature"},
     "base": 40, "step": 14, "sirs_weight": 14},
    {"name": "Viral Syndrome / Influenza-like Illness", "system": "infection",
     "flags": {"sepsis_signs"}, "drivers": {"temperature"},
     "base": 24, "step": 6, "sirs_weight": 6},

    # Respiratory
    {"name": "Lower Respiratory Infection / Pneumonia", "system": "respiratory",
     "flags": {"dyspnoea"}, "drivers": {"resp_rate", "spo2", "temperature"},
     "base": 38, "step": 12, "sirs_weight": 12},
    {"name": "Pulmonary Embolism", "system": "respiratory",
     # "sudden_onset" boosts this once breathlessness is already in play, but
     # is far too generic (it applies to dozens of unrelated presentations —
     # a stroke, a faint, a laceration) to independently nominate PE on its
     # own; "dyspnoea" is the required anchor.
     "flags": {"dyspnoea"}, "boost_flags": {"sudden_onset"}, "drivers": {"heart_rate", "spo2", "resp_rate"},
     "base": 28, "step": 10, "sirs_weight": 0},
    {"name": "Asthma / COPD Exacerbation", "system": "respiratory",
     "flags": {"dyspnoea"}, "drivers": {"resp_rate", "spo2"},
     "base": 24, "step": 6, "sirs_weight": 0},

    # Allergy
    {"name": "Anaphylaxis", "system": "allergy",
     "flags": {"anaphylaxis"}, "drivers": {"spo2", "systolic_bp"},
     "base": 46, "step": 12, "sirs_weight": 0},
    {"name": "Localised Allergic Reaction / Angioedema", "system": "allergy",
     "flags": {"anaphylaxis"}, "drivers": set(),
     "base": 22, "step": 4, "sirs_weight": 0},

    # Trauma / haemorrhage
    {"name": "Hypovolaemic / Haemorrhagic Shock", "system": "trauma",
     "flags": {"haemorrhage"}, "drivers": {"heart_rate", "systolic_bp", "shock_index"},
     "base": 44, "step": 14, "sirs_weight": 0},
    {"name": "Gastrointestinal Bleed", "system": "trauma",
     "flags": {"haemorrhage"}, "drivers": {"heart_rate"},
     "base": 28, "step": 8, "sirs_weight": 0},

    # Abdominal
    {"name": "Acute Abdomen / Peritonitis", "system": "abdominal",
     "flags": {"abdo_rigid"}, "drivers": set(),
     "base": 40, "step": 10, "sirs_weight": 8},
    {"name": "Bowel Obstruction", "system": "abdominal",
     "flags": {"abdo_rigid"}, "drivers": set(),
     "base": 24, "step": 6, "sirs_weight": 0},

    # Seizure
    {"name": "Seizure Disorder", "system": "neuro",
     "flags": {"seizure"}, "drivers": set(),
     "base": 42, "step": 10, "sirs_weight": 0},
]

MAX_RESULTS = 4
# Never claim certainty — this is pattern-matching over the same evidence a
# nurse already sees, not a diagnosis, so the scale is capped well short of
# 100 no matter how many signals line up.
CONFIDENCE_CAP = 92
# A secondary reading isn't worth showing once it's this far behind the top
# candidate — keeps the list to genuinely competing possibilities rather
# than padding it out with near-zero noise.
MIN_SHOW = 18


def infer(symptom_out: dict[str, Any] | None, sirs_data: dict[str, Any] | None,
          vitals_out: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Returns up to MAX_RESULTS {name, system, confidence, evidence},
    ranked by confidence, dropped entirely if nothing matched. `evidence`
    is the plain-language list of what corroborated the pattern, so a nurse
    reads the same reasoning PULSE used rather than a bare percentage."""
    if not symptom_out or not symptom_out.get("flags"):
        return []

    matched_ids = {f["id"] for f in symptom_out["flags"]}
    flag_labels = {f["id"]: f["label"] for f in symptom_out["flags"]}
    sirs_positive = bool(sirs_data and sirs_data.get("sirs_positive"))
    drivers = (vitals_out or {}).get("drivers", [])
    moved = {d["feature"] for d in drivers if d.get("direction") in ("raises", "lowers")}

    results = []
    for pattern in PATTERNS:
        hit_flags = pattern["flags"] & matched_ids
        if not hit_flags:
            continue
        evidence = [f'"{flag_labels[fid]}" in the complaint' for fid in sorted(hit_flags)]

        # This pattern's own base credit for one matched flag, diminishing
        # credit for any additional one from its set — the same "a second
        # signal adds less than the first" shape nlp_core.py's own severity
        # score already uses, so two loosely-related flags don't outweigh
        # one strong one. Different patterns sharing the same flag(s) start
        # from different bases — that's how a serious reading (Sepsis) and
        # a milder alternative reading (Viral Syndrome) of the identical
        # words end up as two genuinely distinct candidates, not near-ties.
        confidence = pattern["base"] + pattern["step"] * (len(hit_flags) - 1)

        # A boost flag (e.g. "sudden_onset") never nominates a pattern by
        # itself — it only adds credit once a required flag already has —
        # so a generic modifier can sharpen a real candidate without being
        # able to conjure one out of nothing.
        hit_boosts = pattern.get("boost_flags", set()) & matched_ids
        if hit_boosts:
            confidence += pattern["step"] * len(hit_boosts)
            evidence.extend(f'"{flag_labels[fid]}" in the complaint' for fid in sorted(hit_boosts))

        driver_hit = pattern["drivers"] & moved
        if driver_hit:
            confidence += 16
            evidence.append(f"corroborating vitals ({', '.join(sorted(driver_hit))})")
        if sirs_positive and pattern["sirs_weight"]:
            confidence += pattern["sirs_weight"]
            evidence.append("SIRS criteria met")

        results.append({
            "name": pattern["name"],
            "system": pattern["system"],
            "confidence": min(confidence, CONFIDENCE_CAP),
            "evidence": evidence,
        })

    results = [r for r in results if r["confidence"] >= MIN_SHOW]
    # Two patterns can legitimately land on the same name from different
    # flag combinations (e.g. altered_mental corroborating both Sepsis and
    # Delirium separately) — keep only the strongest instance of each.
    best_by_name: dict[str, dict[str, Any]] = {}
    for r in results:
        prior = best_by_name.get(r["name"])
        if prior is None or r["confidence"] > prior["confidence"]:
            best_by_name[r["name"]] = r
    ranked = sorted(best_by_name.values(), key=lambda r: r["confidence"], reverse=True)
    return ranked[:MAX_RESULTS]

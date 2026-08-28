"""End-to-end evaluation of the FUSED decision — not just Layer 1 alone.

`train.py` measures Layer 1's raw model on held-out data: 0.861 ROC-AUC, 85%
sensitivity at a chosen operating threshold. Every one of those numbers
describes the vitals model in isolation. Since then, Layer 3 fusion has
grown a SIRS hard floor (Layer 1b) that can force ESI II regardless of what
the model itself said, plus a synergy multiplier. Nobody had measured what
the SIRS floor actually does to the *deployed* decision's sensitivity,
specificity, or alert rate — reported model metrics and actual triage
behaviour were two different, unreconciled things. This is that
measurement.

Scope, stated honestly rather than implied: this evaluates vitals + SIRS +
fusion, against the same synthetic X/y cohort `train.py` trains on — the
same "is not real patient data" caveat applies here that applies everywhere
else in this project. It does NOT evaluate Layer 2 (symptom NLP) or Layer 2b
(lab LLM evaluation) end-to-end, because the synthetic cohort has no
complaint text or lab panels correlated with the outcome label to evaluate
them against. Building correlated synthetic text/labs is future work, not a
number this script can honestly report today — see docs/ARCHITECTURE.md.

Run: python -m backend.ml.eval_pipeline
"""
from __future__ import annotations

import json
import os
import pickle

import numpy as np
from sklearn.model_selection import train_test_split

from .train import generate_cohort

try:
    from ..layers import layer1b_heuristics, layer3_fusion
except ImportError:
    from layers import layer1b_heuristics, layer3_fusion  # type: ignore[no-redef]

HERE = os.path.dirname(os.path.abspath(__file__))
ARTIFACTS = os.path.join(HERE, "artifacts")

# ESI I/II is the operating question this harness asks: does the fused
# decision escalate this patient into the top acuity band or not. That is
# the same threshold Layer 5 uses to route to resus rather than fast track.
ALERT_ESI = {"I", "II"}

# Column order matches train.py's FEATURES exactly — generate_cohort()
# builds X in this order, so indices below are a contract with that file,
# not a coincidence.
_HR, _SBP, _DBP, _RR, _SPO2, _TEMP, _AMB = 1, 2, 3, 4, 5, 6, 8
_CORE_VITAL_COLS = (_HR, _SBP, _DBP, _RR, _SPO2, _TEMP)


def _vitals_dict(row: np.ndarray) -> dict:
    def val(i):
        return None if np.isnan(row[i]) else float(row[i])
    return {
        "age": val(0), "heart_rate": val(_HR), "systolic_bp": val(_SBP),
        "diastolic_bp": val(_DBP), "resp_rate": val(_RR), "spo2": val(_SPO2),
        "temperature": val(_TEMP),
        "arrival_mode": "ambulance" if row[_AMB] else "walk-in",
    }


def _vitals_out(model, row: np.ndarray) -> dict:
    prob = float(model.predict_proba(row.reshape(1, -1))[0, 1])
    present = sum(1 for i in _CORE_VITAL_COLS if not np.isnan(row[i]))
    return {"risk": prob, "drivers": [], "vitals_present": int(present),
            "vitals_expected": len(_CORE_VITAL_COLS), "sufficient": present >= 3}


def _evaluate(model, X: np.ndarray, y: np.ndarray, use_sirs: bool) -> dict:
    tp = fp = tn = fn = 0
    for row, label in zip(X, y):
        vitals = _vitals_dict(row)
        vitals_out = _vitals_out(model, row)
        sirs_data = layer1b_heuristics.evaluate_sirs(vitals) if use_sirs else None
        fused = layer3_fusion.fuse(vitals_out, None, vitals["age"], None, sirs_data)
        alert = fused["esi"] in ALERT_ESI
        if alert and label:
            tp += 1
        elif alert and not label:
            fp += 1
        elif label:
            fn += 1
        else:
            tn += 1
    n = max(len(y), 1)
    return {
        "sensitivity": round(tp / max(tp + fn, 1), 4),
        "specificity": round(tn / max(tn + fp, 1), 4),
        "alert_rate": round((tp + fp) / n, 4),
        "undertriage_rate": round(fn / n, 4),
        "tp": tp, "fp": fp, "tn": tn, "fn": fn,
    }


def main() -> None:
    with open(os.path.join(ARTIFACTS, "vitals_model.pkl"), "rb") as f:
        model = pickle.load(f)

    # Same generator, same seed as train.py — this reproduces the identical
    # cohort and, with the same split parameters, the identical held-out
    # test set metrics.json's Layer-1-only numbers were measured on.
    X, y = generate_cohort()
    _, X_te, _, y_te = train_test_split(X, y, test_size=0.2, random_state=7, stratify=y)

    without_sirs = _evaluate(model, X_te, y_te, use_sirs=False)
    with_sirs = _evaluate(model, X_te, y_te, use_sirs=True)

    print(f"Held-out encounters: {len(y_te)}")
    print("\nFused decision (ESI I/II = alert), vitals + Layer 3 fusion, SIRS floor OFF:")
    print(json.dumps(without_sirs, indent=2))
    print("\nSame, SIRS floor ON (Layer 1b, current default — always active in main.py):")
    print(json.dumps(with_sirs, indent=2))
    print(
        f"\nSIRS floor effect: sensitivity {without_sirs['sensitivity']:.1%} -> "
        f"{with_sirs['sensitivity']:.1%}  |  alert rate {without_sirs['alert_rate']:.1%} "
        f"-> {with_sirs['alert_rate']:.1%}  |  under-triage "
        f"{without_sirs['undertriage_rate']:.1%} -> {with_sirs['undertriage_rate']:.1%}"
    )
    print(
        "\nNote: this is the fused vitals+SIRS decision, not directly "
        "comparable to metrics.json's Layer-1-only numbers, which fix "
        "sensitivity at a chosen quantile on the raw model probability "
        "rather than measuring the ESI band the SIRS floor can override."
    )


if __name__ == "__main__":
    main()

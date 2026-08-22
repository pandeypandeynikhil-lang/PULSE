"""Layer 1 — Vitals Risk Model.

Wraps the trained gradient-boosted classifier. Two things matter here beyond
the prediction itself:

1. It scores on whatever vitals exist. Missing fields are passed to XGBoost as
   NaN and handled natively by the split logic — we do not impute a plausible
   value and pretend we measured it. The count of present vitals is itself a
   feature, so the model knows how much it is guessing.

2. Every prediction returns exact SHAP contributions via xgboost's own
   `pred_contribs`, so the console can show the nurse what drove the number.
"""
from __future__ import annotations

import json
import os
import pickle
from typing import Any

import numpy as np
import xgboost as xgb

_HERE = os.path.dirname(os.path.abspath(__file__))
_ART = os.path.join(_HERE, "..", "ml", "artifacts")

FEATURES = ["age", "heart_rate", "systolic_bp", "diastolic_bp", "resp_rate",
            "spo2", "temperature", "shock_index", "arrival_ambulance",
            "n_vitals_present"]

PRETTY = {
    "age": "age", "heart_rate": "heart rate", "systolic_bp": "systolic BP",
    "diastolic_bp": "diastolic BP", "resp_rate": "respiratory rate",
    "spo2": "oxygen saturation", "temperature": "temperature",
    "shock_index": "shock index", "arrival_ambulance": "arrived by ambulance",
    "n_vitals_present": "completeness of vitals",
}

_model = None
_metrics: dict[str, Any] = {}


def _load():
    global _model, _metrics
    if _model is None:
        with open(os.path.join(_ART, "vitals_model.pkl"), "rb") as f:
            _model = pickle.load(f)
        with open(os.path.join(_ART, "metrics.json"), "r") as f:
            _metrics = json.load(f)
    return _model


def model_metrics() -> dict[str, Any]:
    _load()
    return _metrics


def _vector(v: dict[str, Any]) -> np.ndarray:
    hr, sbp = v.get("heart_rate"), v.get("systolic_bp")
    shock = (hr / sbp) if (hr and sbp) else np.nan
    core = ["heart_rate", "systolic_bp", "diastolic_bp", "resp_rate", "spo2", "temperature"]
    present = sum(1 for k in core if v.get(k) is not None) + 1

    row = [
        v.get("age", np.nan),
        v.get("heart_rate", np.nan),
        v.get("systolic_bp", np.nan),
        v.get("diastolic_bp", np.nan),
        v.get("resp_rate", np.nan),
        v.get("spo2", np.nan),
        v.get("temperature", np.nan),
        shock,
        1.0 if v.get("arrival_mode") == "ambulance" else 0.0,
        float(present),
    ]
    return np.array([[np.nan if x is None else x for x in row]], dtype=float)


def score(vitals: dict[str, Any]) -> dict[str, Any]:
    m = _load()
    X = _vector(vitals)
    prob = float(m.predict_proba(X)[0, 1])

    booster = m.get_booster()
    contribs = booster.predict(xgb.DMatrix(X, missing=np.nan), pred_contribs=True)[0]

    drivers = []
    for i, name in enumerate(FEATURES):
        c = float(contribs[i])
        if abs(c) < 0.02 or np.isnan(X[0, i]):
            continue
        drivers.append({
            "feature": name,
            "label": PRETTY[name],
            "value": None if np.isnan(X[0, i]) else round(float(X[0, i]), 2),
            "contribution": round(c, 4),
            "direction": "raises" if c > 0 else "lowers",
        })
    drivers.sort(key=lambda d: -abs(d["contribution"]))

    core = ["heart_rate", "systolic_bp", "diastolic_bp", "resp_rate", "spo2", "temperature"]
    present = sum(1 for k in core if vitals.get(k) is not None)

    return {
        "risk": round(prob, 4),
        "drivers": drivers[:5],
        "vitals_present": present,
        "vitals_expected": len(core),
        # Below three vitals the model is extrapolating, and says so rather than
        # quietly returning a confident-looking number.
        "sufficient": present >= 3,
    }

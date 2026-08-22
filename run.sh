#!/usr/bin/env bash
set -e
python3 -m venv .venv 2>/dev/null || true
source .venv/bin/activate 2>/dev/null || true
pip install -q -r requirements.txt
[ -f backend/ml/artifacts/vitals_model.pkl ] || python -m backend.ml.train
echo ""
echo "  PULSE running -> http://127.0.0.1:8000"
echo ""
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000

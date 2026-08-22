@echo off
python -m venv .venv
call .venv\Scripts\activate
pip install -q -r requirements.txt
if not exist backend\ml\artifacts\vitals_model.pkl python -m backend.ml.train
echo.
echo   PULSE running -^> http://127.0.0.1:8000
echo.
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000

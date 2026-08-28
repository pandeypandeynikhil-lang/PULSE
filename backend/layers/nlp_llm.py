"""LLM-grounded extraction — the primary tier ahead of the deterministic
lexicon matcher in `nlp_core.py`, and the translation step behind Voice
Intake in `main.py`.

Two free/low-cost providers, tried in order, so this is genuine two-vendor
failover rather than a single point of failure:
  1. Gemini (Google AI Studio has a free tier — no card required to start).
  2. Groq (fast, generous free tier, different vendor and different outage
     surface than Gemini).
Neither is required: if a key is missing, that provider is skipped silently;
if both are missing or both fail, every function here returns None and the
caller falls through to the deterministic lexicon tier.

Both providers are asked for a bare JSON object (no tool-calling API, so the
same prompt/parse path works across vendors without per-provider schema
code). The result is validated in Python before it is trusted — flag ids are
checked against the closed lexicon vocabulary and quotes are looked up
verbatim in the source text by the caller (`nlp_core.py`); nothing here is
taken on faith.
"""
from __future__ import annotations

import json
import os
import re
from typing import Any

GEMINI_MODEL = os.environ.get("PULSE_GEMINI_MODEL", "gemini-3.6-flash")
GROQ_MODEL = os.environ.get("PULSE_GROQ_MODEL", "openai/gpt-oss-120b")
TIMEOUT = float(os.environ.get("PULSE_NLP_TIMEOUT", "6.0"))

_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```\s*$", re.MULTILINE)


def any_provider_configured() -> bool:
    return bool(os.environ.get("GEMINI_API_KEY") or os.environ.get("GROQ_API_KEY"))


def _parse_json(text: str | None) -> dict[str, Any] | None:
    """Models occasionally wrap JSON in a markdown fence despite being asked
    not to — strip that before parsing rather than failing on it. Any other
    malformed response returns None, same as a network failure."""
    if not text:
        return None
    try:
        return json.loads(_FENCE_RE.sub("", text.strip()))
    except (json.JSONDecodeError, TypeError):
        return None


# --------------------------------------------------------------- providers
def _call_gemini(system: str, user: str) -> str | None:
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        return None
    try:
        from google import genai
        from google.genai import types

        # Gemini's API rejects any deadline under 10s outright (400
        # INVALID_ARGUMENT) rather than just running long — so the floor here
        # isn't a tuning choice, it's a hard requirement independent of
        # PULSE_NLP_TIMEOUT, which may be set lower for the other provider.
        try:
            client = genai.Client(
                api_key=key,
                http_options=types.HttpOptions(timeout=int(max(TIMEOUT, 10.0) * 1000)))
        except Exception:
            client = genai.Client(api_key=key)  # older/newer SDK w/o this option

        resp = client.models.generate_content(
            model=GEMINI_MODEL, contents=user,
            config=types.GenerateContentConfig(
                system_instruction=system,
                response_mime_type="application/json",
                temperature=0))
        return resp.text
    except Exception:
        return None


def _call_groq(system: str, user: str) -> str | None:
    key = os.environ.get("GROQ_API_KEY")
    if not key:
        return None
    try:
        from groq import Groq
        client = Groq(api_key=key, timeout=TIMEOUT)
        resp = client.chat.completions.create(
            model=GROQ_MODEL, temperature=0,
            response_format={"type": "json_object"},
            messages=[{"role": "system", "content": system},
                     {"role": "user", "content": user}])
        return resp.choices[0].message.content
    except Exception:
        return None


def _call_llm(system: str, user: str) -> tuple[dict[str, Any] | None, str | None]:
    """Tries Gemini, then Groq. Returns (parsed_json, provider_name), or
    (None, None) if both are unconfigured or both fail."""
    for provider, call in (("gemini", _call_gemini), ("groq", _call_groq)):
        parsed = _parse_json(call(system, user))
        if parsed is not None:
            return parsed, provider
    return None, None


# ----------------------------------------------------------- red-flag tier
_EXTRACT_SYSTEM = """You are a clinical triage red-flag extractor. Given a \
patient's own words or a caller/paramedic's account, identify which of these \
flag ids are genuinely supported by the text: {ids}.

Respond with ONLY a compact JSON object, no markdown fences, no commentary, \
matching exactly this shape:
{{"age": <int or null>, "flags": [{{"id": "<one of the ids above>", \
"quote": "<exact verbatim substring of the input supporting this flag>"}}]}}

Rules: only use ids from the list above, never invent one; "quote" must be an \
exact verbatim substring of the input text, no paraphrasing; if nothing \
applies return {{"age": null, "flags": []}}."""


def extract_llm(text: str, lexicon: dict[str, Any]) -> dict[str, Any] | None:
    """Returns {"flags": [{"id","quote"}...], "age", "_provider"}, or None if
    no trustworthy answer could be obtained from either provider — callers
    fall back to the lexicon tier in that case."""
    if not text or not any_provider_configured():
        return None
    system = _EXTRACT_SYSTEM.format(ids=", ".join(f["id"] for f in lexicon["flags"]))
    parsed, provider = _call_llm(system, text)
    if parsed is None:
        return None
    parsed["_provider"] = provider
    return parsed


# --------------------------------------------------------- voice intake tier
_VOICE_SYSTEM = """You are a clinical intake assistant helping a nurse who \
does not share a language with the patient or the person accompanying them. \
You are given a transcribed spoken account{lang_note}, possibly not in \
English.

Respond with ONLY a compact JSON object, no markdown fences, no commentary, \
matching exactly this shape:
{{"complaint_summary": "<short English chief-complaint phrase, chart-style \
— a few words, not a full sentence>", "age": <int or null>, \
"vitals": {{"heart_rate": <number or null>, "systolic_bp": <number or null>, \
"diastolic_bp": <number or null>, "resp_rate": <number or null>, \
"spo2": <number or null>, "temperature": <number or null>}}}}

Rules: translate and summarise the account as a short English chief \
complaint; extract age only if explicitly stated; fill a vital ONLY if an \
explicit number was spoken aloud (e.g. a paramedic reading a monitor) — \
never infer one from a description like "breathing fast"; leave it null \
otherwise."""


def extract_voice_intake(text: str, lang_hint: str = "") -> dict[str, Any] | None:
    """Translate + lightly structure a spoken account for the Voice Intake
    path. Returns None on any failure from both providers — the caller
    reports a clear "voice intake unavailable" error rather than guessing.

    The one field this function refuses to let through unchecked is
    `complaint_summary`: it is the English text a nurse who doesn't share
    the patient's language is going to read on the decision console. If a
    provider omits it (schema drift, a truncated response, a model that
    just didn't comply), that must count as a failed translation — not
    quietly fall back to the original-language transcript, which is exactly
    the text a nurse in this scenario cannot read.
    """
    if not text or not any_provider_configured():
        return None
    lang_note = f" (recognised as {lang_hint})" if lang_hint else ""
    system = _VOICE_SYSTEM.format(lang_note=lang_note)
    parsed, provider = _call_llm(system, text)
    if parsed is None:
        return None
    summary = parsed.get("complaint_summary")
    if not isinstance(summary, str) or not summary.strip():
        return None
    parsed["complaint_summary"] = summary.strip()
    parsed["_provider"] = provider
    return parsed

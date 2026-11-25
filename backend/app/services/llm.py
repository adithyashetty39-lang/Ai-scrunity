"""Gemini client with structured JSON + offline fallback + circuit breaker."""

from __future__ import annotations

import json
import re
from typing import Any, Optional

import httpx

from app.config import settings

_CONSECUTIVE_FAILURES = 0
MAX_FAILURES_BEFORE_CIRCUIT_BREAK = 2


def llm_available() -> bool:
    global _CONSECUTIVE_FAILURES
    if not settings.gemini_api_key:
        return False
    if _CONSECUTIVE_FAILURES >= MAX_FAILURES_BEFORE_CIRCUIT_BREAK:
        return False
    return True


def _record_success():
    global _CONSECUTIVE_FAILURES
    _CONSECUTIVE_FAILURES = 0


def _record_failure():
    global _CONSECUTIVE_FAILURES
    _CONSECUTIVE_FAILURES += 1


def _extract_json(text: str) -> Any:
    text = text.strip()
    fenced = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if fenced:
        text = fenced.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            return json.loads(text[start : end + 1])
        start = text.find("[")
        end = text.rfind("]")
        if start >= 0 and end > start:
            return json.loads(text[start : end + 1])
        raise


def generate_json(prompt: str, system: str = "") -> Optional[Any]:
    if not llm_available():
        return None
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{settings.gemini_model}:generateContent"
    )
    body = {
        "system_instruction": {"parts": [{"text": system or "Return valid JSON only."}]},
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.2,
            "responseMimeType": "application/json",
        },
    }
    try:
        with httpx.Client(timeout=4.0) as client:
            res = client.post(url, params={"key": settings.gemini_api_key}, json=body)
            res.raise_for_status()
            data = res.json()
        text = data["candidates"][0]["content"]["parts"][0]["text"]
        _record_success()
        return _extract_json(text)
    except Exception:
        _record_failure()
        return None


def generate_text(prompt: str, system: str = "") -> Optional[str]:
    if not llm_available():
        return None
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{settings.gemini_model}:generateContent"
    )
    body = {
        "system_instruction": {
            "parts": [{"text": system or "You are a university examination scrutiny expert."}]
        },
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.4},
    }
    try:
        with httpx.Client(timeout=4.0) as client:
            res = client.post(url, params={"key": settings.gemini_api_key}, json=body)
            res.raise_for_status()
            data = res.json()
        _record_success()
        return data["candidates"][0]["content"]["parts"][0]["text"].strip()
    except Exception:
        _record_failure()
        return None

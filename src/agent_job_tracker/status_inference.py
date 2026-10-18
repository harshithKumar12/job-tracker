"""Gemini-backed status inference with deterministic offline fallback."""

from __future__ import annotations

import json
import re
from typing import Any

from ._gemini import is_quota_error, pick_working_model
from .config import Config
from .models import StatusInference, Thread

VALID_STATUSES = (
    "applied",
    "interview_scheduled",
    "rejected",
    "offer",
    "no_response",
    "unclear",
)


def infer_status(thread: Thread, cfg: Config) -> StatusInference:
    if not cfg.gemini_api_key:
        return _rule_based_status(thread, "no API key")
    try:
        import google.generativeai as genai

        genai.configure(api_key=cfg.gemini_api_key)
        prompt = (
            "You classify a single email thread about a job application.\n"
            f"Choose exactly one status from: {', '.join(VALID_STATUSES)}. Confidence [0,1]. "
            "Signals are quoted phrases. If unsure, use status='unclear' and confidence<0.5.\n\n"
            f"SUBJECT: {thread.subject}\n"
            f"PARTICIPANTS: {', '.join(sorted(thread.participants))}\n\n"
            f"THREAD CORPUS:\n{thread.as_text_corpus()}"
        )
        model_name = pick_working_model(genai, cfg.gemini_model)
        model = genai.GenerativeModel(
            model_name=model_name,
            generation_config={"response_mime_type": "application/json", "temperature": 0.2},
        )
        data = json.loads(model.generate_content(prompt).text)
        status = str(data.get("status", "unclear")).strip().lower()
        if status not in VALID_STATUSES:
            status = "unclear"
        confidence = max(0.0, min(1.0, float(data.get("confidence", 0.0))))
        if confidence < cfg.confidence_threshold and status != "unclear":
            status = "unclear"
        signals = data.get("signals", [])
        if isinstance(signals, str):
            signals = [signals]
        if not isinstance(signals, list):
            signals = []
        return StatusInference(
            status=status,
            confidence=confidence,
            signals=[str(signal) for signal in signals],
            last_role=data.get("role"),
            last_company=data.get("company"),
            raw=data,
        )
    except Exception as exc:
        reason = "quota hit" if is_quota_error(exc) else f"Gemini fallback ({type(exc).__name__})"
        return _rule_based_status(thread, reason)


def _rule_based_status(thread: Thread, reason: str) -> StatusInference:
    def detect(text: str) -> tuple[str, float, list[str]] | None:
        lower = text.lower()
        if re.search(r"\b(unfortunately|moving forward with other|we have decided|rejected)\b", lower):
            return "rejected", 0.85, ["rejection language"]
        if re.search(r"\b(offer|offer letter|pleased to extend)\b", lower):
            return "offer", 0.9, ["offer language"]
        if re.search(r"\b(interview|phone screen|schedule|onsite|panel)\b", lower):
            return "interview_scheduled", 0.8, ["interview language"]
        if re.search(r"\b(received your application|thanks for applying)\b", lower):
            return "applied", 0.75, ["app acknowledgement"]
        if re.search(r"\b(no response|haven't heard|waiting to hear|still waiting)\b", lower):
            return "no_response", 0.6, ["no-response language"]
        return None

    # Prefer the newest unquoted message so a stale offer quoted inside a
    # later rejection cannot win the status decision.
    for message in sorted(thread.messages, key=lambda item: item.date, reverse=True):
        unquoted = "\n".join(line for line in message.body.splitlines() if not line.lstrip().startswith(">"))
        detected = detect(unquoted)
        if detected:
            status, confidence, signals = detected
            return StatusInference(status, confidence, signals + [reason])
    detected = detect(thread.as_text_corpus(max_chars=8_000))
    if detected:
        status, confidence, signals = detected
    else:
        status, confidence, signals = "unclear", 0.3, ["no decisive signal"]
    return StatusInference(status, confidence, signals + [reason])

"""Optional Gemini integration kept behind a lazy import."""

from __future__ import annotations

from typing import Any


def is_quota_error(exc: BaseException) -> bool:
    try:
        from google.api_core import exceptions as google_exceptions

        return isinstance(exc, (google_exceptions.ResourceExhausted, google_exceptions.TooManyRequests))
    except ImportError:
        return False


def pick_working_model(genai: Any, configured: str) -> str:
    if configured:
        return configured
    try:
        for model in genai.list_models():
            if "generateContent" in getattr(model, "supported_generation_methods", []):
                name = model.name.split("/")[-1]
                if name.startswith("gemini"):
                    return name
    except Exception:
        pass
    return "gemini-1.5-flash"

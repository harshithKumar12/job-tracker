"""Environment-backed configuration with safe offline defaults."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping


def _optional_secret(value: str | None) -> str | None:
    """Treat copied .env.example placeholders as missing credentials."""

    if not value:
        return None
    normalized = value.strip()
    if not normalized or normalized.startswith("your_") or "..." in normalized:
        return None
    return normalized


def _int_value(environ: Mapping[str, str], name: str, default: int) -> int:
    raw = environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc


def _bool_value(environ: Mapping[str, str], name: str, default: bool) -> bool:
    raw = environ.get(name)
    if raw is None or not raw.strip():
        return default
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be true or false")


@dataclass(frozen=True)
class Config:
    imap_host: str = "imap.gmail.com"
    imap_port: int = 993
    imap_username: str | None = None
    imap_password: str | None = None
    imap_folder: str = "INBOX"
    imap_days_back: int = 60
    gemini_api_key: str | None = None
    gemini_model: str = "gemini-1.5-flash"
    monitoring_enabled: bool = False
    monitoring_interval_minutes: int = 60
    monitoring_log_file: str = "./monitoring/runs.jsonl"
    monitoring_alert_days: int = 10
    confidence_threshold: float = 0.6

    def __post_init__(self) -> None:
        if not 1 <= self.imap_port <= 65_535:
            raise ValueError("imap_port must be between 1 and 65535")
        if self.imap_days_back < 0:
            raise ValueError("imap_days_back must not be negative")
        if self.monitoring_interval_minutes <= 0:
            raise ValueError("monitoring_interval_minutes must be positive")
        if self.monitoring_alert_days < 0:
            raise ValueError("monitoring_alert_days must not be negative")
        if not 0 <= self.confidence_threshold <= 1:
            raise ValueError("confidence_threshold must be between 0 and 1")

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> "Config":
        """Load .env when available, then parse and validate environment values."""

        if environ is None:
            try:
                from dotenv import load_dotenv

                load_dotenv()
            except ImportError:
                pass
            environ = os.environ

        return cls(
            imap_host=environ.get("IMAP_HOST", "imap.gmail.com").strip() or "imap.gmail.com",
            imap_port=_int_value(environ, "IMAP_PORT", 993),
            imap_username=_optional_secret(environ.get("IMAP_USERNAME")),
            imap_password=_optional_secret(environ.get("IMAP_PASSWORD")),
            imap_folder=environ.get("IMAP_FOLDER", "INBOX").strip() or "INBOX",
            imap_days_back=_int_value(environ, "IMAP_DAYS_BACK", 60),
            gemini_api_key=_optional_secret(environ.get("GEMINI_API_KEY")),
            gemini_model=environ.get("GEMINI_MODEL", "gemini-1.5-flash").strip(),
            monitoring_enabled=_bool_value(environ, "MONITORING_ENABLED", False),
            monitoring_interval_minutes=_int_value(environ, "MONITORING_INTERVAL_MINUTES", 60),
            monitoring_log_file=environ.get("MONITORING_LOG_FILE", "./monitoring/runs.jsonl").strip()
            or "./monitoring/runs.jsonl",
            monitoring_alert_days=_int_value(environ, "MONITORING_ALERT_DAYS", 10),
            confidence_threshold=float(environ.get("CONFIDENCE_THRESHOLD", "0.6")),
        )

    @property
    def has_imap_credentials(self) -> bool:
        return bool(self.imap_username and self.imap_password)

    @property
    def has_any_imap_credentials(self) -> bool:
        return bool(self.imap_username or self.imap_password)

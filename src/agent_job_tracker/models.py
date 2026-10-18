"""Data structures shared by the tracker pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class EmailMessage:
    message_id: str
    from_: str
    to: str
    subject: str
    date: datetime
    body: str
    in_reply_to: str | None = None
    references: str | None = None


@dataclass
class Thread:
    thread_id: str
    subject: str
    messages: list[EmailMessage] = field(default_factory=list)
    participants: set[str] = field(default_factory=set)
    last_date: datetime | None = None

    @property
    def last_contact(self) -> datetime | None:
        return self.last_date

    def as_text_corpus(self, max_chars: int = 12_000) -> str:
        ordered = sorted(self.messages, key=lambda message: message.date)
        if max_chars <= 0 or not ordered:
            return ""

        serialized = [
            (
                f"From: {message.from_}\nTo: {message.to}\n"
                f"Date: {message.date.isoformat()}\nSubject: {message.subject}\n\n"
                f"{message.body.strip()}\n{'-' * 40}\n"
            )
            for message in ordered
        ]
        # The newest message is the most useful signal. Keep it even when an
        # older message contains a very large quoted body.
        newest = serialized[-1]
        if len(newest) >= max_chars:
            return newest[:max_chars]

        selected = [newest]
        total = len(newest)
        truncated = False
        for chunk in reversed(serialized[:-1]):
            if total + len(chunk) <= max_chars:
                selected.insert(0, chunk)
                total += len(chunk)
            else:
                truncated = True
                break
        if truncated:
            marker = "[…earlier messages truncated to fit context window]\n"
            if total + len(marker) <= max_chars:
                selected.insert(0, marker)
            else:
                selected.insert(0, marker[: max_chars - total])
        return "\n".join(selected)[:max_chars]


@dataclass
class Classification:
    is_job_thread: bool
    reason: str
    company_hint: str | None = None
    role_hint: str | None = None


@dataclass
class StatusInference:
    status: str
    confidence: float
    signals: list[str]
    last_role: str | None = None
    last_company: str | None = None
    raw: dict[str, Any] | None = None


@dataclass
class FollowUpDraft:
    subject: str
    body: str
    tone: str
    status_at_draft: str


@dataclass
class ApplicationRecord:
    thread_id: str
    subject: str
    company: str | None
    role: str | None
    status: str
    confidence: float
    signals: list[str]
    last_contact: str
    business_days_elapsed: int
    needs_follow_up: bool
    draft_subject: str | None = None
    draft_body: str | None = None
    draft_tone: str | None = None

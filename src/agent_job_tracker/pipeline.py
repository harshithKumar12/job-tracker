"""The privacy-gated application processing pipeline."""

from __future__ import annotations

from datetime import datetime, timezone

from .business_days import between
from .config import Config
from .follow_up_drafter import draft_follow_up
from .models import ApplicationRecord, Thread
from .status_inference import infer_status
from .thread_classifier import classify


def process_threads(
    threads: list[Thread],
    cfg: Config,
    now: datetime | None = None,
) -> list[ApplicationRecord]:
    current = now or datetime.now(timezone.utc)
    results: list[ApplicationRecord] = []
    for thread in threads:
        classification = classify(thread)
        if not classification.is_job_thread:
            continue
        status = infer_status(thread, cfg)
        company = status.last_company or classification.company_hint
        role = status.last_role or classification.role_hint
        last_contact = thread.last_contact or current
        elapsed = between(last_contact, current)
        terminal = status.status in {"rejected", "offer", "unclear"}
        needs_follow_up = not terminal and elapsed >= cfg.monitoring_alert_days
        draft = (
            draft_follow_up(thread, status, cfg, elapsed, company=company, role=role)
            if needs_follow_up
            else None
        )
        results.append(
            ApplicationRecord(
                thread_id=thread.thread_id,
                subject=thread.subject,
                company=company,
                role=role,
                status=status.status,
                confidence=status.confidence,
                signals=status.signals,
                last_contact=last_contact.isoformat(),
                business_days_elapsed=elapsed,
                needs_follow_up=needs_follow_up,
                draft_subject=draft.subject if draft else None,
                draft_body=draft.body if draft else None,
                draft_tone=draft.tone if draft else None,
            )
        )
    return sorted(results, key=lambda application: application.last_contact, reverse=True)


def print_digest(applications: list[ApplicationRecord]) -> None:
    print("\n=== Job Tracker Digest ===")
    if not applications:
        print("No job application threads found.")
        return
    for application in applications:
        flag = " !! follow-up" if application.needs_follow_up else ""
        print(f"\n* {application.company or '?'} - {application.role or '?'}{flag}")
        print(f"  status: {application.status} (conf={application.confidence:.2f})")
        print(
            f"  last contact: {application.last_contact} "
            f"({application.business_days_elapsed} bd)"
        )
        if application.draft_subject:
            print(f"  draft: {application.draft_subject}\n    {application.draft_body}")

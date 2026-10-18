"""Deterministic offline fixtures covering every documented status."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .email_fetcher import consolidate_threads
from .models import EmailMessage, Thread


def load_sample_data(now: datetime | None = None) -> list[Thread]:
    current = now or datetime.now(timezone.utc)
    messages = [
        EmailMessage("a1", "careers@acme.com", "me@example.com", "Acme - Senior Backend - Offer", current - timedelta(days=2), "We are thrilled to extend an offer!"),
        EmailMessage("b1", "no-reply@beta.io", "me@example.com", "BetaLabs - Decision", current - timedelta(days=5), "We have decided to move forward with another candidate."),
        EmailMessage("c1", "recruiter@cloud.com", "me@example.com", "CloudOps - Phone screen", current - timedelta(days=18), "Would love to set up a call!"),
        EmailMessage("d1", "careers@data.com", "me@example.com", "DataCorp - Software Engineer application", current - timedelta(days=22), "Received your application. We will be in touch."),
        EmailMessage("e1", "recruiter@ember.com", "me@example.com", "Ember - Product role", current - timedelta(days=25), "Application submitted; still waiting to hear back."),
        EmailMessage("f1", "talent@frost.com", "me@example.com", "Frost - Product role", current - timedelta(days=32), "Thanks for connecting about opportunities.",),
    ]
    return consolidate_threads(messages)

"""Grounded, draft-only follow-up generation."""

from __future__ import annotations

import json

from ._gemini import pick_working_model
from .business_days import tone_bucket
from .config import Config
from .models import FollowUpDraft, StatusInference, Thread


def draft_follow_up(
    thread: Thread,
    status: StatusInference,
    cfg: Config,
    business_days_elapsed: int,
    company: str | None = None,
    role: str | None = None,
) -> FollowUpDraft | None:
    if status.status in {"rejected", "offer"}:
        return None
    tone = tone_bucket(business_days_elapsed)
    company = company or status.last_company or "your team"
    role = role or status.last_role or "the role"
    if not cfg.gemini_api_key:
        return _rule_based_draft(status.status, tone, company, role)
    try:
        import google.generativeai as genai

        genai.configure(api_key=cfg.gemini_api_key)
        model_name = pick_working_model(genai, cfg.gemini_model)
        prompt = (
            "Draft a follow-up email grounded only in this thread. Return JSON with subject and body. "
            f"Tone: {tone}. Role: {role}. Company: {company}. Status: {status.status}. "
            f"Days since contact: {business_days_elapsed}.\n\nTHREAD:\n{thread.as_text_corpus()}"
        )
        model = genai.GenerativeModel(
            model_name=model_name,
            generation_config={"response_mime_type": "application/json", "temperature": 0.2},
        )
        data = json.loads(model.generate_content(prompt).text)
        subject, body = str(data.get("subject", "")).strip(), str(data.get("body", "")).strip()
        if not subject or not body:
            raise ValueError("Gemini returned an empty draft")
        return FollowUpDraft(subject, body, tone, status.status)
    except Exception:
        return _rule_based_draft(status.status, tone, company, role)


def _rule_based_draft(status: str, tone: str, company: str, role: str) -> FollowUpDraft:
    role_phrase = "this role" if role == "the role" else f"the {role} role"
    subject = f"Following up - {role_phrase} at {company}"
    if tone == "warm":
        body = (
            f"Hi team,\n\nI wanted to quickly follow up on my application for {role_phrase}. "
            "Happy to share anything else that would help.\n\nThanks!"
        )
    elif tone == "firm":
        body = f"Hi team,\n\nChecking in on {role_phrase}. Could you let me know where things stand?\n\nThanks!"
    else:
        body = (
            f"Hi team,\n\nI haven't heard back on {role_phrase}. "
            "Should I assume the file is closed?\n\nThanks!"
        )
    return FollowUpDraft(subject, body, tone, status)

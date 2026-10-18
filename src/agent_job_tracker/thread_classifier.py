"""Local job-thread gate used before any optional LLM call."""

from __future__ import annotations

import re
from email.utils import getaddresses

from .models import Classification, Thread


_JOB_KEYWORDS = re.compile(
    r"\b(application|applied|applicant|resume|cv|cover letter|interview|phone screen|"
    r"hiring|recruiter|talent acquisition|job offer|offer letter|position|role|opening|"
    r"requisition|job description|jd|on[- ]site|onsite|thank you for (your|applying)|"
    r"unfortunately|we have decided|moving forward|take[- ]home|assessment|coding challenge|"
    r"reference check|background check|offer(?:ed)?|compensation|salary|start date)\b",
    re.IGNORECASE,
)
_NON_JOB_HINTS = re.compile(
    r"\b(invoice|receipt|payment due|subscription|order confirmation|reset your password|"
    r"verify your account|weekly digest|newsletter|promo|sale|coupon|reservation|itinerary|"
    r"confirmation number|loan|mortgage)\b",
    re.IGNORECASE,
)


def classify(thread: Thread) -> Classification:
    corpus = thread.as_text_corpus(max_chars=20_000)
    if _NON_JOB_HINTS.search(corpus):
        return Classification(False, "matched non-job hints")
    if _JOB_KEYWORDS.search(corpus) or _JOB_KEYWORDS.search(thread.subject or ""):
        return Classification(True, "matched job keywords", _guess_company(thread), _guess_role(thread))
    return Classification(False, "no job indicators")


def _guess_company(thread: Thread) -> str | None:
    for message in thread.messages:
        for _, address in getaddresses([message.from_]):
            if "@" not in address:
                continue
            domain = address.split("@", 1)[1].lower()
            for prefix in ("mail.", "noreply.", "no-reply.", "www."):
                domain = domain.removeprefix(prefix)
            head = domain.split(".", 1)[0]
            if head and head not in {"gmail", "outlook", "yahoo", "icloud", "hotmail"}:
                return head.title()
    if thread.subject:
        first = thread.subject.split(" - ")[0].strip()
        if 1 < len(first) <= 30 and first.lower() not in {"re", "fwd", "fw"}:
            return first
    return None


def _guess_role(thread: Thread) -> str | None:
    subject = thread.subject
    match = re.search(r"[-–—]\s*([A-Z][A-Za-z/ &.+#-]{3,60}?)\s*[-–—]", subject)
    if match:
        return match.group(1).strip()
    match = re.search(
        r"\b((?:Senior|Junior|Staff|Principal)?\s?[A-Za-z]+(?:\s+[A-Za-z]+){0,3})\s+"
        r"(?:role|position|application|interview)\b",
        subject,
        re.IGNORECASE,
    )
    return match.group(1).strip() if match else None

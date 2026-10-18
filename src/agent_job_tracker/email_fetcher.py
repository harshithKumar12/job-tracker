"""Read-only IMAP fetching, MIME parsing, and thread consolidation."""

from __future__ import annotations

import imaplib
import re
import ssl
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from email import policy
from email.message import EmailMessage as MimeEmailMessage
from email.parser import BytesParser
from email.utils import getaddresses, parsedate_to_datetime
from html import unescape

from .config import Config
from .models import EmailMessage, Thread


def _strip_subject(subject: str) -> str:
    return re.sub(r"^(?:\s*(?:re|fwd|fw)\s*:\s*)+", "", subject.strip(), flags=re.IGNORECASE).strip()


def _normalize_message_id(value: str | None) -> str:
    return (value or "").strip().strip("<>").lower()


def _subject_fallback_key(message: EmailMessage) -> str:
    addresses = sorted(
        address.lower()
        for _, address in getaddresses([message.from_, message.to])
        if address
    )
    return f"{_strip_subject(message.subject).lower()[:120]}|{'|'.join(addresses)}"


def _reference_ids(message: EmailMessage) -> list[str]:
    return [
        normalized
        for normalized in (
            *(_normalize_message_id(item) for item in (message.references or "").split()),
            _normalize_message_id(message.in_reply_to),
        )
        if normalized
    ]


class _UnionFind:
    def __init__(self, size: int) -> None:
        self.parent = list(range(size))

    def find(self, item: int) -> int:
        while self.parent[item] != item:
            self.parent[item] = self.parent[self.parent[item]]
            item = self.parent[item]
        return item

    def union(self, left: int, right: int) -> None:
        left_root, right_root = self.find(left), self.find(right)
        if left_root != right_root:
            self.parent[right_root] = left_root


def consolidate_threads(messages: list[EmailMessage]) -> list[Thread]:
    """Deduplicate Message-IDs and merge replies through References/In-Reply-To."""

    unique: list[EmailMessage] = []
    seen_ids: set[str] = set()
    for message in messages:
        message_id = _normalize_message_id(message.message_id)
        if message_id and message_id in seen_ids:
            continue
        if message_id:
            seen_ids.add(message_id)
        unique.append(message)

    if not unique:
        return []

    by_message_id = {
        _normalize_message_id(message.message_id): index
        for index, message in enumerate(unique)
        if _normalize_message_id(message.message_id)
    }
    by_subject: dict[str, list[int]] = defaultdict(list)
    for index, message in enumerate(unique):
        by_subject[_subject_fallback_key(message)].append(index)

    by_reference: dict[str, list[int]] = defaultdict(list)
    for index, message in enumerate(unique):
        for reference_id in _reference_ids(message):
            by_reference[reference_id].append(index)

    groups = _UnionFind(len(unique))
    for siblings in by_reference.values():
        for sibling in siblings[1:]:
            groups.union(siblings[0], sibling)
    for index, message in enumerate(unique):
        linked = bool(_reference_ids(message))
        for reference_id in _reference_ids(message):
            parent_index = by_message_id.get(reference_id)
            if parent_index is not None:
                groups.union(index, parent_index)
        if not linked and not _normalize_message_id(message.message_id) and not _reference_ids(message):
            subject_key = _subject_fallback_key(message)
            for sibling in by_subject[subject_key]:
                groups.union(index, sibling)

    components: dict[int, list[EmailMessage]] = defaultdict(list)
    for index, message in enumerate(unique):
        components[groups.find(index)].append(message)

    threads: list[Thread] = []
    for component in components.values():
        ordered = sorted(component, key=lambda item: item.date)
        first_id = _normalize_message_id(ordered[0].message_id)
        thread_id = f"msg:{first_id}" if first_id else f"subj:{_subject_fallback_key(ordered[0])}"
        participants = {
            address
            for message in ordered
            for _, address in getaddresses([message.from_, message.to])
            if address
        }
        threads.append(
            Thread(
                thread_id=thread_id,
                subject=_strip_subject(ordered[0].subject),
                messages=ordered,
                participants=participants,
                last_date=max(message.date for message in ordered),
            )
        )
    return sorted(threads, key=lambda thread: thread.last_date or datetime.min, reverse=True)


def fetch_threads(cfg: Config) -> list[Thread]:
    if not cfg.has_imap_credentials:
        raise RuntimeError("IMAP credentials not set.")

    context = ssl.create_default_context()
    imap = imaplib.IMAP4_SSL(cfg.imap_host, cfg.imap_port, ssl_context=context, timeout=30)
    try:
        status, _ = imap.login(cfg.imap_username, cfg.imap_password)
        if status != "OK":
            raise RuntimeError("IMAP login failed.")
        status, _ = imap.select(cfg.imap_folder, readonly=True)
        if status != "OK":
            raise RuntimeError(f"Unable to select IMAP folder {cfg.imap_folder!r}.")
        since = (datetime.now(timezone.utc) - timedelta(days=cfg.imap_days_back)).strftime("%d-%b-%Y")
        status, data = imap.search(None, f"(SINCE {since})")
        if status != "OK":
            raise RuntimeError("IMAP search failed.")
        if not data or not data[0]:
            return []

        messages: list[EmailMessage] = []
        for message_id in data[0].split():
            status, raw = imap.fetch(message_id, "(RFC822)")
            if status != "OK":
                raise RuntimeError("IMAP message fetch failed.")
            if not raw or not isinstance(raw[0], tuple):
                continue
            messages.append(_parse_message(BytesParser(policy=policy.default).parsebytes(raw[0][1])))
        return consolidate_threads(messages)
    finally:
        try:
            imap.logout()
        except Exception:
            pass


def _parse_message(message: MimeEmailMessage) -> EmailMessage:
    try:
        message_date = parsedate_to_datetime(message.get("Date", ""))
        if message_date.tzinfo is None:
            message_date = message_date.replace(tzinfo=timezone.utc)
    except Exception:
        message_date = datetime.now(timezone.utc)
    return EmailMessage(
        message_id=(message.get("Message-ID") or "").strip(),
        from_=(message.get("From") or "").strip(),
        to=(message.get("To") or "").strip(),
        subject=(message.get("Subject") or "").strip(),
        date=message_date,
        body=_extract_body(message),
        in_reply_to=message.get("In-Reply-To"),
        references=message.get("References"),
    )


def _extract_body(message: MimeEmailMessage) -> str:
    if message.is_multipart():
        text_parts: list[str] = []
        html_parts: list[str] = []
        attachment_parts: set[int] = set()
        for part in message.walk():
            if part.get_content_disposition() == "attachment" or part.get_content_type() == "message/rfc822":
                attachment_parts.update(id(child) for child in part.walk())
        for part in message.walk():
            if id(part) in attachment_parts:
                continue
            if part.is_multipart():
                continue
            if part.get_content_type() not in {"text/plain", "text/html"}:
                continue
            try:
                payload = part.get_content()
            except (KeyError, TypeError):
                continue
            if payload is None:
                continue
            if part.get_content_type() == "text/plain":
                text_parts.append(str(payload))
            elif part.get_content_type() == "text/html":
                html_parts.append(str(payload))
        if text_parts:
            return "\n".join(text_parts)
        if html_parts:
            html = re.sub(r"<(script|style)\b[^>]*>.*?</\1>", " ", html_parts[0], flags=re.IGNORECASE | re.DOTALL)
            stripped = re.sub(r"<[^>]+>", " ", html)
            return re.sub(r"\s+", " ", unescape(stripped)).strip()
        return ""
    payload = message.get_content()
    if message.get_content_type() == "text/html" and payload is not None:
        html = re.sub(r"<(script|style)\b[^>]*>.*?</\1>", " ", str(payload), flags=re.IGNORECASE | re.DOTALL)
        return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", html))).strip()
    return str(payload) if payload is not None else ""

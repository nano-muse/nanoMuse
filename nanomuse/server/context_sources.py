"""Short read-only observations for the background context review."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from email.utils import parseaddr
from typing import Any

from nanomuse.calendar.feeds import CalendarFeeds
from nanomuse.server.followups import fresh_busy_events
from nanomuse.server.watch_discovery import WatchCandidate, reference_watches, suggest_watches
from nanomuse.tools.email_tool import scrub_email_secrets
from nanomuse.triggers.mail import MailWatcher


@dataclass(frozen=True)
class ContextSample:
    source: str
    key: str
    label: str
    text: str
    recorded_at: str = ""
    calendar: str = ""
    candidates: tuple[WatchCandidate, ...] = ()
    references: tuple[WatchCandidate, ...] = ()


_URL = re.compile(r"\b[a-z][\w+.-]*://\S+", re.I)
_AUTH_MAIL = re.compile(
    r"verification code|passcode|one.time (?:code|password)|password reset|"
    r"reset your password|sign.in code|security code|验证码|驗證碼|重置密码|重設密碼",
    re.I,
)
_CREDENTIAL = re.compile(
    r"(?i)\b(?:bearer\s+|(?:token|api[_-]?key|secret|password)\s*[=:]\s*)[^\s&,;]+"
)
_VAULT = re.compile(r"\{\{\s*vault:[^}]*\}\}", re.I)


def preview(text: str, limit: int, redact: Callable[[str], str] | None = None) -> str:
    # URLs (including signed links and userinfo) and credential material are not needed for triage.
    text = scrub_email_secrets(text)
    text = _CREDENTIAL.sub("[redacted]", _VAULT.sub("[redacted]", _URL.sub("[link]", text)))
    if redact is not None:
        text = redact(text)
    return " ".join(text.split())[:limit].strip()


def connected_candidates(
    text: str, redact: Callable[[str], str] | None = None
) -> tuple[WatchCandidate, ...]:
    if _AUTH_MAIL.search(text):
        return ()
    clean = scrub_email_secrets(text)
    return tuple(suggest_watches(redact(clean) if redact else clean, personal=False))


def resource_preview(
    raw: str,
    *,
    candidates: list[WatchCandidate] | None = None,
    references: list[WatchCandidate] | None = None,
) -> str:
    """Preserve separate entries so a new line does not make an old item look new."""
    try:
        obj = json.loads(raw)
    except (ValueError, RecursionError):
        if raw.lstrip().startswith(("{", "[{", '["')):
            return ""  # Incomplete structured data cannot be filtered by field.
        rows = raw.splitlines()
    else:
        if isinstance(obj, dict):
            obj = next(
                (
                    obj[k]
                    for k in ("updates", "items", "events", "messages", "records")
                    if isinstance(obj.get(k), list)
                ),
                [obj],
            )
        if isinstance(obj, str):
            obj = [obj]
        if not isinstance(obj, list):
            return ""
        rows = []
        for item in obj:
            if isinstance(item, str):
                rows.extend(item.splitlines())
            elif isinstance(item, dict):
                title = next(
                    (item[k] for k in ("subject", "title", "name") if isinstance(item.get(k), str)),
                    "",
                )
                start = len(rows)
                for key in (
                    "summary",
                    "status",
                    "change",
                    "description",
                    "snippet",
                    "bodyPreview",
                    "location",
                    "start",
                    "end",
                    "due",
                ):
                    if isinstance(value := item.get(key), str) and value.strip():
                        rows.append(f"{title} ({key}): {value}" if title else f"{key}: {value}")
                if title and len(rows) == start:
                    rows.append(title)
    if candidates is not None:
        for row in rows[:96]:
            if len(candidates) >= 4:
                break
            candidates.extend(connected_candidates(row)[: 4 - len(candidates)])
    if references is not None:
        for row in rows[:96]:
            if len(references) >= 4:
                break
            if not _AUTH_MAIL.search(row):
                references.extend(reference_watches(row)[: 4 - len(references)])
    lines = [preview(row, 900) for row in rows if row.strip() and not _AUTH_MAIL.search(row)]
    if len(lines) > 96:
        lines = [*lines[:48], *lines[-48:]]
    text = "\n".join(lines)
    if len(text) > 16384:
        # Drop partial lines at the cut; an isolated fragment can reverse a sentence's meaning.
        return text[:8192].rpartition("\n")[0] + "\n" + text[-8191:].partition("\n")[2]
    return text


async def mail_samples(
    watcher: MailWatcher, cursor: dict[str, Any]
) -> tuple[list[ContextSample], dict[str, Any]]:
    if not watcher.configured:
        return [], {}
    fresh, state = await watcher.context_batch(cursor)
    records = []
    redact = watcher.vault.redact if watcher.vault is not None else None
    for mail in fresh:
        if _AUTH_MAIL.search(mail.subject) or _AUTH_MAIL.search(mail.body):
            continue
        name, address = parseaddr(mail.sender)
        sender = preview(name or address, 100, redact)
        title = preview(mail.subject, 180, redact)
        body = preview(mail.body, 1100, redact)
        if not title and not body:
            continue
        key = hashlib.sha256(
            f"{state['mailbox']}/{state['validity']}/{mail.uid}".encode()
        ).hexdigest()
        text = f"From: {sender}\nReceived: {mail.date}\nSubject: {title}\n{body}".strip()
        records.append(
            ContextSample(
                "mail",
                key,
                title or sender,
                text,
                mail.date,
                candidates=connected_candidates(mail.subject + "\n" + mail.body, redact),
                references=tuple(
                    reference_watches((redact or str)(mail.subject + "\n" + mail.body))
                ),
            )
        )
    return records, state


def calendar_samples(calendar: CalendarFeeds, now: datetime) -> list[ContextSample]:
    records = []
    redact = calendar.vault.redact if calendar.vault else None
    for event in fresh_busy_events(calendar, now):
        if not now < event.start <= now + timedelta(days=1):
            continue
        start = event.start.astimezone(now.tzinfo).isoformat(timespec="minutes")
        end = event.end.astimezone(now.tzinfo).isoformat(timespec="minutes")
        title = preview(event.summary, 180, redact)
        location = preview(event.location, 140, redact)
        detail = preview(event.description, 400, redact)
        key = hashlib.sha256(f"{event.calendar}\n{event.uid}\n{start}".encode()).hexdigest()
        text = f"{start} to {end}: {title}\n{location}\n{detail}".strip()
        records.append(
            ContextSample(
                "calendar",
                key,
                title,
                text,
                calendar=event.calendar,
                references=tuple(
                    reference_watches(
                        (redact or str)(event.summary + "\n" + (event.description or ""))
                    )
                ),
                candidates=connected_candidates(
                    event.summary + "\n" + (event.description or ""), redact
                ),
            )
        )
        if len(records) == 12:
            break
    return records

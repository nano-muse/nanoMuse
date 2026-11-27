"""Watching the inbox for ``mail`` triggers: new messages since the last look, by IMAP UID.

The first look only records where the inbox ends, so connecting a mailbox never replays
a thousand old messages through the triggers. Each later look fetches what arrived since,
oldest first, at most MAX_PER_LOOK of them so a burst cannot start dozens of runs at once;
the mark moves to the last one looked at, and the rest come with the next look. Nothing
that arrived is skipped.
"""

from __future__ import annotations

import asyncio
import email
import email.message
import email.utils
import hashlib
import imaplib
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from nanomuse.config import EmailSettings
from nanomuse.vault import CredentialVault

MAX_PER_LOOK = 20
BODY_CHARS = 2000


@dataclass
class NewMail:
    uid: int
    sender: str
    subject: str
    date: str
    body: str

    @property
    def key(self) -> str:
        return f"uid:{self.uid}"

    def render(self) -> str:
        return (
            f"From: {self.sender}\nDate: {self.date}\nSubject: {self.subject}\n\n{self.body}"
        ).strip()


class MailWatcher:
    def __init__(self, settings: EmailSettings, vault: CredentialVault | None = None):
        self.settings = settings
        self.vault = vault

    @property
    def configured(self) -> bool:
        return bool(self.settings.enabled and self.settings.imap_host)

    def _creds(self) -> tuple[str, str]:
        address, password = self.settings.address, self.settings.password
        if self.vault is not None:
            address = self.vault.resolve(address, strict=False)
            password = self.vault.resolve(password, strict=False)
        if "{{" in address or "{{" in password or not address or not password:
            raise RuntimeError("email credentials are not set")
        return address, password

    async def look(self, last_uid: int) -> tuple[list[NewMail], int]:
        """Messages with UID above ``last_uid`` and the new high-water mark.

        ``last_uid == 0`` means "first look": nothing is returned, the mark is set to the
        newest UID in the inbox. Raises ``RuntimeError`` / ``OSError`` when IMAP fails.
        """
        # here, not at the top: nanomuse.tools imports the triggers tool, which imports us
        from nanomuse.tools.email_tool import (
            IMAP_TIMEOUT_S,
            _body_of,
            _decode,
            scrub_email_secrets,
        )

        address, password = self._creds()
        settings = self.settings

        def _look() -> tuple[list[NewMail], int]:
            # the timeout matters here more than anywhere: this runs from the poll loop,
            # and a server that stops answering would otherwise hold it for good
            with imaplib.IMAP4_SSL(
                settings.imap_host, settings.imap_port, timeout=IMAP_TIMEOUT_S
            ) as imap:
                imap.login(address, password)
                status, _ = imap.select("INBOX", readonly=True)
                if status != "OK":
                    raise RuntimeError("cannot open INBOX")
                status, data = imap.uid("search", "ALL")
                if status != "OK":
                    raise RuntimeError("IMAP search failed")
                uids = [int(u) for u in (data[0].split() if data and data[0] else [])]
                newest = max(uids, default=0)
                if last_uid <= 0:
                    return [], newest
                fresh = sorted(u for u in uids if u > last_uid)[:MAX_PER_LOOK]
                out: list[NewMail] = []
                for uid in fresh:
                    status, parts = imap.uid("fetch", str(uid), "(RFC822)")
                    if status != "OK" or not parts or not isinstance(parts[0], tuple):
                        continue
                    msg = email.message_from_bytes(parts[0][1])
                    body = _body_of(msg)
                    if settings.scrub_secrets:
                        body = scrub_email_secrets(body)
                    if len(body) > BODY_CHARS:
                        body = body[:BODY_CHARS] + "... [truncated]"
                    out.append(
                        NewMail(
                            uid=uid,
                            sender=_decode(msg.get("From")),
                            subject=_decode(msg.get("Subject")),
                            date=str(msg.get("Date", "")),
                            body=body,
                        )
                    )
                # the mark: the last UID of this batch when there was one (what came after it
                # is for the next look), else where the inbox ends now
                return out, max(fresh) if fresh else max(newest, last_uid)

        try:
            return await asyncio.to_thread(_look)
        except imaplib.IMAP4.error as exc:
            raise RuntimeError(f"IMAP error: {exc}") from exc

    async def context_batch(self, cursor: dict[str, Any]) -> tuple[list[NewMail], dict[str, Any]]:
        """Read bounded previews following consent. The cursor is specific to the IMAP mailbox
        and its UIDVALIDITY. Even an empty INBOX has a real, initialized cursor.
        """
        from nanomuse.tools.email_tool import IMAP_TIMEOUT_S, _body_of, _decode

        address, password = self._creds()
        host, port = self.settings.imap_host, self.settings.imap_port
        mailbox = hashlib.sha256(f"{host}\n{port}\n{address}".encode()).hexdigest()
        now = datetime.now(UTC)

        def collect() -> tuple[list[NewMail], dict[str, Any]]:
            with imaplib.IMAP4_SSL(host, port, timeout=IMAP_TIMEOUT_S) as imap:
                imap.login(address, password)
                if imap.select("INBOX", readonly=True)[0] != "OK":
                    raise RuntimeError("cannot open INBOX")

                def number(code: str) -> int:
                    _, data = imap.response(code)
                    if not data or not data[0] or not data[0].isdigit():
                        raise RuntimeError("missing IMAP mailbox generation or high-water mark")
                    return int(data[0])

                validity = number("UIDVALIDITY")
                _, announced = imap.response("UIDNEXT")
                if announced and announced[0] and announced[0].isdigit():
                    newest = int(announced[0]) - 1
                else:
                    status, info = imap.status("INBOX", "(UIDNEXT UIDVALIDITY)")
                    fields = dict(
                        re.findall(rb"(UIDNEXT|UIDVALIDITY) (\d+)", (info[0] or b"").upper())
                    )
                    if (
                        status != "OK"
                        or fields.get(b"UIDVALIDITY") != str(validity).encode()
                        or not fields.get(b"UIDNEXT")
                    ):
                        raise RuntimeError("missing IMAP mailbox high-water mark")
                    newest = int(fields[b"UIDNEXT"]) - 1
                state = {"mailbox": mailbox, "validity": validity, "uid": newest}
                last = cursor.get("uid")
                if (
                    cursor.get("mailbox") != mailbox
                    or cursor.get("validity") != validity
                    or type(last) is not int
                    or last < 0
                ):
                    return [], state
                if last >= newest:
                    return [], cursor
                end = min(last + 512, newest)
                status, data = imap.uid("search", "UID", f"{last + 1}:{end}")
                if status != "OK":
                    raise RuntimeError("IMAP search failed")
                uids = sorted(
                    {
                        int(s)
                        for s in (data[0] or b"").split()
                        if s.isdigit() and last < int(s) <= end
                    }
                )
                batch = uids[:8]
                out: list[NewMail] = []
                for uid in batch:
                    status, parts = imap.uid(
                        "fetch", str(uid), "(UID INTERNALDATE BODY.PEEK[]<0.65536>)"
                    )
                    if status != "OK":
                        raise RuntimeError("IMAP preview fetch failed")
                    for index, part in enumerate(parts or []):
                        if (
                            not isinstance(part, tuple)
                            or not isinstance(part[0], bytes)
                            or not isinstance(part[1], bytes)
                        ):
                            continue  # expunged after the search
                        # Servers may put UID and INTERNALDATE after the body literal.
                        trailer = parts[index + 1] if index + 1 < len(parts) else b""
                        meta = part[0] + b" " + (trailer if isinstance(trailer, bytes) else b"")
                        if not re.search(rb"\bUID " + str(uid).encode() + rb"\b", meta, re.I):
                            continue
                        match = re.search(rb'INTERNALDATE "([^"]+)"', meta, re.I)
                        if not match:
                            continue
                        try:
                            received = email.utils.parsedate_to_datetime(
                                match[1].decode("ascii").strip().replace("-", " ", 2)
                            )
                        except (TypeError, ValueError, UnicodeError):
                            continue
                        if not received.tzinfo or not now - timedelta(
                            days=2
                        ) <= received <= now + timedelta(minutes=5):
                            continue
                        msg = email.message_from_bytes(part[1][:65536])
                        out.append(
                            NewMail(
                                uid,
                                _decode(msg.get("From")),
                                _decode(msg.get("Subject")),
                                received.isoformat(),
                                _body_of(msg)[:BODY_CHARS],
                            )
                        )
                        break
                state["uid"] = batch[-1] if len(uids) > len(batch) else end
                return out, state

        try:
            return await asyncio.to_thread(collect)
        except imaplib.IMAP4.error:
            raise RuntimeError("cannot read the connected mailbox") from None


__all__ = ["MailWatcher", "NewMail"]

"""Which conversation a model call belongs to, for the vendors that want to be told.

OpenCode Go asks every client to name itself with its own user agent and to send one stable id
per conversation in ``x-opencode-session`` (opencode.ai/docs/go, "Where can I use it?"). The
catalogue names such a header in an entry's ``session_header``; the chat clients add it to each
request with :func:`session_id`, and name nanoMuse with :data:`USER_AGENT`.

The agent loop says which conversation it is working on with :func:`conversation`, a context
variable, so every call made while the turn runs (the hands' model included) carries the same
id without threading it through each ``ask``. A call made outside a conversation (a connection
test, a background summary) carries the client's own id instead, stable for as long as the
client lives.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token

from nanomuse import __version__

_conversation: ContextVar[str | None] = ContextVar("nanomuse_conversation", default=None)

#: what a header value may be as it is: visible ASCII, short enough for any gateway
_HEADER_SAFE = re.compile(r"^[\x21-\x7e]{1,128}$")
_NAMESPACE = uuid.UUID("5b0f7c1e-3a52-4f4e-9d0e-6e616e6f4d75")

#: the user agent nanoMuse names itself with where a vendor asks for the client's own
USER_AGENT = f"nanoMuse/{__version__}"


@contextmanager
def conversation(conversation_id: str) -> Iterator[None]:
    """Model calls made inside the block belong to this conversation."""
    token = _conversation.set(conversation_id)
    try:
        yield
    finally:
        _conversation.reset(token)


def enter(conversation_id: str) -> Token[str | None]:
    """:func:`conversation` for a caller whose block is a ``try``: pass the token to
    :func:`leave` in its ``finally``."""
    return _conversation.set(conversation_id)


def leave(token: Token[str | None]) -> None:
    _conversation.reset(token)


def current_conversation() -> str | None:
    return _conversation.get()


def session_id(fallback: str) -> str:
    """The id to send for the current call: the conversation's, else ``fallback``. An id that
    is not a safe header value (spaces, non-ASCII, very long) is sent as a UUID derived from
    it, so it stays the same for the same conversation."""
    raw = _conversation.get() or fallback
    return raw if _HEADER_SAFE.match(raw) else str(uuid.uuid5(_NAMESPACE, raw))


def client_headers(extra: dict[str, str] | None, session_header: str) -> dict[str, str]:
    """The headers a client sends on every request: the slot's ``extra_headers``, plus
    nanoMuse's own user agent for a vendor that wants the client named (one the person set
    in ``extra_headers`` stands)."""
    headers = dict(extra or {})
    if session_header and not any(k.lower() == "user-agent" for k in headers):
        headers["User-Agent"] = USER_AGENT
    return headers


def new_fallback() -> str:
    """A client's own id, for the calls made outside any conversation."""
    return str(uuid.uuid4())


__all__ = [
    "USER_AGENT",
    "client_headers",
    "conversation",
    "current_conversation",
    "enter",
    "leave",
    "new_fallback",
    "session_id",
]

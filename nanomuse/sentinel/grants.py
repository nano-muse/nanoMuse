"""Approval grants: capabilities the user handed out, bound to a tool and a target.

Muse treats an approval as a strict capability, not a conversational "yes": it is bound to
the connector or destination it was given for, and it has a lifetime. Same here. A grant
key looks like ``web_fetch:example.com``, ``send_email:alice@example.com`` or ``shell:git``;
a bare tool name means the whole tool.

Scopes:

* ``once``         – this one call; nothing is stored
* ``conversation`` – until that conversation is cleared (``task`` meant this up to 0.1.30)
* ``session``      – until the process exits
* ``24h``      – for a day (persisted)
* ``always``   – until revoked (persisted)

Configuration binding:

A grant is given under one approval policy, so a store can be wired to the
policy it serves (the Sentinel and the gatekeeper both wire theirs): every
grant the store records is stamped with the policy's current fingerprint
(see :func:`policy_fingerprint`), and a grant is honoured only while the
live fingerprint still equals its stamp. Changing the policy pauses the
standing permissions given under it instead of silently extending them to
a policy they were never given under; changing it back revives them,
because a mismatched grant is skipped, never deleted. Grants recorded
before the binding existed carry no stamp, and a wired store does not
honour them: after an upgrade, a standing permission has to be given once
more. A store without a fingerprint provider behaves exactly as before.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from nanomuse.logger import logger

if TYPE_CHECKING:
    from nanomuse.config import SentinelSettings

GrantScope = Literal["once", "conversation", "session", "24h", "always"]
SCOPES: tuple[str, ...] = ("once", "conversation", "session", "24h", "always")
# The middle scope was "task" (one agent run) up to 0.1.30; clients that still say so mean
# the conversation, which is the scope the phone has always had.
LEGACY_SCOPES: dict[str, str] = {"task": "conversation"}
PERSISTED_SCOPES = ("24h", "always")
DAY = 24 * 3600.0


def normalize_scope(scope: str | None) -> str:
    """The scope under its current name; unknown or missing scopes are ``once``."""
    if not scope:
        return "once"
    scope = LEGACY_SCOPES.get(scope, scope)
    return scope if scope in SCOPES else "once"


@dataclass
class Grant:
    key: str
    tool: str
    target: str | None
    scope: str
    granted_at: float
    expires_at: float | None = None
    conversation_id: str | None = None
    # The policy fingerprint in force when the grant was given (see the
    # module docstring); None on grants recorded before the binding
    # existed, and on every grant from a store with no provider wired.
    config_fingerprint: str | None = None

    def active(self, now: float, conversation_id: str | None) -> bool:
        if self.scope == "conversation":
            return self.conversation_id is not None and self.conversation_id == conversation_id
        if self.expires_at is not None and now >= self.expires_at:
            return False
        return True

    def to_dict(self) -> dict:
        d = asdict(self)
        d["granted_at"] = _iso(self.granted_at)
        d["expires_at"] = _iso(self.expires_at) if self.expires_at else None
        return d


def _iso(ts: float | None) -> str | None:
    if ts is None:
        return None
    return datetime.fromtimestamp(ts, UTC).isoformat(timespec="seconds")


def grant_key(tool: str, target: str | None) -> str:
    return f"{tool}:{target}" if target else tool


def policy_fingerprint(settings: SentinelSettings) -> str:
    """A hash of the approval policy in ``settings``, and nothing else.

    The digest covers the fields that decide approvals: ``mode``,
    ``always_ask_tools``, ``always_allow_tools``, ``deny_tools``,
    ``egress_allowlist``, ``rules`` and ``taint_tracking``. The four lists
    have set semantics (the policy only asks whether a tool or a host is
    in them), so they are sorted first: reordering them in the config
    file is not a policy change and must not retire grants. Rules keep
    their order, because the first matching rule wins, so their order
    is part of the policy.

    Deliberately left out: ``audit_file`` (a path, not a policy) and
    ``gatekeeper`` with ``gatekeeper_socket`` (how a decision is
    transported, not what it is; the local store and the gatekeeper's
    store are separate stores over one file, and switching the
    gatekeeper changes the judge, not the meaning of a grant). The
    fingerprint also says nothing about the tools themselves, the
    model or the rest of the configuration: a tool whose behaviour
    changes under the same name is not caught by it. Only the hash is
    ever stored, never the configuration it came from.
    """
    payload = {
        "mode": settings.mode,
        "always_ask_tools": sorted(settings.always_ask_tools),
        "always_allow_tools": sorted(settings.always_allow_tools),
        "deny_tools": sorted(settings.deny_tools),
        "egress_allowlist": sorted(settings.egress_allowlist),
        "rules": [rule.model_dump(mode="json") for rule in settings.rules],
        "taint_tracking": settings.taint_tracking,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class GrantStore:
    """In-memory grants plus a JSON file for the ones that outlive the process.

    ``fingerprint`` is a provider for the live policy fingerprint, read
    on every stamp and every lookup rather than captured once: a
    settings object can be edited while the process runs, and the
    store must judge grants against the policy as it stands now.
    Without a provider the store stamps nothing and honours every
    grant it holds, the behaviour from before the binding existed.
    """

    def __init__(self, path: Path | None = None, *, fingerprint: Callable[[], str] | None = None):
        self.path = path
        self._fingerprint = fingerprint
        self._grants: list[Grant] = []
        self._mismatch_logged: set[tuple[str, str | None]] = set()
        self._load()

    # ------------------------------------------------------------------ persistence
    def _load(self) -> None:
        if not self.path or not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text("utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        now = time.time()
        if isinstance(data, list):
            # v1 file: a list of tool names that were "always allowed"
            self._grants = [
                Grant(key=t, tool=t, target=None, scope="always", granted_at=now) for t in data
            ]
            return
        for item in data.get("grants", []):
            try:
                g = Grant(
                    key=str(item["key"]),
                    tool=str(item.get("tool") or str(item["key"]).split(":", 1)[0]),
                    target=item.get("target"),
                    scope=str(item.get("scope", "always")),
                    granted_at=float(item.get("granted_at") or now),
                    expires_at=(float(item["expires_at"]) if item.get("expires_at") else None),
                    config_fingerprint=(
                        str(item["config_fingerprint"]) if item.get("config_fingerprint") else None
                    ),
                )
            except (KeyError, TypeError, ValueError):
                continue
            if g.scope in PERSISTED_SCOPES and g.active(now, None):
                self._grants.append(g)

    def _save(self) -> None:
        if not self.path:
            return
        keep = [
            {
                "key": g.key,
                "tool": g.tool,
                "target": g.target,
                "scope": g.scope,
                "granted_at": g.granted_at,
                "expires_at": g.expires_at,
                "config_fingerprint": g.config_fingerprint,
            }
            for g in self._grants
            if g.scope in PERSISTED_SCOPES
        ]
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({"version": 2, "grants": keep}, indent=1), "utf-8")

    # ------------------------------------------------------------------ queries
    def _honoured(self, grant: Grant) -> bool:
        """Whether ``grant`` still counts under the store's configuration binding.

        Without a fingerprint provider every grant counts. With one, a
        grant counts only while the live fingerprint equals its stamp;
        a grant stamped under another configuration, or by a version
        that stamped nothing, is skipped and the skip is logged once
        per grant, so a retired permission is visible in the log. The
        grant itself is left in place: it counts again if the
        configuration returns to what it was when it was given.
        """
        if self._fingerprint is None:
            return True
        if grant.config_fingerprint == self._fingerprint():
            return True
        mark = (grant.key, grant.config_fingerprint)
        if mark not in self._mismatch_logged:
            self._mismatch_logged.add(mark)
            logger.info(
                "grant {} is not honoured: the sentinel configuration changed since it was given",
                grant.key,
            )
        return False

    def _exact(self, key: str, now: float, conversation_id: str | None) -> Grant | None:
        for g in self._grants:
            if g.key == key and g.active(now, conversation_id) and self._honoured(g):
                return g
        return None

    def match(self, key: str, conversation_id: str | None = None) -> Grant | None:
        """The grant covering ``key``, if any.

        A grant for the whole tool covers every target. A call with several targets
        (``shell:git,head`` – a pipeline; ``send_email:a@x,b@y`` – two recipients) is covered
        only when every single target is.
        """
        now = time.time()
        found = self._exact(key, now, conversation_id)
        if found is not None:
            return found
        tool, _, target = key.partition(":")
        if target:
            toolwide = self._exact(tool, now, conversation_id)
            if toolwide is not None:
                return toolwide
            parts = [p for p in target.split(",") if p]
            if len(parts) > 1:
                grants = [self._exact(grant_key(tool, p), now, conversation_id) for p in parts]
                if all(grants):
                    return grants[0]
        return None

    def active(self, conversation_id: str | None = None) -> list[Grant]:
        now = time.time()
        return [
            g
            for g in self._grants
            if (g.active(now, conversation_id) or g.scope == "conversation") and self._honoured(g)
        ]

    # ------------------------------------------------------------------ mutations
    def add(
        self, tool: str, target: str | None, scope: str, conversation_id: str | None = None
    ) -> Grant | None:
        """Store a grant. Several targets (``git,head``) become one grant each, so
        approving a pipeline also covers its programs on their own — and vice versa."""
        scope = normalize_scope(scope)
        if scope == "once":
            return None
        if scope == "conversation" and not conversation_id:
            logger.debug("conversation-scoped grant requested outside one; treating as once")
            return None
        now = time.time()
        fingerprint = self._fingerprint() if self._fingerprint is not None else None
        targets: list[str | None] = [p for p in target.split(",") if p] if target else [None]
        first: Grant | None = None
        persist_changed = scope in PERSISTED_SCOPES
        for t in targets:
            grant = Grant(
                key=grant_key(tool, t),
                tool=tool,
                target=t,
                scope=scope,
                granted_at=now,
                expires_at=now + DAY if scope == "24h" else None,
                conversation_id=conversation_id if scope == "conversation" else None,
                config_fingerprint=fingerprint,
            )
            # A conversation's answer replaces only its own grant. Another chat may
            # have approved the same tool too; neither decision revokes the other.
            replaced = [
                g
                for g in self._grants
                if g.key == grant.key and g.conversation_id == grant.conversation_id
            ]
            persist_changed |= any(g.scope in PERSISTED_SCOPES for g in replaced)
            self._grants = [g for g in self._grants if g not in replaced]
            self._grants.append(grant)
            first = first or grant
        # Replacing a durable grant with a session grant must remove it from disk too.
        if persist_changed:
            self._save()
        return first

    def revoke(self, key: str) -> bool:
        before = len(self._grants)
        self._grants = [g for g in self._grants if g.key != key]
        if len(self._grants) != before:
            self._save()
            return True
        return False

    def end_conversation(self, conversation_id: str) -> None:
        """The conversation is over (deleted, cleared, or the run that stood in for one
        ended): its grants go with it."""
        self._grants = [
            g
            for g in self._grants
            if not (g.scope == "conversation" and g.conversation_id == conversation_id)
        ]

    def clear(self) -> None:
        self._grants.clear()
        self._save()

    def purge_expired(self) -> None:
        now = time.time()
        self._grants = [
            g
            for g in self._grants
            if g.scope == "conversation" or g.expires_at is None or now < g.expires_at
        ]


__all__ = [
    "DAY",
    "LEGACY_SCOPES",
    "PERSISTED_SCOPES",
    "SCOPES",
    "Grant",
    "GrantScope",
    "GrantStore",
    "grant_key",
    "normalize_scope",
    "policy_fingerprint",
]

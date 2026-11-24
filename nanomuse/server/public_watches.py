"""Account-owned watch choices, quiet baselines and changes waiting for context review."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable, Iterable
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

from nanomuse.server import public_feed, public_sources
from nanomuse.server.context_sources import ContextSample, preview
from nanomuse.server.events import MAIN_THREAD
from nanomuse.server.preparations import Source, fingerprint
from nanomuse.server.waiting import personal_message
from nanomuse.server.watch_discovery import (
    WatchCandidate,
    normalize_watch,
    reference_watches,
    suggest_watches,
)

if TYPE_CHECKING:
    from nanomuse.server.context_watch import ContextWatch

_MAX_ACTIVE = 16
_MAX_SUGGESTED = 16
_MAX_AGE = timedelta(days=7).total_seconds()


def _row(kind: str, target: str, status: str, origin: str = "manual") -> dict[str, Any]:
    return {
        "id": fingerprint(kind, target)[:32],
        "kind": kind,
        "target": target,
        "status": status,
        "label": target,
        "origin": origin,
    }


def _capacity(rows: dict[str, Any], row: dict[str, Any]) -> bool:
    status = row["status"]
    return (row["id"] in rows or len(rows) < 512) and sum(
        r["status"] == status for key, r in rows.items() if key != row["id"]
    ) < (_MAX_ACTIVE if status == "active" else _MAX_SUGGESTED)


def edit_choices(
    state: dict[str, Any],
    *,
    enabled: bool | None = None,
    share_public_updates: bool | None = None,
    kind: str = "",
    target: str = "",
    watch_id: str = "",
    action: str = "",
) -> None:
    rows = state.setdefault("watches", {})
    if enabled is not None or share_public_updates is not None:
        if share_public_updates is not None and share_public_updates != state.get(
            "share_public_updates", False
        ):
            state["share_public_updates"] = share_public_updates
            state["share_generation"] = uuid.uuid4().hex if share_public_updates else ""
        if enabled is not None and enabled != state.get("enabled", True):
            if state.get("share_public_updates"):
                state["share_generation"] = uuid.uuid4().hex
            state["enabled"] = enabled
            state["discover_after"] = datetime.now().timestamp()
            for key, row in list(rows.items()):
                rows[key] = _row(
                    row["kind"], row["target"], row["status"], row.get("origin", "manual")
                )
    elif not state.get("enabled", True) and action not in ("pause", "dismiss"):
        raise ValueError("Enable public watches first.")
    else:
        original = rows.get(watch_id)
        if watch_id and (not original or original["status"] == "dismissed"):
            raise ValueError("This watch is no longer available.")
        transitions = {
            "confirm": ("suggested", "active"),
            "pause": ("active", "paused"),
            "resume": ("paused", "active"),
        }
        if original:
            if action == "dismiss":
                row = _row(original["kind"], original["target"], "dismissed")
            else:
                if action not in transitions or original["status"] != transitions[action][0]:
                    raise ValueError("This watch changed. Reopen the settings.")
                if original["kind"] == "scholar_profile" and action == "confirm":
                    if kind not in ("research_author", "research_work"):
                        raise ValueError("Choose an exact research author identifier or DOI.")
                else:
                    if kind or target:
                        raise ValueError("The target of this watch cannot be changed.")
                    kind, target = original["kind"], original["target"]
                row = _row(kind, normalize_watch(kind, target), transitions[action][1])
        else:
            row = _row(
                kind,
                normalize_watch(kind, target),
                "suggested" if kind == "scholar_profile" else "active",
            )
        if row["status"] in ("active", "suggested") and not _capacity(rows, row):
            raise ValueError("The watch limit has been reached.")
        if original and watch_id != row["id"]:
            rows[watch_id] = _row(original["kind"], original["target"], "dismissed")
        if rows.get(row["id"], {}).get("status") != row["status"]:
            if original and row["id"] == watch_id:
                row["origin"] = original.get("origin", "manual")
            rows[row["id"]] = row
    state["generation"] = uuid.uuid4().hex


def add_candidates(
    state: dict[str, Any], candidates: Iterable[WatchCandidate], origin: str = "chat"
) -> bool:
    if not state.get("enabled", True):
        return False
    rows = state.setdefault("watches", {})
    edited = False
    for candidate in candidates:
        status = (
            "active" if candidate.confirmed and candidate.kind != "scholar_profile" else "suggested"
        )
        row = _row(
            candidate.kind, normalize_watch(candidate.kind, candidate.target), status, origin
        )
        old = rows.get(row["id"])
        if old and not (old["status"] == "suggested" and status == "active"):
            continue
        if _capacity(rows, row):
            rows[row["id"]] = row
            edited = True
    if edited:
        state["generation"] = uuid.uuid4().hex
    return edited


def observe_text(state: dict[str, Any], text: str, *, turn: str, now: datetime) -> bool:
    """Learn from one verified personal turn. Hosts own the account and timestamp checks."""
    stamp = now.timestamp()
    if not state.get("enabled", True) or stamp < state.get("discover_after", 0):
        return False
    processed = state.get("processed", [])
    key = fingerprint(turn, text)
    if key in processed:
        return False
    cutoff = max(state.get("discover_after", 0), (now - timedelta(days=30)).timestamp())
    mentions = {key: item for key, item in state.get("mentions", {}).items() if item[1] >= cutoff}
    recurring = []
    for ref in reference_watches(text):
        identity = fingerprint(ref.kind, ref.target)
        last = mentions.pop(identity, None)
        if last and last[0] != fingerprint(turn):
            recurring.append(ref)
        mentions[identity] = [fingerprint(turn), stamp]
    add_candidates(state, suggest_watches(text))
    add_candidates(state, recurring, "recurring")
    state["mentions"] = dict(list(mentions.items())[-256:])
    state["processed"] = (processed + [key])[-160:]
    return True


async def refresh_row(
    row: dict[str, Any], now: datetime, redact: Callable[[str], str] | None = None
) -> None:
    stamp = now.timestamp()
    kind = row["kind"]
    try:
        async with asyncio.timeout(22):
            if kind == "feed":
                feed_url, items = await public_feed.fetch_feed(row["target"], now=now)
                if row.get("feed_url") != feed_url:
                    # A publisher can replace its advertised feed. A new one gets a quiet baseline.
                    row.pop("seen", None)
                    row.pop("pending", None)
                row["feed_url"] = feed_url
            else:
                items = await public_sources.fetch_public(kind, row["target"], now=now)
    except Exception:
        failures = min(row.get("failures", 0) + 1, 6)
        row.update(failures=failures, next=stamp + min(3600 * 12, 900 * 2 ** (failures - 1)))
        return
    seen = row.get("seen", [])
    pending = {k: v for k, v in row.get("pending", {}).items() if stamp - v["at"] <= _MAX_AGE}
    fresh = {}
    # Keep only changes still present in the latest complete sample. A closed issue or
    # withdrawn notice should disappear from the queue, and a corrected title should replace it.
    known = set(seen)
    for item in items[:100]:
        key = fingerprint(item.key)
        if key not in known:
            known.add(key)
            seen.append(key)
            observed = stamp
        elif key in pending:
            observed = pending[key]["at"]
        else:
            continue
        if "seen" in row and key not in fresh:
            fresh[key] = {
                "text": preview(item.text, 520, redact),
                "url": public_link(item.url),
                "at": observed,
            }
    row.update(
        seen=seen[-512:],
        failures=0,
        last_checked=now.isoformat(timespec="minutes"),
        next=stamp + (86400 if kind.startswith("research_") else 14400),
        pending=dict(list(fresh.items())[:40]),
    )


class PublicWatches:
    def __init__(self, owner: ContextWatch):
        self.owner = owner
        self.service = owner.service

    def _load(self, scope: str) -> dict[str, Any]:
        if not scope:
            return {}
        name = "public:" + scope
        state = self.owner._load(name)
        if not state and self.owner._file(name).exists():
            # An unreadable preference file cannot be treated as a fresh install.
            return {"enabled": False}
        return state

    def _save(self, scope: str, state: dict[str, Any]) -> None:
        self.owner._save("public:" + scope, state)

    def revision(self, scope: str) -> str:
        return fingerprint(
            scope, str(self.service.hub.account_epoch), self._load(scope).get("generation", "")
        )

    def has_active(self, scope: str) -> bool:
        state = self._load(scope)
        return state.get("enabled", True) and any(
            r["status"] == "active" for r in state.get("watches", {}).values()
        )

    def sharing_token(self, scope: str) -> str:
        """Only the current signed-in account can publish newly approved public updates."""
        if not scope.startswith("account:") or not self.service.sync.active:
            return ""
        state = self._load(scope)
        if state.get("enabled", True) and state.get("share_public_updates") is True:
            return str(state.get("share_generation") or "")
        return ""

    def view(self) -> dict[str, Any]:
        scope = self.service._chat_followup_scope()
        state = self._load(scope)
        return {
            "enabled": bool(scope and state.get("enabled", True)),
            "can_share": scope.startswith("account:"),
            "share_public_updates": state.get("share_public_updates") is True,
            "revision": self.revision(scope),
            "watches": [
                {
                    **{name: r[name] for name in ("id", "kind", "label", "target", "status")},
                    "origin": r.get("origin"),
                    "last_checked": r.get("last_checked"),
                    "unavailable": bool(r.get("failures")),
                }
                for r in state.get("watches", {}).values()
                if r["status"] != "dismissed"
            ],
        }

    def configure(
        self,
        revision: str,
        *,
        enabled: bool | None = None,
        share_public_updates: bool | None = None,
        kind: str = "",
        target: str = "",
        watch_id: str = "",
        action: str = "",
    ) -> dict[str, Any]:
        scope = self.service._chat_followup_scope()
        if not scope or self.revision(scope) != revision:
            raise ValueError("The active account or watch settings changed. Reopen the settings.")
        if share_public_updates is True and not scope.startswith("account:"):
            raise ValueError("Sign in before sharing public updates.")
        state = self._load(scope)
        edit_choices(
            state,
            enabled=enabled,
            share_public_updates=share_public_updates,
            kind=kind,
            target=target,
            watch_id=watch_id,
            action=action,
        )
        self._save(scope, state)
        self.owner.next_poll = 0
        self.service.wake()
        return self.view()

    def observe_connected(
        self, scope: str, samples: Iterable[ContextSample], now: datetime
    ) -> None:
        state = self._load(scope)
        recent = {
            k
            for k, (_, ts) in state.get("mentions", {}).items()
            if ts >= max(state.get("discover_after", 0), (now - timedelta(days=30)).timestamp())
        }
        candidates = [
            c
            for sample in samples
            for c in (
                *sample.candidates,
                *(ref for ref in sample.references if fingerprint(ref.kind, ref.target) in recent),
            )
        ]
        if add_candidates(state, candidates, "connected"):
            self._save(scope, state)

    def discover(self, scope: str, now: datetime) -> None:
        state = self._load(scope)
        if not state.get("enabled", True):
            return
        cutoff = max(state.get("discover_after", 0), (now - timedelta(days=30)).timestamp())
        edited = False
        for event in self.service.threads[MAIN_THREAD].timeline.events[-120:]:
            if not personal_message(event) or not event.get("id") or not event.get("text"):
                continue
            try:
                ts = datetime.fromisoformat(event["ts"]).astimezone()
            except (KeyError, ValueError, TypeError):
                continue
            if cutoff <= ts.timestamp() <= now.timestamp():
                text = self.service.app.vault.redact(event["text"][:6000])
                if observe_text(state, text, turn=event["id"], now=ts):
                    edited = True
        if edited:
            self._save(scope, state)

    async def refresh(self, scope: str, now: datetime) -> None:
        state = self._load(scope)
        if not state.get("enabled", True):
            return
        revision = self.revision(scope)
        stamp = now.timestamp()
        due = sorted(
            (
                r
                for r in state.get("watches", {}).values()
                if r["status"] == "active" and r.get("next", 0) <= stamp
            ),
            key=lambda r: r.get("next", 0),
        )[:3]

        await asyncio.gather(*(refresh_row(r, now, self.service.app.vault.redact) for r in due))
        if (
            due
            and self.service._chat_followup_scope() == scope
            and self.revision(scope) == revision
            and self.service.profile.proactive
        ):
            self._save(scope, state)

    def pending(self, scope: str, now: datetime) -> dict[str, tuple[Source, str]]:
        state = self._load(scope)
        records: dict[str, tuple[Source, str]] = {}
        if state.get("enabled", True):
            for row in state.get("watches", {}).values():
                if row["status"] != "active":
                    continue
                for key, change in row.get("pending", {}).items():
                    if 0 <= now.timestamp() - change["at"] <= _MAX_AGE:
                        source = Source(
                            "public_watch",
                            key,
                            self.service.app.vault.redact(change["text"]),
                            True,
                            label=row["target"],
                        )
                        records.setdefault(fingerprint(source.kind, key), (source, change["url"]))
        return records

    def consume(self, scope: str, keys: set[str]) -> None:
        if not keys:
            return
        state = self._load(scope)
        for row in state.get("watches", {}).values():
            pending = row.get("pending", {})
            for key in keys:
                pending.pop(key, None)
        self._save(scope, state)


def public_link(url: str) -> str:
    # This link comes from an adapter, never the review model or private connected context.
    if not url or len(url) > 1600 or any(c.isspace() or ord(c) < 32 or c in '<>\\`"' for c in url):
        return ""
    try:
        parsed = urlsplit(url)
        if (
            parsed.scheme == "https"
            and parsed.hostname
            and not parsed.username
            and not parsed.password
        ):
            return url
    except ValueError:
        pass
    return ""

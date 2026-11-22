"""Current Feed suggestions grounded in saved goals and the connected calendar cache."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime, timedelta
from typing import Any
from weakref import WeakKeyDictionary

from nanomuse.calendar.feeds import CalendarFeeds
from nanomuse.calendar.ics import Occurrence, expand
from nanomuse.goals.store import Goal, parse_due


def _key(*parts: str) -> str:
    return hashlib.sha256(json.dumps(parts, ensure_ascii=False).encode()).hexdigest()


def current_followups(
    goals: list[Goal],
    calendar: CalendarFeeds,
    now: datetime,
    hidden: dict[str, str],
    *,
    only_id: str | None = None,
) -> list[dict[str, Any]]:
    today = now.date()
    cards = []
    ranked: list[tuple[int, int, str, dict[str, Any]]] = []
    for goal in goals:
        due = parse_due(goal.due)
        if goal.status != "active" or due is None:
            continue
        days = (due - today).days
        if not -7 <= days <= 1:
            continue
        if goal.steps and all(s.status in ("done", "skipped") for s in goal.steps):
            continue
        key = _key("goal", goal.id, due.isoformat())
        if (only_id is not None and key != only_id) or hidden.get(key, "") > today.isoformat():
            continue
        step = goal.next_step
        card = {
            "id": key,
            "kind": "goal",
            "goal_id": goal.id,
            "title": goal.title,
            "due": due.isoformat(),
            "days_until": days,
            "next_step": step.title if step else None,
        }
        ranked.append((0 if days == 0 else 1 if days < 0 else 2, abs(days), goal.id, card))
    if ranked:
        cards.append(min(ranked, key=lambda row: row[:3])[3])
        if only_id is not None:
            return cards
    elif review := _pending_review(goals, now, hidden, only_id):
        cards.append(review)
    overlap = _upcoming_overlap(calendar, now, hidden, today, only_id=only_id)
    if overlap:
        cards.append(overlap)
    return cards


def _pending_review(
    goals: list[Goal], now: datetime, hidden: dict[str, str], only_id: str | None
) -> dict[str, Any] | None:
    selected: dict[str, Any] | None = None
    best: tuple[int, float, str] | None = None
    today = now.date()
    for goal in goals:
        if goal.status != "active":
            continue
        # Surface a concrete decision or obstacle recorded on this goal. The clock alone
        # cannot tell us that a person has stopped making progress.
        records = [
            ("blocked", step.id, step.title, step.note, step.updated_at)
            for step in goal.steps
            if step.status == "blocked"
        ]
        if goal.proposal:
            records.append(
                (
                    "proposal",
                    json.dumps(goal.proposal.get("steps", [])),
                    str(goal.proposal.get("reason") or ""),
                    "",
                    str(goal.proposal.get("created_at") or ""),
                )
            )
        for reason, source, detail, note, stamp in records:
            try:
                observed = datetime.fromisoformat(stamp)
            except ValueError:
                continue
            if observed.tzinfo is None:
                observed = observed.replace(tzinfo=UTC)
            local = observed.astimezone(now.tzinfo)
            if not (0 <= (today - local.date()).days <= 7) or observed > now or not detail:
                continue
            key = _key("review", goal.id, reason, source, detail, note, stamp)
            if (only_id is not None and key != only_id) or hidden.get(key, "") > today.isoformat():
                continue
            rank = (0 if reason == "proposal" else 1, -observed.timestamp(), key)
            if best is None or rank < best:
                best = rank
                selected = {
                    "kind": "review",
                    "id": key,
                    "goal_id": goal.id,
                    "title": goal.title,
                    "reason": reason,
                    "detail": detail,
                    "note": note,
                    "observed_on": local.date().isoformat(),
                }
    return selected


# Each configured calendar instance holds at most one expansion. Re-check freshness on
# every draw; moving the clock inside the hour must still update the exact 24-hour window.
_CachedWindow = tuple[datetime, tuple[tuple[str, float, int], ...], list[Occurrence]]
_windows: WeakKeyDictionary[CalendarFeeds, _CachedWindow] = WeakKeyDictionary()


def _busy_events(calendar: CalendarFeeds, now: datetime) -> list[Occurrence]:
    if not calendar.configured:
        _windows.pop(calendar, None)
        return []
    stamp = now.timestamp()
    fresh = [
        state
        for feed in calendar.settings.feeds
        if (state := calendar.states.get(feed.name))
        and not state.error
        and 0 <= stamp - state.fetched_at <= calendar.settings.refresh_minutes * 60
    ]
    hour = now.astimezone(UTC).replace(minute=0, second=0, microsecond=0)
    sources = tuple((s.name, s.fetched_at, id(s.events)) for s in fresh)
    cached = _windows.get(calendar)
    if cached is not None and cached[0] == hour and cached[1] == sources:
        return cached[2]
    events: dict[tuple[str, datetime], Occurrence] = {}
    for state in fresh:
        for item in expand(state.events, hour, hour + timedelta(hours=25)):
            begins = item.start.astimezone(UTC)
            if not item.all_day and not item.transparent and item.end.astimezone(UTC) > begins:
                events.setdefault((item.uid, begins), item)
    ordered = [events[k] for k in sorted(events, key=lambda k: (k[1], k[0]))]
    _windows[calendar] = (hour, sources, ordered)
    return ordered


def _upcoming_overlap(
    calendar: CalendarFeeds,
    now: datetime,
    hidden: dict[str, str],
    today: date,
    *,
    only_id: str | None = None,
) -> dict[str, Any] | None:
    start = now.astimezone(UTC)
    end = start + timedelta(hours=24)
    active: list[Occurrence] = []
    for later in _busy_events(calendar, now):
        begins = later.start.astimezone(UTC)
        if begins >= end:
            break
        if later.end.astimezone(UTC) <= start:
            continue
        active = [e for e in active if e.end.astimezone(UTC) > begins]
        for other in active:
            if other.uid == later.uid:
                continue
            until = min(other.end.astimezone(UTC), later.end.astimezone(UTC))
            if until <= max(start, begins):
                continue
            pair = sorted((other, later), key=lambda e: (e.start.astimezone(UTC), e.uid))
            key = _key(
                "overlap",
                *(
                    v
                    for e in pair
                    for v in (
                        e.uid,
                        e.start.astimezone(UTC).isoformat(),
                        e.end.astimezone(UTC).isoformat(),
                    )
                ),
            )
            if (only_id is not None and key != only_id) or hidden.get(key, "") > today.isoformat():
                continue
            return {
                "id": key,
                "kind": "overlap",
                "titles": [e.summary for e in pair],
                "start": begins.isoformat(),
                "end": until.isoformat(),
            }
        active.append(later)
    return None

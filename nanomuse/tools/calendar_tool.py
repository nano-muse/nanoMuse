"""The ``calendar`` tool: agenda, search, free time, and events drafted as ``.ics`` files.

With Google Calendar connected over OAuth the same tool also reads every calendar the
account can see and — when the write scope was granted — creates, changes and deletes
events directly (``create`` / ``update`` / ``delete`` / ``calendars``).
"""

from __future__ import annotations

import html
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from nanomuse.calendar import CalendarFeeds, GoogleError, make_ics
from nanomuse.schema import RiskLevel, ToolResult
from nanomuse.tools.base import BaseTool, CallAssessment


def _parse_day(value: str | None, today: date) -> date:
    v = (value or "").strip().lower()
    if not v or v == "today":
        return today
    if v == "tomorrow":
        return today + timedelta(days=1)
    if v == "yesterday":
        return today - timedelta(days=1)
    return date.fromisoformat(v[:10])


def _parse_when(value: str, tz: Any) -> tuple[datetime, bool]:
    """'YYYY-MM-DD HH:MM' → aware local datetime; 'YYYY-MM-DD' → midnight, all-day."""
    v = value.strip().replace("T", " ")
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", v):
        return datetime.combine(date.fromisoformat(v), datetime.min.time(), tzinfo=tz), True
    dt = datetime.strptime(v[:16], "%Y-%m-%d %H:%M")
    return dt.replace(tzinfo=tz), False


def _slug(text: str) -> str:
    s = re.sub(r"[^\w\u3400-\u9fff-]+", "-", text.strip().lower()).strip("-")
    return (s or "event")[:60]


class Calendar(BaseTool):
    name: str = "calendar"
    description: str = (
        "The user's calendar. Actions: `agenda` — the events on a `day` ('today', "
        "'tomorrow' or 'YYYY-MM-DD') and the `days` after it (default 1, max 31); `search` — "
        "events whose title, place or notes contain `query` (past 90 and next 180 days); "
        "`free` — gaps of at least `minutes` in the working hours of `day`; `draft` — write an "
        "event as an .ics file the user can add with a tap (`title`, `start` 'YYYY-MM-DD HH:MM' "
        "or 'YYYY-MM-DD' for all-day, `end` likewise or `duration_minutes`, optional "
        "`location`, `notes`). When Google Calendar is connected the tool also writes directly: "
        "`create` — add an event (`title`, `start`, `end`/`duration_minutes`, optional "
        "`location`, `notes`, `calendar`); `update` — change an event by `event_id` (needs "
        "`calendar`); `delete` — remove an event by `event_id` (needs `calendar`); `calendars` "
        "— list the Google calendars the account can write to. An agenda or search entry for a "
        "Google event shows its `event_id` in parentheses. Times are the user's local time."
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": [
                    "agenda",
                    "search",
                    "free",
                    "draft",
                    "refresh",
                    "create",
                    "update",
                    "delete",
                    "calendars",
                ],
            },
            "day": {"type": "string", "description": "'today', 'tomorrow' or 'YYYY-MM-DD'"},
            "days": {"type": "integer", "minimum": 1, "maximum": 31},
            "query": {"type": "string"},
            "minutes": {"type": "integer", "minimum": 5, "description": "free: shortest gap"},
            "title": {"type": "string"},
            "start": {"type": "string"},
            "end": {"type": "string"},
            "duration_minutes": {"type": "integer", "minimum": 5},
            "location": {"type": "string"},
            "notes": {"type": "string"},
            "calendar": {"type": "string", "description": "Google calendar id (default: primary)"},
            "event_id": {"type": "string", "description": "update/delete: the event's id"},
            "recurrence": {
                "type": "string",
                "description": "create: an RFC 5545 RRULE, e.g. RRULE:FREQ=WEEKLY;BYDAY=MO",
            },
        },
        "required": ["action"],
    }
    risk: RiskLevel = RiskLevel.SAFE
    reads_private_data: bool = True
    feeds: CalendarFeeds
    workspace: Path

    def assess(self, args: dict[str, Any]) -> CallAssessment:
        a = super().assess(args)
        action = str(args.get("action") or "?")
        if action in ("draft", "create", "update", "delete"):
            a.risk = RiskLevel.MODERATE
            a.reads_private_data = False
            title = html.unescape(str(args.get("title") or ""))
            if action == "draft":
                a.summary = f"calendar: draft “{title}” {args.get('start', '')}"
            elif action == "create":
                a.summary = f"calendar: create “{title}” {args.get('start', '')}"
            elif action == "update":
                a.summary = f"calendar: update event {args.get('event_id', '')}"
            else:
                a.summary = f"calendar: delete event {args.get('event_id', '')}"
        elif action == "search":
            a.summary = f"calendar: search “{args.get('query', '')}”"
        elif action == "free":
            a.summary = f"calendar: free time {args.get('day') or 'today'}"
        elif action == "refresh":
            a.reads_private_data = False
            a.summary = "calendar: refresh feeds"
        elif action == "calendars":
            a.summary = "calendar: list writable calendars"
        else:
            span = f" +{args['days']}d" if args.get("days") else ""
            a.summary = f"calendar: agenda {args.get('day') or 'today'}{span}"
        return a

    async def execute(self, action: str = "agenda", **args: Any) -> ToolResult:
        feeds = self.feeds
        if action in ("create", "update", "delete", "calendars"):
            return await self._write(action, args)
        if not feeds.configured and action != "draft":
            return ToolResult.fail(
                "no calendar is connected. The user can add one under Connections → Calendar "
                "(a private .ics link, or sign in with Google)."
            )
        today = datetime.now(feeds.tz).date()
        try:
            if action == "refresh":
                status = await feeds.refresh(force=True)
                lines = [
                    f"{f['name']}: {f['events']} events"
                    + (f" — {f['error']}" if f["error"] else "")
                    for f in status["feeds"]
                ]
                return ToolResult(output="Refreshed.\n" + "\n".join(lines))
            if action == "draft":
                return self._draft(args)
            await feeds.refresh()  # only if stale
            if action == "search":
                query = str(args.get("query") or "").strip()
                if not query:
                    return ToolResult.fail("search needs a query")
                hits = feeds.search(query, today)[:30]
                head = (
                    f"{len(hits)} event(s) matching “{query}”:"
                    if hits
                    else f"No events match “{query}”."
                )
                return ToolResult(output=head + ("\n" + feeds.render(hits, today) if hits else ""))
            day = _parse_day(args.get("day"), today)
            if action == "free":
                minutes = int(args.get("minutes") or 30)
                s = feeds.settings
                slots = feeds.free_slots(day, minutes, s.day_start, s.day_end)
                # All-day events do not block hours, but the user may well be away: say so.
                all_day = [o.summary for o in feeds.agenda(day) if o.all_day]
                note = (
                    f"\nAll-day that day: {', '.join(all_day)} — the gaps assume it leaves the hours free; check with the user."
                    if all_day
                    else ""
                )
                if not slots:
                    return ToolResult(
                        output=f"No free gap of {minutes}+ minutes on {day:%a %Y-%m-%d} between {s.day_start} and {s.day_end}."
                        + note
                    )
                lines = [f"  {sl.start:%H:%M}–{sl.end:%H:%M}  ({sl.minutes} min)" for sl in slots]
                return ToolResult(
                    output=f"Free on {day:%a %Y-%m-%d} ({s.day_start}–{s.day_end}), gaps of {minutes}+ min:\n"
                    + "\n".join(lines)
                    + note
                )
            days = max(1, min(31, int(args.get("days") or 1)))
            items = feeds.agenda(day, days)
            note = self._errors_note()
            return ToolResult(output=feeds.render(items, today) + note)
        except ValueError as exc:
            return ToolResult.fail(str(exc))

    # ------------------------------------------------------------------ Google writes
    async def _write(self, action: str, args: dict[str, Any]) -> ToolResult:
        feeds = self.feeds
        if not feeds.google.connected:
            return ToolResult.fail(
                "Google Calendar is not connected. The user can sign in under "
                "Connections → Calendar → Connect Google."
            )
        if action == "calendars":
            try:
                calendars = await feeds.write_calendars()
            except GoogleError as exc:
                return ToolResult.fail(str(exc))
            if not calendars:
                return ToolResult(output="No writable Google calendars on this account.")
            lines = [
                f"  {c['id']}  ({c['name']}{', primary' if c['primary'] else ''})"
                for c in calendars
            ]
            return ToolResult(output="Writable Google calendars:\n" + "\n".join(lines))

        status = feeds.google.status()
        if not status.get("can_write"):
            return ToolResult.fail(
                "the Google connection is read-only. Sign in again under Connections → "
                "Calendar and allow access so the agent can change events."
            )
        if not feeds.settings.google.write:
            return ToolResult.fail(
                "writing to Google Calendar is turned off. The user can enable it under "
                "Connections → Calendar."
            )
        calendar_id = str(
            args.get("calendar") or feeds.settings.google.default_calendar or "primary"
        )
        try:
            if action == "delete":
                event_id = str(args.get("event_id") or "").strip()
                if not event_id:
                    return ToolResult.fail("delete needs an event_id")
                await feeds.delete_event(calendar_id=calendar_id, event_id=event_id)
                return ToolResult(output=f"Deleted event {event_id}.")
            if action == "update":
                event_id = str(args.get("event_id") or "").strip()
                if not event_id:
                    return ToolResult.fail("update needs an event_id")
                fields = self._event_fields(args)
                if isinstance(fields, ToolResult):
                    return fields
                result = await feeds.update_event(
                    calendar_id=calendar_id, event_id=event_id, **fields
                )
                return self._write_output("Updated", result)
            # create
            fields = self._event_fields(args)
            if isinstance(fields, ToolResult):
                return fields
            recurrence = str(args.get("recurrence") or "").strip()
            result = await feeds.create_event(
                calendar_id=calendar_id, recurrence=recurrence, **fields
            )
            return self._write_output("Created", result)
        except GoogleError as exc:
            return ToolResult.fail(str(exc))
        except ValueError as exc:
            return ToolResult.fail(str(exc))

    def _event_fields(self, args: dict[str, Any]) -> dict[str, Any] | ToolResult:
        title = html.unescape(str(args.get("title") or "")).strip()
        if not title:
            return ToolResult.fail("an event needs a title")
        if not args.get("start"):
            return ToolResult.fail("an event needs a start")
        tz = self.feeds.tz
        start, all_day = _parse_when(str(args["start"]), tz)
        if args.get("end"):
            end, _ = _parse_when(str(args["end"]), tz)
            if all_day:
                end = end + timedelta(days=1)  # DTEND is exclusive for all-day events
        elif all_day:
            end = start + timedelta(days=1)
        else:
            end = start + timedelta(minutes=int(args.get("duration_minutes") or 60))
        if end <= start:
            return ToolResult.fail("the end must be after the start")
        return {
            "summary": title,
            "start": start,
            "end": end,
            "all_day": all_day,
            # None means "not given" (leave it as it is on an update); "" means "clear it"
            "location": html.unescape(str(args["location"])) if "location" in args else None,
            "description": html.unescape(str(args["notes"])) if "notes" in args else None,
        }

    def _write_output(self, verb: str, result: dict[str, Any]) -> ToolResult:
        event = result.get("event") or {}
        when = event.get("start", "")
        if event.get("all_day"):
            when = when[:10]
        else:
            when = f"{event.get('start', '')[:16]}–{event.get('end', '')[11:16]}"
        link = result.get("htmlLink") or ""
        event_id = result.get("id") or ""
        tail = f"\n{link}" if link else ""
        if event_id:
            tail += f"\n(event_id: {event_id})"
        return ToolResult(output=f"{verb} “{event.get('summary', '')}” ({when})" + tail)

    def _errors_note(self) -> str:
        broken = [s for s in self.feeds.states.values() if s.error]
        broken += [s for s in self.feeds.google_states.values() if s.error]
        if not broken:
            return ""
        return "\n(feed problems: " + "; ".join(f"{s.name}: {s.error}" for s in broken) + ")"

    def _draft(self, args: dict[str, Any]) -> ToolResult:
        # Some models HTML-escape their arguments ("Alex &amp; Alice"); nothing on a calendar
        # is meant to carry entities, so they are undone here.
        title = html.unescape(str(args.get("title") or "")).strip()
        if not title or not args.get("start"):
            return ToolResult.fail("draft needs a title and a start")
        tz = self.feeds.tz
        start, all_day = _parse_when(str(args["start"]), tz)
        if args.get("end"):
            end, _ = _parse_when(str(args["end"]), tz)
            if all_day:
                end = end + timedelta(days=1)  # DTEND is exclusive for all-day events
        elif all_day:
            end = start + timedelta(days=1)
        else:
            end = start + timedelta(minutes=int(args.get("duration_minutes") or 60))
        if end <= start:
            return ToolResult.fail("the end must be after the start")
        ics = make_ics(
            title,
            start,
            end,
            all_day=all_day,
            location=html.unescape(str(args.get("location") or "")),
            description=html.unescape(str(args.get("notes") or "")),
        )
        folder = self.workspace / "calendar"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{start:%Y-%m-%d}-{_slug(title)}.ics"
        path.write_text(ics, encoding="utf-8")
        rel = path.relative_to(self.workspace).as_posix()
        when = f"{start:%a %Y-%m-%d}" if all_day else f"{start:%a %Y-%m-%d %H:%M}–{end:%H:%M}"
        return ToolResult(
            output=f"Drafted “{title}” ({when}) as {rel}. The user adds it to their calendar by "
            "opening the file; tell them where it is."
        )


__all__ = ["Calendar"]

"""Follow-up cards from actual iCalendar components and the subscription cache."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from nanomuse.calendar import CalendarFeeds, FeedState, expand, parse_ics
from nanomuse.calendar.ics import Event, Occurrence
from nanomuse.config import CalendarFeedSettings, CalendarSettings
from nanomuse.server import followups

NOW = datetime(2026, 11, 23, 9, tzinfo=UTC)


def component(uid: str, *properties: str) -> str:
    return "\r\n".join(("BEGIN:VEVENT", f"UID:{uid}", *properties, "END:VEVENT"))


def document(*events: str) -> str:
    return "\r\n".join(("BEGIN:VCALENDAR", "VERSION:2.0", *events, "END:VCALENDAR", ""))


def source(text: str, name: str = "Work") -> CalendarFeeds:
    feed = CalendarFeedSettings(name=name, url="calendar.ics")
    cal = CalendarFeeds(CalendarSettings(enabled=True, feeds=[feed]), tz=UTC)
    cal.states[name] = FeedState(name, parse_ics(text, UTC, calendar=name), NOW.timestamp())
    return cal


def meeting(uid: str, start: str, end: str, *properties: str) -> str:
    return component(uid, f"DTSTART:{start}", f"DTEND:{end}", f"SUMMARY:{uid}", *properties)


def test_cancelled_occurrences_and_whole_series_do_not_create_conflicts() -> None:
    daily = meeting("Class", "20261122T100000Z", "20261122T110000Z", "RRULE:FREQ=DAILY;COUNT=4")
    booking = meeting("Practice", "20261123T103000Z", "20261123T113000Z")
    cancelled = component("Class", "RECURRENCE-ID:20261123T100000Z", "STATUS:CANCELLED")
    assert not followups.current_followups([], source(document(daily, booking, cancelled)), NOW, {})
    moved = meeting(
        "Class",
        "20261123T104500Z",
        "20261123T114500Z",
        "RECURRENCE-ID:20261123T100000Z",
        "SEQUENCE:2",
    )
    # A later revision reinstates the date, while a cancelled series also removes
    # its detached exception, even when the cancellation carries no DTSTART.
    items = [daily, moved, booking, cancelled]
    [card] = followups.current_followups([], source(document(*items)), NOW, {})
    assert card["titles"] == ["Practice", "Class"]
    assert card["start"] == "2026-11-23T10:45:00+00:00"
    series_cancel = component("Class", "STATUS:CANCELLED", "SEQUENCE:3")
    assert not followups.current_followups([], source(document(*items, series_cancel)), NOW, {})
    # A detached cancellation from a different subscription does not cancel this class.
    events = parse_ics(document(daily), UTC, calendar="Work")
    events += parse_ics(document("METHOD:CANCEL", cancelled), UTC, calendar="Personal")
    assert [o.summary for o in expand(events, NOW, NOW + timedelta(hours=12))] == ["Class"]
    # Multiple VCALENDAR objects can arrive as a stream. An iTIP cancellation with
    # no per-event status applies only to its own object and occurrence.
    notice = document(component("Class", "RECURRENCE-ID:20261123T100000Z"), "METHOD:CANCEL")
    streamed = parse_ics(document(daily, booking) + notice, UTC, calendar="Work")
    assert [o.summary for o in expand(streamed, NOW, NOW + timedelta(hours=12))] == ["Practice"]


def test_busy_only_mirrors_and_exact_window_boundaries() -> None:
    work = meeting("Work", "20261123T083000Z", "20261123T100000Z")
    events = [
        work,
        work,
        meeting("Finished", "20261123T080000Z", "20261123T090000Z"),
        meeting("Free", "20261123T090000Z", "20261123T100000Z", "TRANSP:TRANSPARENT"),
        component("Holiday", "DTSTART;VALUE=DATE:20261123", "DTEND;VALUE=DATE:20261124"),
        component("Instant", "DTSTART:20261123T093000Z"),
        meeting("Next", "20261123T100000Z", "20261123T110000Z"),
        meeting("After 24h", "20261124T090000Z", "20261124T093000Z"),
        meeting("Also next day", "20261124T090000Z", "20261124T100000Z"),
    ]
    cal = source(document(*events))
    mirror = source(document(work), name="Mirror")
    cal.settings.feeds.extend(mirror.settings.feeds)
    cal.states.update(mirror.states)
    assert not followups.current_followups([], cal, NOW, {})
    [next_day] = followups.current_followups([], cal, NOW + timedelta(minutes=1), {})
    assert next_day["titles"] == ["After 24h", "Also next day"]
    assert not followups.current_followups(
        [], cal, NOW + timedelta(minutes=1), {next_day["id"]: "2026-11-24"}
    )


async def test_disk_cache_reuse_replacements_errors_and_expiry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    text = document(
        meeting("Visit", "20261123T110000Z", "20261123T113000Z"),
        meeting("Class", "20261123T111500Z", "20261123T114500Z"),
    )
    path, cache = tmp_path / "agenda.ics", tmp_path / "cache.json"
    path.write_text(text, encoding="utf-8")
    settings = CalendarSettings(
        enabled=True, feeds=[CalendarFeedSettings(name="Work", url=str(path))]
    )
    monkeypatch.setattr("nanomuse.calendar.feeds.time.time", lambda: NOW.timestamp())
    await CalendarFeeds(settings, cache_file=cache, tz=UTC).refresh()
    cal = CalendarFeeds(settings, cache_file=cache, tz=UTC)
    calls = 0

    def counted(events: list[Event], start: datetime, end: datetime) -> list[Occurrence]:
        nonlocal calls
        calls += 1
        return expand(events, start, end)

    monkeypatch.setattr(followups, "expand", counted)
    [before] = followups.current_followups([], cal, NOW, {})
    assert followups.current_followups([], cal, NOW + timedelta(minutes=1), {}) == [before]
    assert calls == 1
    assert not followups.current_followups([], cal, NOW + timedelta(minutes=31), {})
    path.write_text(
        text.replace("20261123T111500Z", "20261123T100000Z").replace(
            "20261123T114500Z", "20261123T103000Z"
        ),
        encoding="utf-8",
    )
    await cal.refresh(force=True)
    assert not followups.current_followups([], cal, NOW, {})
    path.write_text(text, encoding="utf-8")
    await cal.refresh(force=True)
    assert followups.current_followups([], cal, NOW, {}) == [before]
    path.unlink()
    await cal.refresh(force=True)
    assert cal.states["Work"].error
    assert not followups.current_followups([], cal, NOW, {})
    stale = CalendarFeeds(settings, cache_file=cache, tz=UTC)
    assert not followups.current_followups([], stale, NOW, {})


def test_hidden_action_can_identify_the_second_current_conflict() -> None:
    cal = source(
        document(
            meeting("Class", "20261123T110000Z", "20261123T113000Z"),
            meeting("Review", "20261123T111500Z", "20261123T114500Z"),
            meeting("Lunch", "20261123T112500Z", "20261123T123000Z"),
        )
    )
    [first] = followups.current_followups([], cal, NOW, {})
    [second] = followups.current_followups([], cal, NOW, {first["id"]: "2026-11-24"})
    assert first["id"] != second["id"]
    assert followups.current_followups([], cal, NOW, {}, only_id=second["id"]) == [second]
    assert not followups.current_followups([], cal, NOW, {}, only_id="missing")


def test_timed_event_keeps_explicit_end_across_the_fall_clock_change() -> None:
    events = parse_ics(
        document(
            component(
                "Visit", "DTSTART;TZID=America/New_York:20261101T013000", "DTEND:20261101T063000Z"
            )
        ),
        UTC,
    )
    window = datetime(2026, 11, 1, 6, 45, tzinfo=UTC)
    assert expand(events, window, window + timedelta(hours=1)) == []


def test_long_running_fixed_intervals_keep_alignment_count_and_extra_dates() -> None:
    # A 30-minute schedule started eight years ago. The first overlapping slot
    # began before the window; the independent RDATE outlives a finite COUNT.
    base = meeting(
        "Slots",
        "20181101T091700Z",
        "20181101T093700Z",
        "RRULE:FREQ=MINUTELY;INTERVAL=30",
        "EXDATE:20261123T091700Z",
    )
    rows = expand(parse_ics(document(base), UTC), NOW, NOW + timedelta(hours=1))
    assert [o.start.strftime("%H:%M") for o in rows] == ["08:47", "09:47"]
    finished = base.replace("INTERVAL=30", "INTERVAL=30;COUNT=8").replace(
        "END:VEVENT", "RDATE:20261123T094500Z\r\nEND:VEVENT"
    )
    rows = expand(parse_ics(document(finished), UTC), NOW, NOW + timedelta(hours=1))
    assert [o.start.strftime("%H:%M") for o in rows] == ["09:45"]
    finite = (
        base.replace("20181101", "20261123")
        .replace("T09", "T07", 2)
        .replace("INTERVAL=30", "INTERVAL=30;COUNT=5")
        .replace("EXDATE:20261123T091700Z", "EXDATE:20261123T094700Z")
    )
    rows = expand(parse_ics(document(finite), UTC), NOW, NOW + timedelta(hours=1))
    assert [o.start.strftime("%H:%M") for o in rows] == ["08:47", "09:17"]

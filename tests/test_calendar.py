"""The calendar connector: .ics parsing and recurrence, feeds and cache, the tool."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
import pytest

from nanomuse.calendar import CalendarFeeds, expand, make_ics, parse_ics
from nanomuse.calendar.ics import parse_duration, unescape, unfold
from nanomuse.config import CalendarFeedSettings, CalendarSettings
from nanomuse.tools import Calendar

TZ = ZoneInfo("Asia/Shanghai")

FEED = """BEGIN:VCALENDAR\r
VERSION:2.0\r
PRODID:-//Test//EN\r
BEGIN:VEVENT\r
UID:standup\r
DTSTART;TZID=Asia/Shanghai:20260921T093000\r
DTEND;TZID=Asia/Shanghai:20260921T100000\r
RRULE:FREQ=WEEKLY;BYDAY=MO,WE,FR;UNTIL=20261231T000000Z\r
EXDATE;TZID=Asia/Shanghai:20260925T093000\r
SUMMARY:Standup\r
LOCATION:Zoom\r
BEGIN:VALARM\r
TRIGGER:-PT10M\r
ACTION:DISPLAY\r
DESCRIPTION:Reminder\r
END:VALARM\r
END:VEVENT\r
BEGIN:VEVENT\r
UID:standup\r
RECURRENCE-ID;TZID=Asia/Shanghai:20260923T093000\r
DTSTART;TZID=Asia/Shanghai:20260923T110000\r
DTEND;TZID=Asia/Shanghai:20260923T113000\r
SUMMARY:Standup (moved)\r
END:VEVENT\r
BEGIN:VEVENT\r
UID:holiday\r
DTSTART;VALUE=DATE:20260924\r
DTEND;VALUE=DATE:20260926\r
SUMMARY:公司团建\r
END:VEVENT\r
BEGIN:VEVENT\r
UID:lunch\r
DTSTART:20260922T040000Z\r
DURATION:PT1H30M\r
SUMMARY:Lunch with Li\\, Wei\r
DESCRIPTION:Line one\\nLine two; with a semicolon\\; kept\r
END:VEVENT\r
BEGIN:VEVENT\r
UID:gone\r
DTSTART:20260922T080000Z\r
DTEND:20260922T090000Z\r
SUMMARY:Cancelled thing\r
STATUS:CANCELLED\r
END:VEVENT\r
BEGIN:VEVENT\r
UID:long\r
DTSTART;TZID=China Standard Time:20260923T150000\r
DTEND;TZID=China Standard Time:20260923T160000\r
SUMMARY:A meeting with a title that is long enough to be folded onto a second line by t\r
 he server\r
END:VEVENT\r
END:VCALENDAR\r
"""


def test_unfold_unescape_duration():
    assert unfold("A:1\r\n b\r\nB:2\r\n\tc") == ["A:1b", "B:2c"]
    assert unescape("a\\, b\\; c\\nd\\\\e") == "a, b; c\nd\\e"
    assert parse_duration("PT1H30M") == timedelta(hours=1, minutes=30)
    assert parse_duration("P1DT2H") == timedelta(days=1, hours=2)
    assert parse_duration("-P1W") == -timedelta(weeks=1)


def test_parse_and_expand_a_real_looking_feed():
    events = parse_ics(FEED, TZ, calendar="Work")
    assert [e.uid for e in events] == ["standup", "standup", "holiday", "lunch", "gone", "long"]
    lunch = next(e for e in events if e.uid == "lunch")
    assert lunch.summary == "Lunch with Li, Wei"
    assert lunch.description == "Line one\nLine two; with a semicolon; kept"
    assert lunch.start.astimezone(TZ).hour == 12 and lunch.duration == timedelta(minutes=90)
    long = next(e for e in events if e.uid == "long")
    assert long.summary.endswith("by the server") and long.start.tzinfo == TZ

    week = expand(events, datetime(2026, 9, 21, tzinfo=TZ), datetime(2026, 9, 28, tzinfo=TZ))
    rows = [(o.start.astimezone(TZ).strftime("%a %H:%M"), o.summary) for o in week]
    assert ("Mon 09:30", "Standup") in rows
    assert ("Wed 11:00", "Standup (moved)") in rows, "RECURRENCE-ID replaces that occurrence"
    assert ("Wed 09:30", "Standup") not in rows
    assert not any(r[0].startswith("Fri") and r[1] == "Standup" for r in rows), "EXDATE"
    assert not any(o.summary == "Cancelled thing" for o in week)
    holiday = next(o for o in week if o.summary == "公司团建")
    assert holiday.all_day and (holiday.end - holiday.start) == timedelta(days=2)
    # sorted by start; the two-day holiday still overlaps a window that starts on its 2nd day
    assert [o.start for o in week] == sorted(o.start for o in week)
    day2 = expand(events, datetime(2026, 9, 25, tzinfo=TZ), datetime(2026, 9, 26, tzinfo=TZ))
    assert [o.summary for o in day2] == ["公司团建"]


def test_expand_handles_until_dates_and_monthly_rules():
    ics = (
        "BEGIN:VCALENDAR\nBEGIN:VEVENT\nUID:rent\nDTSTART;VALUE=DATE:20260101\n"
        "RRULE:FREQ=MONTHLY;BYMONTHDAY=1;UNTIL=20260401\nSUMMARY:Rent\nEND:VEVENT\nEND:VCALENDAR\n"
    )
    events = parse_ics(ics, TZ)
    year = expand(events, datetime(2026, 1, 1, tzinfo=TZ), datetime(2027, 1, 1, tzinfo=TZ))
    assert [o.start.date() for o in year] == [date(2026, m, 1) for m in (1, 2, 3, 4)]


def test_broken_events_are_skipped_not_fatal():
    ics = "BEGIN:VCALENDAR\nBEGIN:VEVENT\nUID:x\nDTSTART:not-a-date\nSUMMARY:Bad\nEND:VEVENT\nBEGIN:VEVENT\nUID:y\nDTSTART:20260922T080000Z\nSUMMARY:Good\nEND:VEVENT\nEND:VCALENDAR\n"
    events = parse_ics(ics, TZ)
    assert [e.uid for e in events] == ["y"]
    assert events[0].end == events[0].start, "no DTEND, no DURATION: a zero-length event"


def test_make_ics_round_trips():
    start = datetime(2026, 10, 3, 14, 0, tzinfo=TZ)
    text = make_ics(
        "Dentist, then coffee",
        start,
        start + timedelta(minutes=45),
        location="12 Nanjing Rd; 3F",
        description="Bring the x-ray\nand the card",
    )
    assert "SUMMARY:Dentist\\, then coffee" in text and "LOCATION:12 Nanjing Rd\\; 3F" in text
    assert "DTSTART:20261003T060000Z" in text
    [ev] = parse_ics(text, TZ)
    assert (
        ev.summary == "Dentist, then coffee"
        and ev.start == start
        and ev.duration == timedelta(minutes=45)
    )
    assert ev.description == "Bring the x-ray\nand the card"
    all_day = make_ics(
        "Holiday", datetime(2026, 10, 1, tzinfo=TZ), datetime(2026, 10, 2, tzinfo=TZ), all_day=True
    )
    [ev] = parse_ics(all_day, TZ)
    assert ev.all_day and ev.start.date() == date(2026, 10, 1)
    assert all(len(line.encode()) <= 75 for line in make_ics("x" * 200, start, start).split("\r\n"))


def test_a_long_chinese_line_folds_without_cutting_a_character():
    """RFC 5545 §3.1: a content line is at most 75 octets and the rest continues on the next
    one after a single space. Chinese is three octets a character, so the 74th octet is
    almost never a character boundary: the fold has to step back rather than cut one in
    half, and unfolding has to give the line back exactly as it was escaped."""
    summary = "季度绩效沟通会: 目标回顾, 新目标与衡量方式; 请提前十分钟到场，带上本季度的项目进展"
    location = "上海南京西路 1266 号 3 楼大会议室"
    note = (
        "第一行：把上季度的三个目标逐条过一遍。\n第二行：新的目标要能衡量。\n第三行：带上笔记本。"
    )
    start = datetime(2026, 10, 8, 15, 0, tzinfo=TZ)
    text = make_ics(summary, start, start + timedelta(hours=1), location=location, description=note)

    physical = text.split("\r\n")
    assert all(len(line.encode()) <= 75 for line in physical), "no physical line is over 75 octets"
    # the text ends in CRLF, and every continuation is one more physical line
    folded = [line for line in physical if line.startswith(" ")]
    assert len(folded) >= 2, "the long summary and the three-line note each continue"

    # folding and unfolding compose: the logical lines come back byte for byte
    lines = unfold(text)
    assert len(lines) == len(physical) - 1 - len(folded)
    escaped = summary.replace(";", "\\;").replace(",", "\\,")
    assert next(line for line in lines if line.startswith("SUMMARY:")) == "SUMMARY:" + escaped

    [ev] = parse_ics(text, TZ)
    assert ev.summary == summary and ev.location == location and ev.description == note


def settings_for(*urls: str, enabled: bool = True) -> CalendarSettings:
    return CalendarSettings(
        enabled=enabled,
        feeds=[CalendarFeedSettings(name=f"cal{i}", url=u) for i, u in enumerate(urls)],
        refresh_minutes=30,
    )


async def test_feeds_read_files_cache_and_answer_from_the_cache(tmp_path: Path):
    ics_file = tmp_path / "work.ics"
    ics_file.write_text(FEED, encoding="utf-8")
    cache = tmp_path / "cache.json"
    feeds = CalendarFeeds(settings_for(str(ics_file)), cache_file=cache, tz=TZ)
    assert feeds.configured and feeds.stale()
    status = await feeds.refresh()
    assert status["feeds"][0]["events"] == 6 and not status["feeds"][0]["error"]
    assert not feeds.stale()

    agenda = feeds.agenda(date(2026, 9, 23))
    assert [o.summary for o in agenda] == [
        "Standup (moved)",
        "A meeting with a title that is long enough to be folded onto a second line by the server",
    ]
    text = feeds.render(agenda, today=date(2026, 9, 23))
    assert (
        text.startswith("Wed 2026-09-23 (today)") and "11:00–11:30" in text and "@ Zoom" not in text
    )

    lunch = feeds.search("li, wei", date(2026, 9, 22))
    assert [o.summary for o in lunch] == ["Lunch with Li, Wei"]
    # a UTC DTSTART comes out in the user's zone, in the app (to_dict) as in the text
    assert lunch[0].start.tzinfo is TZ and lunch[0].to_dict()["start"] == "2026-09-22T12:00+08:00"
    slots = feeds.free_slots(date(2026, 9, 23), 30, "09:00", "18:00")
    assert [(s.start.strftime("%H:%M"), s.end.strftime("%H:%M")) for s in slots] == [
        ("09:00", "11:00"),
        ("11:30", "15:00"),
        ("16:00", "18:00"),
    ]
    # a fresh object with the same cache file answers without fetching
    again = CalendarFeeds(settings_for(str(ics_file)), cache_file=cache, tz=TZ)
    assert not again.stale() and len(again.agenda(date(2026, 9, 23))) == 2


async def test_feeds_fetch_over_http_and_report_a_broken_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        if request.url.path == "/good.ics":
            return httpx.Response(200, text=FEED)
        return httpx.Response(404, text="gone")

    transport = httpx.MockTransport(handler)
    real_client = httpx.AsyncClient

    def client(**kwargs: object) -> httpx.AsyncClient:
        kwargs.pop("transport", None)
        return real_client(transport=transport, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(httpx, "AsyncClient", client)
    feeds = CalendarFeeds(
        settings_for("webcal://cal.example/good.ics", "https://cal.example/missing.ics"), tz=TZ
    )
    status = await feeds.refresh()
    good, bad = status["feeds"]
    assert good["events"] == 6 and not good["error"]
    assert bad["events"] == 0 and bad["error"] == "HTTP 404"
    assert "missing.ics" not in bad["error"], "a private link never shows in the status"
    assert len(feeds.agenda(date(2026, 9, 21))) == 1, "the good feed still answers"
    assert seen[0] == "https://cal.example/good.ics", "a webcal:// link is fetched over https"


async def test_calendar_tool(tmp_path: Path):
    ics_file = tmp_path / "work.ics"
    ics_file.write_text(FEED, encoding="utf-8")
    feeds = CalendarFeeds(settings_for(str(ics_file)), tz=TZ)
    ws = tmp_path / "ws"
    ws.mkdir()
    tool = Calendar(feeds=feeds, workspace=ws)

    assert tool.assess({"action": "agenda", "day": "2026-09-23"}).reads_private_data
    assert (
        tool.assess({"action": "draft", "title": "x", "start": "2026-10-01 09:00"}).risk.value
        == "moderate"
    )

    out = (await tool.execute(action="agenda", day="2026-09-21", days=3)).output
    assert (
        "Mon 2026-09-21" in out
        and "Standup" in out
        and "Lunch with Li, Wei" in out
        and "Standup (moved)" in out
    )
    assert "Cancelled thing" not in out

    out = (await tool.execute(action="free", day="2026-09-23", minutes=60)).output
    assert "09:00–11:00" in out and "11:30–15:00" in out and "16:00–18:00" in out
    assert "All-day" not in out
    # an all-day event does not block hours, but the model is told the user may be away
    out = (await tool.execute(action="free", day="2026-09-25", minutes=60)).output
    assert "All-day that day: 公司团建" in out

    out = (await tool.execute(action="search", query="团建")).output
    assert "公司团建" in out and "all day" in out

    result = await tool.execute(
        action="draft",
        title="Dentist",
        start="2026-10-03 14:00",
        duration_minutes=45,
        location="Nanjing Rd",
        notes="bring the card",
    )
    assert result.ok and "calendar/2026-10-03-dentist.ics" in result.output
    [ev] = parse_ics((ws / "calendar" / "2026-10-03-dentist.ics").read_text(encoding="utf-8"), TZ)
    assert (
        ev.summary == "Dentist"
        and ev.duration == timedelta(minutes=45)
        and ev.location == "Nanjing Rd"
    )

    result = await tool.execute(action="draft", title="Trip", start="2026-10-01", end="2026-10-03")
    assert result.ok
    [ev] = parse_ics((ws / "calendar" / "2026-10-01-trip.ics").read_text(encoding="utf-8"), TZ)
    assert ev.all_day and ev.duration == timedelta(days=3), "an all-day range is inclusive"

    # a model that HTML-escapes its arguments does not put "&amp;" on the calendar
    result = await tool.execute(
        action="draft", title="1:1 — Alex &amp; Alice", start="2026-10-04 14:00", location="3&#39;F"
    )
    assert result.ok and "Alex & Alice" in result.output
    [ev] = parse_ics(
        (ws / "calendar" / "2026-10-04-1-1-alex-alice.ics").read_text(encoding="utf-8"), TZ
    )
    assert ev.summary == "1:1 — Alex & Alice" and ev.location == "3'F"

    assert (await tool.execute(action="draft", title="", start="2026-10-01")).error
    assert (await tool.execute(action="agenda", day="not a day")).error

    off = Calendar(feeds=CalendarFeeds(settings_for(enabled=False), tz=TZ), workspace=ws)
    assert "no calendar is connected" in (await off.execute(action="agenda")).error


def test_rdate_adds_the_dates_a_rule_does_not_make():
    """RFC 5545 §3.8.5.2: RDATE names further occurrences of an event. A feed that dates a
    series this way (Outlook and iCloud do, for one-off additions) used to lose all of
    them: the reader kept DTSTART, unrolled RRULE and dropped EXDATE dates, and had no
    place for a date on its own line."""
    ics = (
        "BEGIN:VCALENDAR\nBEGIN:VEVENT\nUID:physio\n"
        "DTSTART;TZID=Asia/Shanghai:20261105T090000\n"
        "DTEND;TZID=Asia/Shanghai:20261105T093000\n"
        "RDATE;TZID=Asia/Shanghai:20261112T090000,20261119T090000\n"
        "SUMMARY:Physio\nEND:VEVENT\nEND:VCALENDAR\n"
    )
    events = parse_ics(ics, TZ)
    assert [rd.date() for rd in events[0].rdates] == [date(2026, 11, 12), date(2026, 11, 19)]
    month = expand(events, datetime(2026, 11, 1, tzinfo=TZ), datetime(2026, 12, 1, tzinfo=TZ))
    assert [o.start.date() for o in month] == [
        date(2026, 11, 5),
        date(2026, 11, 12),
        date(2026, 11, 19),
    ]
    assert {o.end - o.start for o in month} == {timedelta(minutes=30)}


def test_rdate_beside_a_rule_doubles_nothing_and_keeps_all_day_dates():
    """An RDATE that lands on a date the rule already makes is one occurrence; an all-day
    one is a whole day; a PERIOD one is skipped rather than added with the wrong length."""
    ics = (
        "BEGIN:VCALENDAR\nBEGIN:VEVENT\nUID:standup\n"
        "DTSTART;TZID=Asia/Shanghai:20261102T093000\n"
        "DTEND;TZID=Asia/Shanghai:20261102T100000\n"
        "RRULE:FREQ=WEEKLY;BYDAY=MO;UNTIL=20261201T000000Z\n"
        "RDATE;TZID=Asia/Shanghai:20261107T140000,20261109T093000\n"
        "SUMMARY:Standup\nEND:VEVENT\n"
        "BEGIN:VEVENT\nUID:rent\nDTSTART;VALUE=DATE:20261101\n"
        "RDATE;VALUE=DATE:20261115\n"
        "RDATE;VALUE=PERIOD:20261120T000000/PT3H\n"
        "SUMMARY:Rent\nEND:VEVENT\nEND:VCALENDAR\n"
    )
    events = parse_ics(ics, TZ)
    month = expand(events, datetime(2026, 11, 1, tzinfo=TZ), datetime(2026, 12, 1, tzinfo=TZ))
    standup = [
        o.start.astimezone(TZ).strftime("%m-%d %H:%M") for o in month if o.summary == "Standup"
    ]
    assert standup == [
        "11-02 09:30",
        "11-07 14:00",
        "11-09 09:30",
        "11-16 09:30",
        "11-23 09:30",
        "11-30 09:30",
    ]
    rent = [o for o in month if o.summary == "Rent"]
    assert [o.start.date() for o in rent] == [date(2026, 11, 1), date(2026, 11, 15)]
    assert {o.end - o.start for o in rent} == {timedelta(days=1)}, "PERIOD is skipped"
    assert all(o.all_day for o in rent)
    assert any(o.rdates for o in events)


def test_exdate_still_removes_an_rdate():
    """An EXDATE on a date that RDATE added cancels it, as it cancels a rule's occurrence."""
    head = (
        "BEGIN:VCALENDAR\nBEGIN:VEVENT\nUID:standup\n"
        "DTSTART;TZID=Asia/Shanghai:20261102T093000\n"
        "RRULE:FREQ=WEEKLY;BYDAY=MO;UNTIL=20261117T000000Z\n"
        "RDATE;TZID=Asia/Shanghai:20261107T140000\n"
    )
    tail = "SUMMARY:Standup\nEND:VEVENT\nEND:VCALENDAR\n"
    window = (datetime(2026, 11, 1, tzinfo=TZ), datetime(2026, 12, 1, tzinfo=TZ))

    def days(text: str) -> list[str]:
        found = expand(parse_ics(text, TZ), *window)
        return [o.start.astimezone(TZ).strftime("%m-%d") for o in found]

    assert days(head + tail) == ["11-02", "11-07", "11-09", "11-16"]
    cancelled = head + "EXDATE;TZID=Asia/Shanghai:20261107T140000\n" + tail
    assert days(cancelled) == ["11-02", "11-09", "11-16"]

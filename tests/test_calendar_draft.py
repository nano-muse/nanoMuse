"""The calendar's ``draft`` names its file after the day and the title's slug, so two
proposals for the same day with the same title used to land on one path — the second
silently overwriting the first while the model still pointed the user at both."""

from __future__ import annotations

from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from nanomuse.calendar.feeds import CalendarFeeds
from nanomuse.config import CalendarSettings
from nanomuse.tools.calendar_tool import Calendar


@pytest.fixture()
def calendar(tmp_path: Path) -> Calendar:
    feeds = CalendarFeeds(settings=CalendarSettings(), tz=ZoneInfo("UTC"))
    return Calendar(feeds=feeds, workspace=tmp_path)


async def test_two_drafts_with_one_title_are_two_files(calendar: Calendar) -> None:
    first = await calendar.execute(
        action="draft", title="morning run", start="2026-03-01 07:00", duration_minutes=45
    )
    second = await calendar.execute(
        action="draft",
        title="morning run",
        start="2026-03-01 07:00",
        duration_minutes=45,
        notes="backup plan if it rains",
    )
    assert first.ok and second.ok
    folder = calendar.workspace / "calendar"
    files = sorted(folder.glob("*.ics"))
    assert len(files) == 2, "the second draft overwrote the first"
    texts = [f.read_text(encoding="utf-8") for f in files]
    assert sum("backup plan if it rains" in t for t in texts) == 1
    assert sum("backup plan if it rains" not in t for t in texts) == 1
    # the model hands the user the path each draft reported; they must differ
    assert (
        first.output.split(" as ")[1].split(". ")[0]
        != second.output.split(" as ")[1].split(". ")[0]
    )


async def test_a_draft_alone_keeps_the_plain_name(calendar: Calendar) -> None:
    r = await calendar.execute(
        action="draft", title="dentist", start="2026-03-02 09:00", duration_minutes=60
    )
    assert r.ok
    files = list((calendar.workspace / "calendar").glob("*.ics"))
    assert [f.name for f in files] == ["2026-03-02-dentist.ics"]

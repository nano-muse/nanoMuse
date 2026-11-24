from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace as NS

from nanomuse.config import MCPServerSettings
from nanomuse.llm import MockLLM
from nanomuse.server.service import MuseService
from nanomuse.tools.mcp_resources import MCPResourceReader


async def test_read_selected_resource_only_while_connected(settings, tmp_path, monkeypatch):
    service = MuseService(settings, llm=MockLLM())
    conn = service.connections
    board = tmp_path / "board.txt"
    board.write_text("Review scheduled", encoding="utf-8")
    fixture = Path(__file__).with_name("mcp_context_server.py")
    cfg = {"name": "board", "command": sys.executable, "args": [str(fixture), str(board)]}
    try:
        view = await conn.add_mcp(cfg)
        assert view["mcp"][0]["connected"] and not view["mcp"][0]["tools"]
        choices = await conn.context_resources()
        assert len(choices) == 2 and "board://" not in str(choices)
        key = next(row["id"] for row in choices if "Team updates" in row["label"])
        assert (await conn.context_resource_samples([key]))[0].text == "Review scheduled"
        board.write_text("Review postponed to Friday", encoding="utf-8")
        samples = await conn.context_resource_samples([key, "board://work/unselected"])
        assert [(s.key, s.source, s.text) for s in samples] == [
            (key, "mcp", "Review postponed to Friday")
        ]
        assert not await conn.context_resource_samples([key], allowed=lambda: False)
        board.unlink()
        assert not await conn.context_resource_samples([key])
        reads = []

        async def unexpected_read(resource):
            reads.append(resource)
            return "unavailable"

        monkeypatch.setattr(conn._context_readers()["board"], "read", unexpected_read)
        decisions = iter((True, False))
        assert not await conn.context_resource_samples([key], allowed=lambda: next(decisions))
        assert not reads

    finally:
        await conn.remove_mcp("board")
    assert not await conn.context_resource_samples([key])
    # A different endpoint sharing this name and URI does not inherit the selection.
    other = tmp_path / "different.txt"
    other.write_text("different account", encoding="utf-8")
    try:
        await conn.add_mcp({**cfg, "args": [str(fixture), str(other)]})
        assert not await conn.context_resource_samples([key])
    finally:
        await conn.remove_mcp("board")


async def test_resource_discovery_keeps_credential_uris_private_and_checks_result_uri():
    uri = "board://updates?token=credential"

    class Session:
        async def list_resources(self, *, params=None):
            if params is None:
                return NS(resources=[NS(uri=uri, name=uri)], next_cursor="more")
            assert params.cursor == "more"
            return NS(resources=[NS(uri="file://photo", name="photo", mime_type="image/png")])

        async def read_resource(self, request):
            assert request == uri
            return NS(
                contents=[
                    NS(uri="board://other", text="private attachment"),
                    NS(uri=uri, mime_type="image/png", text="binary"),
                    NS(uri=uri, text="updated"),
                ]
            )

    reader = MCPResourceReader(MCPServerSettings(name="Project"), Session(), lambda text: text)
    rows = await reader.listed()
    assert len(rows) == 1 and "credential" not in repr(rows)
    assert await reader.read(rows[0]) == "updated"


def test_calendar_preview_uses_fresh_upcoming_busy_events_and_hides_private_links():
    from datetime import UTC, datetime, timedelta

    from nanomuse.calendar import CalendarFeeds, FeedState
    from nanomuse.calendar.ics import Event
    from nanomuse.config import CalendarFeedSettings, CalendarSettings
    from nanomuse.server.context_sources import calendar_samples

    now = datetime(2026, 2, 3, 9, tzinfo=UTC)
    cal = CalendarFeeds(
        CalendarSettings(enabled=True, feeds=[CalendarFeedSettings(name="Work", url="unused")]),
        tz=UTC,
    )
    event = Event(
        "A",
        "Site visit",
        now + timedelta(hours=1),
        now + timedelta(hours=2),
        location="Hall B",
        description="Bring the prototype. https://example.invalid/?token=private",
        calendar="Work",
    )
    from dataclasses import replace

    cal.states["Work"] = FeedState(
        "Work", [event, replace(event, uid="B", transparent=True)], now.timestamp()
    )
    [sample] = calendar_samples(cal, now)
    assert sample.source == "calendar" and "Hall B" in sample.text and "private" not in sample.text
    cal.states["Work"].events = [replace(event, location="Hall D")]
    [updated] = calendar_samples(cal, now)
    assert updated.key == sample.key and "Hall D" in updated.text
    cal.states["Work"].error = "disconnected"
    assert not calendar_samples(cal, now)


def test_resource_preview_filters_json_fields_and_preserves_newest_updates():
    import json

    from nanomuse.server.context_sources import resource_preview

    assert not resource_preview('{"privateNotes":"do not review","refreshToken":"hidden"}')
    assert not resource_preview('{"privateNotes":"interrupted at boundary')
    rows = [
        {"title": "Print", "status": f"Update number {number}", "privateNotes": "hidden"}
        for number in range(130)
    ]
    raw = json.dumps({"items": rows})
    preview = resource_preview(raw)
    assert "Update number 129" in preview and "hidden" not in preview
    assert "Print (status):" in preview and "Update number 65" not in preview
    assert resource_preview("Your verification code is 000000.\nProof delayed.") == "Proof delayed."


async def test_connecting_can_follow_only_one_resource_and_respects_removal(settings, tmp_path):
    svc = MuseService(settings, llm=MockLLM())
    watch = svc.context_watch
    board = tmp_path / "board"
    board.write_text("Draft complete.")
    fixture = str(Path(__file__).with_name("mcp_context_server.py"))
    cfg = {"name": "project", "command": sys.executable, "args": [fixture, str(board)]}

    async def connect(single, enabled):
        await svc.connections.add_mcp(
            {
                **cfg,
                "args": [*cfg["args"], *(["--single"] if single else [])],
                "review": {"revision": watch.view()["revision"], "enabled": enabled},
            }
        )

    try:
        await connect(False, True)
        assert watch.view()["resources"] == []
        await svc.connections.remove_mcp("project")
        await connect(True, False)
        assert not watch.view()["on_connect"]["mcp"]
        assert watch.view()["resources"] == []
        await svc.connections.remove_mcp("project")
        await connect(True, True)
        assert len(watch.view()["resources"]) == 1
        watch.configure(watch.view()["revision"], False, False, [], False)
        await svc.connections.remove_mcp("project")
        await connect(True, True)
        assert watch.view()["resources"] == []
    finally:
        await svc.connections.remove_mcp("project")

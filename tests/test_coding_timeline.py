from __future__ import annotations

import asyncio
import base64
import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from nanomuse.coding import agents
from nanomuse.coding import service as coding_service
from nanomuse.coding.protocol import PageError, page, preview, scope
from nanomuse.coding.runner import Run
from nanomuse.coding.service import CodingError, CodingService
from nanomuse.coding.timeline import Timeline, history, patch_files

FIXTURES = json.loads((Path(__file__).parent / "fixtures/coding-timeline.json").read_text())


def test_codex_saved_titles_and_context_filter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("NANOMUSE_CODING_HOME", str(tmp_path))
    root = tmp_path / ".codex"
    store = root / "sessions"
    store.mkdir(parents=True)
    sid = "0f9a7b6c-1111-2222-3333-444455556666"
    rows = [
        {"type": "session_meta", "payload": {"id": sid}},
        {
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "user",
                "content": "# AGENTS.md instructions for /workspace\nInjected context",
            },
        },
        {
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "user",
                "content": "Fix the parser",
            },
        },
    ]
    (store / f"rollout-{sid}.jsonl").write_text("\n".join(map(json.dumps, rows)))
    assert agents.sessions("codex")[0].title == "Fix the parser"
    (root / "session_index.jsonl").write_text(
        json.dumps({"id": sid, "thread_name": "Old index name"})
        + "\ninvalid\n"
        + json.dumps({"id": sid, "thread_name": "Indexed name"})
    )
    assert agents.read_session("codex", sid).title == "Indexed name"
    db = sqlite3.connect(root / "state_5.sqlite")
    db.execute("CREATE TABLE threads (id TEXT, title TEXT, name TEXT)")
    db.execute("INSERT INTO threads VALUES (?, ?, ?)", (sid, "Prompt", "Desktop renamed title"))
    db.commit()
    db.close()
    detail = agents.read_session("codex", sid)
    assert detail and detail.title == "Desktop renamed title"
    assert agents.sessions("codex")[0].title == detail.title
    assert [item["text"] for item in detail.timeline] == ["Fix the parser"]
    assert [item["text"] for item in detail.transcript] == ["Fix the parser"]
    (root / "state_6.sqlite").write_text("broken database")
    assert agents.read_session("codex", sid).title == "Desktop renamed title"


@pytest.mark.parametrize("wrapped", ["raw", "json", "object"])
def test_codex_patch_inputs(wrapped: str) -> None:
    patch = "*** Begin Patch\n*** Update File: a.py\n@@\n-old\n+new\n*** End Patch"
    raw = (
        patch
        if wrapped == "raw"
        else json.dumps({"patch": patch})
        if wrapped == "json"
        else {"patch": patch}
    )
    timeline = Timeline()
    timeline.call("patch-1", "functions.apply_patch", raw)
    timeline.result("patch-1", "Success")
    item = timeline.values()[0]
    assert item["kind"] == "file_change"
    assert item["files"][0]["diff"] == "@@\n-old\n+new"
    assert preview(item)["files"][0]["diff_reference"] == "patch-1:0"
    assert preview(item)["files"][0]["additions"] == 1


@pytest.mark.parametrize("fixture", FIXTURES, ids=lambda f: f["agent"])
def test_provider_projection(fixture: dict[str, Any]) -> None:
    items = history(fixture["agent"], fixture["rows"], str.strip)
    assert items == history(fixture["agent"], fixture["rows"], str.strip)
    assert [i["text"] for i in items if i["kind"] == "message"] == ["Fix tests", "**Done**"]
    call = next(i for i in items if i["id"] == fixture["tool"])
    assert call["kind"] == "command" and call["status"] == "failed"
    assert call["command"]["display_command"] == "pytest -q"
    assert "FAILED" in call["output"]
    assert len([i for i in items if i["kind"] == "command"]) == 1
    if fixture.get("patch"):
        patch = next(i for i in items if i["id"] == fixture["patch"])
        assert patch["files"][0]["additions"] == 1
        assert patch["files"][0]["deletions"] == 1
        assert "diff" not in preview(patch)["files"][0]


def test_patch_unknown_deleted_file_counts() -> None:
    files = patch_files("*** Begin Patch\n*** Delete File: a.py\n*** End Patch")
    assert "deletions" not in files[0]
    assert (
        patch_files("*** Begin Patch\n*** Add File: a.py\n+a\n+b\n*** End Patch")[0]["additions"]
        == 2
    )


def test_pages_are_bounded_and_versioned() -> None:
    values = ["a", "b", "c"]
    first = page(values, {"limit": 2})
    assert page(values, {"cursor": first["next_cursor"]})["data"] == ["c"]
    tail = page(values, {"tail": True, "limit": 2})
    assert tail["data"] == ["b", "c"]
    assert page(values, {"tail": True, "cursor": tail["next_cursor"]})["data"] == ["a"]
    with pytest.raises(PageError, match="stale_cursor"):
        page(values + ["d"], {"cursor": first["next_cursor"]})
    for token in ["?", "not-base64", base64.urlsafe_b64encode(b"[]").decode()]:
        with pytest.raises(PageError, match="invalid_cursor"):
            page(values, {"cursor": token})
    assert len(page("x" * 100_000, {"limit": 999999})["data"]) == 32768


def test_scopes_do_not_confuse_project_prefixes(tmp_path: Path) -> None:
    assert scope("", tmp_path) == "chats"
    assert scope(str(tmp_path / "Documents/nanoMuse/Chats/a"), tmp_path) == "chats"
    assert scope(str(tmp_path / "Documents/nanoMuse/Chats-extra"), tmp_path) == "projects"


def test_item_and_diff_are_bound_to_a_session(monkeypatch: pytest.MonkeyPatch) -> None:
    svc = CodingService(SimpleNamespace())
    fixture = FIXTURES[0]
    session = agents.Session(
        agent="codex",
        id="s1",
        title="tests",
        workspace="/workspace",
        path="",
        created_at=0,
        updated_at=0,
    )
    session.timeline = history("codex", fixture["rows"], str.strip)
    monkeypatch.setattr(agents, "read_session", lambda agent, sid: session if sid == "s1" else None)
    args = {"agent": "codex", "session_id": "s1", "item_id": "c1"}
    assert svc.handle("coding.item", args)["command"]["exit_code"] == 1
    diff = svc.handle("coding.diff", {**args, "diff_reference": "p1:0"})
    assert diff["data"] == "@@\n-old\n+new" and diff["path"] == "b.py"
    with pytest.raises(CodingError, match="not on this computer"):
        svc.handle("coding.diff", {**args, "session_id": "other", "diff_reference": "p1:0"})
    with pytest.raises(CodingError):
        svc.handle("coding.diff", {**args, "diff_reference": "../../private:0"})


def test_live_item_revision_replaces_not_duplicates() -> None:
    timeline = Timeline()
    for phase in ["item.started", "item.updated", "item.completed"]:
        timeline.feed(
            "codex",
            {
                "type": phase,
                "item": {
                    "id": "c1",
                    "type": "command_execution",
                    "command": "pwd",
                    "aggregated_output": "/workspace",
                    "exit_code": 0,
                },
            },
        )
    assert len(timeline.values()) == 1
    assert timeline.values()[0]["status"] == "completed"


def test_duplicate_send_and_restart_reuse_retained_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    count = 0

    async def fake_run(agent: str, text: str, **args: Any) -> Run:
        nonlocal count
        count += 1
        run = Run(args["run_id"], agent, args["session_id"], args["workspace"], text)
        args["register"](run)
        await asyncio.sleep(0.01)
        run.status = "done"
        return run

    svc = SimpleNamespace(
        data_dir=tmp_path,
        app=SimpleNamespace(audit=SimpleNamespace(record=lambda *a, **k: None)),
        bus=SimpleNamespace(publish=lambda *a: None),
    )
    monkeypatch.setattr(agents, "which", lambda _: "fake")
    monkeypatch.setattr(coding_service, "start_run", fake_run)
    service = CodingService(svc)

    async def scenario() -> None:
        results = await asyncio.gather(
            *[service.send("codex", "test", request_id="request-1", wait=True) for _ in range(2)]
        )
        assert results[0]["id"] == results[1]["id"]
        with pytest.raises(CodingError):
            await service.send("codex", "different", request_id="request-1")
        service._save()
        restarted = CodingService(svc)
        same = await restarted.send("codex", "test", request_id="request-1")
        assert same["id"] == results[0]["id"]
        await service.close()

    asyncio.run(scenario())
    assert count == 1


def test_watch_owned_new_run_after_session_id_changes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    svc = SimpleNamespace(data_dir=tmp_path)
    service = CodingService(svc)
    run = Run("r1", "codex", "", "", "test")
    service.runs[run.id] = run
    args = {"agent": "codex", "session_id": "", "run_id": run.id}
    monkeypatch.setattr(agents, "read_session", lambda *a: None)
    assert service.handle("coding.watch", args)["status"] == "running"
    run.result_session_id = "new-session"
    run.status = "done"
    run.output = "finished"
    result = service.handle("coding.watch", args)
    assert result["status"] == "done"
    assert result["runs"][0]["session_id"] == "new-session"
    assert result["runs"][0]["output"] == "finished"
    with pytest.raises(CodingError):
        service.handle("coding.watch", {**args, "session_id": "unrelated"})

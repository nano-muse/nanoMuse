"""Private desktop worker protocol, shared public source behavior and bounded input."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from nanomuse.server import public_sources, watch_stdio


def sample(text: str, *, personal: bool, turn: str = "", days: int = 0) -> dict[str, Any]:
    return {
        "text": text,
        "turn": turn,
        "personal": personal,
        "at": int((datetime.now(UTC) - timedelta(days=days)).timestamp() * 1000),
    }


async def test_worker_quiet_baseline_and_real_change(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0

    async def read(kind: str, target: str, *, now: datetime) -> list[public_sources.PublicItem]:
        nonlocal calls
        assert (kind, target) == ("github_repo", "sample/project")
        calls += 1
        return [public_sources.PublicItem(str(calls), f"Changed item {calls}", "")]

    monkeypatch.setattr(public_sources, "fetch_public", read)
    state = await watch_stdio.run(
        {
            "version": 1,
            "op": "observe",
            "state": {},
            "texts": [
                sample(
                    "My project is https://github.com/sample/project", personal=True, turn="first"
                )
            ],
        }
    )
    [row] = state["watches"].values()
    assert row["status"] == "active" and calls == 0
    poll = {"version": 1, "op": "poll", "state": state, "texts": []}
    await watch_stdio.run(poll)
    assert calls == 1 and not row["pending"]
    await watch_stdio.run(poll)
    assert calls == 1
    row["next"] = 0
    await watch_stdio.run(poll)
    assert [change["text"] for change in row["pending"].values()] == ["Changed item 2"]
    await watch_stdio.run(
        {
            "version": 1,
            "op": "edit",
            "state": state,
            "edit": {"action": "dismiss", "watch_id": row["id"]},
        }
    )
    await watch_stdio.run(poll)
    assert calls == 2


async def test_worker_does_not_elevate_connected_or_stale_context() -> None:
    state = await watch_stdio.run(
        {
            "version": 1,
            "op": "observe",
            "state": {},
            "texts": [
                sample("My project is https://github.com/sample/project", personal=False),
                sample(
                    "My project is https://github.com/sample/old",
                    personal=True,
                    turn="earlier",
                    days=45,
                ),
            ],
        }
    )
    [row] = state["watches"].values()
    assert (row["status"], row["origin"], row["target"]) == (
        "suggested",
        "connected",
        "sample/project",
    )
    views = [{"personal": False, "text": "x", "turn": "", "at": 0}] * 17
    with pytest.raises(ValueError, match="batch"):
        await watch_stdio.run({"version": 1, "op": "observe", "state": {}, "texts": views})


def test_hidden_cli_reads_one_request_and_prints_only_its_reply() -> None:
    def invoke(payload: object) -> dict[str, Any]:
        proc = subprocess.run(
            [sys.executable, "-m", "nanomuse", "watch-stdio"],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            timeout=20,
            check=True,
        )
        assert not proc.stderr and len(proc.stdout.splitlines()) == 1
        return json.loads(proc.stdout)

    reply = invoke(
        {
            "version": 1,
            "op": "edit",
            "state": {},
            "edit": {"kind": "research_work", "target": "10.1234/test"},
        }
    )
    assert next(iter(reply["state"]["watches"].values()))["target"] == "10.1234/test"
    assert invoke({"version": 2, "state": {}, "op": "poll"}) == {
        "version": 1,
        "error": "invalid_watch_request",
    }

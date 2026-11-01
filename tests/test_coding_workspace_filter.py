"""A workspace's sessions stay findable however many newer chats other repos hold.

(The rest of the coding tests skip on Windows for their POSIX shell; these build stores
only, so they run everywhere the readers do.)
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

from nanomuse.coding import agents


def _jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n")


def _zstd_frames(path: Path, groups: list[list[dict[str, Any]]]) -> None:
    import zstandard

    path.parent.mkdir(parents=True, exist_ok=True)
    c = zstandard.ZstdCompressor()
    path.write_bytes(
        b"".join(
            c.compress(("\n".join(json.dumps(r) for r in rows) + "\n").encode("utf-8"))
            for rows in groups
        )
    )


def _dir_slug(ws: Path) -> str:
    """The directory name Cursor and the harness use for a workspace on this OS."""
    return str(ws).replace("\\", "/").replace(":", "-").strip("/").replace("/", "-")


@pytest.fixture()
def coding_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("NANOMUSE_CODING_HOME", str(home))
    return home


def _claude_chat(home: Path, ws: Path, sid: str, text: str, at: float) -> None:
    f = home / ".claude" / "projects" / ("-" + _dir_slug(ws)) / f"{sid}.jsonl"
    _jsonl(
        f,
        [
            {
                "type": "user",
                "sessionId": sid,
                "cwd": str(ws),
                "timestamp": "2026-09-23T10:00:00Z",
                "message": {"role": "user", "content": text},
            },
            {
                "type": "assistant",
                "sessionId": sid,
                "message": {"role": "assistant", "content": [{"type": "text", "text": "done"}]},
            },
        ],
    )
    os.utime(f, (at, at))


def _codex_chat(home: Path, ws: Path, sid: str, text: str, at: float) -> None:
    f = (
        home
        / ".codex"
        / "sessions"
        / "2026"
        / "09"
        / "23"
        / f"rollout-2026-09-23T10-00-00-{sid}.jsonl"
    )
    _jsonl(
        f,
        [
            {
                "timestamp": "2026-09-23T10:00:00Z",
                "type": "session_meta",
                "payload": {"id": sid, "cwd": str(ws), "originator": "cli"},
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": text}],
                },
            },
        ],
    )
    os.utime(f, (at, at))


def _dsh_chat(home: Path, ws: Path, sid: str, text: str, at: float) -> None:
    f = home / ".dsh" / "sessions" / _dir_slug(ws) / sid / "session.v4.jsonl.zstd"
    _zstd_frames(
        f,
        [
            [
                {
                    "type": "session",
                    "version": 4,
                    "id": sid,
                    "createdAt": int(at * 1000),
                    "cwd": str(ws),
                }
            ],
            [
                {
                    "type": "user/message",
                    "seq": 1,
                    "data": {
                        "content": [{"type": "text", "text": text}],
                        "source": {"kind": "user"},
                        "role": "user",
                    },
                }
            ],
        ],
    )
    os.utime(f, (at, at))


def test_a_workspaces_own_sessions_are_not_pushed_off_by_newer_chats_elsewhere(
    coding_home: Path, tmp_path: Path
) -> None:
    home = coding_home
    ws = tmp_path / "proj" / "app"
    other = tmp_path / "other" / "repo"
    ws.mkdir(parents=True)
    other.mkdir(parents=True)
    _claude_chat(home, ws, "s-old", "Explain the build", at=1_000_000)
    _codex_chat(
        home, ws, "01a0c858-5820-7853-ba4c-dee7f183169c", "Rename the CLI flag", at=1_000_000
    )
    _dsh_chat(home, ws, "session-old", "Refactor the loader", at=1_000_000)
    # more newer chats in another repo than any reader's recency slice
    for i in range(30):
        at = 2_000_000 + i
        _claude_chat(home, other, f"new-{i}", f"unrelated {i}", at=at)
        _codex_chat(
            home, other, f"7777777{i:05d}-8888-4999-aaaa-bbbbbbbbbbbb", f"unrelated {i}", at=at
        )
        _dsh_chat(home, other, f"session-new-{i}", f"unrelated {i}", at=at)
    for agent in ("claude", "codex", "dsh"):
        rows = agents.sessions(agent, limit=10, workspace=str(ws))
        assert rows and {s.id for s in rows} == {
            "s-old"
            if agent == "claude"
            else "01a0c858-5820-7853-ba4c-dee7f183169c"
            if agent == "codex"
            else "session-old"
        }, agent
    # without a filter the newest chats still lead, as before
    top = agents.sessions("claude", limit=10)
    assert top and top[0].id.startswith("new-")


@pytest.mark.parametrize("agent", ["claude", "dsh"])
def test_workspace_metadata_wins_when_two_paths_share_a_directory_slug(
    coding_home: Path, tmp_path: Path, agent: str
) -> None:
    workspace = tmp_path / "repo" / "tools"
    other = tmp_path / "repo-tools"
    workspace.mkdir(parents=True)
    other.mkdir()
    assert _dir_slug(workspace) == _dir_slug(other)
    write = _claude_chat if agent == "claude" else _dsh_chat
    write(coding_home, workspace, "wanted", "The older session", at=1_000_000)
    write(coding_home, other, "different", "The newer session", at=2_000_000)

    rows = agents.sessions(agent, limit=1, workspace=str(workspace))
    assert [row.id for row in rows] == ["wanted"]
    assert [row.id for row in agents.sessions(agent, limit=1, workspace=str(other))] == [
        "different"
    ]

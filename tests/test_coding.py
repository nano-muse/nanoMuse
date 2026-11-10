"""The coding agents bridge: reading Cursor / Codex / Claude Code transcripts, driving a CLI
and streaming its output, the runtime API on top (docs/coding-agents.md)."""

from __future__ import annotations

import asyncio
import json
import os
import stat
import sys
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from nanomuse.coding import agents, runner
from nanomuse.coding.runner import Run, _normalise, start_run
from nanomuse.config import Settings
from nanomuse.llm import MockLLM
from nanomuse.server import create_app
from nanomuse.server.service import MuseService


def _jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n")


def _zstd_frames(path: Path, groups: list[list[dict[str, Any]]]) -> None:
    """A dsh session file the way the harness writes it: one zstd frame per write."""
    import zstandard

    path.parent.mkdir(parents=True, exist_ok=True)
    c = zstandard.ZstdCompressor()
    frames = [
        c.compress(
            ("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n").encode("utf-8")
        )
        for rows in groups
    ]
    path.write_bytes(b"".join(frames))


@pytest.fixture()
def coding_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A home with one session of each agent, as the tools write them."""
    home = tmp_path / "home"
    ws = tmp_path / "proj" / "app"
    ws.mkdir(parents=True)
    if sys.platform == "win32":
        # the stores slug the workspace the way the CLIs do on Windows: Cursor and dsh
        # drop the drive's colon, Claude Code turns it into a dash (see _slug_to_path)
        slug = str(ws).replace("\\", "-").replace(":", "")
        claude_slug = str(ws).replace("\\", "-").replace(":", "-")
    else:
        slug = str(ws).strip("/").replace("/", "-")
        claude_slug = "-" + slug
    # Cursor: an IDE chat (wrapped user text) and a CLI chat with meta
    _jsonl(
        home / ".cursor" / "projects" / slug / "agent-transcripts" / "c1" / "c1.jsonl",
        [
            {
                "role": "user",
                "message": {
                    "content": [
                        {
                            "type": "text",
                            "text": "<timestamp>Mon</timestamp>\n<user_query>\nFix the login bug\n</user_query>",
                        }
                    ]
                },
            },
            {
                "role": "assistant",
                "message": {"content": [{"type": "text", "text": "Looking at auth.py now."}]},
            },
            {
                "role": "assistant",
                "message": {
                    "content": [{"type": "text", "text": "Done: the token check was inverted."}]
                },
            },
            {"type": "turn_ended", "status": "completed"},
        ],
    )
    _jsonl(
        home / ".cursor" / "projects" / slug / "agent-transcripts" / "c2" / "c2.jsonl",
        [
            {
                "role": "user",
                "message": {"content": [{"type": "text", "text": "Add tests for the parser"}]},
            },
            {
                "role": "assistant",
                "message": {"content": [{"type": "text", "text": "Writing tests…"}]},
            },
        ],
    )
    meta = home / ".cursor" / "chats" / "abc" / "c2" / "meta.json"
    meta.parent.mkdir(parents=True)
    meta.write_text(
        json.dumps({"cwd": str(ws), "createdAtMs": 1790000000000, "hasConversation": True})
    )
    # Codex: a rollout with meta, developer noise, a user turn and an answer
    _jsonl(
        home
        / ".codex"
        / "sessions"
        / "2026"
        / "09"
        / "22"
        / "rollout-2026-09-22T17-00-28-01a0c858-5820-7853-ba4c-dee7f183169c.jsonl",
        [
            {
                "type": "session_meta",
                "payload": {
                    "id": "01a0c858-5820-7853-ba4c-dee7f183169c",
                    "cwd": str(ws),
                    "originator": "Codex Desktop",
                    "timestamp": "2026-09-22T09:00:28.065Z",
                },
            },
            {"type": "event_msg", "payload": {"type": "task_started"}},
            {
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "developer",
                    "content": [{"type": "input_text", "text": "<app-context>…</app-context>"}],
                },
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": "<environment_context>x</environment_context>",
                        }
                    ],
                },
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": "Rename the CLI flag"}],
                },
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "assistant",
                    "content": [
                        {"type": "output_text", "text": "Renamed --foo to --bar in three files."}
                    ],
                },
            },
            {"type": "event_msg", "payload": {"type": "task_complete"}},
        ],
    )
    # Claude Code
    _jsonl(
        home / ".claude" / "projects" / claude_slug / "s9.jsonl",
        [
            {
                "type": "user",
                "sessionId": "s9",
                "cwd": str(ws),
                "timestamp": "2026-09-23T10:00:00Z",
                "message": {"role": "user", "content": "Explain the build"},
            },
            {
                "type": "assistant",
                "sessionId": "s9",
                "message": {
                    "role": "assistant",
                    "content": [
                        {"type": "tool_use", "name": "Read"},
                        {"type": "text", "text": "It uses hatch."},
                    ],
                },
            },
        ],
    )
    # dsh: the harness's own store, one zstd frame per write (a long chat is many frames
    # appended, which a single decompression stops at the end of), with runtime context
    # arriving as a user message
    _zstd_frames(
        home / ".dsh" / "sessions" / slug / "session-d1" / "session.v4.jsonl.zstd",
        [
            [
                {
                    "type": "session",
                    "version": 4,
                    "id": "session-d1",
                    "createdAt": 1790000000000,
                    "cwd": str(ws),
                }
            ],
            [
                {
                    "type": "user/message",
                    "seq": 1,
                    "data": {
                        "content": [{"type": "text", "text": "Refactor the loader"}],
                        "source": {"kind": "user"},
                        "role": "user",
                    },
                },
                {"type": "session/title", "seq": 2, "data": {"title": "Refactor the loader"}},
            ],
            [
                {
                    "type": "user/message",
                    "seq": 3,
                    "data": {
                        "content": [
                            {"type": "text", "text": "Current DSH file policy: workspace-write"}
                        ],
                        "source": {"kind": "runtime-context"},
                    },
                },
                {
                    "type": "assistant/message",
                    "seq": 4,
                    "data": {
                        "message": {
                            "role": "assistant",
                            "content": [
                                {"type": "reasoning", "text": "hmm"},
                                {"type": "text", "text": "The loader is now two functions."},
                            ],
                        }
                    },
                },
                {"type": "turn/end", "seq": 5, "data": {"turn": 1}},
            ],
        ],
    )
    # a subagent session is the harness's own working session, not a chat the person had
    _zstd_frames(
        home / ".dsh" / "sessions" / slug / "session-d2" / "session.v4.jsonl.zstd",
        [
            [
                {
                    "type": "session",
                    "version": 4,
                    "id": "session-d2",
                    "cwd": str(ws),
                    "origin": "subagent",
                    "parentSession": "session-d1",
                }
            ],
            [
                {
                    "type": "user/message",
                    "seq": 1,
                    "data": {
                        "content": [{"type": "text", "text": "You are researching something"}],
                        "source": {"kind": "user"},
                    },
                }
            ],
        ],
    )
    monkeypatch.setenv("NANOMUSE_CODING_HOME", str(home))
    return home


# ----------------------------------------------------------------------------- reading
def test_sessions_are_read_from_each_agents_store(coding_home: Path, tmp_path: Path) -> None:
    ws = str(tmp_path / "proj" / "app")
    rows = agents.sessions(limit=10)
    by = {(s.agent, s.id): s for s in rows}
    assert set(by) == {
        ("cursor", "c1"),
        ("cursor", "c2"),
        ("codex", "01a0c858-5820-7853-ba4c-dee7f183169c"),
        ("claude", "s9"),
        ("dsh", "session-d1"),
    }

    c1 = by[("cursor", "c1")]
    assert c1.title == "Fix the login bug" and c1.source == "ide" and c1.messages == 3
    assert c1.workspace == ws and c1.last_assistant == "Done: the token check was inverted."
    assert c1.status == "active"  # written just now, turn closed
    assert c1.resumable is False  # an IDE chat: the CLI cannot reopen it
    c2 = by[("cursor", "c2")]
    assert c2.source == "cli" and c2.workspace == ws and c2.created_at == 1790000000.0
    assert c2.status == "running"  # a user turn without turn_ended, fresh
    assert c2.resumable is True

    cx = by[("codex", "01a0c858-5820-7853-ba4c-dee7f183169c")]
    assert cx.title == "Rename the CLI flag" and cx.source == "Codex Desktop" and cx.messages == 2
    assert cx.workspace == ws and cx.status == "active"
    assert abs(cx.created_at - 1790067628.065) < 1

    cl = by[("claude", "s9")]
    assert (
        cl.title == "Explain the build"
        and cl.workspace == ws
        and cl.last_assistant == "[tool: Read] It uses hatch."
    )

    # dsh: every zstd frame is read, not only the first, and the runtime-context message
    # that arrives as a user message is not the person's words
    ds = by[("dsh", "session-d1")]
    assert ds.title == "Refactor the loader"
    assert ds.workspace == ws and ds.messages == 2
    assert ds.last_user == "Refactor the loader"
    assert ds.created_at == 1790000000.0 and ds.resumable is True
    assert ("dsh", "session-d2") not in by  # a subagent session is not one of the person's chats

    # filters
    assert [s.id for s in agents.sessions("cursor")] == ["c2", "c1"] or {
        s.id for s in agents.sessions("cursor")
    } == {"c1", "c2"}
    assert agents.sessions(workspace=str(tmp_path / "elsewhere")) == []
    assert {s.agent for s in agents.sessions(workspace=ws)} == {
        "cursor",
        "codex",
        "claude",
        "dsh",
    }


def test_read_session_has_the_transcript(coding_home: Path) -> None:
    s = agents.read_session("cursor", "c1")
    assert s is not None
    assert [m["role"] for m in s.transcript] == ["user", "assistant", "assistant"]
    assert s.transcript[0]["text"] == "Fix the login bug"
    cx = agents.read_session("codex", "01a0c858-5820-7853-ba4c-dee7f183169c")
    assert cx is not None and [m["text"] for m in cx.transcript] == [
        "Rename the CLI flag",
        "Renamed --foo to --bar in three files.",
    ]
    assert agents.read_session("codex", "nope") is None
    assert agents.read_session("cursor", "../c1") is None
    assert agents.read_session("claude", "s9") is not None
    # dsh: the whole file, across every frame
    ds = agents.read_session("dsh", "session-d1")
    assert ds is not None
    assert [m["text"] for m in ds.transcript] == [
        "Refactor the loader",
        "The loader is now two functions.",
    ]
    assert agents.read_session("dsh", "session-d2") is None  # a subagent session, not a chat


def test_detect_reports_installs_without_running_anything(
    coding_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        agents, "which", lambda agent: "/usr/bin/fake" if agent == "codex" else None
    )
    found = {a.id: a for a in agents.detect()}
    assert found["codex"].installed and found["codex"].cli == "/usr/bin/fake"
    # no CLI, but transcripts on disk: still "installed" for reading
    assert (
        found["cursor"].installed
        and found["cursor"].cli is None
        and found["cursor"].sessions_root.endswith("projects")
    )
    assert found["claude"].installed


# ----------------------------------------------------------------------------- the stream
def test_normalise_cursor_deltas_then_whole_message() -> None:
    run = Run(id="r", agent="cursor", session_id="", workspace="", text="hi")
    evs = _normalise(
        "cursor", {"type": "system", "subtype": "init", "session_id": "S1", "model": "m"}, run
    )
    assert evs[0].kind == "started" and run.result_session_id == "S1"
    _normalise(
        "cursor",
        {
            "type": "assistant",
            "message": {"content": [{"type": "text", "text": "p"}]},
            "timestamp_ms": 1,
        },
        run,
    )
    _normalise(
        "cursor",
        {
            "type": "assistant",
            "message": {"content": [{"type": "text", "text": "ong"}]},
            "timestamp_ms": 2,
        },
        run,
    )
    assert run.current == "pong" and run.output == ""
    evs = _normalise(
        "cursor",
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "pong"}]}},
        run,
    )
    assert evs[0].extra["partial"] is False and run.output == "pong" and run.current == ""
    evs = _normalise(
        "cursor",
        {
            "type": "tool_call",
            "subtype": "started",
            "tool_call": {"shellToolCall": {"args": {"command": "ls -la"}}},
        },
        run,
    )
    assert evs[0].kind == "tool" and evs[0].text == "shell: ls -la" and run.tools == 1
    evs = _normalise(
        "cursor",
        {
            "type": "result",
            "subtype": "success",
            "result": "pong",
            "session_id": "S1",
            "duration_ms": 5,
        },
        run,
    )
    assert evs[0].kind == "done" and run.output == "pong"


def test_normalise_codex_and_claude() -> None:
    run = Run(id="r", agent="codex", session_id="", workspace="", text="hi")
    assert (
        _normalise("codex", {"type": "thread.started", "thread_id": "T1"}, run)[0].extra[
            "session_id"
        ]
        == "T1"
    )
    evs = _normalise(
        "codex",
        {"type": "item.completed", "item": {"type": "command_execution", "command": "pytest -q"}},
        run,
    )
    assert evs[0].kind == "tool" and evs[0].text == "shell: pytest -q"
    evs = _normalise(
        "codex",
        {"type": "item.completed", "item": {"type": "agent_message", "text": "All green."}},
        run,
    )
    assert evs[0].kind == "text" and run.output == "All green."
    evs = _normalise("codex", {"type": "turn.completed", "usage": {"input_tokens": 5}}, run)
    assert evs[0].kind == "done" and evs[0].text == "All green."
    evs = _normalise("codex", {"type": "error", "message": "refresh token was revoked"}, run)
    assert evs[0].kind == "error" and "revoked" in evs[0].text

    run = Run(id="r", agent="claude", session_id="", workspace="", text="hi")
    _normalise("claude", {"type": "system", "subtype": "init", "session_id": "C1"}, run)
    evs = _normalise(
        "claude",
        {
            "type": "assistant",
            "message": {
                "content": [
                    {"type": "tool_use", "name": "Bash", "input": {"command": "make"}},
                    {"type": "text", "text": "Built."},
                ]
            },
        },
        run,
    )
    assert [e.kind for e in evs] == ["tool", "text"] and evs[0].text == "Bash: make"
    evs = _normalise("claude", {"type": "result", "result": "Built.", "session_id": "C1"}, run)
    assert evs[0].kind == "done" and run.result_session_id == "C1" and run.output == "Built."


def test_dsh_store_cut_short_keeps_the_frames_before(tmp_path: Path) -> None:
    """A last frame cut short (the harness mid-write) loses that frame, not the whole chat."""
    f = tmp_path / "session.v4.jsonl.zstd"
    _zstd_frames(f, [[{"type": "a"}], [{"type": "b"}], [{"type": "c", "pad": "x" * 4000}]])
    whole = f.read_bytes()
    f.write_bytes(whole[: len(whole) - 20])
    assert [o["type"] for o in agents._read_zstd_lines(f)][:2] == ["a", "b"]


def test_normalise_dsh_headless_json() -> None:
    """The lines `dsh --profile headless --json` prints, as a real run spelled them."""
    run = Run(id="r", agent="dsh", session_id="", workspace="", text="hi")
    evs = _normalise("dsh", {"type": "session", "sessionId": "session-abc", "cwd": "/w"}, run)
    assert evs[0].kind == "started" and run.result_session_id == "session-abc"
    assert evs[0].extra["cwd"] == "/w"
    # the status lines carry no words of their own, and reasoning is not the answer
    assert _normalise("dsh", {"type": "status", "phase": "turn_start", "turn": 1}, run) == []
    assert _normalise("dsh", {"type": "thinking", "text": "let me look"}, run) == []
    evs = _normalise("dsh", {"type": "text", "text": "Two files changed."}, run)
    assert evs[0].kind == "text" and run.output == "Two files changed."
    evs = _normalise(
        "dsh",
        {"type": "tool_call", "callId": "c1", "tool": "bash", "input": {"command": "ls -la"}},
        run,
    )
    assert evs[0].kind == "tool" and evs[0].text == "bash: ls -la" and run.tools == 1
    evs = _normalise("dsh", {"type": "tool_result", "callId": "c1", "status": "completed"}, run)
    assert evs[0].kind == "tool" and evs[0].extra["phase"] == "completed"
    evs = _normalise("dsh", {"type": "final", "text": "Two files changed."}, run)
    assert evs[0].kind == "done" and evs[0].extra["session_id"] == "session-abc"
    assert run.output == "Two files changed."  # the final text is not appended twice
    # a failed turn reports its reason on the status line
    evs = _normalise(
        "dsh",
        {
            "type": "status",
            "phase": "turn_end",
            "turn": 1,
            "reason": {
                "kind": "error",
                "error": {"code": "MISSING_CREDENTIAL", "message": "no API key"},
            },
        },
        Run(id="r2", agent="dsh", session_id="", workspace="", text="x"),
    )
    assert evs[0].kind == "error" and evs[0].text == "no API key"


def test_command_for_dsh(monkeypatch: pytest.MonkeyPatch) -> None:
    """`dsh` has no `-C`: it runs in the process's directory, so the run's cwd is what
    makes a resumed session match its recorded one."""
    monkeypatch.setattr(runner, "which", lambda agent: "/u/dsh")
    assert runner.command_for("dsh", "session-1", "/w", "go", True) == [
        "/u/dsh",
        "--profile",
        "headless",
        "--json",
        "--session-id",
        "session-1",
        "go",
    ]
    assert runner.command_for("dsh", "", "/w", "go", False) == [
        "/u/dsh",
        "--profile",
        "headless",
        "--json",
        "go",
    ]


# The same fake as node, for Windows: a batch file is the only thing CreateProcess will
# start for a script, and cmd.exe ends an argument at the first newline, so the wrapper
# stays a one-liner and the behaviour lives in the .mjs it points at.
_FAKE_JS = {
    "base": """import fs from "node:fs";

const args = process.argv.slice(2);
fs.appendFileSync(@ARGS_LOG@, args.join(" ") + "\\n");
if (args.join(" ").includes("--resume nope")) {
  fs.writeSync(2, "Error: chat not found\\n");
  process.exit(1);
}
for (const line of [
  '{"type":"system","subtype":"init","session_id":"S-new","model":"m"}',
  '{"type":"assistant","message":{"content":[{"type":"text","text":"work"}]},"timestamp_ms":1}',
  '{"type":"assistant","message":{"content":[{"type":"text","text":"working on it"}]}}',
  '{"type":"tool_call","subtype":"started","tool_call":{"shellToolCall":{"args":{"command":"ls"}}}}',
  '{"type":"result","subtype":"success","result":"working on it","session_id":"S-new","duration_ms":3}',
]) {
  fs.writeSync(1, line + "\\n");
}
process.exit(0);
""",
    "writer_conflict": """import fs from "node:fs";

fs.appendFileSync(@CALLS_LOG@, "call\\n");
fs.writeSync(2, "Error: thread/resume: thread/resume failed: thread " +
  "01a0c858-5820-7853-ba4c-dee7f183169c already has an active writer (code -32600)\\n");
process.exit(1);
""",
    "terminal_error": """import fs from "node:fs";
import { spawn } from "node:child_process";

for (const line of [
  '{"type":"assistant","message":{"content":[{"type":"text","text":"trying"}]}}',
  '{"type":"result","is_error":true,"result":"the model refused"}',
]) {
  fs.writeSync(1, line + "\\n");
}
spawn(process.execPath, ["-e", "setTimeout(() => {}, 2000)"],
  { stdio: ["ignore", process.stdout, process.stderr] }).unref();
process.exit(0);
""",
    "helper": """import fs from "node:fs";
import { spawn } from "node:child_process";

for (const line of [
  '{"type":"system","subtype":"init","session_id":"S-new","model":"m"}',
  '{"type":"result","subtype":"success","result":"ok","session_id":"S-new","duration_ms":3}',
]) {
  fs.writeSync(1, line + "\\n");
}
// keeps our stdout open long after the CLI itself has exited
spawn(process.execPath, ["-e", "setTimeout(() => {}, 30000)"],
  { stdio: ["ignore", process.stdout, process.stderr] }).unref();
process.exit(0);
""",
    "cancel": """import fs from "node:fs";

fs.writeFileSync(@PID_FILE@, process.pid + "\\n");
fs.writeSync(1, '{"type":"system","subtype":"init","session_id":"S-new","model":"m"}\\n');
setInterval(() => {}, 60000); // an agent still at work
""",
}


def _write_fake(script: Path, sh_body: str, js_body: str) -> None:
    """Rewrite the fake CLI for the next test: the sh script on posix, the same behaviour
    as node on Windows (the .cmd wrapper never changes, only the .mjs it points at)."""
    script.write_text(
        js_body if sys.platform == "win32" else sh_body, encoding="utf-8", newline="\n"
    )


@pytest.fixture()
def fake_cursor(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A stand-in `cursor-agent`: prints a stream-json run; `--resume nope` fails like the
    real one does for an unknown chat; the arguments are written down for the assertions.

    On Windows the same behaviour is node behind a `cursor-agent.cmd` wrapper, and the
    fixture returns the .mjs so the variant tests rewrite the behaviour, not the wrapper."""
    if sys.platform == "win32":
        exe = tmp_path / "cursor-agent.cmd"
        exe.write_bytes(b'@node "%~dp0cursor-agent.mjs" %*\r\n')
        logic = tmp_path / "cursor-agent.mjs"
        logic.write_text(
            _FAKE_JS["base"].replace("@ARGS_LOG@", json.dumps(str(tmp_path / "args.log"))),
            encoding="utf-8",
            newline="\n",
        )
        script = logic
    else:
        script = tmp_path / "cursor-agent"
        script.write_text(
            "#!/bin/sh\n"
            f'echo "$@" >> "{tmp_path}/args.log"\n'
            'case "$*" in *"--resume nope"*) echo "Error: chat not found" >&2; exit 1;; esac\n'
            'echo \'{"type":"system","subtype":"init","session_id":"S-new","model":"m"}\'\n'
            'echo \'{"type":"assistant","message":{"content":[{"type":"text","text":"work"}]},"timestamp_ms":1}\'\n'
            'echo \'{"type":"assistant","message":{"content":[{"type":"text","text":"working on it"}]}}\'\n'
            'echo \'{"type":"tool_call","subtype":"started","tool_call":{"shellToolCall":{"args":{"command":"ls"}}}}\'\n'
            'echo \'{"type":"result","subtype":"success","result":"working on it","session_id":"S-new","duration_ms":3}\'\n'
        )
        script.chmod(script.stat().st_mode | stat.S_IEXEC)
        exe = script
    monkeypatch.setattr(runner, "which", lambda agent: str(exe) if agent == "cursor" else None)
    monkeypatch.setattr(agents, "which", lambda agent: str(exe) if agent == "cursor" else None)
    return script


def test_start_run_streams_and_falls_back_to_a_new_chat(
    coding_home: Path, fake_cursor: Path, tmp_path: Path
) -> None:
    seen: list[dict[str, Any]] = []

    async def on_event(ev: dict[str, Any]) -> None:
        seen.append(ev)

    run = asyncio.run(
        start_run("cursor", "carry on", session_id="c2", on_event=on_event, timeout_s=20)
    )
    assert run.status == "done" and run.resumed is True and run.result_session_id == "S-new"
    assert run.output == "working on it" and run.tools == 1
    assert run.workspace == str(tmp_path / "proj" / "app")  # taken from the session
    kinds = [e["kind"] for e in seen]
    assert kinds == ["started", "text", "text", "tool", "done"]
    args = (tmp_path / "args.log").read_text()
    assert "--resume c2" in args and "--workspace" in args and args.strip().endswith("carry on")

    # an IDE chat is known not to be resumable: no failed attempt first, straight to a new
    # chat in its workspace with the last exchange quoted, and the run says so
    (tmp_path / "args.log").unlink()
    seen.clear()
    run = asyncio.run(
        start_run("cursor", "carry on", session_id="c1", on_event=on_event, timeout_s=20)
    )
    assert run.status == "done" and run.resumed is False and run.result_session_id == "S-new"
    assert seen[0]["kind"] == "tool" and "made in the IDE" in seen[0]["text"]
    args = (tmp_path / "args.log").read_text()
    assert "--resume" not in args and args.count("--workspace") == 1  # one call, no failed try
    assert "Fix the login bug" in args
    if sys.platform != "win32":
        assert "token check was inverted" in args
        assert args.strip().endswith("carry on")
    # on Windows the batch wrapper that stands in for the CLI ends an argument at the
    # first newline, so the quoted exchange's tail and the new message do not reach the
    # fake's argv; the flags, the workspace and the title's first line do

    # an unknown chat: the CLI refuses, the runner starts a new chat with the last exchange quoted
    (tmp_path / "args.log").unlink()
    seen.clear()
    run = asyncio.run(
        start_run(
            "cursor",
            "and now this",
            session_id="nope",
            workspace=str(tmp_path / "proj" / "app"),
            on_event=on_event,
            timeout_s=20,
        )
    )
    assert run.status == "done" and run.resumed is False
    assert any(e["kind"] == "tool" and "cannot be resumed" in e["text"] for e in seen)
    lines = (tmp_path / "args.log").read_text().splitlines()
    assert "--resume nope" in lines[0] and "--resume" not in lines[1] and "and now this" in lines[1]

    # not installed
    run = asyncio.run(start_run("codex", "hi", timeout_s=5))
    assert run.status == "failed" and "not installed" in run.error


def test_codex_writer_conflict_does_not_start_another_session(
    coding_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    script = tmp_path / "fake-codex"
    calls = tmp_path / "calls"
    if sys.platform == "win32":
        exe = tmp_path / "fake-codex.cmd"
        exe.write_bytes(b'@node "%~dp0fake-codex.mjs" %*\r\n')
        script = tmp_path / "fake-codex.mjs"
    else:
        exe = script
    _write_fake(
        script,
        "#!/bin/sh\n"
        f'echo call >> "{calls}"\n'
        "echo 'Error: thread/resume: thread/resume failed: thread "
        "01a0c858-5820-7853-ba4c-dee7f183169c already has an active writer "
        "(code -32600)' >&2\n"
        "exit 1\n",
        _FAKE_JS["writer_conflict"].replace("@CALLS_LOG@", json.dumps(str(calls))),
    )
    if sys.platform != "win32":
        script.chmod(0o755)
    monkeypatch.setattr(runner, "which", lambda agent: str(exe))
    monkeypatch.setattr(runner, "_lock_owner", lambda sid: "codex (PID 123)")
    run = asyncio.run(
        start_run(
            "codex", "how many?", session_id="01a0c858-5820-7853-ba4c-dee7f183169c", timeout_s=10
        )
    )
    assert run.status == "failed"
    assert calls.read_text().strip() == "call"
    assert run.resume_conflict is not None
    assert run.resume_conflict["process"] == "codex (PID 123)"
    assert run.resume_conflict["continuation"].endswith("Now: how many?")
    assert run.to_dict()["resume_conflict"] == run.resume_conflict
    assert runner._is_resume_lock_error("session already registered for process 123")
    assert runner._is_resume_lock_error(
        "Error: thread/resume: thread/resume failed: thread "
        "01a0c858-5820-7853-ba4c-dee7f183169c already has an active writer (code -32600)"
    )
    assert not runner._is_resume_lock_error("resume failed: authentication expired")
    assert not runner._is_resume_lock_error("failed to open thread writer lock: permission denied")
    assert not runner._looks_like_unknown_session("failed to resume: authentication expired")


@pytest.mark.parametrize("phase", ["item.started", "item.completed"])
def test_resume_failure_after_tool_work_does_not_repeat_actions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, phase: str
) -> None:
    calls = tmp_path / "effects"
    rows = [
        {"type": "thread.started", "thread_id": "existing-session"},
        {
            "type": phase,
            "item": {
                "id": "command-1",
                "type": "command_execution",
                "command": "record-effect",
                "aggregated_output": "effect recorded",
                "exit_code": 0,
            },
        },
        {"type": "turn.failed", "error": {"message": "response resource not found"}},
    ]
    script = tmp_path / "fake-codex"
    exe = script
    if sys.platform == "win32":
        exe = tmp_path / "fake-codex.cmd"
        exe.write_bytes(b'@node "%~dp0fake-codex.mjs" %*\r\n')
        script = tmp_path / "fake-codex.mjs"
    _write_fake(
        script,
        "#!/bin/sh\n"
        f'echo effect >> "{calls}"\n'
        + "\n".join("echo '" + json.dumps(row) + "'" for row in rows)
        + "\nexit 1\n",
        'import fs from "node:fs";\n'
        + f'fs.appendFileSync({json.dumps(str(calls))}, "effect\\n");\n'
        + f"for (const row of {json.dumps(rows)}) console.log(JSON.stringify(row));\n"
        + "process.exitCode = 1;\n",
    )
    script.chmod(0o755)
    monkeypatch.setattr(runner, "which", lambda agent: str(exe))
    monkeypatch.setattr(runner, "read_session", lambda agent, sid: None)
    run = asyncio.run(start_run("codex", "act once", session_id="existing-session", timeout_s=10))
    assert run.status == "failed"
    assert run.resumed
    assert calls.read_text().splitlines() == ["effect"]
    assert run.error == "response resource not found"


def test_a_helper_left_behind_does_not_keep_the_run_open(
    fake_cursor: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The real `cursor-agent` leaves a worker running after it answers, and under some
    event loops (uvloop) that worker inherits our pipes, so EOF never comes. The run has to
    finish on the agent's final message, not on EOF."""
    _write_fake(
        fake_cursor,
        "#!/bin/sh\n"
        'echo \'{"type":"system","subtype":"init","session_id":"S-new","model":"m"}\'\n'
        'echo \'{"type":"result","subtype":"success","result":"ok","session_id":"S-new","duration_ms":3}\'\n'
        "sleep 30 &\n"  # keeps our stdout open long after the CLI itself has exited
        "exit 0\n",
        _FAKE_JS["helper"],
    )
    t0 = time.monotonic()
    run = asyncio.run(start_run("cursor", "hi", timeout_s=20))
    assert run.status == "done" and run.output == "ok" and run.result_session_id == "S-new"
    assert time.monotonic() - t0 < 10


def test_terminal_error_with_zero_exit_stays_failed(
    fake_cursor: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_fake(
        fake_cursor,
        "#!/bin/sh\n"
        'echo \'{"type":"assistant","message":{"content":[{"type":"text","text":"trying"}]}}\'\n'
        'echo \'{"type":"result","is_error":true,"result":"the model refused"}\'\n'
        "sleep 2 &\n"
        "exit 0\n",
        _FAKE_JS["terminal_error"],
    )
    started = time.monotonic()
    run = asyncio.run(start_run("cursor", "hi", timeout_s=10))
    assert run.status == "failed"
    assert run.error == "the model refused"
    assert time.monotonic() - started < 8


def test_a_cancelled_run_takes_its_agent_down_with_it(
    coding_home: Path, fake_cursor: Path, tmp_path: Path
) -> None:
    """The chat that waited for the run was stopped: the agent's process group is ended,
    nothing of ours keeps reading its pipes, and the run says it was stopped."""
    _write_fake(
        fake_cursor,
        "#!/bin/sh\n"
        f'echo $$ > "{tmp_path}/pid"\n'
        'echo \'{"type":"system","subtype":"init","session_id":"S-new","model":"m"}\'\n'
        "sleep 60\n",  # an agent still at work
        _FAKE_JS["cancel"].replace("@PID_FILE@", json.dumps(str(tmp_path / "pid"))),
    )

    async def scenario() -> Run:
        runs: list[Run] = []
        task = asyncio.create_task(start_run("cursor", "hi", timeout_s=30, register=runs.append))
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and not (tmp_path / "pid").exists():
            await asyncio.sleep(0.05)
        await asyncio.sleep(0.2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        return runs[0]

    t0 = time.monotonic()
    run = asyncio.run(scenario())
    assert run.status == "stopped" and run.ended_at is not None
    assert run.process is not None and run.process.returncode is not None
    assert time.monotonic() - t0 < 10


# ----------------------------------------------------------------------------- the runtime API
@pytest.fixture()
def server(
    settings: Settings, coding_home: Path, fake_cursor: Path
) -> Iterator[tuple[TestClient, MuseService]]:
    settings.server.token = "secret-token"
    service = MuseService(settings, llm=MockLLM([]))
    app = create_app(settings, service)
    with TestClient(app) as client:
        client.headers["Authorization"] = "Bearer secret-token"
        yield client, service


def test_api_lists_sessions_sends_and_follows(
    server: tuple[TestClient, MuseService], tmp_path: Path
) -> None:
    client, service = server
    status = client.get("/api/coding").json()
    agents_by = {a["id"]: a for a in status["agents"]}
    assert (
        agents_by["cursor"]["installed"] and Path(agents_by["cursor"]["cli"]).stem == "cursor-agent"
    )
    assert status["runs"] == []

    rows = client.get("/api/coding/sessions?agent=cursor").json()["sessions"]
    assert {s["id"] for s in rows} == {"c1", "c2"}
    one = client.get("/api/coding/sessions/cursor/c1").json()
    assert one["title"] == "Fix the login bug" and len(one["transcript"]) == 3
    assert client.get("/api/coding/sessions/cursor/zzz").status_code == 404
    assert client.get("/api/coding/sessions/vim/c1").status_code == 404

    with client.websocket_connect("/ws") as ws:
        ws.send_json({"kind": "auth", "token": "secret-token"})
        assert ws.receive_json()["kind"] == "hello"
        r = client.post(
            "/api/coding/send", json={"agent": "cursor", "text": "carry on", "session_id": "c1"}
        )
        assert r.status_code == 200, r.text
        run = r.json()
        assert run["status"] == "running" and run["agent"] == "cursor"
        kinds: list[str] = []
        final: dict[str, Any] | None = None
        deadline = time.time() + 20
        while time.time() < deadline:
            msg = ws.receive_json()
            if msg.get("kind") != "coding":
                continue
            ev = msg.get("event") or {}
            kinds.append(str(ev.get("kind")))
            if msg.get("run") and msg["run"].get("status") in ("done", "failed"):
                final = msg["run"]
                break
        assert (
            final is not None and final["status"] == "done" and final["output"] == "working on it"
        )
        assert "text" in kinds and "tool" in kinds and "done" in kinds
    runs = client.get("/api/coding").json()["runs"]
    assert (
        runs[0]["id"] == run["id"]
        and runs[0]["status"] == "done"
        and runs[0]["session_id"] == "S-new"
    )
    # the session list shows the run's message count unchanged (the fake CLI writes no transcript)
    assert client.post("/api/coding/send", json={"agent": "codex", "text": "x"}).status_code == 412
    assert client.post("/api/coding/stop", json={"run": "run_none"}).json() == {"stopped": False}
    # the Muse's own tool sees the same
    tool = service.app.tools.get("coding_agents")
    assert tool is not None
    out = asyncio.run(tool.execute(action="sessions", agent="cursor"))
    assert not out.error and "Fix the login bug" in out.output
    out = asyncio.run(
        tool.execute(
            action="session", agent="codex", session_id="01a0c858-5820-7853-ba4c-dee7f183169c"
        )
    )
    assert "Renamed --foo" in out.output
    a = tool.assess({"action": "send", "agent": "cursor", "text": "do it", "workspace": "/w/app"})
    assert a.risk.value == "sensitive" and a.summary == "tell cursor in /w/app: do it"
    assert tool.assess({"action": "sessions", "agent": "cursor"}).risk.value == "safe"


def test_runs_survive_a_restart(
    server: tuple[TestClient, MuseService], settings: Settings, tmp_path: Path
) -> None:
    """The record of runs is written to <data_dir>/coding/runs.json as they finish, and a
    new service reads it back; one that was still going comes back as stopped."""
    client, service = server
    r = client.post(
        "/api/coding/send", json={"agent": "cursor", "text": "carry on", "session_id": "c2"}
    )
    assert r.status_code == 200
    store = Path(settings.data_dir) / "coding" / "runs.json"
    deadline = time.time() + 20
    while time.time() < deadline and not store.is_file():
        time.sleep(0.1)
    rows = json.loads(store.read_text(encoding="utf-8"))
    assert len(rows) == 1 and rows[0]["status"] == "done" and rows[0]["session_id"] == "S-new"
    assert rows[0]["asked_session_id"] == "c2" and rows[0]["text"] == "carry on"
    # a run that never finished (the runtime went down): kept as stopped, with a note
    rows.append({**rows[0], "id": "run_lost", "status": "running", "ended_at": None})
    store.write_text(json.dumps(rows), encoding="utf-8")

    from nanomuse.coding.service import CodingService

    again = CodingService(service)
    listed = {r["id"]: r for r in again.list_runs()}
    assert (
        listed[rows[0]["id"]]["status"] == "done"
        and listed[rows[0]["id"]]["output"] == "working on it"
    )
    lost = listed["run_lost"]
    assert lost["status"] == "stopped" and "restarted" in lost["error"] and lost["ended_at"]


def test_process_table_is_read_the_platforms_way(monkeypatch: pytest.MonkeyPatch) -> None:
    """Linux reads /proc, macOS asks ps, Windows tasklist — the same counts come out, and a
    node process is Cursor's CLI only when its arguments say so."""
    agents._PROCESS_CACHE = (0.0, {})
    monkeypatch.setattr(agents.sys, "platform", "darwin")
    ps_out = (
        "/usr/local/bin/node /usr/local/bin/cursor-agent -p hello\n"
        "/opt/homebrew/bin/codex codex exec --json\n"
        "/usr/local/bin/node /srv/app/server.js\n"
        "/usr/bin/claude claude -p\n"
        "ps ps -axo comm=,args=\n"
    )
    monkeypatch.setattr(
        agents.subprocess,
        "run",
        lambda *a, **k: type("R", (), {"stdout": ps_out, "stderr": ""})(),
    )
    assert agents.running_processes("cursor") == 1
    assert agents.running_processes("codex") == 1 and agents.running_processes("claude") == 1

    agents._PROCESS_CACHE = (0.0, {})
    monkeypatch.setattr(agents.sys, "platform", "win32")
    calls: list[list[str]] = []

    def fake_run(cmd: list[str], **k: Any) -> Any:
        calls.append(cmd)
        if cmd[0] == "tasklist":
            out = '"node.exe","100","Console","1","10 K"\n"codex.exe","101","Console","1","10 K"\n"node.exe","102","Console","1","10 K"\n'
        else:
            out = "C:\\node.exe C:\\cursor-agent\\index.js -p\r\nC:\\node.exe C:\\other\\app.js\r\n"
        return type("R", (), {"stdout": out, "stderr": ""})()

    monkeypatch.setattr(agents.subprocess, "run", fake_run)
    assert agents.running_processes("cursor") == 1 and agents.running_processes("codex") == 1
    assert calls[0][0] == "tasklist" and calls[1][0] == "powershell" and len(calls) == 2
    agents._PROCESS_CACHE = (0.0, {})


def test_offline_device_is_refused(server: tuple[TestClient, MuseService]) -> None:
    client, _ = server
    r = client.get("/api/coding/sessions?device=laptop")
    assert r.status_code in (404, 409, 502)
    assert os.environ.get("NANOMUSE_CODING_HOME")


def test_coding_clis_get_a_scrubbed_environment_plus_their_own_keys() -> None:
    from nanomuse.coding.runner import agent_env

    parent = {
        "PATH": "/usr/bin",
        "HOME": "/home/me",
        "NANOMUSE_CLOUD_TOKEN": "ours",
        "DEEPSEEK_API_KEY": "model-key",
        "OPENAI_API_KEY": "codex-key",
        "ANTHROPIC_API_KEY": "claude-key",
        "CURSOR_API_KEY": "cursor-key",
        "AWS_SECRET_ACCESS_KEY": "aws",
        "SSH_AUTH_SOCK": "/tmp/agent.sock",
    }
    codex = agent_env("codex", parent)
    assert codex["OPENAI_API_KEY"] == "codex-key" and codex["PATH"] == "/usr/bin"
    for name in (
        "NANOMUSE_CLOUD_TOKEN",
        "DEEPSEEK_API_KEY",
        "ANTHROPIC_API_KEY",
        "CURSOR_API_KEY",
        "AWS_SECRET_ACCESS_KEY",
        "SSH_AUTH_SOCK",
    ):
        assert name not in codex, name
    assert "NANOMUSE_SANDBOX" not in codex and codex["CI"] == "1" and codex["NO_COLOR"] == "1"

    claude = agent_env("claude", parent)
    assert claude["ANTHROPIC_API_KEY"] == "claude-key" and "OPENAI_API_KEY" not in claude
    assert "AWS_SECRET_ACCESS_KEY" not in claude
    bedrock = agent_env("claude", {**parent, "CLAUDE_CODE_USE_BEDROCK": "1"})
    assert bedrock["AWS_SECRET_ACCESS_KEY"] == "aws"

    cursor = agent_env("cursor", parent)
    assert cursor["CURSOR_API_KEY"] == "cursor-key" and "ANTHROPIC_API_KEY" not in cursor

    # dsh's own credentials reach it; the other agents' do not
    dsh = agent_env("dsh", parent)
    assert dsh["DEEPSEEK_API_KEY"] == "model-key"
    assert "OPENAI_API_KEY" not in dsh and "ANTHROPIC_API_KEY" not in dsh
    assert "NANOMUSE_CLOUD_TOKEN" not in dsh and dsh["CI"] == "1"
    # and it runs in the store the readers list, whatever DSH_HOME it inherited (the desktop
    # app points it at its own home)
    moved = agent_env("dsh", {**parent, "DSH_HOME": "/app/home", "NANOMUSE_CODING_HOME": "/h"})
    assert moved["DSH_HOME"] == str(Path("/h") / ".dsh")

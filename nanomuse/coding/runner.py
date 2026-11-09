"""Sending a message into a coding agent's session through its command line, and reading
the stream of what it does.

    cursor-agent -p --output-format stream-json --stream-partial-output [--resume <id>] --workspace <dir> <text>
    codex exec [resume <id>] --json --skip-git-repo-check -C <dir> <text>
    claude -p --output-format stream-json --verbose [--resume <id>] <text>
    dsh --profile headless --json [--session-id <id>] <text>

Each prints one JSON object a line; the shapes differ, so ``_normalise`` turns them into
the few kinds the apps show: ``text`` (the agent's words, cumulative), ``tool`` (something
it did), ``done`` (with the final text and the session id to resume next time), ``error``.
A run is one process; ``Run.stop()`` kills its process group.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import re
import signal
import subprocess
import sys
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from nanomuse.coding.agents import AGENTS, Session, read_session, which
from nanomuse.coding.protocol import preview
from nanomuse.coding.timeline import Timeline
from nanomuse.logger import logger
from nanomuse.tools.shell import kill_tree, scrubbed_env

# What each CLI needs from the environment beyond the scrubbed defaults: its own account
# or key variables, by prefix. Everything else that looks like a credential — our own
# NANOMUSE_* keys, the cloud SDK variables, tokens of other programs — stays out of the
# subprocess, as it does for the shell tool. Claude Code on Bedrock or Vertex needs the
# cloud credentials it is told to use.
_AGENT_ENV_PREFIXES: dict[str, tuple[str, ...]] = {
    "cursor": ("CURSOR_",),
    "codex": ("OPENAI_", "CODEX_"),
    "claude": ("ANTHROPIC_", "CLAUDE_"),
    "dsh": ("DSH_", "DEEPSEEK_"),
}
_CLAUDE_CLOUD = {
    "CLAUDE_CODE_USE_BEDROCK": ("AWS_",),
    "CLAUDE_CODE_USE_VERTEX": ("GOOGLE_", "CLOUD_ML_REGION", "GCLOUD_"),
}


def agent_env(agent: str, source: dict[str, str] | None = None) -> dict[str, str]:
    """The environment a coding CLI runs with: scrubbed, plus the variables it needs."""
    parent = dict(os.environ if source is None else source)
    env = scrubbed_env(parent)
    env.pop("NANOMUSE_SANDBOX", None)
    allowed = list(_AGENT_ENV_PREFIXES.get(agent, ()))
    if agent == "claude":
        for switch, prefixes in _CLAUDE_CLOUD.items():
            if parent.get(switch, "").strip().lower() in {"1", "true", "yes"}:
                allowed.extend(prefixes)
    for name, value in parent.items():
        if name.upper().startswith(tuple(allowed)):
            env[name] = value
    if agent == "dsh":
        # the store the readers list: a DSH_HOME inherited from elsewhere (the desktop app
        # points it at its own home) would run the chat where the list does not look
        home = parent.get("NANOMUSE_CODING_HOME") or str(Path.home())
        env["DSH_HOME"] = str(Path(home) / ".dsh")
    env["NO_COLOR"] = "1"
    env["CI"] = "1"
    return env


RUN_TIMEOUT_S = 20 * 60
OUTPUT_LIMIT = 200_000  # characters of agent text kept per run
STOP_GRACE_S = 5.0  # after a stop's SIGTERM, how long before the tree is killed

OnEvent = Callable[[dict[str, Any]], Awaitable[None]]


@dataclass
class RunEvent:
    kind: str  # text | tool | done | error | started
    text: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "text": self.text, **self.extra}


@dataclass
class Run:
    id: str
    agent: str
    session_id: str  # what was asked for ("" = new)
    workspace: str
    text: str
    started_at: float = field(default_factory=time.time)
    ended_at: float | None = None
    status: str = "running"  # running | done | failed | stopped
    output: str = ""
    result_session_id: str = ""
    resumed: bool = False
    error: str = ""
    resume_conflict: dict[str, str] | None = None
    tools: int = 0
    device: str = ""  # the other computer this ran on, when it did (the service's shadow runs)
    process: asyncio.subprocess.Process | None = None
    # the message being streamed (Cursor sends deltas, then the whole message)
    current: str = ""
    timeline: Timeline = field(default_factory=Timeline, repr=False, compare=False)
    request_id: str = ""
    request_signature: str = ""
    # the wind-down a stop() scheduled (kept so it is not collected half-way)
    _finish: asyncio.Task[None] | None = field(default=None, repr=False, compare=False)

    def commit(self) -> None:
        if self.current:
            self.output = _append(self.output, ("\n" if self.output else "") + self.current)
            self.current = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "agent": self.agent,
            "session_id": self.result_session_id or self.session_id,
            "asked_session_id": self.session_id,
            "workspace": self.workspace,
            "text": self.text,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "status": self.status,
            "output": (self.output + ("\n" + self.current if self.current else ""))[-OUTPUT_LIMIT:],
            "resumed": self.resumed,
            "error": self.error,
            **({"resume_conflict": self.resume_conflict} if self.resume_conflict else {}),
            "tools": self.tools,
            "timeline": [preview(i) for i in self.timeline.values()][-100:],
            **({"device": self.device} if self.device else {}),
        }

    def stop(self) -> bool:
        """Ask the agent to stop: SIGTERM to its process group (the agent and the helpers it
        forked). What ignores it is killed a few seconds later by :func:`_wait_exit`, which
        every path out of :func:`start_run` goes through: ``_finish`` is scheduled here so a
        stop from the API ends the run too, not only a stop from the chat that waited."""
        p = self.process
        if p is None or p.returncode is not None:
            return False
        try:
            if sys.platform != "win32":
                os.killpg(p.pid, signal.SIGTERM)
            else:
                # Windows has no process-group signal: the tree goes at once
                kill_tree(p)
        except (ProcessLookupError, PermissionError, OSError):
            return False
        self.status = "stopped"
        with contextlib.suppress(RuntimeError):  # no loop: a test calling stop() cold
            loop = asyncio.get_running_loop()
            self._finish = loop.create_task(_wait_exit(p, grace_s=STOP_GRACE_S), name="coding-stop")
        return True


def command_for(agent: str, session_id: str, workspace: str, text: str, resume: bool) -> list[str]:
    cli = which(agent)
    if not cli:
        raise FileNotFoundError(f"{AGENTS[agent]['name']} is not installed on this computer")
    if agent == "cursor":
        cmd = [cli, "-p", "--output-format", "stream-json", "--stream-partial-output", "--force"]
        if resume and session_id:
            cmd += ["--resume", session_id]
        if workspace:
            cmd += ["--workspace", workspace]
        cmd.append(text)
        return cmd
    if agent == "codex":
        cmd = [cli, "exec"]
        if resume and session_id:
            cmd += ["resume", session_id]
        # edits inside the workspace without asking; `exec` never prompts anyway
        cmd += ["--json", "--skip-git-repo-check", "-c", 'sandbox_mode="workspace-write"']
        if workspace and not (resume and session_id):
            cmd += ["-C", workspace]
        cmd.append(text)
        return cmd
    if agent == "claude":
        cmd = [
            cli,
            "-p",
            "--output-format",
            "stream-json",
            "--verbose",
            "--permission-mode",
            "acceptEdits",
        ]
        if resume and session_id:
            cmd += ["--resume", session_id]
        cmd.append(text)
        return cmd
    if agent == "dsh":
        # the harness's own one-shot runner: `dsh headless "<task>" --json` prints one
        # projected JSON object a line; `--session-id` adopts an existing session (it takes
        # its working directory from the process, so the run's cwd is what makes a resumed
        # session match its recorded one, and there is no `-C`)
        cmd = [cli, "--profile", "headless", "--json"]
        if resume and session_id:
            cmd += ["--session-id", session_id]
        cmd.append(text)
        return cmd
    raise ValueError(f"unknown agent {agent!r}")


def _normalise(agent: str, obj: dict[str, Any], run: Run) -> list[RunEvent]:
    """One line of the agent's stream → zero or more events for the apps."""
    t = str(obj.get("type") or "")
    out: list[RunEvent] = []
    if agent == "cursor":
        if t == "system" and obj.get("subtype") == "init":
            sid = str(obj.get("session_id") or obj.get("chat_id") or "")
            if sid:
                run.result_session_id = sid
            out.append(
                RunEvent("started", extra={"session_id": sid, "model": obj.get("model", "")})
            )
        elif t == "assistant":
            msg = obj.get("message") or {}
            text = _content_text(msg.get("content"))
            if text:
                # with --stream-partial-output the deltas carry `timestamp_ms`; the whole
                # message comes once more without it and replaces what the deltas built
                if obj.get("timestamp_ms") is not None:
                    run.current = _append(run.current, text)
                    out.append(RunEvent("text", text, extra={"partial": True}))
                else:
                    run.current = text
                    run.commit()
                    out.append(RunEvent("text", text, extra={"partial": False}))
        elif t == "tool_call":
            sub = str(obj.get("subtype") or "")
            call = obj.get("tool_call") or {}
            name = next(iter(call.keys()), "") if isinstance(call, dict) else ""
            if sub == "started":
                run.tools += 1
            out.append(RunEvent("tool", _brief_tool(name, call), extra={"phase": sub}))
        elif t == "result":
            run.commit()
            sid = str(obj.get("session_id") or run.result_session_id)
            run.result_session_id = sid or run.result_session_id
            final = str(obj.get("result") or "")
            if final and final not in run.output:
                run.output = _append(run.output, ("\n" if run.output else "") + final)
            ok = obj.get("subtype") in (None, "success") and not obj.get("is_error")
            out.append(
                RunEvent(
                    "done" if ok else "error",
                    final,
                    extra={"session_id": sid, "duration_ms": obj.get("duration_ms")},
                )
            )
    elif agent == "codex":
        if t == "thread.started":
            sid = str(obj.get("thread_id") or "")
            if sid:
                run.result_session_id = sid
            out.append(RunEvent("started", extra={"session_id": sid}))
        elif t == "item.completed":
            item = obj.get("item") or {}
            it = str(item.get("type") or "")
            if it == "agent_message":
                text = str(item.get("text") or "")
                if text:
                    run.output = _append(run.output, ("\n" if run.output else "") + text)
                    out.append(RunEvent("text", text))
            elif it in ("command_execution", "file_change", "mcp_tool_call", "web_search", "patch"):
                run.tools += 1
                out.append(RunEvent("tool", _codex_tool(item), extra={"phase": "completed"}))
            elif it == "reasoning":
                pass
        elif t == "item.started":
            item = obj.get("item") or {}
            if item.get("type") in (
                "command_execution",
                "file_change",
                "mcp_tool_call",
                "web_search",
            ):
                out.append(RunEvent("tool", _codex_tool(item), extra={"phase": "started"}))
        elif t == "turn.completed":
            out.append(
                RunEvent(
                    "done",
                    run.output,
                    extra={"session_id": run.result_session_id, "usage": obj.get("usage")},
                )
            )
        elif t in ("turn.failed", "error"):
            msg = obj.get("error") or obj.get("message") or ""
            if isinstance(msg, dict):
                msg = msg.get("message", "")
            out.append(RunEvent("error", str(msg)))
    elif agent == "claude":
        if t == "system" and obj.get("subtype") == "init":
            sid = str(obj.get("session_id") or "")
            if sid:
                run.result_session_id = sid
            out.append(
                RunEvent("started", extra={"session_id": sid, "model": obj.get("model", "")})
            )
        elif t == "assistant":
            msg = obj.get("message") or {}
            content = msg.get("content") if isinstance(msg, dict) else None
            if isinstance(content, list):
                for c in content:
                    if not isinstance(c, dict):
                        continue
                    if c.get("type") == "text" and c.get("text"):
                        run.output = _append(
                            run.output, ("\n" if run.output else "") + str(c["text"])
                        )
                        out.append(RunEvent("text", str(c["text"])))
                    elif c.get("type") == "tool_use":
                        run.tools += 1
                        out.append(
                            RunEvent(
                                "tool",
                                _brief_tool(str(c.get("name") or ""), c.get("input") or {}),
                                extra={"phase": "started"},
                            )
                        )
        elif t == "result":
            sid = str(obj.get("session_id") or run.result_session_id)
            run.result_session_id = sid or run.result_session_id
            final = str(obj.get("result") or "")
            if final and final not in run.output:
                run.output = _append(run.output, ("\n" if run.output else "") + final)
            ok = not obj.get("is_error")
            out.append(
                RunEvent(
                    "done" if ok else "error",
                    final,
                    extra={"session_id": sid, "duration_ms": obj.get("duration_ms")},
                )
            )
    elif agent == "dsh":
        # `dsh headless --json`: `session` opens, `status` marks the turns and steps, `text`
        # and `thinking` come from committed messages, `tool_call`/`tool_result` are the
        # tools, and the terminal `final` carries the answer (the last line, never bounded)
        if t == "session":
            sid = str(obj.get("sessionId") or "")
            if sid:
                run.result_session_id = sid
            out.append(RunEvent("started", extra={"session_id": sid, "cwd": obj.get("cwd", "")}))
        elif t == "text":
            text = str(obj.get("text") or "")
            if text:
                run.output = _append(run.output, ("\n" if run.output else "") + text)
                out.append(RunEvent("text", text))
        elif t == "tool_call":
            run.tools += 1
            out.append(
                RunEvent(
                    "tool",
                    _brief_tool(str(obj.get("tool") or ""), obj.get("input") or {}),
                    extra={"phase": "started"},
                )
            )
        elif t == "tool_result":
            out.append(
                RunEvent(
                    "tool", str(obj.get("status") or "completed"), extra={"phase": "completed"}
                )
            )
        elif t == "final":
            run.commit()
            final = str(obj.get("text") or "")
            if final and final not in run.output:
                run.output = _append(run.output, ("\n" if run.output else "") + final)
            out.append(
                RunEvent(
                    "done",
                    final or run.output,
                    extra={"session_id": run.result_session_id},
                )
            )
        elif t == "status":
            reason = obj.get("reason")
            if isinstance(reason, dict) and reason.get("kind") == "error":
                err = reason.get("error")
                msg = err.get("message", "") if isinstance(err, dict) else ""
                out.append(RunEvent("error", str(msg)))
    return out


def _content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            str(c.get("text") or "")
            for c in content
            if isinstance(c, dict) and c.get("type") == "text"
        )
    return ""


def _append(current: str, more: str) -> str:
    s = current + more
    return s if len(s) <= OUTPUT_LIMIT else s[-OUTPUT_LIMIT:]


def _brief_tool(name: str, call: Any) -> str:
    detail = ""
    if isinstance(call, dict):
        inner = call.get(name) if name in call else call
        if isinstance(inner, dict):
            args = inner.get("args") if isinstance(inner.get("args"), dict) else inner
            for k in ("command", "path", "file_path", "pattern", "query", "url"):
                if isinstance(args, dict) and args.get(k):
                    detail = str(args[k])
                    break
    label = name.replace("ToolCall", "").replace("_", " ").strip() or "tool"
    return f"{label}: {detail[:120]}" if detail else label


def _codex_tool(item: dict[str, Any]) -> str:
    it = str(item.get("type") or "")
    if it == "command_execution":
        return f"shell: {str(item.get('command') or '')[:120]}"
    if it == "file_change":
        changes = item.get("changes") or []
        paths = ", ".join(str(c.get("path") or "") for c in changes if isinstance(c, dict))[:120]
        return f"edit: {paths}" if paths else "edit"
    if it == "mcp_tool_call":
        return f"tool: {item.get('server', '')}/{item.get('tool', '')}"
    if it == "web_search":
        return f"search: {str(item.get('query') or '')[:120]}"
    return it


async def start_run(
    agent: str,
    text: str,
    session_id: str = "",
    workspace: str = "",
    on_event: OnEvent | None = None,
    timeout_s: float = RUN_TIMEOUT_S,
    run_id: str = "",
    register: Callable[[Run], None] | None = None,
    structured_events: bool = False,
) -> Run:
    """Send ``text`` into ``session_id`` of ``agent`` (a new session when empty) and follow
    it to the end. Returns the finished ``Run``; ``on_event`` sees each step as it happens.

    A Cursor IDE chat cannot be continued by the CLI: for one (``Session.resumable`` false)
    the message goes straight out as a new CLI chat in the same workspace with the last
    exchange quoted for context, and the run says ``resumed: false``; the same happens when
    a chat the store said was resumable turns out unknown to the CLI."""
    if agent not in AGENTS:
        raise ValueError(f"unknown agent {agent!r}")
    text = text.strip()
    if not text:
        raise ValueError("text is required")
    run = Run(
        id=run_id or "run_" + uuid.uuid4().hex[:8],
        agent=agent,
        session_id=session_id,
        workspace=workspace,
        text=text,
    )
    if register is not None:
        register(run)
    prior = read_session(agent, session_id) if session_id else None
    if prior is not None and not workspace:
        run.workspace = prior.workspace
    if run.workspace and not os.path.isdir(run.workspace):
        run.workspace = ""

    async def emit(ev: RunEvent) -> None:
        if on_event is not None:
            try:
                await on_event({"run": run.id, **ev.to_dict()})
            except Exception as exc:  # noqa: BLE001
                logger.debug("coding event handler failed: {}", exc)

    resume = bool(session_id)
    attempt_text = text
    if prior is not None and not prior.resumable:
        resume, attempt_text = False, _continuation(prior, text)
        await emit(
            RunEvent(
                "tool",
                "that chat was made in the IDE and cannot be reopened from the command line; starting a new one in the same workspace",
                extra={"phase": "note"},
            )
        )
    for attempt in (1, 2):
        try:
            cmd = command_for(agent, session_id, run.workspace, attempt_text, resume)
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                stdin=asyncio.subprocess.DEVNULL,
                cwd=run.workspace or None,
                start_new_session=(sys.platform != "win32"),
                env=agent_env(agent),
            )
        except FileNotFoundError as exc:
            run.status, run.error, run.ended_at = "failed", str(exc), time.time()
            await emit(RunEvent("error", run.error))
            return run
        run.process = proc
        run.resumed = resume
        saw_done = False
        terminal_failed = False
        stderr_tail = ""
        last_error = ""
        err_task: asyncio.Task[None] | None = None
        try:
            async with asyncio.timeout(timeout_s):
                assert proc.stdout is not None and proc.stderr is not None

                async def read_err(stream: asyncio.StreamReader) -> None:
                    nonlocal stderr_tail
                    async for raw in stream:
                        line = raw.decode("utf-8", "replace").rstrip()
                        if line:
                            stderr_tail = (stderr_tail + "\n" + line)[-2000:]

                err_task = asyncio.create_task(read_err(proc.stderr))
                while True:
                    # After the agent's final message we stop waiting for EOF: a helper the
                    # CLI leaves running in the background may keep our pipe open forever.
                    patience = 0.5 if proc.returncode is not None else 5
                    try:
                        raw = await asyncio.wait_for(proc.stdout.readline(), patience)
                    except TimeoutError:
                        if (
                            saw_done
                            or terminal_failed
                            or run.status == "stopped"
                            or proc.returncode is not None
                        ):
                            break
                        continue
                    if not raw:
                        break
                    line = raw.decode("utf-8", "replace").strip()
                    if not line or not line.startswith("{"):
                        continue
                    try:
                        obj = json.loads(line)
                    except ValueError:
                        continue
                    if not isinstance(obj, dict):
                        continue
                    revisions = {k: i["revision"] for k, i in run.timeline.items.items()}
                    run.timeline.feed(agent, obj)
                    for key, item in run.timeline.items.items():
                        if revisions.get(key) != item["revision"]:
                            if structured_events:
                                await emit(RunEvent("item", extra={"item": preview(item)}))
                    for ev in _normalise(agent, obj, run):
                        if ev.kind == "done":
                            saw_done = True
                        elif ev.kind == "error" and ev.text:
                            last_error = ev.text
                        if ev.kind == "error" and (
                            obj.get("type") in ("turn.failed", "result")
                            or (obj.get("type") == "status" and obj.get("phase") == "turn_end")
                        ):
                            terminal_failed = True
                        await emit(ev)
                await _wait_exit(
                    proc,
                    grace_s=15 if saw_done or terminal_failed or run.status == "stopped" else 60,
                )
                await asyncio.wait({err_task}, timeout=2)
                if not err_task.done():
                    err_task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await err_task
        except TimeoutError:
            # the agent and its helpers go (SIGTERM, then the kill after STOP_GRACE_S), our
            # ends of its pipes are released and nothing of ours keeps reading them
            run.stop()
            if err_task is not None and not err_task.done():
                err_task.cancel()
            with contextlib.suppress(BaseException):
                await asyncio.shield(_wait_exit(proc, grace_s=STOP_GRACE_S))
            run.status, run.error, run.ended_at = "failed", "the agent took too long", time.time()
            await emit(RunEvent("error", run.error))
            return run
        except asyncio.CancelledError:
            # the chat that waited for this was stopped, or the service is closing: the
            # agent and the helpers it forked do not outlive the run, and nothing of ours
            # keeps reading its pipes
            run.stop()
            if err_task is not None and not err_task.done():
                err_task.cancel()
            with contextlib.suppress(BaseException):
                await asyncio.shield(_wait_exit(proc, grace_s=STOP_GRACE_S))
            if run.status != "stopped":
                run.status = "stopped"
            run.ended_at = time.time()
            raise
        if run.status == "stopped":
            run.ended_at = time.time()
            await emit(RunEvent("error", "stopped", extra={"stopped": True}))
            return run
        rc = proc.returncode or 0
        if rc == 0 and not terminal_failed and (saw_done or run.output):
            run.status, run.ended_at = "done", time.time()
            if not saw_done:
                await emit(
                    RunEvent("done", run.output, extra={"session_id": run.result_session_id})
                )
            return run
        # A failed resume of a chat the CLI does not know: try once more as a new chat.
        diagnostic = "\n".join((stderr_tail, last_error, run.output))
        if resume and agent == "codex" and _is_resume_lock_error(diagnostic):
            run.resume_conflict = {
                "process": await asyncio.to_thread(_lock_owner, session_id),
                "continuation": _continuation(prior, text) if prior else text,
            }
            run.status, run.ended_at = "failed", time.time()
            run.error = (last_error or stderr_tail.strip() or "session writer is occupied")[:2000]
            await emit(RunEvent("error", run.error, extra={"final": True}))
            return run
        lower = diagnostic.lower()
        if attempt == 1 and resume and _looks_like_unknown_session(lower):
            attempt_text = _continuation(prior, text) if prior is not None else text
            resume = False
            run.output = ""
            await emit(
                RunEvent(
                    "tool",
                    "that chat cannot be resumed from the command line; starting a new one in the same workspace",
                    extra={"phase": "note"},
                )
            )
            continue
        run.status, run.ended_at = "failed", time.time()
        run.error = (last_error or (stderr_tail.strip().splitlines() or [f"exit {rc}"])[-1])[:300]
        await emit(RunEvent("error", run.error, extra={"final": True}))
        return run
    return run


def _is_resume_lock_error(text: str) -> bool:
    if re.search(r"permission denied|failed to (?:open|remove|inspect).*writer lock", text, re.I):
        return False
    return bool(
        re.search(
            r"(?:thread|session)[^\n]{0,160}"
            r"(?:locked|in use|already (?:open|running|registered|has an active writer)"
            r"|held by|owned by)",
            text,
            re.I,
        )
        or re.search(r"(?:writer|write|writing)[ -]lock", text, re.I)
        or re.search(
            r"(?:another|other) (?:codex )?process[^\n]{0,100}(?:thread|session|writ|lock)",
            text,
            re.I,
        )
    )


def _lock_owner(session_id: str) -> str:
    if _is_windows() or not re.fullmatch(r"[0-9a-f-]{36}", session_id, re.I):
        return ""
    home = Path(os.environ.get("NANOMUSE_CODING_HOME") or Path.home())
    root = Path(os.environ.get("CODEX_HOME") or home / ".codex")
    try:
        result = subprocess.run(
            ["lsof", "-Fpc", "--", str(root / "thread-writer-locks" / f"{session_id}.lock")],
            capture_output=True,
            timeout=2,
            check=False,
        )
        output = result.stdout.decode("utf-8", errors="replace")
        name, pid = re.search(r"^c(.+)$", output, re.M), re.search(r"^p(\d+)$", output, re.M)
        return name[1][:100] + (f" (PID {pid[1]})" if pid else "") if name else ""
    except (OSError, subprocess.TimeoutExpired):
        return ""


def _is_windows() -> bool:
    return sys.platform == "win32"


def _continuation(prior: Session, text: str) -> str:
    """The message for a fresh chat that carries on an old one: its title, the last exchange."""
    context = ""
    if prior.transcript:
        context = "\n".join(f"{m['role']}: {m['text'][:800]}" for m in prior.transcript[-2:])
    return f"Continuing an earlier chat titled {prior.title!r}.\n\nLast exchange:\n{context}\n\nNow: {text}"


async def _wait_exit(proc: asyncio.subprocess.Process, grace_s: float) -> None:
    """Wait for the CLI to exit without depending on its pipes reaching EOF (a background
    helper it leaves behind may hold them); kill it if it is still around after ``grace_s``."""
    deadline = time.monotonic() + grace_s
    while proc.returncode is None and time.monotonic() < deadline:
        await asyncio.sleep(0.1)
    if proc.returncode is None:
        # the CLI and the helpers it forked (its own process group, see start_run)
        kill_tree(proc)
        deadline = time.monotonic() + 5
        while proc.returncode is None and time.monotonic() < deadline:
            await asyncio.sleep(0.1)
    # Release our ends of the pipes now; the transport would otherwise keep them until
    # every inheritor is gone.
    transport = getattr(proc, "_transport", None)
    if transport is not None:
        with contextlib.suppress(Exception):
            transport.close()


def _looks_like_unknown_session(text: str) -> bool:
    return any(
        k in text
        for k in (
            "not found",
            "no such",
            "unknown chat",
            "could not find",
            "does not exist",
            "no conversation",
            "invalid chat",
            "no session",
        )
    )


__all__ = ["RUN_TIMEOUT_S", "Run", "RunEvent", "command_for", "start_run"]

from __future__ import annotations

import json
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from nanomuse.agent import MuseAgent
from nanomuse.config import Settings
from nanomuse.goals import GoalStore
from nanomuse.llm import MockLLM
from nanomuse.llm import budget as task_budget
from nanomuse.memory import MemoryStore
from nanomuse.schema import Function, LLMResponse, RiskLevel, Role, ToolCall, ToolResult
from nanomuse.sentinel import AuditLog, Sentinel
from nanomuse.tools import Files, Terminate, ToolCollection
from nanomuse.tools.base import BaseTool, CallAssessment
from nanomuse.ui import ApprovalDecision, ApprovalRequest, HeadlessUI


def _tc(name: str, **args: Any) -> ToolCall:
    return ToolCall(function=Function(name=name, arguments=json.dumps(args)))


class FlakySandboxFiles(Files):
    """Files tool that fails the first `fail_times` write/append calls."""

    fail_times: int = 0
    calls_made: int = 0
    on_failure: Callable[[], None] | None = None

    async def execute(
        self,
        action: str = "",
        path: str | None = None,
        content: str | None = None,
        pattern: str | None = None,
        **extra: Any,
    ) -> ToolResult:
        if action in ("write", "append"):
            self.calls_made += 1
            if self.calls_made <= self.fail_times:
                if self.on_failure is not None:
                    self.on_failure()
                return ToolResult.fail(f"transient write failure #{self.calls_made}")
        return await super().execute(
            action=action, path=path, content=content, pattern=pattern, **extra
        )


class FlakyOutwardTool(BaseTool):
    name: str = "send_email"
    description: str = "send an email"
    risk: RiskLevel = RiskLevel.SENSITIVE
    calls_made: int = 0

    def assess(self, args: dict[str, Any]) -> CallAssessment:
        return CallAssessment(
            risk=RiskLevel.SENSITIVE,
            egress=True,
            egress_target="example.com",
            summary="send_email to bob@example.com",
        )

    async def execute(self, **_: Any) -> ToolResult:
        self.calls_made += 1
        return ToolResult.fail("smtp timeout")


class RecordingUI(HeadlessUI):
    def __init__(self, *, approve: bool = True) -> None:
        super().__init__(approve=approve)
        self.approvals: list[ApprovalRequest] = []

    async def ask_approval(self, request: ApprovalRequest) -> ApprovalDecision:
        self.approvals.append(request)
        return await super().ask_approval(request)


def _make_agent(
    settings: Settings,
    script: list[LLMResponse],
    extra_tools: list[BaseTool],
    ui: RecordingUI | None = None,
) -> tuple[MuseAgent, MockLLM, RecordingUI, AuditLog]:
    ui = ui or RecordingUI(approve=True)
    memory = MemoryStore(settings.memory_db)
    goals = GoalStore(settings.goals_db)
    tools = ToolCollection(Terminate(), *extra_tools)
    audit = AuditLog(settings.audit_file)
    sentinel = Sentinel(settings.sentinel, audit, ui)
    llm = MockLLM(script)
    agent = MuseAgent(settings, llm, tools, sentinel, ui, audit, memory=memory, goals=goals)
    return agent, llm, ui, audit


def _read_audit(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


async def test_sandbox_idempotent_write_retries_once_and_reports(settings: Settings) -> None:
    files = FlakySandboxFiles(workspace=settings.agent.workspace, fail_times=1)
    script = [
        LLMResponse(tool_calls=[_tc("files", action="write", path="report.md", content="ok")]),
        LLMResponse(tool_calls=[_tc("terminate", status="success", summary="Wrote report.md.")]),
    ]
    agent, llm, _, audit = _make_agent(settings, script, [files])

    final = await agent.run("write report.md")

    assert files.calls_made == 2
    assert (settings.agent.workspace / "report.md").read_text(encoding="utf-8") == "ok"
    assert "retried 1 time(s)" in final
    assert "succeeded" in final
    assert "transient write failure #1" in final

    tool_msgs = [m for m in llm.calls[1]["messages"] if m.role == Role.TOOL]
    assert tool_msgs and "retried 1 time(s) inside sandbox" in tool_msgs[0].content

    events = [e for e in _read_audit(audit.path) if e.get("event") == "tool_call"]
    file_events = [e for e in events if e.get("tool") == "files"]
    assert len(file_events) == 2
    assert [e["ok"] for e in file_events] == [False, True]


async def test_sandbox_write_stops_after_max_two_retries(settings: Settings) -> None:
    files = FlakySandboxFiles(workspace=settings.agent.workspace, fail_times=10)
    script = [
        LLMResponse(tool_calls=[_tc("files", action="write", path="stuck.md", content="x")]),
        LLMResponse(content="Could not write stuck.md."),
    ]
    agent, _, _, audit = _make_agent(settings, script, [files])

    final = await agent.run("write stuck.md")

    # 1 initial attempt + 2 retries = 3 total attempts
    assert files.calls_made == 3
    assert "retried 2 time(s)" in final
    assert "transient write failure #3" in final

    events = [
        e
        for e in _read_audit(audit.path)
        if e.get("event") == "tool_call" and e.get("tool") == "files"
    ]
    assert len(events) == 3
    assert all(e["ok"] is False for e in events)


async def test_non_idempotent_append_never_retries(settings: Settings) -> None:
    files = FlakySandboxFiles(workspace=settings.agent.workspace, fail_times=1)
    script = [
        LLMResponse(tool_calls=[_tc("files", action="append", path="log.md", content="line\n")]),
        LLMResponse(content="Append failed."),
    ]
    agent, _, _, audit = _make_agent(settings, script, [files])

    final = await agent.run("append log.md")

    assert files.calls_made == 1
    assert "[Retry summary]" not in final
    events = [
        e
        for e in _read_audit(audit.path)
        if e.get("event") == "tool_call" and e.get("tool") == "files"
    ]
    assert len(events) == 1


async def test_outside_sandbox_write_asks_user_and_never_retries(
    settings: Settings, tmp_path: Path
) -> None:
    outside = tmp_path / "outside.txt"
    files = FlakySandboxFiles(workspace=settings.agent.workspace, fail_times=1)
    ui = RecordingUI(approve=False)
    script = [
        LLMResponse(tool_calls=[_tc("files", action="write", path=str(outside), content="secret")]),
        LLMResponse(content="Blocked outside write."),
    ]
    agent, _, _, audit = _make_agent(settings, script, [files], ui=ui)

    final = await agent.run("write outside")

    assert len(ui.approvals) == 1
    assert files.calls_made == 0
    assert "[Retry summary]" not in final
    events = [
        e
        for e in _read_audit(audit.path)
        if e.get("event") == "tool_call" and e.get("tool") == "files"
    ]
    assert len(events) == 1
    assert events[0]["decision"] == "deny"


async def test_high_risk_sensitive_tool_never_retries(settings: Settings) -> None:
    mailer = FlakyOutwardTool()
    ui = RecordingUI(approve=True)
    script = [
        LLMResponse(tool_calls=[_tc("send_email")]),
        LLMResponse(content="Email failed."),
    ]
    agent, _, _, audit = _make_agent(settings, script, [mailer], ui=ui)

    final = await agent.run("send email")

    assert len(ui.approvals) == 1
    assert mailer.calls_made == 1
    assert "[Retry summary]" not in final
    events = [
        e
        for e in _read_audit(audit.path)
        if e.get("event") == "tool_call" and e.get("tool") == "send_email"
    ]
    assert len(events) == 1


@pytest.mark.parametrize("kind", ["file", "parent", "dangling", "hardlink", "fifo"])
async def test_linked_or_special_file_writes_never_retry(settings: Settings, kind: str) -> None:
    ws = settings.agent.workspace
    target = ws / "report.md"
    other = ws / "other.md"
    other.write_text("keep", encoding="utf-8")
    try:
        if kind == "parent":
            folder = ws / "actual"
            folder.mkdir()
            (ws / "linked").symlink_to(folder, target_is_directory=True)
            target = ws / "linked" / "report.md"
        elif kind in ("file", "dangling"):
            target.symlink_to(other if kind == "file" else ws / "missing.md")
        elif kind == "hardlink":
            os.link(other, target)
        elif hasattr(os, "mkfifo"):
            os.mkfifo(target)
        else:
            pytest.skip("FIFOs are unavailable on this platform")
    except OSError as exc:
        pytest.skip(f"link creation unavailable: {exc}")
    files = FlakySandboxFiles(workspace=ws, fail_times=10)
    script = [
        LLMResponse(tool_calls=[_tc("files", action="write", path=str(target), content="new")]),
        LLMResponse(content="Write failed."),
    ]
    agent, _, _, _ = _make_agent(settings, script, [files])
    await agent.run("write report")
    assert files.calls_made == 1
    assert other.read_text(encoding="utf-8") == "keep"


@pytest.mark.parametrize("change", ["file", "parent", "missing", "in_place"])
async def test_retry_does_not_overwrite_a_replacement_target(
    settings: Settings, change: str
) -> None:
    ws = settings.agent.workspace
    folder = ws / "reports"
    folder.mkdir()
    target = folder / "report.md"
    if change != "missing":
        target.write_text("original", encoding="utf-8")

    def replace() -> None:
        if change == "parent":
            folder.rename(ws / "previous-reports")
            folder.mkdir()
        elif change == "file":
            target.rename(folder / "previous.md")
        target.write_text("another writer", encoding="utf-8")

    files = FlakySandboxFiles(workspace=ws, fail_times=1, on_failure=replace)
    script = [
        LLMResponse(tool_calls=[_tc("files", action="write", path=str(target), content="new")]),
        LLMResponse(content="Write failed."),
    ]
    agent, _, _, _ = _make_agent(settings, script, [files])
    await agent.run("write report")
    assert files.calls_made == 1
    assert target.read_text(encoding="utf-8") == "another writer"


@pytest.mark.parametrize("change", ["replace", "symlink"])
async def test_retry_rechecks_target_after_approval(settings: Settings, change: str) -> None:
    ws = settings.agent.workspace
    target = ws / "report.md"
    target.write_text("original", encoding="utf-8")
    other = ws / "other.md"
    other.write_text("keep", encoding="utf-8")
    if change == "symlink":
        probe = ws / "probe"
        try:
            probe.symlink_to(other)
            probe.unlink()
        except OSError as exc:
            pytest.skip(f"symlink creation unavailable: {exc}")

    class ReplacingUI(RecordingUI):
        async def ask_approval(self, request: ApprovalRequest) -> ApprovalDecision:
            decision = await super().ask_approval(request)
            if len(self.approvals) == 2:
                target.rename(ws / "previous.md")
                if change == "symlink":
                    target.symlink_to(other)
                else:
                    target.write_text("keep", encoding="utf-8")
            return decision

    settings.sentinel.mode = "strict"
    ui = ReplacingUI()
    files = FlakySandboxFiles(workspace=ws, fail_times=1)
    script = [
        LLMResponse(tool_calls=[_tc("files", action="write", path=str(target), content="new")]),
        LLMResponse(content="Write failed."),
    ]
    agent, _, _, audit = _make_agent(settings, script, [files], ui)
    await agent.run("write report")
    assert len(ui.approvals) == 2
    assert files.calls_made == 1
    assert target.read_text(encoding="utf-8") == "keep"
    events = [e for e in _read_audit(audit.path) if e.get("tool") == "files"]
    assert [e["decision"] for e in events] == ["allow", "deny"]


async def test_blocked_workspace_write_never_retries(settings: Settings) -> None:
    settings.sentinel.deny_tools = ["files"]
    files = FlakySandboxFiles(workspace=settings.agent.workspace, fail_times=1)
    agent, _, _, audit = _make_agent(
        settings,
        [
            LLMResponse(tool_calls=[_tc("files", action="write", path="x.md", content="x")]),
            LLMResponse(content="Blocked."),
        ],
        [files],
    )
    await agent.run("write x")
    assert files.calls_made == 0
    assert len([e for e in _read_audit(audit.path) if e.get("tool") == "files"]) == 1


async def test_retry_obeys_task_budget(settings: Settings) -> None:
    settings.agent.budget.max_seconds = 600

    def exhaust_budget() -> None:
        budget = task_budget.current()
        assert budget is not None
        budget.started -= 601

    files = FlakySandboxFiles(
        workspace=settings.agent.workspace, fail_times=1, on_failure=exhaust_budget
    )
    agent, _, _, _ = _make_agent(
        settings,
        [LLMResponse(tool_calls=[_tc("files", action="write", path="x.md", content="x")])],
        [files],
    )
    await agent.run("write x")
    assert files.calls_made == 1
    assert agent.last_budget["stopped"] == "time"


async def test_budget_stop_reports_previous_retries(settings: Settings) -> None:
    settings.agent.budget.max_seconds = 600

    def exhaust_budget() -> None:
        budget = task_budget.current()
        assert budget is not None
        budget.started -= 601

    files = FlakySandboxFiles(workspace=settings.agent.workspace, fail_times=1)
    later = FlakySandboxFiles(
        name="later_files",
        workspace=settings.agent.workspace,
        fail_times=1,
        on_failure=exhaust_budget,
    )
    agent, _, ui, _ = _make_agent(
        settings,
        [
            LLMResponse(tool_calls=[_tc("files", action="write", path="x.md", content="x")]),
            LLMResponse(tool_calls=[_tc("later_files", action="write", path="y.md", content="y")]),
        ],
        [files, later],
    )
    final = await agent.run("write two reports")
    assert agent.last_budget["stopped"] == "time"
    assert files.calls_made == 2 and later.calls_made == 1
    assert final.count("[Retry summary]") == 1
    assert [text for kind, text in ui.events if kind == "assistant"][-1] == final

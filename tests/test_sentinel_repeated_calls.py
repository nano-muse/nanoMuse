from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, ClassVar

import pytest

from nanomuse.config import SentinelRule, SentinelSettings
from nanomuse.schema import Function, RiskLevel, ToolCall, ToolResult
from nanomuse.sentinel import AuditLog, Sentinel
from nanomuse.tools.base import BaseTool, CallAssessment
from nanomuse.ui import ApprovalDecision, ApprovalRequest, HeadlessUI


class RecordingUI(HeadlessUI):
    def __init__(self) -> None:
        super().__init__()
        self.requests: list[ApprovalRequest] = []

    async def ask_approval(self, request: ApprovalRequest) -> ApprovalDecision:
        self.requests.append(request)
        return ApprovalDecision(approved=self.approve)


class ExampleTool(BaseTool):
    name: str = "send_email"
    description: str = "test tool"
    parameters: dict[str, Any] = {"type": "object", "properties": {}}
    risk: RiskLevel = RiskLevel.SENSITIVE
    calls: list[dict[str, Any]] = []
    fail: bool = False

    def assess(self, args: dict[str, Any]) -> CallAssessment:
        return CallAssessment(risk=self.risk, summary="send message")

    async def execute(self, **kwargs: Any) -> ToolResult:
        self.calls.append(kwargs)
        return ToolResult.fail("failed") if self.fail else ToolResult(output="sent")


def call(tool: ExampleTool, **args: Any) -> ToolCall:
    return ToolCall(function=Function(name=tool.name, arguments=json.dumps(args)))


@pytest.fixture
def setup(tmp_path: Path) -> tuple[Sentinel, RecordingUI]:
    ui = RecordingUI()
    return Sentinel(SentinelSettings(mode="auto"), AuditLog(tmp_path / "audit.jsonl"), ui), ui


@pytest.mark.parametrize("name", ["send_email", "mail__send", "device__sms_send"])
async def test_repeats_ask_even_in_auto_and_require_approval(
    setup: tuple[Sentinel, RecordingUI], name: str
) -> None:
    gate, ui = setup
    tool = ExampleTool(name=name)
    gate.grants.add(name, None, "session")
    token = gate.begin_task(conversation="chat")
    try:
        assert (await gate.guard(call(tool, body="one", step="first"), tool)).ok
        assert not ui.requests
        assert (await gate.guard(call(tool, step="second", body="one"), tool)).ok
        assert ui.requests[-1].warnings == [
            "the same call already ran in this conversation: send message"
        ]
        assert ui.requests[-1].grant_options == ["once"]
        assert (await gate.guard(call(tool, body="different"), tool)).ok
        assert len(ui.requests) == 1
        ui.approve = False
        assert not (await gate.guard(call(tool, body="one"), tool)).ok
        assert len(tool.calls) == 3
        assert all("step" not in args for args in tool.calls)
    finally:
        gate.end_task(token)


async def test_failure_is_not_recorded(setup: tuple[Sentinel, RecordingUI]) -> None:
    gate, ui = setup
    tool = ExampleTool(fail=True)
    assert not (await gate.guard(call(tool, body="one"), tool)).ok
    tool.fail = False
    assert (await gate.guard(call(tool, body="one"), tool)).ok
    assert not ui.requests
    assert (await gate.guard(call(tool, body="one"), tool)).ok
    assert len(ui.requests) == 1


async def test_conversation_isolation_and_clear(setup: tuple[Sentinel, RecordingUI]) -> None:
    gate, ui = setup
    tool = ExampleTool()
    for conversation in ("first", "second", "first"):
        token = gate.begin_task(conversation=conversation)
        try:
            assert (await gate.guard(call(tool, body="one"), tool)).ok
        finally:
            gate.end_task(token)
    assert len(ui.requests) == 1
    gate.end_conversation("first")
    token = gate.begin_task(conversation="first")
    try:
        assert (await gate.guard(call(tool, body="one"), tool)).ok
        assert len(ui.requests) == 1
    finally:
        gate.end_task(token)
    token = gate.begin_task(conversation="second")
    try:
        assert (await gate.guard(call(tool, body="one"), tool)).ok
        assert len(ui.requests) == 2
    finally:
        gate.end_task(token)


async def test_non_sensitive_calls_are_not_tracked(setup: tuple[Sentinel, RecordingUI]) -> None:
    gate, ui = setup
    tool = ExampleTool(risk=RiskLevel.MODERATE)
    assert (await gate.guard(call(tool, body="one"), tool)).ok
    assert (await gate.guard(call(tool, body="one"), tool)).ok
    tool.risk = RiskLevel.SENSITIVE
    assert (await gate.guard(call(tool, body="one"), tool)).ok
    assert not ui.requests


async def test_full_arguments_and_tool_name(setup: tuple[Sentinel, RecordingUI]) -> None:
    gate, ui = setup
    email = ExampleTool()
    device = ExampleTool(name="device__sms_send")
    assert (await gate.guard(call(email, payload={"a": 1, "b": "中文"}), email)).ok
    assert (await gate.guard(call(email, payload={"b": "中文", "a": 2}), email)).ok
    assert (await gate.guard(call(device, payload={"a": 1, "b": "中文"}), device)).ok
    assert not ui.requests
    assert (await gate.guard(call(email, payload={"b": "中文", "a": 1}), email)).ok
    assert len(ui.requests) == 1


async def test_declined_first_call_is_not_recorded(tmp_path: Path) -> None:
    ui = RecordingUI()
    ui.approve = False
    gate = Sentinel(SentinelSettings(mode="ask"), AuditLog(tmp_path / "audit.jsonl"), ui)
    tool = ExampleTool()
    assert not (await gate.guard(call(tool, body="one"), tool)).ok
    assert not tool.calls
    ui.approve = True
    assert (await gate.guard(call(tool, body="one"), tool)).ok
    assert not ui.requests[-1].warnings
    assert (await gate.guard(call(tool, body="one"), tool)).ok
    assert ui.requests[-1].warnings == [
        "the same call already ran in this conversation: send message"
    ]


async def test_waiting_call_rechecks_after_prior_execution(tmp_path: Path) -> None:
    execution_started = asyncio.Event()
    finish_execution = asyncio.Event()
    approval_started = asyncio.Event()
    finish_approval = asyncio.Event()
    repeat_assessed = asyncio.Event()

    class DelayedTool(ExampleTool):
        assessments: ClassVar[int] = 0

        def assess(self, args: dict[str, Any]) -> CallAssessment:
            assessment = super().assess(args)
            if args["body"] == "hold":
                assessment.warnings.append("hold approval")
            else:
                type(self).assessments += 1
                if self.assessments == 2:
                    repeat_assessed.set()
            return assessment

        async def execute(self, **kwargs: Any) -> ToolResult:
            if kwargs["body"] == "original" and not execution_started.is_set():
                execution_started.set()
                await finish_execution.wait()
            return await super().execute(**kwargs)

    class DelayedUI(RecordingUI):
        async def ask_approval(self, request: ApprovalRequest) -> ApprovalDecision:
            if "hold approval" in request.warnings:
                approval_started.set()
                await finish_approval.wait()
            return await super().ask_approval(request)

    ui = DelayedUI()
    gate = Sentinel(SentinelSettings(mode="auto"), AuditLog(tmp_path / "audit.jsonl"), ui)
    tool = DelayedTool()
    first = asyncio.create_task(gate.guard(call(tool, body="original"), tool))
    await asyncio.wait_for(execution_started.wait(), 1)
    blocker = asyncio.create_task(gate.guard(call(tool, body="hold"), tool))
    await asyncio.wait_for(approval_started.wait(), 1)
    repeat = asyncio.create_task(gate.guard(call(tool, body="original"), tool))
    await asyncio.wait_for(repeat_assessed.wait(), 1)
    finish_execution.set()
    assert (await asyncio.wait_for(first, 1)).ok
    finish_approval.set()
    assert (await asyncio.wait_for(blocker, 1)).ok
    assert (await asyncio.wait_for(repeat, 1)).ok
    assert ui.requests[-1].warnings == [
        "the same call already ran in this conversation: send message"
    ]


async def test_explicit_allow_rule_keeps_existing_warning_exception(tmp_path: Path) -> None:
    ui = RecordingUI()
    settings = SentinelSettings(
        mode="auto", rules=[SentinelRule(tool="send_email", action="allow")]
    )
    gate = Sentinel(settings, AuditLog(tmp_path / "audit.jsonl"), ui)
    tool = ExampleTool()
    assert (await gate.guard(call(tool, body="one"), tool)).ok
    assert (await gate.guard(call(tool, body="one"), tool)).ok
    assert not ui.requests
    assert "the same call already ran" in gate.audit.tail()[-1]["reasons"][-1]


@pytest.mark.parametrize("first_outcome", ["success", "failure", "cancel"])
async def test_identical_calls_wait_for_execution_outcome(
    tmp_path: Path, first_outcome: str
) -> None:
    started = asyncio.Event()
    finish = asyncio.Event()
    twin_assessed = asyncio.Event()
    executions: list[str] = []

    class DelayedTool(ExampleTool):
        assessments: ClassVar[int] = 0

        def assess(self, args: dict[str, Any]) -> CallAssessment:
            type(self).assessments += 1
            if self.assessments == 2:
                twin_assessed.set()
            return super().assess(args)

        async def execute(self, **kwargs: Any) -> ToolResult:
            executions.append(kwargs["body"])
            if len(executions) == 1:
                started.set()
                await finish.wait()
                if first_outcome == "failure":
                    return ToolResult.fail("did not execute")
            return ToolResult(output="sent")

    ui = RecordingUI()
    ui.approve = False
    gate = Sentinel(SentinelSettings(mode="auto"), AuditLog(tmp_path / "audit.jsonl"), ui)
    tool = DelayedTool()
    token = gate.begin_task(conversation="chat")
    try:
        first = asyncio.create_task(gate.guard(call(tool, body="same"), tool))
        await asyncio.wait_for(started.wait(), 1)
        twin = asyncio.create_task(gate.guard(call(tool, body="same"), tool))
        await asyncio.wait_for(twin_assessed.wait(), 1)
        assert executions == ["same"]
        assert not ui.requests
        if first_outcome == "cancel":
            first.cancel()
            with pytest.raises(asyncio.CancelledError):
                await first
        else:
            finish.set()
            assert (await asyncio.wait_for(first, 1)).ok == (first_outcome == "success")
        result = await asyncio.wait_for(twin, 1)
        if first_outcome == "failure":
            assert result.ok
            assert executions == ["same", "same"]
            assert not ui.requests
        else:
            assert not result.ok
            assert executions == ["same"]
            assert len(ui.requests) == 1
            assert ui.requests[0].grant_options == ["once"]
            warning = ui.requests[0].warnings[0]
            assert ("outcome is unknown" in warning) == (first_outcome == "cancel")
    finally:
        gate.end_task(token)


async def test_different_sensitive_calls_do_not_wait_for_execution(tmp_path: Path) -> None:
    started = asyncio.Event()
    finish = asyncio.Event()

    class DelayedTool(ExampleTool):
        async def execute(self, **kwargs: Any) -> ToolResult:
            if kwargs["body"] == "first":
                started.set()
                await finish.wait()
            return await super().execute(**kwargs)

    ui = RecordingUI()
    gate = Sentinel(SentinelSettings(mode="auto"), AuditLog(tmp_path / "audit.jsonl"), ui)
    tool = DelayedTool()
    first = asyncio.create_task(gate.guard(call(tool, body="first"), tool))
    try:
        await asyncio.wait_for(started.wait(), 1)
        assert (await asyncio.wait_for(gate.guard(call(tool, body="other"), tool), 1)).ok
        assert not ui.requests
    finally:
        finish.set()
        await asyncio.wait_for(first, 1)


async def test_cancelling_a_queued_twin_does_not_mark_an_unknown_execution(tmp_path: Path) -> None:
    started = asyncio.Event()
    finish = asyncio.Event()
    twin_assessed = asyncio.Event()

    class DelayedTool(ExampleTool):
        assessments: ClassVar[int] = 0

        def assess(self, args: dict[str, Any]) -> CallAssessment:
            type(self).assessments += 1
            if self.assessments == 2:
                twin_assessed.set()
            return super().assess(args)

        async def execute(self, **kwargs: Any) -> ToolResult:
            self.calls.append(kwargs)
            if len(self.calls) == 1:
                started.set()
                await finish.wait()
                return ToolResult.fail("did not execute")
            return ToolResult(output="sent")

    ui = RecordingUI()
    gate = Sentinel(SentinelSettings(mode="auto"), AuditLog(tmp_path / "audit.jsonl"), ui)
    tool = DelayedTool()
    first = asyncio.create_task(gate.guard(call(tool, body="same"), tool))
    await asyncio.wait_for(started.wait(), 1)
    twin = asyncio.create_task(gate.guard(call(tool, body="same"), tool))
    await asyncio.wait_for(twin_assessed.wait(), 1)
    twin.cancel()
    with pytest.raises(asyncio.CancelledError):
        await twin
    finish.set()
    assert not (await asyncio.wait_for(first, 1)).ok
    assert (await gate.guard(call(tool, body="same"), tool)).ok
    assert len(tool.calls) == 2
    assert not ui.requests

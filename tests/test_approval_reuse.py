from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from nanomuse.config import SentinelSettings
from nanomuse.schema import Function, RiskLevel, ToolCall, ToolResult
from nanomuse.sentinel import AuditLog, Sentinel
from nanomuse.sentinel.grants import GrantStore
from nanomuse.tools.base import BaseTool, CallAssessment
from nanomuse.ui import ApprovalDecision, ApprovalRequest, ApprovalScope, HeadlessUI


class Probe(BaseTool):
    name: str = "approval_probe"
    description: str = "Record the approved arguments without external effects."

    def assess(self, args: dict[str, Any]) -> CallAssessment:
        return CallAssessment(
            risk=RiskLevel.MODERATE,
            summary="Record arguments",
            target=args.get("target"),
            egress=bool(args.get("host")),
            egress_target=args.get("host"),
            warnings=["requires individual approval"] if args.get("warning") else [],
        )

    async def execute(self, **args: Any) -> ToolResult:
        return ToolResult(output=json.dumps(args))


def call(**args: Any) -> ToolCall:
    return ToolCall(function=Function(name="approval_probe", arguments=json.dumps(args)))


class HeldApprovalUI(HeadlessUI):
    """Keep the first card pending while another call reaches the gate."""

    def __init__(self, scope: ApprovalScope = "conversation", approved: bool = True) -> None:
        super().__init__()
        self.scope = scope
        self.approved = approved
        self.requests: list[ApprovalRequest] = []
        self.shown = asyncio.Event()
        self.release = asyncio.Event()

    async def ask_approval(self, request: ApprovalRequest) -> ApprovalDecision:
        self.requests.append(request)
        if len(self.requests) == 1:
            self.shown.set()
            await self.release.wait()
        return ApprovalDecision(approved=self.approved, scope=self.scope)


def gate_for(tmp_path: Path, ui: HeadlessUI) -> Sentinel:
    return Sentinel(
        SentinelSettings(always_ask_tools=["approval_probe"]),
        AuditLog(tmp_path / "audit.jsonl"),
        ui,
        persistent_approvals_file=tmp_path / "approvals.json",
    )


def test_same_capability_in_other_conversations_keeps_each_permission() -> None:
    store = GrantStore()
    first = store.add("tasks__list", None, "conversation", "chat-a")
    second = store.add("tasks__list", None, "conversation", "chat-b")
    assert store.match("tasks__list", "chat-a") is first
    assert store.match("tasks__list", "chat-b") is second
    assert store.match("tasks__list", "chat-c") is None

    store.end_conversation("chat-a")
    assert store.match("tasks__list", "chat-a") is None
    assert store.match("tasks__list", "chat-b") is second
    assert store.revoke("tasks__list")
    assert store.match("tasks__list", "chat-b") is None


@pytest.mark.parametrize("scope", ["24h", "always"])
def test_session_replacement_cannot_resurrect_a_durable_permission(
    tmp_path: Path, scope: str
) -> None:
    path = tmp_path / "approvals.json"
    store = GrantStore(path)
    store.add("tasks__list", None, scope)
    store.add("tasks__list", None, "session")
    grant = store.match("tasks__list")
    assert grant is not None and grant.scope == "session"
    assert GrantStore(path).match("tasks__list") is None


def test_conversation_permission_does_not_replace_a_durable_permission(tmp_path: Path) -> None:
    path = tmp_path / "approvals.json"
    store = GrantStore(path)
    durable = store.add("tasks__list", None, "always")
    store.add("tasks__list", None, "conversation", "chat-a")
    assert store.match("tasks__list", "chat-b") is durable
    assert GrantStore(path).match("tasks__list") is not None


@pytest.mark.parametrize(
    ("scope", "expected_cards"),
    [("once", 2), ("conversation", 1), ("session", 1), ("24h", 1), ("always", 1)],
)
async def test_concurrent_calls_recheck_the_permission_after_the_first_answer(
    tmp_path: Path, scope: ApprovalScope, expected_cards: int
) -> None:
    ui = HeldApprovalUI(scope)
    gate = gate_for(tmp_path, ui)
    token = gate.begin_task("List tasks", conversation="chat-a")
    try:
        first = asyncio.create_task(gate.guard(call(), Probe()))
        await ui.shown.wait()
        second = asyncio.create_task(gate.guard(call(), Probe()))
        await asyncio.sleep(0)
        assert len(ui.requests) == 1, "only one card for this tool should be pending"
        ui.release.set()
        assert all(result.ok for result in await asyncio.gather(first, second))
        assert len(ui.requests) == expected_cards
    finally:
        gate.end_task(token)


async def test_concurrent_different_programs_reuse_the_conversation_tool_permission(
    tmp_path: Path,
) -> None:
    ui = HeldApprovalUI()
    gate = gate_for(tmp_path, ui)
    token = gate.begin_task("Inspect files", conversation="chat-a")
    try:
        first = asyncio.create_task(gate.guard(call(target="head"), Probe()))
        await ui.shown.wait()
        second = asyncio.create_task(gate.guard(call(target="wc"), Probe()))
        await asyncio.sleep(0)
        ui.release.set()
        assert all(result.ok for result in await asyncio.gather(first, second))
        assert len(ui.requests) == 1
    finally:
        gate.end_task(token)


@pytest.mark.parametrize("second_args", [{"host": "other.example"}, {"warning": True}])
async def test_waiting_call_cannot_reuse_a_different_destination_or_bypass_warnings(
    tmp_path: Path, second_args: dict[str, Any]
) -> None:
    ui = HeldApprovalUI("session")
    gate = gate_for(tmp_path, ui)
    first = asyncio.create_task(gate.guard(call(host="first.example"), Probe()))
    await ui.shown.wait()
    second = asyncio.create_task(gate.guard(call(**second_args), Probe()))
    await asyncio.sleep(0)
    ui.release.set()
    assert all(result.ok for result in await asyncio.gather(first, second))
    assert len(ui.requests) == 2
    if second_args.get("warning"):
        assert ui.requests[-1].grant_options == ["once"]


async def test_warning_calls_each_require_their_own_answer(tmp_path: Path) -> None:
    ui = HeldApprovalUI("always")
    gate = gate_for(tmp_path, ui)
    gate.grants.add("approval_probe", None, "always")
    first = asyncio.create_task(gate.guard(call(warning=True), Probe()))
    await ui.shown.wait()
    second = asyncio.create_task(gate.guard(call(warning=True), Probe()))
    await asyncio.sleep(0)
    ui.release.set()
    assert all(result.ok for result in await asyncio.gather(first, second))
    assert len(ui.requests) == 2
    assert all(request.grant_options == ["once"] for request in ui.requests)


async def test_waiting_call_rechecks_new_taint_before_auto_mode_can_skip(tmp_path: Path) -> None:
    ui = HeldApprovalUI("once")
    gate = gate_for(tmp_path, ui)
    gate.settings.mode = "auto"
    token = gate.begin_task("Check a report", conversation="chat-a")
    try:
        first = asyncio.create_task(gate.guard(call(warning=True), Probe()))
        await ui.shown.wait()
        second = asyncio.create_task(gate.guard(call(host="outside.example"), Probe()))
        await asyncio.sleep(0)
        gate.taint()
        ui.release.set()
        assert all(result.ok for result in await asyncio.gather(first, second))
        assert len(ui.requests) == 2
        assert any("private data" in reason for reason in ui.requests[-1].reasons)
    finally:
        gate.end_task(token)


async def test_waiting_call_rechecks_deny_policy_before_using_new_grant(tmp_path: Path) -> None:
    ui = HeldApprovalUI("session")
    gate = gate_for(tmp_path, ui)
    first = asyncio.create_task(gate.guard(call(), Probe()))
    await ui.shown.wait()
    second = asyncio.create_task(gate.guard(call(), Probe()))
    await asyncio.sleep(0)
    gate.settings.deny_tools = ["approval_probe"]
    ui.release.set()
    results = await asyncio.gather(first, second)
    assert results[0].ok and not results[1].ok
    assert len(ui.requests) == 1


async def test_other_conversations_and_revocation_still_require_an_answer(tmp_path: Path) -> None:
    ui = HeldApprovalUI()
    ui.release.set()
    gate = gate_for(tmp_path, ui)
    for conversation in ("chat-a", "chat-b", "chat-a", "chat-b"):
        token = gate.begin_task("List tasks", conversation=conversation)
        try:
            assert (await gate.guard(call(), Probe())).ok
        finally:
            gate.end_task(token)
    assert len(ui.requests) == 2
    assert gate.revoke("approval_probe")
    ui.approved = False
    token = gate.begin_task("List tasks", conversation="chat-a")
    try:
        assert not (await gate.guard(call(), Probe())).ok
        assert len(ui.requests) == 3
    finally:
        gate.end_task(token)


@pytest.mark.parametrize("denied", [False, True])
async def test_another_chat_does_not_wait_for_an_unanswered_card(
    tmp_path: Path, denied: bool
) -> None:
    ui = HeldApprovalUI()
    gate = gate_for(tmp_path, ui)
    gate.grants.add("approval_probe", None, "conversation", "chat-b")
    token = gate.begin_task("First chat", conversation="chat-a")
    first = asyncio.create_task(gate.guard(call(), Probe()))
    gate.end_task(token)
    await ui.shown.wait()
    token = gate.begin_task("Other chat", conversation="chat-b")
    try:
        if denied:
            gate.settings.deny_tools = ["approval_probe"]
        result = await asyncio.wait_for(gate.guard(call(), Probe()), timeout=1)
        assert result.ok is not denied
        assert len(ui.requests) == 1
    finally:
        gate.end_task(token)
        ui.release.set()
        await first


async def test_idle_locks_do_not_accumulate_for_standalone_runs(tmp_path: Path) -> None:
    ui = HeldApprovalUI("once")
    ui.release.set()
    gate = gate_for(tmp_path, ui)
    for _ in range(20):
        token = gate.begin_task("One standalone run")
        try:
            assert (await gate.guard(call(), Probe())).ok
        finally:
            gate.end_task(token)
    assert not gate._approval_locks


async def test_cancelling_pending_approval_does_not_leave_the_tool_locked(tmp_path: Path) -> None:
    ui = HeldApprovalUI("once", approved=False)
    gate = gate_for(tmp_path, ui)
    first = asyncio.create_task(gate.guard(call(), Probe()))
    await ui.shown.wait()
    second = asyncio.create_task(gate.guard(call(), Probe()))
    await asyncio.sleep(0)
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    assert not (await second).ok
    assert len(ui.requests) == 2
    assert not gate.active_grants()


async def test_application_permissions_also_recheck_after_waiting(tmp_path: Path) -> None:
    ui = HeldApprovalUI("always")
    gate = gate_for(tmp_path, ui)
    first = asyncio.create_task(gate.allow_app("org.example.Editor", "Editor"))
    await ui.shown.wait()
    second = asyncio.create_task(gate.allow_app("org.example.Editor", "Editor"))
    await asyncio.sleep(0)
    ui.release.set()
    assert all(await asyncio.gather(first, second))
    assert len(ui.requests) == 1


async def test_approval_ui_cannot_change_the_executed_arguments(tmp_path: Path) -> None:
    ui = HeldApprovalUI("once")
    gate = gate_for(tmp_path, ui)
    running = asyncio.create_task(gate.guard(call(payload={"action": "read"}), Probe()))
    await ui.shown.wait()
    ui.requests[0].args["payload"]["action"] = "delete"
    ui.release.set()
    result = await running
    assert json.loads(result.output) == {"payload": {"action": "read"}}

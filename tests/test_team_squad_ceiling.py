"""Squad ceiling tests: the assignment risk level, composed and
frozen at enqueue, enforced in front of the Sentinel.

Everything runs on MockLLM and a temporary workspace; no network, no
real model.  The store-level tests pin the composition rule (tighter
wins, unnamed inherits, never widens down a chain) and the freeze
(a level written at enqueue does not move afterwards).  The
execution tests build the production factory over the real tool
classes and a Sentinel that counts how often it was consulted, so a
ceiling refusal is asserted to be a short circuit, not a Sentinel
decision.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from nanomuse.config import Settings
from nanomuse.llm import MockLLM
from nanomuse.schema import Function, LLMResponse, RiskLevel, Role, ToolCall, ToolResult
from nanomuse.sentinel import AuditLog, Sentinel
from nanomuse.team.presets import PRESETS, assessed_risk, effective_preset, preset_for
from nanomuse.team.runner import MuseAgentFactory, build_factory
from nanomuse.team.squad import Squad
from nanomuse.team.store import SquadStore, compose_level
from nanomuse.tools import Files, Shell, Terminate, ToolCollection, WebFetch, WebSearch
from nanomuse.tools.base import BaseTool
from nanomuse.tools.shell import PythonExecute
from nanomuse.ui import HeadlessUI


def tc(name: str, **args: Any) -> ToolCall:
    return ToolCall(function=Function(name=name, arguments=json.dumps(args)))


def make_store(tmp_path: Path) -> SquadStore:
    return SquadStore(tmp_path / "squad.db")


def registry(settings: Settings) -> ToolCollection:
    workspace = Path(settings.agent.workspace)
    return ToolCollection(
        Terminate(),
        Files(workspace=workspace),
        WebSearch(),
        WebFetch(),
        Shell(workspace=workspace),
        PythonExecute(workspace=workspace),
    )


# ---------------------------------------------------------------------- composition


def test_the_presets_carry_their_ceilings() -> None:
    assert preset_for("research").ceiling is RiskLevel.SAFE
    assert preset_for("verify").ceiling is RiskLevel.SAFE
    # execute caps at the top of the scale: no cap of the squad's own,
    # the Sentinel's approvals are the control on its sensitive calls
    assert preset_for("execute").ceiling is RiskLevel.SENSITIVE
    # consult drops any preset's ceiling to safe with its face
    consult = effective_preset(preset_for("execute"), "consult")
    assert consult.read_only is True and consult.ceiling is RiskLevel.SAFE
    assert effective_preset(preset_for("execute"), "work").ceiling is RiskLevel.SENSITIVE


def test_compose_level_takes_the_tighter_side() -> None:
    assert compose_level("sensitive", "safe") == "safe"  # the preset is tighter
    assert compose_level("safe", "sensitive") == "safe"  # the parent is tighter
    assert compose_level("moderate", "moderate") == "moderate"
    assert compose_level("", "moderate") == "moderate"  # only one side named
    assert compose_level("moderate", "") == "moderate"  # unnamed inherits
    assert compose_level("", "") == ""


def test_a_level_must_be_a_risk_level(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    with pytest.raises(ValueError):
        store.create_root(origin="user", brief="root", level="ask")
    root = store.create_root(origin="user", brief="root", level="sensitive")
    with pytest.raises(ValueError):
        store.enqueue(parent_id=root.id, origin="user", brief="child", level="whenever")
    with pytest.raises(ValueError):
        compose_level("safe", "whenever")


def test_levels_never_widen_down_a_three_level_chain(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    root = store.create_root(origin="user", brief="root", level="sensitive")
    child = store.enqueue(parent_id=root.id, origin="user", brief="one", level="moderate")
    grandchild = store.enqueue(parent_id=child.id, origin="user", brief="two", level="sensitive")
    assert child.level == "moderate"
    # the grandchild named the loosest level there is and still froze
    # at its parent's: composition is the only way in, and it tightens
    assert grandchild.level == "moderate"
    ranks = [RiskLevel(a.level).rank for a in (root, child, grandchild)]
    assert ranks == sorted(ranks, reverse=True)


def test_a_frozen_level_does_not_move_afterwards(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    root = store.create_root(origin="user", brief="root", level="moderate")
    child = store.enqueue(parent_id=root.id, origin="user", brief="one", level="sensitive")
    assert child.level == "moderate"
    # later work under the same parent, named any way, leaves the
    # first child's frozen level exactly where enqueue put it
    store.enqueue(parent_id=root.id, origin="user", brief="two", level="safe")
    store.settle(child.id, "completed", result="done")
    store.close()
    reopened = make_store(tmp_path)
    kept = reopened.get(child.id)
    assert kept is not None and kept.level == "moderate"


def test_dispatch_freezes_the_composed_levels(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    squad = Squad.form(store=store)
    assert squad.dispatch("research", "look up", {"mode": "work"})
    assert squad.dispatch("execute", "write it", {"mode": "work"})
    assert squad.dispatch("execute", "ask it", {})  # consult by default
    root = store.get(squad.root_assignment_id or "")
    assert root is not None and root.level == "sensitive"  # the default root ceiling
    levels = {c.brief: c.level for c in store.children(root.id)}
    assert levels == {"look up": "safe", "write it": "sensitive", "ask it": "safe"}


def test_a_tighter_squad_ceiling_bounds_the_whole_tree(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    squad = Squad.form(store=store, ceiling=RiskLevel.MODERATE)
    assert squad.dispatch("execute", "write it", {"mode": "work"})
    assert squad.dispatch("research", "look up", {"mode": "work"})
    root = store.get(squad.root_assignment_id or "")
    assert root is not None and root.level == "moderate"
    levels = {c.brief: c.level for c in store.children(root.id)}
    # execute's own ceiling is the top of the scale; the root's wins
    assert levels == {"write it": "moderate", "look up": "safe"}
    with pytest.raises(ValueError):
        Squad.form(store=store, ceiling="whenever")


# ---------------------------------------------------------------------- measured risk


def test_assessed_risk_measures_calls_the_way_the_ceiling_reads_them(
    settings: Settings,
) -> None:
    tools = registry(settings)
    files, shell, search, fetch = (
        tools.get(n) for n in ("files", "shell", "web_search", "web_fetch")
    )
    assert files is not None and shell is not None and search is not None and fetch is not None
    assert assessed_risk(files, {"action": "read", "path": "a.txt"}) is RiskLevel.SAFE
    assert assessed_risk(files, {"action": "write", "path": "a.txt", "content": "x"}) is (
        RiskLevel.MODERATE
    )
    assert assessed_risk(shell, {"command": "ls"}) is RiskLevel.SENSITIVE
    assert assessed_risk(fetch, {"url": "https://example.com"}) is RiskLevel.MODERATE
    # a search assesses moderate only because the query leaves for the
    # owner's configured provider; the ceiling measures a counted
    # read at its family's declared risk, like the gate does
    assert assessed_risk(search, {"query": "x"}) is RiskLevel.SAFE


def test_an_unassessable_call_has_no_risk_to_measure(settings: Settings) -> None:
    class Exploding(Files):
        def assess(self, args: dict[str, Any]):  # type: ignore[override]
            raise RuntimeError("no judgement possible")

    workspace = Path(settings.agent.workspace)
    assert assessed_risk(Exploding(workspace=workspace), {"action": "read"}) is None


# ---------------------------------------------------------------------- enforcement


class CountingSentinel(Sentinel):
    """The real Sentinel, counting how often guard was consulted."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.guard_calls = 0

    async def guard(self, call: ToolCall, tool: BaseTool) -> ToolResult:
        self.guard_calls += 1
        return await super().guard(call, tool)


def make_counting_factory(
    settings: Settings, llm: MockLLM, store: SquadStore
) -> tuple[MuseAgentFactory, CountingSentinel]:
    audit = AuditLog(settings.audit_file)
    sentinel = CountingSentinel(settings.sentinel, audit, HeadlessUI())
    factory = build_factory(
        settings,
        tools=registry(settings),
        sentinel=sentinel,
        ui=HeadlessUI(),
        audit=audit,
        store=store,
        llm_for_tier=lambda preset: llm,
    )
    return factory, sentinel


async def test_a_call_above_the_ceiling_is_refused_before_the_sentinel(
    settings: Settings, tmp_path: Path
) -> None:
    workspace = Path(settings.agent.workspace)
    workspace.mkdir(parents=True, exist_ok=True)
    script: list[Any] = [
        LLMResponse(tool_calls=[tc("shell", command="touch pwned.txt")]),
        LLMResponse(content="the shell was refused"),
    ]
    llm = MockLLM(script)
    store = make_store(tmp_path)
    factory, sentinel = make_counting_factory(settings, llm, store)
    squad = Squad.form(store=store, execute=True, factory=factory, ceiling="moderate")
    assert squad.dispatch("execute", "run it", {"task": "touch a file", "mode": "work"})
    await squad.wait_idle()
    (child,) = store.children(squad.root_assignment_id or "")
    assert child.level == "moderate" and child.status == "completed"
    assert child.result == "the shell was refused"
    # the refusal was the ceiling layer's: the real Sentinel was never
    # consulted for the call, and nothing ran
    assert sentinel.guard_calls == 0
    assert not (workspace / "pwned.txt").exists()
    tool_msgs = [m for m in llm.calls[1]["messages"] if m.role == Role.TOOL]
    assert tool_msgs and "refused by the squad ceiling" in (tool_msgs[0].content or "")
    events = {e.kind: e.detail for e in store.events(child.id)}
    assert "ceiling_refused" in events and "shell" in events["ceiling_refused"]
    assert "above this assignment's ceiling of moderate" in events["ceiling_refused"]


async def test_a_call_at_the_ceiling_still_goes_through_the_sentinel(
    settings: Settings, tmp_path: Path
) -> None:
    workspace = Path(settings.agent.workspace)
    workspace.mkdir(parents=True, exist_ok=True)
    script: list[Any] = [
        LLMResponse(tool_calls=[tc("files", action="write", path="note.txt", content="hello")]),
        LLMResponse(content="written"),
    ]
    llm = MockLLM(script)
    store = make_store(tmp_path)
    factory, sentinel = make_counting_factory(settings, llm, store)
    squad = Squad.form(store=store, execute=True, factory=factory, ceiling="moderate")
    assert squad.dispatch("execute", "write note", {"task": "write note.txt", "mode": "work"})
    await squad.wait_idle()
    (child,) = store.children(squad.root_assignment_id or "")
    assert child.status == "completed"
    # a write assesses moderate, the ceiling is moderate: the call
    # passed the layer and the Sentinel judged it, as in step two
    assert sentinel.guard_calls == 1
    assert (workspace / "note.txt").read_text(encoding="utf-8") == "hello"
    assert "ceiling_refused" not in [e.kind for e in store.events(child.id)]


class AllowAllSentinel:
    """A stand-in for a Sentinel that would allow everything: the
    state a call is in after every approval has been granted."""

    def __init__(self) -> None:
        self.guard_calls = 0

    def begin_task(self, *args: Any, **kwargs: Any) -> object:
        return object()

    def end_task(self, token: Any) -> None:
        return None

    def untaint(self, conversation: str | None = None) -> None:
        return None

    async def guard(self, call: ToolCall, tool: BaseTool) -> ToolResult:
        self.guard_calls += 1
        return ToolResult(output="ran")


async def test_no_approval_inside_the_assignment_lifts_the_ceiling(
    settings: Settings, tmp_path: Path
) -> None:
    workspace = Path(settings.agent.workspace)
    workspace.mkdir(parents=True, exist_ok=True)
    script: list[Any] = [
        LLMResponse(tool_calls=[tc("files", action="write", path="note.txt", content="hello")]),
        LLMResponse(content="done"),
    ]
    llm = MockLLM(script)
    store = make_store(tmp_path)
    root = store.create_root(origin="user", brief="root", level="safe")
    child = store.enqueue(
        parent_id=root.id, origin="user", mode="work", role="execute", brief="write", level="safe"
    )
    allow_all = AllowAllSentinel()
    factory = MuseAgentFactory(
        settings,
        tools=registry(settings),
        sentinel=allow_all,  # type: ignore[arg-type]
        ui=HeadlessUI(),
        audit=AuditLog(settings.audit_file),
        llm_for_tier=lambda preset: llm,
    )
    handle = factory(preset_for("execute"), child)
    await handle.run("write note.txt")
    # the inner guard would have allowed the write; it was never
    # consulted, because the ceiling sits in front of it and bounds
    # the whole assignment, not one approval
    assert allow_all.guard_calls == 0
    assert not (workspace / "note.txt").exists()
    tool_msgs = [m for m in llm.calls[1]["messages"] if m.role == Role.TOOL]
    assert tool_msgs and "no approval inside it can lift it" in (tool_msgs[0].content or "")


async def test_enforcement_reads_the_frozen_row_not_the_preset_of_the_moment(
    settings: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = Path(settings.agent.workspace)
    workspace.mkdir(parents=True, exist_ok=True)
    script: list[Any] = [
        LLMResponse(tool_calls=[tc("files", action="write", path="note.txt", content="hello")]),
        LLMResponse(content="written"),
    ]
    llm = MockLLM(script)
    store = make_store(tmp_path)
    root = store.create_root(origin="user", brief="root", level="sensitive")
    child = store.enqueue(
        parent_id=root.id, origin="user", mode="work", role="execute", brief="write"
    )
    assert child.level == "sensitive"
    # after the assignment was enqueued, the execute preset's ceiling
    # is reconfigured to the tightest there is; enforcement reads the
    # frozen row, so the write still passes the layer to the Sentinel
    monkeypatch.setitem(PRESETS, "execute", replace(preset_for("execute"), ceiling=RiskLevel.SAFE))
    factory = build_factory(
        settings,
        tools=registry(settings),
        sentinel=Sentinel(settings.sentinel, AuditLog(settings.audit_file), HeadlessUI()),
        ui=HeadlessUI(),
        audit=AuditLog(settings.audit_file),
        store=store,
        llm_for_tier=lambda preset: llm,
    )
    handle = factory(preset_for("execute"), child)
    await handle.run("write note.txt")
    assert (workspace / "note.txt").read_text(encoding="utf-8") == "hello"


async def test_consult_still_refuses_at_the_gate_not_the_ceiling(
    settings: Settings, tmp_path: Path
) -> None:
    workspace = Path(settings.agent.workspace)
    workspace.mkdir(parents=True, exist_ok=True)
    script: list[Any] = [
        LLMResponse(tool_calls=[tc("files", action="write", path="note.txt", content="hello")]),
        LLMResponse(content="I could not write that"),
    ]
    llm = MockLLM(script)
    store = make_store(tmp_path)
    factory, sentinel = make_counting_factory(settings, llm, store)
    squad = Squad.form(store=store, execute=True, factory=factory)
    assert squad.dispatch("execute", "write note", {"task": "write note.txt"})  # consult default
    await squad.wait_idle()
    (child,) = store.children(squad.root_assignment_id or "")
    assert child.level == "safe" and child.status == "completed"
    assert not (workspace / "note.txt").exists()
    # the read-only gate speaks first for a consult subtask, exactly
    # as in step two; the ceiling layer behind it added no refusal
    tool_msgs = [m for m in llm.calls[1]["messages"] if m.role == Role.TOOL]
    assert tool_msgs and "refused by the squad preset" in (tool_msgs[0].content or "")
    kinds = [e.kind for e in store.events(child.id)]
    assert "tool_refused" in kinds and "ceiling_refused" not in kinds


async def test_an_assignment_with_no_level_gets_no_ceiling_layer(
    settings: Settings, tmp_path: Path
) -> None:
    script: list[Any] = [LLMResponse(content="a short answer")]
    llm = MockLLM(script)
    store = make_store(tmp_path)
    root = store.create_root(origin="user", brief="root")  # no level recorded
    child = store.enqueue(parent_id=root.id, origin="user", mode="work", role="execute", brief="go")
    assert child.level == ""
    sentinel = Sentinel(settings.sentinel, AuditLog(settings.audit_file), HeadlessUI())
    factory = MuseAgentFactory(
        settings,
        tools=registry(settings),
        sentinel=sentinel,
        ui=HeadlessUI(),
        audit=AuditLog(settings.audit_file),
        llm_for_tier=lambda preset: llm,
    )
    handle = factory(preset_for("execute"), child)
    # the agent holds the very Sentinel the factory was given: the
    # wiring is step two's, untouched
    assert handle.agent.sentinel is sentinel
    assert await handle.run("answer briefly") == "a short answer"
    # and an assignment with a level does get the wrapper, even at
    # the top of the scale where it refuses nothing
    capped = store.enqueue(parent_id=root.id, origin="user", brief="go capped", level="sensitive")
    capped_handle = factory(preset_for("execute"), capped)
    assert capped_handle.agent.sentinel is not sentinel

"""Squad execution tests: role presets, the consult default, the
read-only gate, the stall watch, and the ledger bookkeeping of a run.

Everything runs on MockLLM and a temporary workspace; no network, no
real model.  The agent-level tests build the production factory
(:class:`MuseAgentFactory`) over a small registry of the real tool
classes, so the faces and the gate are asserted against the tools'
own risk annotations, not against copies of them.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from nanomuse.config import Settings
from nanomuse.cost import recording
from nanomuse.cost.ledger import CostLedger, PriceEntry
from nanomuse.cost.recording import TaskCostRecorder
from nanomuse.llm import MockLLM
from nanomuse.memory import MemoryStore
from nanomuse.schema import Function, LLMResponse, Role, ToolCall
from nanomuse.sentinel import AuditLog, Sentinel
from nanomuse.team.presets import (
    PRESETS,
    effective_preset,
    is_read_only_call,
    preset_for,
    read_only_face,
)
from nanomuse.team.runner import MuseAgentFactory, StallPolicy, StallWatch, SubtaskRun
from nanomuse.team.squad import Squad, SquadFrame
from nanomuse.team.store import Assignment, SquadStore
from nanomuse.tools import Files, Shell, Terminate, ToolCollection, WebFetch, WebSearch
from nanomuse.tools.memory_tools import Forget, Recall, Remember
from nanomuse.tools.shell import PythonExecute
from nanomuse.ui import HeadlessUI


def tc(name: str, **args: Any) -> ToolCall:
    return ToolCall(function=Function(name=name, arguments=json.dumps(args)))


def make_store(tmp_path: Path) -> SquadStore:
    return SquadStore(tmp_path / "squad.db")


def registry(settings: Settings) -> ToolCollection:
    """A small registry of the real tool classes, safe and acting alike."""
    workspace = Path(settings.agent.workspace)
    return ToolCollection(
        Terminate(),
        Files(workspace=workspace),
        WebSearch(),
        WebFetch(),
        Shell(workspace=workspace),
        PythonExecute(workspace=workspace),
    )


def tool_names(params: list[dict[str, Any]] | None) -> set[str]:
    return {p["function"]["name"] for p in params or []}


# ---------------------------------------------------------------------- presets


def test_the_three_presets_carry_their_tiers_and_faces() -> None:
    research, verify, execute = (PRESETS[r] for r in ("research", "verify", "execute"))
    assert (research.tier, research.read_only) == ("cheap", True)
    assert (verify.tier, verify.read_only) == ("cheap", True)
    assert (execute.tier, execute.read_only) == ("default", False)
    # verify works to a checklist; the prompt says so
    assert "checklist" in verify.system_prompt
    with pytest.raises(ValueError):
        preset_for("nobody")


def test_consult_tightens_any_preset_to_read_only() -> None:
    execute = preset_for("execute")
    assert effective_preset(execute, "consult").read_only is True
    assert effective_preset(execute, "work") is execute
    assert effective_preset(preset_for("research"), "consult").read_only is True


def test_the_read_only_face_offers_only_statically_safe_families(settings: Settings) -> None:
    face = read_only_face(registry(settings))
    # files and web_search declare safe; web_fetch, shell and python
    # declare more and stay out, exactly as their classes annotate
    assert {t.name for t in face} == {"terminate", "files", "web_search"}


def test_read_only_calls_are_judged_per_call_by_the_tools_own_assessment(
    settings: Settings, tmp_path: Path
) -> None:
    tools = registry(settings)
    memory = MemoryStore(settings.memory_db)
    files = tools.get("files")
    assert files is not None
    assert is_read_only_call(files, {"action": "read", "path": "a.txt"}) is True
    assert is_read_only_call(files, {"action": "list"}) is True
    # the same tool, a writing action: not a read, by its own assess
    assert is_read_only_call(files, {"action": "write", "path": "a.txt", "content": "x"}) is False
    assert is_read_only_call(files, {"action": "append", "path": "a.txt", "content": "x"}) is False
    # search goes only to the configured provider: a read; a fetch of a
    # model-chosen page is not
    assert is_read_only_call(tools.get("web_search"), {"query": "x"}) is True
    assert is_read_only_call(tools.get("web_fetch"), {"url": "https://example.com"}) is False
    # acting families refuse every call shape
    assert is_read_only_call(tools.get("shell"), {"command": "ls"}) is False
    assert is_read_only_call(tools.get("python_execute"), {"code": "print(1)"}) is False
    # remembering is a change wearing a safe static label: its assess says so
    remember = Remember(store=memory)
    assert is_read_only_call(remember, {"content": "a fact"}) is False
    assert is_read_only_call(Recall(store=memory), {"query": "x"}) is True
    assert is_read_only_call(Forget(store=memory), {"memory_id": "m_x"}) is False
    assert tmp_path is not None  # the store fixture lives under the settings dirs


# ---------------------------------------------------------------------- envelope


def test_frames_carry_a_provenance_envelope_with_weak_defaults() -> None:
    frame = SquadFrame("event", "a", "b", "ping", {})
    assert frame.origin == "" and frame.reason == "" and frame.authority == "information"
    as_dict = frame.to_dict()
    assert as_dict["origin"] == "" and as_dict["authority"] == "information"
    with pytest.raises(ValueError):
        SquadFrame("event", "a", "b", "ping", {}, authority="owner")


def test_a_dispatch_frame_speaks_for_the_user(tmp_path: Path) -> None:
    squad = Squad.form(store=make_store(tmp_path), origin="user")
    assert squad.dispatch("research", "search", {"q": "x"}) is True
    (frame,) = squad.bus.drain("specialist:research")
    assert frame.authority == "user" and frame.origin == "user" and frame.reason == "search"


# ---------------------------------------------------------------------- stub factory runs


class StubAgent:
    def __init__(self, result: str = "done", error: Exception | None = None) -> None:
        self.result = result
        self.error = error
        self.tasks: list[str] = []

    async def run(self, task: str) -> str:
        self.tasks.append(task)
        if self.error is not None:
            raise self.error
        return self.result


def stub_factory(agent: StubAgent) -> Callable[..., SubtaskRun]:
    def factory(preset: Any, assignment: Assignment) -> SubtaskRun:
        return SubtaskRun(agent=agent, watch=StallWatch(StallPolicy()))

    return factory


async def test_dispatch_runs_and_settles_completed_with_a_result_frame(
    tmp_path: Path,
) -> None:
    store = make_store(tmp_path)
    agent = StubAgent(result="the answer")
    squad = Squad.form(store=store, execute=True, factory=stub_factory(agent))
    assert squad.dispatch("research", "look up", {"task": "find the thing", "mode": "work"})
    await squad.wait_idle()
    (child,) = store.children(squad.root_assignment_id or "")
    assert child.status == "completed" and child.result == "the answer"
    kinds = [e.kind for e in store.events(child.id)]
    assert "execution_started" in kinds and "settled" in kinds
    assert agent.tasks == ["find the thing"]
    (frame,) = [f for f in squad.bus.drain("steward") if f.kind == "result"]
    assert frame.body["assignment_id"] == child.id
    assert frame.body["status"] == "completed" and frame.body["summary"] == "the answer"
    assert frame.authority == "information"


async def test_a_failing_run_settles_failed_with_the_error(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    agent = StubAgent(error=RuntimeError("no key for the model"))
    squad = Squad.form(store=store, execute=True, factory=stub_factory(agent))
    assert squad.dispatch("research", "look up", {"mode": "work"})
    await squad.wait_idle()
    (child,) = store.children(squad.root_assignment_id or "")
    assert child.status == "failed" and child.outcome == "error"
    assert "no key for the model" in child.result


async def test_a_long_result_is_a_summary_in_the_ledger_and_shorter_in_the_frame(
    tmp_path: Path,
) -> None:
    store = make_store(tmp_path)
    agent = StubAgent(result="x" * 5000)
    squad = Squad.form(store=store, execute=True, factory=stub_factory(agent))
    assert squad.dispatch("research", "look up", {"mode": "work"})
    await squad.wait_idle()
    (child,) = store.children(squad.root_assignment_id or "")
    assert len(child.result) == 2000 and child.result.endswith("[truncated]")
    (frame,) = [f for f in squad.bus.drain("steward") if f.kind == "result"]
    assert len(frame.body["summary"]) == 500


async def test_notify_is_recorded_and_never_run(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    calls: list[str] = []

    def counting_factory(preset: Any, assignment: Assignment) -> SubtaskRun:
        calls.append(assignment.id)
        return SubtaskRun(agent=StubAgent(), watch=StallWatch(StallPolicy()))

    squad = Squad.form(store=store, execute=True, factory=counting_factory)
    assert squad.dispatch("research", "tell them", {"mode": "notify"})
    await squad.wait_idle()
    (child,) = store.children(squad.root_assignment_id or "")
    assert child.mode == "notify" and child.status == "queued"
    assert calls == []


async def test_execute_off_records_exactly_like_the_ledger_step(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    squad = Squad.form(store=store, factory=stub_factory(StubAgent()))  # execute stays False
    assert squad.dispatch("research", "search", {"mode": "work"})
    assert squad.pending_executions == 0
    (child,) = store.children(squad.root_assignment_id or "")
    assert child.status == "queued"


def test_a_synchronous_caller_gets_a_finished_dispatch(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    squad = Squad.form(store=store, execute=True, factory=stub_factory(StubAgent("sync done")))
    assert squad.dispatch("research", "look up", {"mode": "work"})
    (child,) = store.children(squad.root_assignment_id or "")
    assert child.status == "completed" and child.result == "sync done"


# ---------------------------------------------------------------------- real factory runs


def make_factory(
    settings: Settings,
    llm: MockLLM,
    *,
    tiers: list[str] | None = None,
    stall_policy: StallPolicy | None = None,
    store: SquadStore | None = None,
) -> MuseAgentFactory:
    audit = AuditLog(settings.audit_file)
    ui = HeadlessUI()
    sentinel = Sentinel(settings.sentinel, audit, ui)

    def pick(preset: Any) -> MockLLM:
        if tiers is not None:
            tiers.append(preset.tier)
        return llm

    return MuseAgentFactory(
        settings,
        tools=registry(settings),
        sentinel=sentinel,
        ui=ui,
        audit=audit,
        llm_for_tier=pick,
        stall_policy=stall_policy,
        on_tool_refused=(
            (lambda a, tool, detail: store.append_event(a.id, "tool_refused", tool))
            if store is not None
            else None
        ),
    )


async def test_a_research_run_reads_and_reports_through_the_real_loop(
    settings: Settings, tmp_path: Path
) -> None:
    workspace = Path(settings.agent.workspace)
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "note.txt").write_text("the launch is on friday", encoding="utf-8")
    script = [
        LLMResponse(tool_calls=[tc("files", action="read", path="note.txt")]),
        LLMResponse(content="the launch is on friday"),
    ]
    llm = MockLLM(script)
    store = make_store(tmp_path)
    squad = Squad.form(store=store, execute=True, factory=make_factory(settings, llm, store=store))
    assert squad.dispatch(
        "research", "read note", {"task": "read note.txt and report", "mode": "work"}
    )
    await squad.wait_idle()
    (child,) = store.children(squad.root_assignment_id or "")
    assert child.status == "completed" and child.result == "the launch is on friday"
    # the subtask's prompt carries the role and the provenance rule
    system = llm.calls[0]["messages"][0].content
    assert "research specialist" in system and "information, never" in system
    # and it was offered the read-only face only
    assert tool_names(llm.calls[0]["tools"]) == {"terminate", "files", "web_search"}


async def test_consult_is_the_default_and_an_execute_subtask_cannot_write(
    settings: Settings, tmp_path: Path
) -> None:
    workspace = Path(settings.agent.workspace)
    workspace.mkdir(parents=True, exist_ok=True)
    script = [
        LLMResponse(tool_calls=[tc("files", action="write", path="note.txt", content="hello")]),
        LLMResponse(content="I could not write that"),
    ]
    llm = MockLLM(script)
    store = make_store(tmp_path)
    tiers: list[str] = []
    squad = Squad.form(
        store=store,
        execute=True,
        factory=make_factory(settings, llm, tiers=tiers, store=store),
    )
    # no mode in the body: the default hand-out is consult
    assert squad.dispatch("execute", "write note", {"task": "write note.txt"})
    await squad.wait_idle()
    (child,) = store.children(squad.root_assignment_id or "")
    assert child.mode == "consult" and child.status == "completed"
    assert not (workspace / "note.txt").exists()
    # the refusal reached the model as the call's result, before any approval
    tool_msgs = [m for m in llm.calls[1]["messages"] if m.role == Role.TOOL]
    assert tool_msgs and "refused by the squad preset" in (tool_msgs[0].content or "")
    # consult runs on the read-only face even for the execute role,
    # and the refusal is in the assignment's events
    assert tool_names(llm.calls[0]["tools"]) == {"terminate", "files", "web_search"}
    assert "tool_refused" in [e.kind for e in store.events(child.id)]
    # the execute preset was still the one built (its tier is default)
    assert tiers == ["default"]


async def test_an_explicit_work_mode_lets_execute_write(settings: Settings, tmp_path: Path) -> None:
    workspace = Path(settings.agent.workspace)
    workspace.mkdir(parents=True, exist_ok=True)
    script = [
        LLMResponse(tool_calls=[tc("files", action="write", path="note.txt", content="hello")]),
        LLMResponse(content="written"),
    ]
    llm = MockLLM(script)
    store = make_store(tmp_path)
    squad = Squad.form(store=store, execute=True, factory=make_factory(settings, llm))
    assert squad.dispatch("execute", "write note", {"task": "write note.txt", "mode": "work"})
    await squad.wait_idle()
    (child,) = store.children(squad.root_assignment_id or "")
    assert child.status == "completed"
    assert (workspace / "note.txt").read_text(encoding="utf-8") == "hello"
    # the full face was offered, acting families included
    assert {"shell", "web_fetch", "python_execute"} <= tool_names(llm.calls[0]["tools"])


async def test_the_same_error_three_times_with_no_success_stalls_the_run(
    settings: Settings, tmp_path: Path
) -> None:
    script = [
        LLMResponse(tool_calls=[tc("files", action="read", path="missing.txt")]),
        LLMResponse(tool_calls=[tc("files", action="read", path="missing.txt")]),
        LLMResponse(tool_calls=[tc("files", action="read", path="missing.txt")]),
        LLMResponse(tool_calls=[tc("files", action="read", path="missing.txt")]),
        LLMResponse(content="never reached"),
    ]
    llm = MockLLM(script)
    store = make_store(tmp_path)
    squad = Squad.form(store=store, execute=True, factory=make_factory(settings, llm))
    assert squad.dispatch("research", "read missing", {"task": "read missing.txt", "mode": "work"})
    await squad.wait_idle()
    (child,) = store.children(squad.root_assignment_id or "")
    assert child.status == "failed" and child.outcome == "stalled"
    assert "stopped" in child.result
    assert len(llm.calls) == 3  # the watch stopped the run at the third error
    events = {e.kind: e.detail for e in store.events(child.id)}
    assert "stalled" in events and "same error 3 times" in events["stalled"]
    assert events["tool_calls"] == "3 call(s), 0 successful"


async def test_a_tool_call_cap_stops_a_run_that_keeps_working(
    settings: Settings, tmp_path: Path
) -> None:
    workspace = Path(settings.agent.workspace)
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "note.txt").write_text("data", encoding="utf-8")
    script = [
        LLMResponse(tool_calls=[tc("files", action="read", path="note.txt")]),
        LLMResponse(tool_calls=[tc("files", action="read", path="note.txt")]),
        LLMResponse(tool_calls=[tc("files", action="read", path="note.txt")]),
        LLMResponse(content="never reached"),
    ]
    llm = MockLLM(script)
    store = make_store(tmp_path)
    factory = make_factory(
        settings, llm, stall_policy=StallPolicy(after_errors=3, max_tool_calls=2)
    )
    squad = Squad.form(store=store, execute=True, factory=factory)
    assert squad.dispatch("research", "read note", {"task": "read it", "mode": "work"})
    await squad.wait_idle()
    (child,) = store.children(squad.root_assignment_id or "")
    assert child.status == "failed" and child.outcome == "stalled"
    assert len(llm.calls) == 2


async def test_a_subtasks_model_calls_are_recorded_under_its_assignment_id(
    settings: Settings, tmp_path: Path
) -> None:
    settings.llm.model = "mock"
    books = CostLedger(prices={"mock": PriceEntry("mock", 1.0, 2.0)})
    recording.install(TaskCostRecorder(ledger=books, device_id="test-device"))
    try:
        script = [
            LLMResponse(content="a short answer", usage={"input_tokens": 40, "output_tokens": 10})
        ]
        llm = MockLLM(script)
        tiers: list[str] = []
        store = make_store(tmp_path)
        squad = Squad.form(
            store=store,
            execute=True,
            factory=make_factory(settings, llm, tiers=tiers),
        )
        assert squad.dispatch("research", "answer", {"task": "answer briefly", "mode": "work"})
        await squad.wait_idle()
        (child,) = store.children(squad.root_assignment_id or "")
        assert child.status == "completed"
        (entry,) = books.entries
        assert entry.task_id == child.id
        assert entry.input_tokens == 40 and entry.output_tokens == 10
        # research runs on the cheap tier
        assert tiers == ["cheap"]
        # and the reconcile's evidence check can now see the subtask acted
        from nanomuse.team.store import ledger_evidence

        acted = ledger_evidence(_persisted_ledger(settings, books))
        assert acted(child) is True
    finally:
        recording.install(None)


def _persisted_ledger(settings: Settings, books: CostLedger) -> Path:
    """Write the in-memory books out as the persisted ledger file the
    evidence check reads, under the same task ids."""
    path = settings.cost_ledger_file
    lines = [
        json.dumps({"task_id": e.task_id, "model": e.model, "cost_usd": e.cost_usd})
        for e in books.entries
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
    return path

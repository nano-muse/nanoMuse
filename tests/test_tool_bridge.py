"""The tool bridge: classification, the index, the dispatch, the switch.

Everything is offline: the guard in the unit tests is a counting
double that runs the tool the way ``safe_execute`` does, and the
agent tests run on MockLLM with a real Sentinel over a temporary
audit log.
"""

from __future__ import annotations

import importlib
import json
import pkgutil
from pathlib import Path
from typing import Any

import nanomuse.tools as tools_package
from nanomuse.agent.core import MuseAgent
from nanomuse.config import Settings, ToolBridgeSettings
from nanomuse.llm.mock import MockLLM
from nanomuse.memory import MemoryStore
from nanomuse.schema import Function, LLMResponse, RiskLevel, ToolCall, ToolResult
from nanomuse.sentinel import AuditLog, Sentinel
from nanomuse.team.presets import read_only_face
from nanomuse.team.runner import _GuardedSentinel
from nanomuse.tools import (
    Files,
    Forget,
    Recall,
    Remember,
    Shell,
    Terminate,
    ToolCollection,
    WebFetch,
    WebSearch,
)
from nanomuse.tools.base import BaseTool, safe_execute
from nanomuse.tools.bridge import (
    BRIDGED_NAMES,
    DIRECT_NAMES,
    EXEMPT_NAMES,
    META_NAMES,
    REGISTERED_NAMES,
    BridgeClass,
    ToolBridge,
    ToolIndex,
    bridge_active,
    build_tool_bridge,
    classify_name,
    context_window,
    exempt_reason,
)
from nanomuse.ui import HeadlessUI


def tc(name: str, **args: Any) -> ToolCall:
    return ToolCall(function=Function(name=name, arguments=json.dumps(args)))


def use_tc(target: str, arguments: dict[str, Any]) -> ToolCall:
    payload = json.dumps({"name": target, "arguments": arguments})
    return ToolCall(function=Function(name="use_tool", arguments=payload))


def registry(settings: Settings) -> ToolCollection:
    """Real tool classes, direct core and bridged tail alike."""
    workspace = Path(settings.agent.workspace)
    store = MemoryStore(settings.data_dir / "memory.db")
    return ToolCollection(
        Terminate(),
        Files(workspace=workspace),
        Shell(workspace=workspace),
        WebSearch(),
        WebFetch(),
        Remember(store=store),
        Recall(store=store),
        Forget(store=store),
    )


class CountingGuard:
    """A guard double: records what it was asked to run, then runs it."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.tools: list[BaseTool] = []

    async def guard(self, call: ToolCall, tool: BaseTool) -> ToolResult:
        self.calls.append((call.name, call.arguments))
        self.tools.append(tool)
        return await safe_execute(tool, call.arguments)


# ------------------------------------------------------------ classification


def shipped_tool_classes() -> dict[str, type[BaseTool]]:
    """Every tool class the runtime ships, by its class-level name.

    Classes whose name is set per instance (MCP tools) have no
    class-level default and are skipped: they are classified by rule
    at run time, not by this registry.
    """
    found: dict[str, type[BaseTool]] = {}
    for info in pkgutil.iter_modules(tools_package.__path__):
        module = importlib.import_module(f"nanomuse.tools.{info.name}")
        for obj in vars(module).values():
            if (
                isinstance(obj, type)
                and issubclass(obj, BaseTool)
                and obj.__module__ == module.__name__
            ):
                field = obj.model_fields.get("name")
                default = field.default if field else None
                if isinstance(default, str) and default:
                    found[default] = obj
    return found


def test_every_shipped_tool_is_registered_and_no_registration_is_stale() -> None:
    shipped = shipped_tool_classes()
    assert set(shipped) == REGISTERED_NAMES - META_NAMES
    for name, cls in shipped.items():
        # a shipped tool the classification does not know fails here,
        # so a new tool cannot drift in unclassified
        assert name in REGISTERED_NAMES
        assert cls.model_fields["purpose"].default, f"{name} has no one-line purpose"


def test_the_registered_sets_are_disjoint_and_classify_as_named() -> None:
    assert not (DIRECT_NAMES & EXEMPT_NAMES)
    assert not (DIRECT_NAMES & BRIDGED_NAMES)
    assert not (EXEMPT_NAMES & BRIDGED_NAMES)
    for name in DIRECT_NAMES | META_NAMES:
        assert classify_name(name) is BridgeClass.DIRECT
    for name in EXEMPT_NAMES:
        assert classify_name(name) is BridgeClass.EXEMPT
    for name in BRIDGED_NAMES:
        assert classify_name(name) is BridgeClass.BRIDGED


def test_the_word_backstops_catch_unregistered_senders_and_machinery() -> None:
    # an MCP-style name nobody registered: the sending word in it is enough
    assert classify_name("acme__send_sms") is BridgeClass.EXEMPT
    assert classify_name("acme__notify_user") is BridgeClass.EXEMPT
    assert classify_name("blog__publish_post") is BridgeClass.EXEMPT
    assert exempt_reason("acme__send_sms") is not None
    # the approval machinery is never reached by name either
    assert classify_name("gatekeeper_review") is BridgeClass.EXEMPT
    assert classify_name("sentinel_grants") is BridgeClass.EXEMPT
    # and an ordinary unknown name is the bridged default, the long tail
    assert classify_name("mqtt__subscribe") is BridgeClass.BRIDGED
    assert exempt_reason("files") is None


# ------------------------------------------------------------------ the index


def test_find_returns_full_schemas_of_the_best_matches(settings: Settings) -> None:
    bridge = ToolBridge(registry(settings), CountingGuard())
    find = bridge.get("find_tools")
    assert find is not None
    result = asyncio_run(find.execute(query="save a fact to memory"))
    payload = json.loads(result.output)
    names = [m["name"] for m in payload["matches"]]
    assert "remember" in names
    assert len(names) <= 3
    first = payload["matches"][0]
    assert first["schema"]["function"]["name"] == first["name"]
    assert "parameters" in first["schema"]["function"]
    assert first["purpose"]


def test_find_searches_only_the_bridged_set(settings: Settings) -> None:
    bridge = ToolBridge(registry(settings), CountingGuard())
    find = bridge.get("find_tools")
    assert find is not None
    result = asyncio_run(find.execute(query="shell command"))
    names = [m["name"] for m in json.loads(result.output)["matches"]]
    assert "shell" not in names  # direct tools are not the index's business


def test_find_with_no_match_says_so_plainly(settings: Settings) -> None:
    bridge = ToolBridge(registry(settings), CountingGuard())
    find = bridge.get("find_tools")
    assert find is not None
    result = asyncio_run(find.execute(query="quantum teleporter"))
    payload = json.loads(result.output)
    assert payload["matches"] == []
    assert "No tool matches" in payload["note"]
    assert "do not invent" in payload["note"]
    assert "remember" in payload["note"]  # it names what can be reached instead


def test_the_index_is_deterministic(settings: Settings) -> None:
    index = ToolIndex(registry(settings).tools)
    one = [t.name for t in index.search("memory")]
    two = [t.name for t in index.search("memory")]
    assert one == two and one


# ------------------------------------------------------------------ use_tool


def test_use_tool_dispatches_through_the_guard_it_was_given(settings: Settings) -> None:
    coll = registry(settings)
    guard = CountingGuard()
    bridge = ToolBridge(coll, guard)
    use = bridge.get("use_tool")
    assert use is not None
    result = asyncio_run(use.execute(name="remember", arguments={"content": "likes tea"}))
    assert result.ok
    assert [name for name, _args in guard.calls] == ["remember"]
    # the very object from the caller's collection is what the guard got
    assert guard.tools[0] is coll.get("remember")
    # and it really ran: the fact is in the store now
    recall = asyncio_run(coll.get("recall").execute(query="tea"))  # type: ignore[union-attr]
    assert "likes tea" in recall.output


def test_use_tool_refusals_name_their_category(settings: Settings) -> None:
    bridge = ToolBridge(registry(settings), CountingGuard())
    use = bridge.get("use_tool")
    assert use is not None

    unknown = asyncio_run(use.execute(name="nope_tool", arguments={}))
    assert unknown.error and "unknown tool" in unknown.error

    exempt = asyncio_run(use.execute(name="send_email", arguments={}))
    assert exempt.error and "never runs through the tool bridge" in exempt.error

    outside = asyncio_run(use.execute(name="files", arguments={"action": "list"}))
    assert outside.error and "outside the tool surface" in outside.error

    meta = asyncio_run(use.execute(name="use_tool", arguments={}))
    assert meta.error and "cannot be called through use_tool" in meta.error

    bad = asyncio_run(use.execute(name="remember", arguments="[not json"))
    assert bad.error and "must be an object" in bad.error


def test_use_tool_assessment_is_the_target_calls_own(settings: Settings) -> None:
    bridge = ToolBridge(registry(settings), CountingGuard())
    use = bridge.get("use_tool")
    assert use is not None
    # remember assesses moderate (a change, not a read); the envelope
    # must present that, not the meta tool's own static level
    assessment = use.assess({"name": "remember", "arguments": {"content": "x"}})
    assert assessment.risk is RiskLevel.MODERATE
    assert assessment.summary.startswith("use_tool: ")


# -------------------------------------------------------------- view and switch


def test_the_view_is_core_then_meta_and_the_params_do_not_move(settings: Settings) -> None:
    coll = registry(settings)
    bridge = ToolBridge(coll, CountingGuard())
    assert bridge.names() == [
        "terminate",
        "files",
        "shell",
        "web_search",
        "web_fetch",
        "find_tools",
        "use_tool",
    ]
    assert bridge.bridged_names == ("remember", "recall", "forget")
    assert bridge.params() is bridge.params()
    twin = ToolBridge(registry(settings), CountingGuard())
    assert json.dumps(bridge.params(), sort_keys=True) == json.dumps(twin.params(), sort_keys=True)


def test_the_switch_has_three_states_and_auto_needs_a_known_window() -> None:
    off = ToolBridgeSettings()
    assert not bridge_active(off, None)
    assert not bridge_active(off, 100)
    assert bridge_active(ToolBridgeSettings(enabled=True), None)
    auto = ToolBridgeSettings(auto=True, window_threshold=32_768)
    assert bridge_active(auto, 8_000)
    assert not bridge_active(auto, 128_000)
    # an unknown window never engages auto: a guessed window would
    # switch the bridge on a fiction
    assert not bridge_active(auto, None)
    assert not bridge_active(ToolBridgeSettings(auto=True), 100)  # no threshold set


def test_no_window_source_exists_in_the_repository(settings: Settings) -> None:
    assert context_window(settings) is None
    assert build_tool_bridge(registry(settings), CountingGuard(), settings) is None
    settings.tool_bridge.auto = True
    settings.tool_bridge.window_threshold = 32_768
    assert build_tool_bridge(registry(settings), CountingGuard(), settings) is None
    settings.tool_bridge.enabled = True
    assert build_tool_bridge(registry(settings), CountingGuard(), settings) is not None


# ------------------------------------------------------------------ the agent


def make_agent(
    settings: Settings, script: list, tools: ToolCollection, sentinel: Any = None
) -> tuple[MuseAgent, MockLLM]:
    ui = HeadlessUI()
    audit = AuditLog(settings.audit_file)
    llm = MockLLM(script)
    agent = MuseAgent(
        settings,
        llm,
        tools,
        sentinel if sentinel is not None else Sentinel(settings.sentinel, audit, ui),
        ui,
        audit,
    )
    return agent, llm


def audit_entries(settings: Settings) -> list[dict]:
    path = settings.audit_file
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def test_bridge_off_leaves_the_agents_list_and_dispatch_untouched(settings: Settings) -> None:
    coll = registry(settings)
    agent, llm = make_agent(settings, [LLMResponse(content="done")], coll)
    assert agent._bridge is None
    asyncio_run(agent.run("hello"))
    assert llm.calls[0]["tools"] == coll.to_params()


def test_a_bridged_call_runs_through_the_same_sentinel_and_audit(settings: Settings) -> None:
    settings.tool_bridge.enabled = True
    coll = registry(settings)
    script = [
        LLMResponse(tool_calls=[use_tc("remember", {"content": "likes tea"})]),
        LLMResponse(tool_calls=[tc("terminate", status="success", summary="saved")]),
    ]
    agent, llm = make_agent(settings, script, coll)
    assert agent._bridge is not None
    asyncio_run(agent.run("remember that I like tea"))
    # the list the model saw is the bridged view: no remember on it
    listed = [p["function"]["name"] for p in llm.calls[0]["tools"]]
    assert listed == agent._bridge.names()
    assert "remember" not in listed
    # the audit log carries the call twice over, as the design says:
    # once as use_tool, once as the target, both through the Sentinel
    calls = [e for e in audit_entries(settings) if e.get("event") == "tool_call"]
    by_tool = {e["tool"]: e for e in calls}
    assert by_tool["use_tool"]["decision"] == "allow"
    assert by_tool["remember"]["decision"] == "allow"
    # and the bridged call really did its work
    recall = asyncio_run(coll.get("recall").execute(query="tea"))  # type: ignore[union-attr]
    assert "likes tea" in recall.output


def test_the_list_is_byte_for_byte_stable_across_runs(settings: Settings) -> None:
    settings.tool_bridge.enabled = True
    script = [LLMResponse(content="one"), LLMResponse(content="two")]
    agent, llm = make_agent(settings, script, registry(settings))
    asyncio_run(agent.run("first"))
    asyncio_run(agent.run("second"))
    first = json.dumps(llm.calls[0]["tools"], sort_keys=True)
    second = json.dumps(llm.calls[1]["tools"], sort_keys=True)
    assert first == second


# ------------------------------------------- the bridge inside a squad preset


def preset_agent(
    settings: Settings,
    script: list,
    *,
    ceiling: RiskLevel | None,
    read_only: bool = True,
) -> tuple[MuseAgent, MockLLM, ToolCollection]:
    """An agent on a preset's terms: its face, behind the preset's guard."""
    settings.tool_bridge.enabled = True
    coll = registry(settings)
    tools = read_only_face(coll) if read_only else coll
    ui = HeadlessUI()
    audit = AuditLog(settings.audit_file)
    inner = Sentinel(settings.sentinel, audit, ui)
    guarded = _GuardedSentinel(inner, read_only=read_only, ceiling=ceiling)
    llm = MockLLM(script)
    agent = MuseAgent(settings, llm, tools, guarded, ui, audit)  # type: ignore[arg-type]
    return agent, llm, tools


def tool_results(agent: MuseAgent) -> list[str]:
    return [m.content or "" for m in agent.messages if m.role.value == "tool"]


def test_in_a_read_only_preset_the_bridge_reaches_only_the_face(settings: Settings) -> None:
    script = [
        LLMResponse(tool_calls=[tc("find_tools", query="run a shell command")]),
        LLMResponse(tool_calls=[use_tc("shell", {"command": "ls"})]),
        LLMResponse(tool_calls=[use_tc("remember", {"content": "a fact"})]),
        LLMResponse(tool_calls=[use_tc("recall", {"query": "fact"})]),
        LLMResponse(content="done"),
    ]
    agent, _llm, face = preset_agent(settings, script, ceiling=RiskLevel.SAFE)
    asyncio_run(agent.run("look into things"))
    results = tool_results(agent)
    # find inside the face: shell is not there to be found
    found = json.loads(results[0])
    assert found["matches"] == []
    # use_tool for a tool outside the face is refused before it can run;
    # no guard anywhere ever saw a shell call
    assert results[1].startswith("Error:")
    calls = [e for e in audit_entries(settings) if e.get("event") == "tool_call"]
    assert all(e["tool"] != "shell" for e in calls)
    # a write through the bridge meets the preset's read-only gate:
    # refused, and nothing was remembered
    assert "read-only" in results[2]
    recall = face.get("recall")
    assert recall is not None
    after = asyncio_run(recall.execute(query="fact"))
    assert "a fact" not in after.output
    # a read through the bridge passes the same gate and runs
    assert results[3] and not results[3].startswith("Error:")


def test_the_ceiling_layer_refuses_a_bridged_call_above_it(settings: Settings) -> None:
    script = [
        LLMResponse(tool_calls=[use_tc("remember", {"content": "a fact"})]),
        LLMResponse(tool_calls=[use_tc("recall", {"query": "fact"})]),
        LLMResponse(content="done"),
    ]
    agent, _llm, coll = preset_agent(settings, script, ceiling=RiskLevel.SAFE, read_only=False)
    asyncio_run(agent.run("remember this"))
    results = tool_results(agent)
    # remember assesses moderate: above a safe ceiling, refused by the
    # ceiling layer whether it arrives directly or through the bridge
    assert "ceiling" in results[0]
    recall = coll.get("recall")
    assert recall is not None
    after = asyncio_run(recall.execute(query="fact"))
    assert "a fact" not in after.output
    # recall sits at the ceiling and runs
    assert not results[1].startswith("Error:")


# --------------------------------------------------------------------- helpers


def asyncio_run(coro: Any) -> Any:
    import asyncio

    return asyncio.run(coro)

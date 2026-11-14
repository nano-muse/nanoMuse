"""Running one squad assignment: the factory and its two guards.

The squad's executor (``nanomuse.team.squad``) knows the ledger side:
enqueue, run, settle.  This module knows the agent side: given a role
preset and an assignment, build the one run that carries it out.

:class:`MuseAgentFactory` is the production factory.  Each call
builds a fresh :class:`~nanomuse.agent.core.MuseAgent` from the
runtime's own parts (the configured settings, the caller's tool
collection, Sentinel, UI and audit log), narrowed by the preset:

- the tool collection is filtered to the preset's face and every tool
  is wrapped in a tracker for the stall watch;
- a read-only preset's agent gets a gated Sentinel (below);
- the agent's conversation id is the assignment id, so the cost
  ledger records the subtask's model calls under the assignment,
  which is exactly what the startup reconcile's evidence check reads
  (``nanomuse.team.store.ledger_evidence``);
- the preset's prompt and the provenance line
  (``nanomuse.team.presets.envelope_note``) ride along as the
  conversation's prompt addendum.

Tests inject their own factory instead: anything callable with
``(preset, assignment)`` returning a :class:`SubtaskRun`.

Two guards live here, both tightening, neither bypassing:

- the *stall watch* counts tool calls as the subtask makes them:
  successful calls, and failures by their error signature.  A run
  with no successful call that meets the same error
  ``after_errors`` times in a row is going nowhere; so is a run past
  its tool-call cap when one is set.  Either way the watch turns the
  current call's result into a stop, the agent loop ends, and the
  executor settles the assignment failed as stalled, with the counts
  written to the assignment's events.  The main loop's own stuck
  detection is a different signal (repeated replies) and is left
  alone.  Calls the Sentinel refuses never reach a tool, so they are
  not the watch's evidence.
- the *gate and ceiling* wrapper sits in front of the real Sentinel
  (below).  The gate serves read-only presets: ``guard`` first asks
  the preset layer whether the call only reads
  (``nanomuse.team.presets.is_read_only_call``) and refuses it on the
  spot when it does not, before any approval is asked for.  The
  ceiling serves every role: it is the assignment's frozen level,
  read from the ledger row the factory was handed, never from the
  preset or the settings of the moment, so nothing reconfigured
  after the assignment was enqueued can widen it.  A call measured
  above the ceiling (``nanomuse.team.presets.assessed_risk``) is
  refused before the wrapped Sentinel is consulted, which is what
  makes the ceiling unbypassable from inside the assignment: no
  approval, grant or token the Sentinel might honour is ever
  reached.  The ceiling bounds the whole assignment, where an
  approval settles one action.  Every call neither layer refuses
  goes to the real Sentinel's guard unchanged: the wrapper adds
  refusals and removes nothing.  An assignment whose row names no
  level gets no ceiling layer, exactly the second step's wiring.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pydantic import PrivateAttr

from nanomuse.agent.core import MuseAgent
from nanomuse.config import Settings
from nanomuse.goals import GoalStore
from nanomuse.llm.base import BaseLLM
from nanomuse.logger import logger
from nanomuse.memory import MemoryStore
from nanomuse.schema import RiskLevel, ToolCall, ToolResult
from nanomuse.sentinel import AuditLog, Sentinel
from nanomuse.team.presets import (
    RolePreset,
    assessed_risk,
    envelope_note,
    is_read_only_call,
    read_only_face,
)
from nanomuse.team.store import Assignment
from nanomuse.tools.base import BaseTool, ToolCollection, safe_execute
from nanomuse.ui import UI


@dataclass(frozen=True)
class StallPolicy:
    """When a subtask's tool calls say the run is going nowhere."""

    after_errors: int = 3
    max_tool_calls: int = 0  # 0: no cap of the watch's own


class StallWatch:
    """The evidence of one subtask run's tool calls, counted live."""

    def __init__(self, policy: StallPolicy) -> None:
        self.policy = policy
        self.calls = 0
        self.successes = 0
        self.stalled_reason = ""
        self._streak_signature: tuple[str, str] | None = None
        self._streak = 0

    @property
    def stalled(self) -> bool:
        return bool(self.stalled_reason)

    def record(self, tool_name: str, result: ToolResult) -> bool:
        """Count one finished call.  True means: stop the run here."""
        self.calls += 1
        if result.ok:
            self.successes += 1
            self._streak = 0
            self._streak_signature = None
        else:
            signature = (tool_name, (result.error or result.output or "")[:120])
            self._streak = self._streak + 1 if signature == self._streak_signature else 1
            self._streak_signature = signature
            if self.successes == 0 and self._streak >= self.policy.after_errors:
                self.stalled_reason = (
                    f"no successful tool call and the same error {self._streak} times"
                    f" in a row (last from {tool_name})"
                )
                return True
        if self.policy.max_tool_calls and self.calls >= self.policy.max_tool_calls:
            self.stalled_reason = f"tool call cap reached ({self.policy.max_tool_calls})"
            return True
        return False


class _TrackedTool(BaseTool):
    """One tool, wrapped so its calls land in the run's stall watch."""

    _inner: BaseTool = PrivateAttr()
    _watch: StallWatch = PrivateAttr()

    def __init__(self, inner: BaseTool, watch: StallWatch) -> None:
        super().__init__(
            name=inner.name,
            description=inner.description,
            parameters=inner.parameters,
            purpose=inner.purpose,
            keywords=inner.keywords,
            risk=inner.risk,
            reads_private_data=inner.reads_private_data,
            egress=inner.egress,
            accepts_secrets=inner.accepts_secrets,
        )
        self._inner = inner
        self._watch = watch

    @property
    def inner(self) -> BaseTool:
        return self._inner

    @property
    def watch(self) -> StallWatch:
        return self._watch

    def assess(self, args: dict[str, Any]):  # type: ignore[override]
        return self._inner.assess(args)

    async def execute(self, **kwargs: Any) -> ToolResult:
        result = await safe_execute(self._inner, kwargs)
        if not self._watch.record(self._inner.name, result):
            return result
        note = f"(subtask stopped: {self._watch.stalled_reason})"
        if result.ok:
            output = f"{result.output}\n{note}" if result.output else note
            return ToolResult(output=output, stop=True, images=result.images)
        return ToolResult(output=f"{result.for_model()} {note}", stop=True)


class _GuardedSentinel:
    """The real Sentinel, with the squad's refusals in front of guard().

    Two layers refuse here, the read-only gate first (the second
    step's order, kept), then the assignment's risk ceiling; a call
    neither refuses goes to the wrapped Sentinel's guard unchanged.
    Only the methods the agent loop uses are spelled out; anything
    else delegates to the wrapped Sentinel untouched.
    """

    def __init__(
        self,
        inner: Sentinel,
        *,
        read_only: bool = False,
        ceiling: RiskLevel | None = None,
        on_refusal: Callable[[str, str], None] | None = None,
        on_ceiling_refusal: Callable[[str, str], None] | None = None,
    ) -> None:
        self._inner = inner
        self._read_only = read_only
        self._ceiling = ceiling
        self._on_refusal = on_refusal
        self._on_ceiling_refusal = on_ceiling_refusal

    def __getattr__(self, name: str) -> Any:
        inner = self.__dict__.get("_inner")
        if inner is None:
            raise AttributeError(name)
        return getattr(inner, name)

    def begin_task(self, *args: Any, **kwargs: Any) -> Any:
        return self._inner.begin_task(*args, **kwargs)

    def end_task(self, token: Any) -> None:
        self._inner.end_task(token)

    def untaint(self, conversation: str | None = None) -> None:
        self._inner.untaint(conversation)

    async def guard(self, call: ToolCall, tool: BaseTool) -> ToolResult:
        args = call.arguments
        if "__raw__" in args:
            # The arguments never parsed: the real Sentinel owns that
            # case (it runs the call unassessed or not at all), exactly
            # as it did before this wrapper existed.
            return await self._inner.guard(call, tool)
        if self._read_only and not is_read_only_call(tool, args):
            detail = "the call is not read-only under the squad preset"
            if self._on_refusal is not None:
                self._on_refusal(tool.name, detail)
            return ToolResult.fail(
                f"refused by the squad preset: {tool.name} may not run in a"
                f" read-only subtask ({detail})"
            )
        if self._ceiling is not None:
            risk = assessed_risk(tool, args)
            if risk is None or risk.rank > self._ceiling.rank:
                detail = (
                    "the call could not be assessed"
                    if risk is None
                    else f"the call assesses {risk.value}, above this"
                    f" assignment's ceiling of {self._ceiling.value}"
                )
                if self._on_ceiling_refusal is not None:
                    self._on_ceiling_refusal(tool.name, detail)
                return ToolResult.fail(
                    f"refused by the squad ceiling: {tool.name} may not run in"
                    f" this assignment ({detail}); the ceiling bounds the whole"
                    " assignment and no approval inside it can lift it"
                )
        return await self._inner.guard(call, tool)


@dataclass
class SubtaskRun:
    """One built subtask: the agent to run and its stall watch."""

    agent: Any  # anything with ``async run(task: str) -> str``; MuseAgent in production
    watch: StallWatch

    async def run(self, task: str) -> str:
        return str(await self.agent.run(task))


# The factory the squad's executor calls: preset and assignment in,
# one built run out.
AgentFactory = Callable[[RolePreset, Assignment], SubtaskRun]


def _frozen_ceiling(assignment: Assignment) -> RiskLevel | None:
    """The ceiling the assignment's ledger row froze, if it froze one.

    The row is the only source: not the preset, not the settings, so
    nothing reconfigured after enqueue can move it.  Rows are
    validated at enqueue, so an unrecognized value can only be a
    hand-edited row; it is read as the tightest level rather than
    silently widening to none.
    """
    if not assignment.level:
        return None
    try:
        return RiskLevel(assignment.level)
    except ValueError:
        return RiskLevel.SAFE


def _slot_llm(settings: Settings, preset: RolePreset) -> BaseLLM:
    """The model client for a preset's tier, from the [llm] slot.

    A preset's own model name wins; the cheap tier otherwise takes
    ``[squad] cheap_model`` when one is set, and the slot as
    configured when neither names a model (the same rule the decider
    uses for its cheap slot).
    """
    from nanomuse.llm.factory import create_llm

    slot = settings.llm
    model = preset.model or (settings.squad.cheap_model if preset.tier == "cheap" else "")
    if model and model != slot.model:
        slot = slot.model_copy(update={"model": model})
    return create_llm(slot, data_dir=settings.data_dir)


class MuseAgentFactory:
    """Builds one real MuseAgent per assignment, narrowed by preset."""

    def __init__(
        self,
        settings: Settings,
        *,
        tools: ToolCollection,
        sentinel: Sentinel,
        ui: UI,
        audit: AuditLog,
        llm_for_tier: Callable[[RolePreset], BaseLLM] | None = None,
        memory: MemoryStore | None = None,
        goals: GoalStore | None = None,
        stall_policy: StallPolicy | None = None,
        on_tool_refused: Callable[[Assignment, str, str], None] | None = None,
        on_ceiling_refused: Callable[[Assignment, str, str], None] | None = None,
    ) -> None:
        self.settings = settings
        self.tools = tools
        self.sentinel = sentinel
        self.ui = ui
        self.audit = audit
        self.llm_for_tier = llm_for_tier or (lambda preset: _slot_llm(settings, preset))
        self.memory = memory
        self.goals = goals
        self.stall_policy = stall_policy or StallPolicy(
            after_errors=settings.squad.stall_after_errors,
            max_tool_calls=settings.squad.max_tool_calls,
        )
        self.on_tool_refused = on_tool_refused
        self.on_ceiling_refused = on_ceiling_refused

    def _refused(self, assignment: Assignment, tool_name: str, detail: str) -> None:
        self.audit.record(
            "squad_tool_refused", tool=tool_name, assignment=assignment.id, detail=detail
        )
        if self.on_tool_refused is not None:
            self.on_tool_refused(assignment, tool_name, detail)

    def _ceiling_refused(self, assignment: Assignment, tool_name: str, detail: str) -> None:
        self.audit.record(
            "squad_ceiling_refused", tool=tool_name, assignment=assignment.id, detail=detail
        )
        if self.on_ceiling_refused is not None:
            self.on_ceiling_refused(assignment, tool_name, detail)

    def __call__(self, preset: RolePreset, assignment: Assignment) -> SubtaskRun:
        watch = StallWatch(self.stall_policy)
        face = read_only_face(self.tools) if preset.read_only else self.tools
        tracked = ToolCollection(*[_TrackedTool(tool, watch) for tool in face])
        ceiling = _frozen_ceiling(assignment)
        sentinel: Any = self.sentinel
        if preset.read_only or ceiling is not None:
            sentinel = _GuardedSentinel(
                self.sentinel,
                read_only=preset.read_only,
                ceiling=ceiling,
                on_refusal=lambda tool_name, detail: self._refused(assignment, tool_name, detail),
                on_ceiling_refusal=lambda tool_name, detail: self._ceiling_refused(
                    assignment, tool_name, detail
                ),
            )
        agent = MuseAgent(
            self.settings,
            self.llm_for_tier(preset),
            tracked,
            sentinel,
            self.ui,
            self.audit,
            memory=self.memory,
            goals=self.goals,
            conversation_id=assignment.id,
        )
        note = preset.system_prompt + "\n\n" + envelope_note(assignment.origin)
        agent.prompt_addendum = lambda: note
        return SubtaskRun(agent=agent, watch=watch)


def build_factory(
    settings: Settings,
    *,
    tools: ToolCollection,
    sentinel: Sentinel,
    ui: UI,
    audit: AuditLog,
    store: Any = None,
    **kwargs: Any,
) -> MuseAgentFactory:
    """The production factory for an executing squad.

    With the squad's store given, a read-only refusal is also written
    to the assignment's events, beside the audit line, and so is a
    ceiling refusal, under its own event kind.  Hand the result to
    ``Squad.form`` together with the store and
    ``execute=settings.squad.execute``; the server and the companion
    do not form executing squads yet, so this wiring is the caller's
    to make.
    """
    if store is not None and "on_tool_refused" not in kwargs:

        def _to_events(assignment: Assignment, tool_name: str, detail: str) -> None:
            try:
                store.append_event(assignment.id, "tool_refused", f"{tool_name}: {detail}")
            except Exception:  # noqa: BLE001 - the audit line already carries the refusal
                logger.warning("could not write a squad refusal to the ledger")

        kwargs["on_tool_refused"] = _to_events
    if store is not None and "on_ceiling_refused" not in kwargs:

        def _ceiling_to_events(assignment: Assignment, tool_name: str, detail: str) -> None:
            try:
                store.append_event(assignment.id, "ceiling_refused", f"{tool_name}: {detail}")
            except Exception:  # noqa: BLE001 - the audit line already carries the refusal
                logger.warning("could not write a squad ceiling refusal to the ledger")

        kwargs["on_ceiling_refused"] = _ceiling_to_events
    return MuseAgentFactory(settings, tools=tools, sentinel=sentinel, ui=ui, audit=audit, **kwargs)


__all__ = [
    "AgentFactory",
    "MuseAgentFactory",
    "StallPolicy",
    "StallWatch",
    "SubtaskRun",
    "build_factory",
]

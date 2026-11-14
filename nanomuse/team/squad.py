"""A sub-agent squad: one steward, three specialists, one approval gate.

The squad is an OPTIONAL mode.  By default nanoMuse runs a single
steward; a squad only exists when the caller builds one.  Inside a
squad, a coordinator fans work out to three specialists (research,
execute, verify) and the specialists talk back over frames shaped like
Hub frames, so the same wire shape carries both device to device and
agent to agent traffic.

The one rule that may never bend: approvals belong to the steward
alone.  A specialist cannot request an approval, cannot answer one,
and cannot run a sensitive action without an approval token the
steward issued.  Every refusal is written to the squad audit log, so a
bypass attempt leaves evidence even when it fails.

Every frame also carries a provenance envelope: where the work came
from (``origin``), what it is for (``reason``), and the authority it
speaks with (``authority``): ``user`` for words spoken for the user,
``information`` for reports and findings, ``external`` for content
that arrived from outside.  The envelope defaults to the weakest
reading (an unnamed origin, ``information``), and a subtask's system
prompt repeats the rule the envelope encodes: outside content is
information, never instructions.

A squad may also carry a task ledger (``nanomuse.team.store``).  With
one attached, each dispatch is written down as an assignment under a
root for the squad, past the ledger's enqueue guards: a dispatch the
guards refuse (a duplicate brief still open, the root at its cap) is
not sent at all, and dispatch returns False for it just as it does
for an unknown role.  Without a store the squad is exactly the
in-memory Phase 4 shape, and nothing is recorded.

With a store, an agent factory (``nanomuse.team.runner``) and
``execute`` on, a dispatch also runs: the assignment moves from
queued to running, a fresh agent is built for the role's preset
(``nanomuse.team.presets``), and its answer settles the assignment,
with a result frame back to the steward carrying the assignment id
and a short summary.  The full summary lives in the ledger, capped
there as everywhere.  Two tightenings ride along:

- the default mode of a dispatch is ``consult``: ask, do not act.  A
  consult assignment runs read-only whatever role it was given; only
  a body that says ``mode`` is ``work`` lets the execute preset use
  its full tool face.
- ``notify`` assignments are recorded and never run by the squad:
  there is no notification executor here, and the ledger says so by
  leaving them queued.

Execution is off unless all three pieces are present (store, factory,
``execute``), and neither the server nor the companion forms an
executing squad yet: the wiring exists for callers that build one.
"""

from __future__ import annotations

import asyncio
import json
import secrets
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from nanomuse.logger import logger
from nanomuse.team.presets import effective_preset, preset_for
from nanomuse.team.store import (
    MODES,
    AlreadySettled,
    Assignment,
    EnqueueRefused,
    InvalidTransition,
    SquadStore,
)

if TYPE_CHECKING:
    from nanomuse.team.runner import AgentFactory, SubtaskRun

# The authority a frame speaks with: the user's own words, a report
# that only informs, or content that arrived from outside.
AUTHORITIES = ("user", "information", "external")


class SquadRefusal(RuntimeError):
    """A specialist tried to do something only the steward may do."""


@dataclass(frozen=True)
class SquadFrame:
    """One message on the squad bus, shaped like a Hub frame.

    The last three fields are the provenance envelope (see the module
    docstring).  They default to the weakest reading, so a frame built
    the Phase 4 way claims no authority it was not given.
    """

    kind: str  # "call" | "event" | "result"
    sender: str
    recipient: str
    action: str
    body: dict[str, Any] = field(default_factory=dict)
    origin: str = ""
    reason: str = ""
    authority: str = "information"

    def __post_init__(self) -> None:
        if self.authority not in AUTHORITIES:
            raise ValueError(f"authority must be one of {AUTHORITIES}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.kind,
            "from": self.sender,
            "to": self.recipient,
            "action": self.action,
            "body": self.body,
            "origin": self.origin,
            "reason": self.reason,
            "authority": self.authority,
        }


class SquadBus:
    """In-memory frame bus.  Frames are delivered in order, to the
    named recipient only; a frame addressed to nobody in the squad is
    dropped and counted, never broadcast."""

    def __init__(self) -> None:
        self._inboxes: dict[str, list[SquadFrame]] = {}
        self.dropped: int = 0

    def register(self, member_id: str) -> None:
        self._inboxes.setdefault(member_id, [])

    def send(self, frame: SquadFrame) -> bool:
        inbox = self._inboxes.get(frame.recipient)
        if inbox is None:
            self.dropped += 1
            return False
        inbox.append(frame)
        return True

    def drain(self, member_id: str) -> list[SquadFrame]:
        inbox = self._inboxes.setdefault(member_id, [])
        frames = list(inbox)
        inbox.clear()
        return frames


@dataclass
class ApprovalToken:
    """Proof the steward approved one sensitive action, once."""

    token: str
    action: str
    target: str
    issued_to: str
    used: bool = False


class ApprovalGate:
    """The steward's approval desk.

    Only the steward's identity may request or answer approvals, and
    only a token this gate issued (unused, for this action and target,
    to this specialist) unlocks a sensitive action.  A forged token, a
    reused token, or a token presented by the wrong specialist is
    refused, and the refusal is audited.
    """

    STEWARD = "steward"

    def __init__(self) -> None:
        self._tokens: dict[str, ApprovalToken] = {}
        self.audit: list[dict[str, Any]] = []

    def _log(self, event: str, actor: str, detail: str) -> None:
        self.audit.append(
            {"seq": len(self.audit), "event": event, "actor": actor, "detail": detail}
        )

    def request_approval(self, actor: str, action: str, target: str) -> ApprovalToken:
        if actor != self.STEWARD:
            self._log("approval_request_refused", actor, f"{action}:{target}")
            raise SquadRefusal(f"only the steward may request an approval, not {actor!r}")
        token = ApprovalToken(
            token=secrets.token_hex(16),
            action=action,
            target=target,
            issued_to=self.STEWARD,
        )
        self._tokens[token.token] = token
        self._log("approval_issued", actor, f"{action}:{target}")
        return token

    def issue_to(self, actor: str, token: ApprovalToken, specialist: str) -> ApprovalToken:
        """Hand a steward-issued token to one specialist for one action."""
        if actor != self.STEWARD:
            self._log("approval_handoff_refused", actor, specialist)
            raise SquadRefusal("only the steward may hand an approval to a specialist")
        handed = ApprovalToken(
            token=token.token,
            action=token.action,
            target=token.target,
            issued_to=specialist,
        )
        self._tokens[token.token] = handed
        return handed

    def confirm(self, actor: str, token_value: str) -> bool:
        """The steward confirms an approval.  Anyone else is refused."""
        if actor != self.STEWARD:
            self._log("approval_confirm_refused", actor, token_value[:8])
            raise SquadRefusal(f"only the steward may confirm an approval, not {actor!r}")
        return token_value in self._tokens

    def run_sensitive(self, actor: str, token_value: str, action: str, target: str) -> bool:
        """Run a sensitive action only with a live token for this actor,
        action and target.  A valid token is spent on use."""
        token = self._tokens.get(token_value)
        if (
            token is None
            or token.used
            or token.issued_to != actor
            or token.action != action
            or token.target != target
        ):
            self._log("sensitive_action_refused", actor, f"{action}:{target}")
            return False
        token.used = True
        self._log("sensitive_action_run", actor, f"{action}:{target}")
        return True


@dataclass
class Specialist:
    """One squad member.  Specialists do work; they never approve."""

    member_id: str
    role: str  # "research" | "execute" | "verify"
    bus: SquadBus

    def report(
        self,
        recipient: str,
        action: str,
        body: dict[str, Any],
        *,
        origin: str = "",
        reason: str = "",
        authority: str = "information",
    ) -> bool:
        return self.bus.send(
            SquadFrame(
                kind="event",
                sender=self.member_id,
                recipient=recipient,
                action=action,
                body=body,
                origin=origin,
                reason=reason,
                authority=authority,
            )
        )


def _task_text(action: str, body: dict[str, Any]) -> str:
    """The prompt a dispatched subtask runs on: the body's ``task``
    (or ``prompt``) when it carries one, else the action itself, with
    the rest of the body as context from the steward."""
    task = str(body.get("task") or body.get("prompt") or action)
    extra = {
        key: value for key, value in body.items() if key not in ("mode", "task", "prompt", "reason")
    }
    if extra:
        task += "\n\nContext from the steward: " + json.dumps(
            extra, ensure_ascii=False, default=str
        )
    return task


class Squad:
    """Coordinator plus three specialists, defaulting to no squad at all.

    ``Squad.single()`` is the default mode: no bus, no specialists, the
    steward alone.  ``Squad.form()`` builds the optional squad mode.

    ``store`` attaches the task ledger (see the module docstring);
    ``origin`` names where the squad's work comes from in that ledger.
    ``execute`` and ``factory`` together switch dispatch from
    recording to running: both are needed, with a store, before any
    assignment is run.
    """

    ROLES = ("research", "execute", "verify")

    def __init__(
        self,
        *,
        formed: bool,
        store: SquadStore | None = None,
        origin: str = "user",
        execute: bool = False,
        factory: AgentFactory | None = None,
    ) -> None:
        self.formed = formed
        self.bus = SquadBus()
        self.gate = ApprovalGate()
        self.specialists: dict[str, Specialist] = {}
        self.created_at = time.time()
        self.store = store
        self.origin = origin
        self.execute = execute
        self.factory = factory
        self._root_id: str | None = None
        self._pending: set[asyncio.Task[None]] = set()
        if formed:
            self.bus.register(ApprovalGate.STEWARD)
            for role in self.ROLES:
                member_id = f"specialist:{role}"
                self.bus.register(member_id)
                self.specialists[role] = Specialist(member_id, role, self.bus)

    @classmethod
    def single(
        cls,
        *,
        store: SquadStore | None = None,
        execute: bool = False,
        factory: AgentFactory | None = None,
    ) -> Squad:
        return cls(formed=False, store=store, execute=execute, factory=factory)

    @classmethod
    def form(
        cls,
        *,
        store: SquadStore | None = None,
        origin: str = "user",
        execute: bool = False,
        factory: AgentFactory | None = None,
    ) -> Squad:
        return cls(formed=True, store=store, origin=origin, execute=execute, factory=factory)

    @property
    def root_assignment_id(self) -> str | None:
        """The ledger root this squad's dispatches hang under, once
        the first dispatch has opened it."""
        return self._root_id

    @property
    def pending_executions(self) -> int:
        """How many dispatched runs are still in flight."""
        return len(self._pending)

    def _record_dispatch(self, role: str, action: str, body: dict[str, Any]) -> Assignment | None:
        """Write one dispatch to the ledger and return its assignment.

        None means a guard refused it, in which case the frame is not
        sent either.  Only called when a store is attached.  A mode
        the body does not name (or names wrongly) is ``consult``: the
        default hand-out asks and does not act.
        """
        store = self.store
        assert store is not None
        try:
            if self._root_id is None:
                root = store.create_root(
                    origin=self.origin,
                    mode="work",
                    role=ApprovalGate.STEWARD,
                    brief="squad session",
                )
                self._root_id = root.id
            mode = body.get("mode")
            return store.enqueue(
                parent_id=self._root_id,
                origin=self.origin,
                mode=mode if mode in MODES else "consult",
                role=role,
                brief=action,
            )
        except EnqueueRefused:
            return None

    def dispatch(self, role: str, action: str, body: dict[str, Any]) -> bool:
        """The coordinator (steward side) sends work to one specialist.

        With execution on (see the class docstring) the run is also
        scheduled: on the caller's event loop when there is one, or
        run to completion first when there is not, so a synchronous
        caller never holds a dispatch that only pretends to run.
        """
        if not self.formed:
            return False
        specialist = self.specialists.get(role)
        if specialist is None:
            return False
        assignment: Assignment | None = None
        if self.store is not None:
            assignment = self._record_dispatch(role, action, body)
            if assignment is None:
                return False
        sent = self.bus.send(
            SquadFrame(
                kind="call",
                sender=ApprovalGate.STEWARD,
                recipient=specialist.member_id,
                action=action,
                body=body,
                origin=self.origin,
                reason=str(body.get("reason") or action),
                authority="user",
            )
        )
        if sent and assignment is not None and assignment.mode != "notify":
            self._schedule_execution(assignment, role, action, body)
        return sent

    # -------------------------------------------------------------- execution
    def _schedule_execution(
        self, assignment: Assignment, role: str, action: str, body: dict[str, Any]
    ) -> None:
        if not self.execute:
            return
        if self.factory is None:
            logger.warning(
                "squad execute is on but no agent factory was given;"
                " assignments will only be recorded"
            )
            return
        coro = self._run_assignment(assignment, role, action, body)
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            asyncio.run(coro)
            return
        task = loop.create_task(coro)
        self._pending.add(task)
        task.add_done_callback(self._pending.discard)

    async def wait_idle(self) -> None:
        """Wait for every scheduled run to finish (tests, shutdown)."""
        while self._pending:
            await asyncio.gather(*list(self._pending), return_exceptions=True)

    async def _run_assignment(
        self, assignment: Assignment, role: str, action: str, body: dict[str, Any]
    ) -> None:
        store = self.store
        factory = self.factory
        assert store is not None and factory is not None
        preset = effective_preset(preset_for(role), assignment.mode)
        try:
            store.transition(assignment.id, "running")
        except InvalidTransition:
            return  # settled or moved on elsewhere; nothing to run
        store.append_event(
            assignment.id,
            "execution_started",
            f"role {role}, mode {assignment.mode},"
            f" {'read-only' if preset.read_only else 'full'} tool face",
        )
        handle: SubtaskRun | None = None
        final = ""
        try:
            handle = factory(preset, assignment)
            final = await handle.run(_task_text(action, body))
        except Exception as exc:  # noqa: BLE001 - a failed run is a settled assignment
            logger.warning("squad subtask {} failed: {}", assignment.id, exc)
            settled = self._settle(assignment.id, "failed", outcome="error", result=str(exc))
            if settled is not None:
                self._report_result(assignment, role, action, settled)
            return
        watch = handle.watch if handle is not None else None
        if watch is not None:
            store.append_event(
                assignment.id,
                "tool_calls",
                f"{watch.calls} call(s), {watch.successes} successful",
            )
        if watch is not None and watch.stalled:
            store.append_event(assignment.id, "stalled", watch.stalled_reason)
            settled = self._settle(assignment.id, "failed", outcome="stalled", result=final)
        elif final:
            settled = self._settle(assignment.id, "completed", result=final)
        else:
            settled = self._settle(assignment.id, "failed", outcome="empty_result")
        if settled is not None:
            self._report_result(assignment, role, action, settled)

    def _settle(
        self, assignment_id: str, status: str, *, outcome: str = "", result: str = ""
    ) -> Assignment | None:
        """Settle, unless a reconcile settled the assignment first."""
        store = self.store
        assert store is not None
        try:
            return store.settle(assignment_id, status, outcome=outcome, result=result)
        except AlreadySettled:
            return store.get(assignment_id)

    def _report_result(
        self, assignment: Assignment, role: str, action: str, settled: Assignment
    ) -> None:
        """The result frame back to the steward: the pointer (the
        assignment id) and a short summary, never the full text."""
        self.bus.send(
            SquadFrame(
                kind="result",
                sender=f"specialist:{role}",
                recipient=ApprovalGate.STEWARD,
                action=action,
                body={
                    "assignment_id": assignment.id,
                    "status": settled.status,
                    "outcome": settled.outcome,
                    "summary": settled.result[:500],
                },
                origin=self.origin,
                reason=action,
                authority="information",
            )
        )

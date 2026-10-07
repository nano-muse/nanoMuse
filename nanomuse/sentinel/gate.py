"""The Sentinel: every tool call passes through here.

    agent  ──►  Sentinel.guard()  ──►  policy  ──►  grants / approval  ──►  vault.resolve
                                                                              │
    agent  ◄──  redact(result)  ◄──  taint bookkeeping  ◄──  execute  ◄───────┘

Nothing the model asks for reaches the outside world unless the Sentinel lets it. An
approval the user gives is a capability bound to a tool and a target (host, recipient,
program) with a lifetime — see :mod:`nanomuse.sentinel.grants`.
"""

from __future__ import annotations

import json
import time
import uuid
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from nanomuse.config import SentinelSettings
from nanomuse.logger import logger
from nanomuse.schema import RiskLevel, ToolCall, ToolResult
from nanomuse.sentinel.audit import AuditLog, channel_of
from nanomuse.sentinel.grants import Grant, GrantStore, grant_key, normalize_scope
from nanomuse.sentinel.policy import Decision, Policy
from nanomuse.tools.base import BaseTool, CallAssessment, safe_execute
from nanomuse.ui import UI, ApprovalRequest
from nanomuse.vault import PLACEHOLDER_RE, CredentialVault


@dataclass
class TaskContext:
    """The agent run a tool call belongs to: gives approvals a purpose, and the
    conversation the run is part of gives them their middle scope. A run outside any
    conversation (``nanomuse run``, a scheduled job) stands in for one itself."""

    id: str
    purpose: str = ""
    conversation: str = ""

    @property
    def conversation_id(self) -> str:
        return self.conversation or self.id


_current_task: ContextVar[TaskContext | None] = ContextVar("nanomuse_task", default=None)


def current_task() -> TaskContext | None:
    return _current_task.get()


class Sentinel:
    def __init__(
        self,
        settings: SentinelSettings,
        audit: AuditLog,
        ui: UI,
        vault: CredentialVault | None = None,
        persistent_approvals_file: Path | None = None,
    ):
        self.settings = settings
        self.policy = Policy(settings)
        self.audit = audit
        self.ui = ui
        self.vault = vault
        # private data was read in these conversations; per conversation, because one agent
        # loop per thread shares this Sentinel and clearing a side chat must not forget
        # what another conversation read
        self._tainted: set[str] = set()
        self.grants = GrantStore(persistent_approvals_file)

    # ------------------------------------------------------------------ taint
    @staticmethod
    def _taint_key() -> str:
        """The conversation the running call belongs to; a run outside any conversation
        stands in for one itself, as in :attr:`TaskContext.conversation_id`."""
        task = _current_task.get()
        return task.conversation_id if task else ""

    @property
    def tainted(self) -> bool:
        """Whether private data was read in the conversation of the call being assessed."""
        return self.tainted_for(self._taint_key())

    def tainted_for(self, conversation: str | None) -> bool:
        return (conversation or "") in self._tainted

    def tainted_any(self) -> bool:
        """For a status view that is not answering for one conversation."""
        return bool(self._tainted)

    def taint(self, conversation: str | None = None) -> None:
        cid = self._taint_key() if conversation is None else conversation
        if cid not in self._tainted:
            logger.debug("conversation {} is now tainted (read private data)", cid or "itself")
        self._tainted.add(cid)

    def untaint(self, conversation: str | None = None) -> None:
        self._tainted.discard(self._taint_key() if conversation is None else conversation)

    # ------------------------------------------------------------------ task scope
    def begin_task(
        self, purpose: str = "", task_id: str | None = None, conversation: str | None = None
    ) -> Any:
        """Mark the start of an agent run, within ``conversation`` when it has one.
        Returns a token for :meth:`end_task`."""
        ctx = TaskContext(
            id=task_id or uuid.uuid4().hex[:10],
            purpose=purpose.strip()[:200],
            conversation=(conversation or "").strip(),
        )
        return _current_task.set(ctx)

    def end_task(self, token: Any) -> None:
        """The run is over. Grants for *this conversation* stay while the conversation
        does (:meth:`end_conversation`); a run that stood in for one takes its own."""
        ctx = _current_task.get()
        if ctx is not None and not ctx.conversation:
            self.grants.end_conversation(ctx.id)
        _current_task.reset(token)

    def end_conversation(self, conversation_id: str) -> None:
        """A conversation was deleted or cleared: the approvals given for it go with it,
        and so does the memory that it read private data."""
        self.grants.end_conversation(conversation_id)
        self._tainted.discard(conversation_id or "")

    # ------------------------------------------------------------------ grants
    def forget_approvals(self) -> None:
        self.grants.clear()

    def revoke(self, key: str) -> bool:
        return self.grants.revoke(key)

    def active_grants(self) -> list[Grant]:
        ctx = _current_task.get()
        return self.grants.active(ctx.conversation_id if ctx else None)

    @staticmethod
    def grant_options(assessment: CallAssessment, target: str | None) -> list[str]:
        """Which standing permissions to offer. Calls with warnings get none: a
        dangerous-looking command or a purchase is approved every single time."""
        if assessment.warnings:
            return ["once"]
        options = ["once", "conversation"]
        unknown_destination = target is None and assessment.egress
        if unknown_destination and assessment.risk.rank >= RiskLevel.MODERATE.rank:
            return options  # arbitrary code with network access: never a standing grant
        options += ["session", "24h"]
        if target is not None or assessment.risk != RiskLevel.SENSITIVE:
            options.append("always")
        return options

    # ------------------------------------------------------------------ per-app permission
    APP_TOOL = "computer_app"

    async def allow_app(self, app_id: str, label: str = "", muse: str = "nanoMuse") -> bool:
        """The hands' first action in an application asks: "Let <Muse> use <App>?" — once,
        for this conversation, or always. The answer is a grant under
        ``computer_app:<bundle id or name>``, so the Permissions page lists and revokes it
        like any other, and ``[sentinel] mode = "auto"`` skips it like any other."""
        app_id = app_id.strip()[:120]
        if not app_id:
            return True
        label = label.strip()[:80] or app_id
        key = grant_key(self.APP_TOOL, app_id)
        task = _current_task.get()
        conversation = task.conversation_id if task else None
        if self.settings.mode == "auto":
            return True
        grant = self.grants.match(key, conversation)
        if grant is not None:
            return True
        request = ApprovalRequest(
            tool=self.APP_TOOL,
            args={"app": app_id, "name": label},
            summary=f"Let {muse} use {label}?",
            risk=RiskLevel.MODERATE,
            reasons=["the first action in this application"],
            purpose=task.purpose if task else "",
            target=app_id,
            grant_key=key,
            grant_options=["once", "conversation", "always"],
        )
        verdict = await self.ui.ask_approval(request)
        scope = normalize_scope(verdict.scope)
        if verdict.approved and scope in ("conversation", "always"):
            self.grants.add(self.APP_TOOL, app_id, scope, conversation)
        self.audit.record(
            "app_permission",
            tool=self.APP_TOOL,
            target=app_id,
            summary=request.summary,
            decision="allow" if verdict.approved else "deny",
            approved=verdict.approved,
            approval_scope=scope if verdict.approved else None,
            reasons=[] if verdict.approved else [verdict.reason or "user declined"],
            grant_key=key,
            purpose=task.purpose if task else "",
        )
        self.ui.on_sentinel(
            "allow" if verdict.approved else "deny",
            request.summary,
            [] if verdict.approved else [verdict.reason or "user declined"],
        )
        return bool(verdict.approved)

    # ------------------------------------------------------------------ main entry
    async def guard(self, call: ToolCall, tool: BaseTool) -> ToolResult:
        args = call.arguments
        if "__raw__" in args:
            # The arguments never parsed (cut off in transit): there is nothing to assess,
            # nothing to approve and nothing to run. The result tells the model what happened.
            return await safe_execute(tool, args)
        try:
            assessment = tool.assess(args)
        except Exception as exc:  # noqa: BLE001
            # assess() reads the model's arguments before anything is approved or run; an
            # argument of the wrong shape (a list for a path, a dict for a number) must be
            # one failed call the model can correct, not the end of the turn.
            logger.warning("{} assess() refused the arguments: {}", tool.name, exc)
            return ToolResult.fail(
                f"bad arguments for {tool.name}: {type(exc).__name__}: {str(exc)[:200]}"
            )
        target = assessment.target if assessment.target is not None else assessment.egress_target
        key = grant_key(tool.name, target)
        task = _current_task.get()
        result_policy = self.policy.evaluate(tool.name, args, assessment, tainted=self.tainted)
        decision, reasons = result_policy.decision, list(result_policy.reasons)
        approved: bool | None = None
        scope: str | None = None

        if decision == Decision.ASK:
            grant = (
                None
                if assessment.warnings
                else self.grants.match(key, task.conversation_id if task else None)
            )
            # auto mode skips the question, except for a call that carries a warning or
            # one that would send data private to this conversation out to a host nobody
            # allowlisted: steps 6 and 5 of the policy keep those an ASK whatever the
            # mode, and the gate honours it (docs/sentinel.md), so an unattended pass asks
            # or stops rather than reading a file and mailing it somewhere
            waved_through = assessment.warnings or result_policy.tainted_ask
            if self.settings.mode == "auto" and not waved_through:
                decision = Decision.ALLOW
                reasons.append("auto mode: approval skipped")
            elif grant is not None:
                decision = Decision.ALLOW
                scope = grant.scope
                reasons.append(f"covered by your '{grant.scope}' permission for {grant.key}")
            else:
                options = self.grant_options(assessment, target)
                request = ApprovalRequest(
                    tool=tool.name,
                    args=args,
                    summary=assessment.summary,
                    risk=assessment.risk,
                    reasons=reasons,
                    warnings=assessment.warnings,
                    egress_target=assessment.egress_target,
                    purpose=task.purpose if task else "",
                    target=target,
                    grant_key=key,
                    grant_options=options,  # type: ignore[arg-type]
                )
                verdict = await self.ui.ask_approval(request)
                approved, scope = verdict.approved, normalize_scope(verdict.scope)
                if verdict.approved:
                    decision = Decision.ALLOW
                    if scope not in options:
                        logger.warning(
                            "scope '{}' was not offered for {}; treating as once", scope, key
                        )
                        scope = "once"
                    bind = target
                    if scope == "conversation" and assessment.egress_target is None:
                        # "For this conversation" on a tool whose target is not a destination
                        # (shell, where it is the list of programs) means the tool for the rest
                        # of the conversation: a job that needs `git` now will need `ls` and
                        # `wc` next, and asking for each new program is noise, not safety.
                        # Warnings still stop every call; destinations (mail recipients,
                        # hosts) stay bound.
                        bind = None
                    self.grants.add(tool.name, bind, scope, task.conversation_id if task else None)
                else:
                    decision = Decision.DENY
                    reasons.append(
                        f"user declined{': ' + verdict.reason if verdict.reason else ''}"
                    )

        self.ui.on_sentinel(decision.value, assessment.summary, reasons)
        redacted_args = self._redact_obj(args)

        if decision == Decision.DENY:
            why = "; ".join(reasons) or "policy"
            result = ToolResult.fail(
                f"Sentinel blocked '{tool.name}': {why}. Do not retry the same call; "
                "explain the situation to the user or choose a different approach."
            )
            self.audit.record(
                "tool_call",
                tool=tool.name,
                channel=channel_of(tool.name),
                args=redacted_args,
                summary=assessment.summary,
                risk=assessment.risk.value,
                decision="deny",
                approved=approved,
                reasons=reasons,
                tainted=self.tainted,
                egress_target=assessment.egress_target,
                grant_key=key,
                purpose=task.purpose if task else "",
                ok=False,
                error=result.error,
            )
            return result

        # Resolve vault placeholders only for tools that opted in. No production tool does
        # (shell, python_execute and the rest run with the literal text otherwise, which is
        # never what was meant), so the call is refused with the reason rather than run.
        exec_args: dict[str, Any] = args
        if self.vault is not None and self.vault.has_placeholders(args):
            if tool.accepts_secrets:
                try:
                    exec_args = self.vault.resolve(args)
                except Exception as exc:  # noqa: BLE001
                    return ToolResult.fail(str(exc))
            else:
                logger.warning(
                    "tool '{}' received vault placeholders but does not accept secrets", tool.name
                )
                result = ToolResult.fail(
                    f"'{tool.name}' does not take {{{{vault:NAME}}}} placeholders: secrets from the "
                    "vault reach only the connectors configured with them (mail, calendars, the "
                    "model), never a command or a script. Do without the secret, or ask the "
                    "person to use a connector that has it."
                )
                self.audit.record(
                    "tool_call",
                    tool=tool.name,
                    channel=channel_of(tool.name),
                    args=redacted_args,
                    summary=assessment.summary,
                    risk=assessment.risk.value,
                    decision="deny",
                    approved=approved,
                    reasons=["vault placeholder in a tool that takes none"],
                    tainted=self.tainted,
                    egress_target=assessment.egress_target,
                    grant_key=key,
                    purpose=task.purpose if task else "",
                    ok=False,
                    error=result.error,
                )
                return result

        started = time.perf_counter()
        result = await safe_execute(tool, exec_args)
        duration_ms = int((time.perf_counter() - started) * 1000)

        if self.vault is not None:
            result.output = self.vault.redact(result.output)
            if result.error:
                result.error = self.vault.redact(result.error)

        if assessment.reads_private_data and result.ok and self.settings.taint_tracking:
            self.taint()

        self.audit.record(
            "tool_call",
            tool=tool.name,
            channel=channel_of(tool.name),
            args=redacted_args,
            summary=assessment.summary,
            risk=assessment.risk.value,
            decision="allow",
            approved=approved,
            approval_scope=scope,
            reasons=reasons,
            tainted=self.tainted,
            egress_target=assessment.egress_target,
            grant_key=key,
            purpose=task.purpose if task else "",
            ok=result.ok,
            error=result.error,
            duration_ms=duration_ms,
            output_preview=result.output[:300] if result.output else "",
        )
        return result

    # ------------------------------------------------------------------ helpers
    def _redact_obj(self, value: Any) -> Any:
        text = json.dumps(value, ensure_ascii=False, default=str)
        if self.vault is not None:
            text = self.vault.redact(text)
        # placeholders are fine to log as-is; make sure raw values never sneak in
        text = PLACEHOLDER_RE.sub(lambda m: "{{vault:" + m.group(1) + "}}", text)
        try:
            return json.loads(text)
        except json.JSONDecodeError:  # pragma: no cover
            return text


__all__ = ["Sentinel", "TaskContext", "current_task"]

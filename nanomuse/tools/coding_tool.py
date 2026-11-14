"""``coding_agents``: the user's Cursor / Codex / Claude Code sessions, here or on another
computer of theirs, and a way to send a message into one.

The Muse uses it when the person asks what their coding agent is doing ("is Cursor done
with the refactor?"), wants the gist of a session, or wants to tell the agent something
from wherever they are ("tell Codex to also add tests"). Reading is safe; sending a message
starts work on that computer, so it is moderate risk and shows up as an approval when the
sentinel asks for one.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from pydantic import ConfigDict

from nanomuse.schema import RiskLevel, ToolResult
from nanomuse.tools.base import BaseTool, CallAssessment

if TYPE_CHECKING:
    from nanomuse.coding.service import CodingService


def _json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, default=str)


class CodingAgents(BaseTool):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    name: str = "coding_agents"
    purpose: str = "Run one of the user's coding agents on a coding job in a repository."
    keywords: list[str] = ["code", "coding agent", "cursor", "codex", "repository"]
    description: str = (
        "The user's coding agents (Cursor, Codex, Claude Code, DeepSeek Harness as `dsh`) on "
        "this computer or on another of their computers (`device`). Actions: `agents` (which "
        "are installed, how many are "
        "running), `sessions` (recent chats: title, workspace, when, whether one is running now; "
        "optional `agent`, `workspace`), `session` (one chat's transcript; needs `agent` and "
        "`session_id`), `send` (a message into a chat: `agent`, `text`, and `session_id` to "
        "continue one or `workspace` to start a new one; the agent works on it there and the "
        "reply comes back when it is done), `runs` (messages sent this way and how they went), "
        "`stop` (`run_id`). Prefer `sessions` then `session` to answer questions about what an "
        "agent did; `send` only when the user asks to tell the agent something."
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["agents", "sessions", "session", "send", "runs", "stop"],
            },
            "agent": {"type": "string", "enum": ["cursor", "codex", "claude", "dsh"]},
            "session_id": {"type": "string"},
            "workspace": {
                "type": "string",
                "description": "a project folder, to filter or to start in",
            },
            "text": {"type": "string", "description": "for send: the message, in the user's words"},
            "run_id": {"type": "string"},
            "device": {
                "type": "string",
                "description": "another computer of the user's, by the name `devices` lists; omit for this one",
            },
            "limit": {"type": "integer"},
        },
        "required": ["action"],
    }
    risk: RiskLevel = RiskLevel.SAFE
    coding: Any  # CodingService

    def assess(self, args: dict[str, Any]) -> CallAssessment:
        a = super().assess(args)
        action = str(args.get("action") or "?")
        agent = str(args.get("agent") or "")
        where = f" on {args['device']}" if args.get("device") else ""
        if action == "send":
            # the agent then runs with the permissions it has on that computer (edits,
            # commands, the network): the same level as `shell`, as docs/coding-agents.md says
            a.risk = RiskLevel.SENSITIVE
            folder = f" in {args['workspace']}" if args.get("workspace") else ""
            a.summary = (
                f"tell {agent or 'the coding agent'}{where}{folder}: "
                f"{str(args.get('text') or '')[:60]}"
            )
        elif action == "stop":
            a.risk = RiskLevel.MODERATE
            a.summary = f"stop coding run {args.get('run_id', '')}{where}"
        else:
            a.summary = f"coding agents {action}{(' ' + agent) if agent else ''}{where}"
        return a

    async def execute(
        self,
        action: str = "",
        agent: str = "",
        session_id: str = "",
        workspace: str = "",
        text: str = "",
        run_id: str = "",
        device: str = "",
        limit: int = 0,
        **_: Any,
    ) -> ToolResult:
        from nanomuse.coding.service import CodingError

        coding: CodingService = self.coding
        try:
            if device:
                return await self._remote(
                    coding, device, action, agent, session_id, workspace, text, run_id, limit
                )
            if action == "agents":
                return ToolResult(output=_json({"agents": coding.agents()}))
            if action == "sessions":
                rows = coding.sessions(agent or None, limit or 15, workspace or None)
                slim = [
                    {
                        k: s[k]
                        for k in (
                            "agent",
                            "id",
                            "title",
                            "workspace",
                            "updated_at",
                            "status",
                            "messages",
                            "last_assistant",
                        )
                    }
                    for s in rows
                ]
                return ToolResult(output=_json({"sessions": slim}))
            if action == "session":
                if not (agent and session_id):
                    return ToolResult.fail("`agent` and `session_id` are required")
                s = coding.session(agent, session_id)
                s["transcript"] = s.get("transcript", [])[-40:]
                return ToolResult(output=_json(s))
            if action == "send":
                if not (agent and text):
                    return ToolResult.fail("`agent` and `text` are required")
                run = await coding.send(
                    agent, text, session_id=session_id, workspace=workspace, wait=True
                )
                return ToolResult(output=_json(_slim_run(run)))
            if action == "runs":
                return ToolResult(
                    output=_json({"runs": [_slim_run(r) for r in coding.list_runs(limit or 10)]})
                )
            if action == "stop":
                if not run_id:
                    return ToolResult.fail("`run_id` is required")
                return ToolResult(output=_json({"stopped": coding.stop(run_id)}))
            return ToolResult.fail(f"unknown action {action!r}")
        except CodingError as exc:
            return ToolResult.fail(f"{exc.message} ({exc.code})")

    async def _remote(
        self,
        coding: CodingService,
        device: str,
        action: str,
        agent: str,
        session_id: str,
        workspace: str,
        text: str,
        run_id: str,
        limit: int,
    ) -> ToolResult:
        args: dict[str, Any] = {
            "agent": agent,
            "session_id": session_id,
            "workspace": workspace,
            "limit": limit or None,
        }
        if action == "send":
            args.update({"text": text, "wait": True})
        if action == "stop":
            args["run"] = run_id
        result = await coding.remote(
            device, f"coding.{action}", {k: v for k, v in args.items() if v}
        )
        if action == "session" and isinstance(result.get("transcript"), list):
            result["transcript"] = result["transcript"][-40:]
        if action == "sessions" and isinstance(result.get("sessions"), list):
            result["sessions"] = [
                {
                    k: s.get(k)
                    for k in (
                        "agent",
                        "id",
                        "title",
                        "workspace",
                        "updated_at",
                        "status",
                        "messages",
                        "last_assistant",
                    )
                }
                for s in result["sessions"]
            ]
        return ToolResult(output=_json(result))


def _slim_run(run: dict[str, Any]) -> dict[str, Any]:
    out = {
        k: run.get(k)
        for k in (
            "id",
            "agent",
            "session_id",
            "status",
            "resumed",
            "error",
            "tools",
            "started_at",
            "ended_at",
        )
    }
    out["output"] = str(run.get("output") or "")[-4000:]
    return out


__all__ = ["CodingAgents"]

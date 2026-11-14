"""Tool base classes.

Every capability the agent has is a :class:`BaseTool`. Besides the JSON schema
the model sees, a tool declares *how dangerous it is* so the Sentinel can decide
whether to run it, ask the user, or refuse:

* ``risk`` – static default risk level (see :class:`~nanomuse.schema.RiskLevel`)
* ``purpose`` / ``keywords`` – one line saying what the tool is for, and the words
  a person would use for it. The tool bridge's index searches these (and the
  description) when the full tool list is not on the call; a tool without a
  ``purpose`` is indexed by the first line of its description.
* ``reads_private_data`` – executing it exposes the user's private data to the
  model (emails, files, memories). Once that happened the session is *tainted*.
* ``egress`` – it can send data out of the machine (network, email...).
* ``accepts_secrets`` – ``{{vault:NAME}}`` placeholders in its arguments are
  resolved to real secrets right before execution (the model never sees them).

Tools may refine these per call by overriding :meth:`assess`.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from nanomuse.logger import logger
from nanomuse.schema import STEP_KEY, RiskLevel, ToolResult


class CallAssessment(BaseModel):
    """Per-call risk assessment handed to the Sentinel."""

    risk: RiskLevel = RiskLevel.SAFE
    reads_private_data: bool = False
    egress: bool = False
    # Network destination (hostname) if known, e.g. "example.com". ``None`` with
    # ``egress=True`` means "unknown destination" (shell, python...).
    egress_target: str | None = None
    # The destination was set by the owner in the settings (the search provider, the
    # mail server), not chosen by the model: taint tracking treats it like the allowlist.
    egress_configured: bool = False
    # What a standing approval for this call should be bound to: a host, a recipient, a
    # program name. Defaults to ``egress_target``; ``None`` means "the whole tool".
    target: str | None = None
    # One-line, human-readable description shown in approval prompts / audit log.
    summary: str = ""
    # Extra warnings ("command contains rm -rf", ...).
    warnings: list[str] = Field(default_factory=list)


def with_step(parameters: dict[str, Any]) -> dict[str, Any]:
    """The tool's schema with the shared ``step`` words added (a copy; the tool's own stays)."""
    props = parameters.get("properties")
    if not isinstance(props, dict) or STEP_KEY in props:
        return parameters
    return {**parameters, "properties": {**props, STEP_KEY: STEP_PARAM}}


def short_json(args: dict[str, Any], limit: int = 200) -> str:
    text = json.dumps(args, ensure_ascii=False, default=str)
    return text if len(text) <= limit else text[: limit - 3] + "..."


def number_arg(value: Any, default: float, low: float, high: float) -> float:
    """A number the model passed (``"30"``, ``30``, ``None``, ``"ten"``), clamped to
    ``[low, high]``; anything that is not a number is the default. Models write numbers as
    strings often enough that a raw ``float(value)`` is a crash waiting to happen."""
    if value is None or isinstance(value, bool):
        n = float(default)
    elif isinstance(value, int | float):
        n = float(value)
    else:
        try:
            n = float(str(value).strip())
        except ValueError:
            n = float(default)
    if n != n:  # NaN
        n = float(default)
    return max(low, min(n, high))


def int_arg(value: Any, default: int, low: int, high: int) -> int:
    """:func:`number_arg` for whole numbers."""
    return int(number_arg(value, default, low, high))


# The one argument every tool shares, for the person rather than the tool: see ``STEP_KEY``.
STEP_PARAM: dict[str, Any] = {
    "type": "string",
    "description": (
        "What this step does, for the person watching: a few words in their language, "
        "e.g. '打开携程网站' or 'Check the login page'. Shown under your avatar while the "
        "tool runs. Always fill it in."
    ),
}


class BaseTool(ABC, BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    name: str
    description: str
    parameters: dict[str, Any] = Field(default_factory=lambda: {"type": "object", "properties": {}})

    # The searchable face of the tool, for the tool bridge's index: one line
    # saying what the tool is for, and the words a person would use for it.
    purpose: str = ""
    keywords: list[str] = Field(default_factory=list)

    risk: RiskLevel = RiskLevel.SAFE
    reads_private_data: bool = False
    egress: bool = False
    accepts_secrets: bool = False

    async def __call__(self, **kwargs: Any) -> ToolResult:
        return await self.execute(**kwargs)

    @abstractmethod
    async def execute(self, **kwargs: Any) -> ToolResult:
        """Run the tool. Must not raise for expected failures – return ``ToolResult.fail``."""

    def to_param(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": with_step(self.parameters),
            },
        }

    def assess(self, args: dict[str, Any]) -> CallAssessment:
        return CallAssessment(
            risk=self.risk,
            reads_private_data=self.reads_private_data,
            egress=self.egress,
            summary=f"{self.name}({short_json(args)})",
        )

    def family_risk(self, args: dict[str, Any]) -> RiskLevel:
        """The declared risk of the family this call belongs to.

        The squad ceiling measures a call it counts as a read at this
        level rather than at the call's own assessment (see
        ``nanomuse.team.presets.assessed_risk``). Every tool's family
        is itself; an envelope tool, the tool bridge's ``use_tool``,
        speaks for the tool it names and answers with that tool's
        level instead, so the ceiling measures the named call and
        not the envelope around it.
        """
        return self.risk

    async def cleanup(self) -> None:  # pragma: no cover - default no-op
        return None


async def safe_execute(tool: BaseTool, args: dict[str, Any] | None = None) -> ToolResult:
    """Run a tool, converting every failure into a :class:`ToolResult` error."""
    args = args or {}
    if "__raw__" in args:
        raw = str(args["__raw__"])
        hint = (
            " The JSON stops mid-way, so the arguments were probably cut off in transit: "
            "call the tool again with less content at a time (write the file in parts with "
            "`append`, or generate it with python_execute)."
            if len(raw) > 1000
            else ""
        )
        return ToolResult.fail(
            f"arguments for {tool.name} were not valid JSON ({len(raw)} chars): "
            f"...{raw[-120:]}{hint}"
        )
    try:
        result = await tool.execute(**args)
    except TypeError as exc:
        # raised by the call itself (an unknown or missing argument): the traceback has
        # this frame only; a TypeError from inside the tool is a crash like any other
        tb = exc.__traceback__
        if tb is not None and tb.tb_next is None:
            return ToolResult.fail(f"bad arguments for {tool.name}: {exc}")
        logger.exception("tool {} crashed", tool.name)
        return ToolResult.fail(f"TypeError: {exc}")
    except Exception as exc:  # noqa: BLE001 – tools must never crash the loop
        logger.exception("tool {} crashed", tool.name)
        return ToolResult.fail(f"{type(exc).__name__}: {exc}")
    if not isinstance(result, ToolResult):
        # third-party tools do not always honour the signature
        result = ToolResult(output=str(result))  # type: ignore[unreachable]
    return result


class ToolCollection:
    """An ordered, name-addressable set of tools."""

    def __init__(self, *tools: BaseTool):
        self.tools: list[BaseTool] = []
        self.tool_map: dict[str, BaseTool] = {}
        self.add(*tools)

    def add(self, *tools: BaseTool) -> ToolCollection:
        for tool in tools:
            if tool.name in self.tool_map:
                logger.warning("tool '{}' already registered; replacing", tool.name)
                self.tools = [t for t in self.tools if t.name != tool.name]
            self.tools.append(tool)
            self.tool_map[tool.name] = tool
        return self

    def remove(self, name: str) -> None:
        self.tool_map.pop(name, None)
        self.tools = [t for t in self.tools if t.name != name]

    def get(self, name: str) -> BaseTool | None:
        return self.tool_map.get(name)

    def to_params(self) -> list[dict[str, Any]]:
        return [t.to_param() for t in self.tools]

    async def execute(self, name: str, args: dict[str, Any] | None = None) -> ToolResult:
        tool = self.get(name)
        if tool is None:
            return ToolResult.fail(f"unknown tool: {name}")
        return await safe_execute(tool, args)

    async def cleanup(self) -> None:
        for tool in self.tools:
            try:
                await tool.cleanup()
            except Exception as exc:  # noqa: BLE001
                logger.warning("cleanup of {} failed: {}", tool.name, exc)

    def __iter__(self):
        return iter(self.tools)

    def __len__(self) -> int:
        return len(self.tools)

    def __contains__(self, name: object) -> bool:
        return name in self.tool_map


__all__ = [
    "STEP_PARAM",
    "BaseTool",
    "CallAssessment",
    "ToolCollection",
    "int_arg",
    "number_arg",
    "safe_execute",
    "short_json",
    "with_step",
]

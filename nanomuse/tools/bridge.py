"""The tool bridge: a short tool list per call, the rest reachable by name.

The tool list is part of every model call, in full, schemas and all.
As the tool surface grows (devices, memory, mail, the browser),
that list eats the context window of exactly the models with the
least room to spare.  The bridge is the answer this codebase takes
from the find/use pattern: with it on, the list on each call keeps a
small direct core plus two meta tools, and the rest of the tools are
found and run by name:

- ``find_tools(query)`` searches an in-memory index over the bridged
  tools (name, one-line purpose, keywords, description; plain word
  matching, no service and no embeddings) and returns the full
  schema of the best three matches.  No match is an explicit answer,
  never a near miss dressed up as one: the result says there is no
  such tool and names what can be reached instead.
- ``use_tool(name, arguments)`` runs one named tool.  It does not
  have an execution path of its own: it builds the same
  :class:`~nanomuse.schema.ToolCall` the agent loop builds and hands
  it to the same Sentinel the loop hands its calls to, with the real
  tool object.  Policy, gatekeeper, grants, vault handling, taint
  and the audit record are therefore not similar to a direct call;
  they are the same code, reached the same way.

That sameness is the design's load-bearing fact.  In a design where
approval happens when a tool is *listed*, deciding by name at call
time would need the bridge banned; here approval happens at the
execution point, per call, with the tool's own assessment, so a call
that arrives by name is judged exactly as one that arrives from the
list.  (A bridged call passes the guard twice over, once as
``use_tool``, whose assessment is the target call's own, and once as
the target; an approval can therefore be asked for twice, never
zero times.)

What never travels the bridge, and stays direct, always:

- sending tools: mail going out, a notification shown on another
  device, a task handed to another device's Muse.  They are named
  in :data:`EXEMPT_NAMES`, and a word-level backstop
  (:func:`exempt_reason`) exempts any tool, present or future, whose
  name carries a sending word (send, notify, publish), because a
  list can be forgotten and the class cannot.  The tools' risk
  annotations carry no sender flag to lean on instead: a
  notification's own assessment does not even mark egress.  The
  name is the honest signal there is.
- anything named like the approval machinery itself (sentinel,
  gatekeeper, grant, approval): deciding about the decider by name
  through a bridge is the one shape this design refuses outright.

The rest of the classification is an explicit registry
(:data:`DIRECT_NAMES`, :data:`BRIDGED_NAMES`): a test walks every
tool class the runtime ships and fails if a name is in no set, so a
new tool cannot drift in unclassified.  Tools whose names are made
at run time (an MCP server's, the phone's own ``device__`` tools)
are classified by the same rules: the backstops first, then the
bridge as the default, since the long tail is what the bridge is
for.

The switch is one function (:func:`bridge_active`) over the
``[tool_bridge]`` settings, and it is off by default: off, the
agent's tool list is byte for byte what it has always been.  The
bridge is built once, when the agent is built, so within one
conversation the list on every call is the same bytes; turning the
setting over mid-conversation is not a thing that happens.

Why the bridge exists, stated plainly so nobody oversells it later:
it buys context room for small-window and cheap models.  It does
not save money: a bridged call costs what a direct call costs, and
looking a tool up first costs one short schema listing extra.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from enum import Enum
from typing import Any, Protocol

from pydantic import PrivateAttr

from nanomuse.config import Settings, ToolBridgeSettings
from nanomuse.schema import Function, RiskLevel, ToolCall, ToolResult
from nanomuse.tools.base import BaseTool, CallAssessment, ToolCollection


class GuardLike(Protocol):
    """What ``use_tool`` dispatches through: the Sentinel's one entry point."""

    async def guard(self, call: ToolCall, tool: BaseTool) -> ToolResult: ...


class BridgeClass(Enum):
    """Where a tool sits when the bridge is on."""

    DIRECT = "direct"  # on the list, as always
    BRIDGED = "bridged"  # reachable through find_tools / use_tool only
    EXEMPT = "exempt"  # never travels the bridge; direct by rule, not by size


#: The bridge's own two tools. They are the face of the bridge, so
#: they are direct by construction; classifying them as bridged
#: would make the bridge unreachable.
META_NAMES: frozenset[str] = frozenset({"find_tools", "use_tool"})

#: The direct core: the conversation controls and the tools the
#: runtime's own messages name (the loop tells the model to call
#: ``terminate``; an attachment note tells it to read with ``files``),
#: plus the everyday workspace, command and web tools a task reaches
#: for without thinking. Everything else is the long tail the bridge
#: exists for.
DIRECT_NAMES: frozenset[str] = frozenset(
    {
        "terminate",
        "ask_user",
        "files",
        "shell",
        "python_execute",
        "web_search",
        "web_fetch",
    }
)

#: Sending tools, named one by one. These leave the machine in the
#: user's name; they are decided by their own name, every time, and
#: never hidden behind a lookup. ``delegate`` is here because it
#: hands work to another device and waits on it: an outward dispatch
#: of the same kind, and one whose whole point is which device it
#: names.
EXEMPT_NAMES: frozenset[str] = frozenset({"send_email", "device_notify", "delegate"})

#: Every other tool the runtime ships today, by name. A test walks
#: the shipped tool classes and fails on a name that is in no set,
#: so this list cannot quietly rot.
BRIDGED_NAMES: frozenset[str] = frozenset(
    {
        "browser",
        "calendar",
        "coding_agents",
        "computer_screen",
        "computer_act",
        "computer_task",
        "contacts",
        "device_files",
        "device_get",
        "device_open",
        "device_put",
        "device_screen",
        "device_shell",
        "devices",
        "forget",
        "goals",
        "phone_act",
        "phone_screen",
        "phone_task",
        "read_emails",
        "recall",
        "remember",
        "reminders",
        "skills",
        "triggers",
    }
)

#: Every name the classification knows by name (the meta tools
#: included); run-time names (MCP, ``device__``) are classified by
#: rule instead.
REGISTERED_NAMES: frozenset[str] = DIRECT_NAMES | EXEMPT_NAMES | BRIDGED_NAMES | META_NAMES

_SEND_WORDS = frozenset({"send", "notify", "publish"})
_MACHINERY_WORDS = frozenset({"sentinel", "gatekeeper", "grant", "grants", "approval", "approvals"})


def _words(name: str) -> list[str]:
    return [w for w in re.split(r"[^a-z0-9]+", name.lower()) if w]


def exempt_reason(name: str) -> str | None:
    """Why a tool name never travels the bridge, or None.

    The explicit list first, then the word backstops, so a sending
    tool nobody registered yet is still caught by its own name.
    """
    if name in EXEMPT_NAMES:
        return "it is a sending tool, named in the bridge's exempt list"
    words = _words(name)
    if any(w in _SEND_WORDS for w in words):
        return "its name marks it as a sending tool"
    if any(w in _MACHINERY_WORDS for w in words):
        return "it is part of the approval machinery, which is never reached by name"
    return None


def classify_name(name: str) -> BridgeClass:
    """The class of one tool name when the bridge is on.

    The exemptions outrank the registry (a listed tool whose name
    turns out to carry a sending word is exempt anyway), the direct
    core follows, and everything else, registered or made at run
    time, is bridged.
    """
    if name in META_NAMES:
        return BridgeClass.DIRECT
    if exempt_reason(name) is not None:
        return BridgeClass.EXEMPT
    if name in DIRECT_NAMES:
        return BridgeClass.DIRECT
    return BridgeClass.BRIDGED


def classify_tool(tool: BaseTool) -> BridgeClass:
    return classify_name(tool.name)


# --------------------------------------------------------------------- index


def _tokens(text: str) -> list[str]:
    # one-character tokens carry no signal ("a", "I") and would match
    # nearly everything, so the index ignores them on both sides
    return [w for w in re.split(r"[\W_]+", text.lower()) if len(w) >= 2]


class ToolIndex:
    """Word matching over the bridged tools, built in memory per bridge.

    Each tool is indexed by the tokens of its name, its one-line
    ``purpose`` (or the description's first line where it has none),
    its ``keywords`` and its full description.  A query token scores
    by the best field it hits; ties break on the tool name, so the
    same query always returns the same order.
    """

    def __init__(self, tools: Iterable[BaseTool]) -> None:
        self._entries: list[tuple[BaseTool, dict[str, set[str]]]] = []
        for tool in tools:
            purpose = tool.purpose or tool.description.strip().split("\n")[0]
            fields = {
                "name": set(_tokens(tool.name)) | {tool.name.lower()},
                "keywords": {tok for kw in tool.keywords for tok in _tokens(kw)},
                "purpose": set(_tokens(purpose)),
                "description": set(_tokens(tool.description)),
            }
            self._entries.append((tool, fields))

    def __len__(self) -> int:
        return len(self._entries)

    def search(self, query: str, limit: int = 3) -> list[BaseTool]:
        tokens = _tokens(query)
        if not tokens:
            return []
        scored: list[tuple[int, str, BaseTool]] = []
        for tool, fields in self._entries:
            score = 0
            if query.strip().lower() in (tool.name.lower(), tool.name.replace("_", " ")):
                score += 10
            for token in tokens:
                if token in fields["name"]:
                    score += 5
                elif token in fields["keywords"]:
                    score += 4
                elif token in fields["purpose"]:
                    score += 2
                elif token in fields["description"]:
                    score += 1
            if score:
                scored.append((score, tool.name, tool))
        scored.sort(key=lambda item: (-item[0], item[1]))
        return [tool for _score, _name, tool in scored[:limit]]


# ------------------------------------------------------------------ meta tools


class FindTools(BaseTool):
    """``find_tools``: the index, as a tool the model can call."""

    _index: ToolIndex = PrivateAttr()
    _reachable: tuple[str, ...] = PrivateAttr()

    def __init__(self, index: ToolIndex, reachable: Iterable[str]) -> None:
        super().__init__(
            name="find_tools",
            description=(
                "Find a tool that is not in your tool list, by what it does. Pass a few "
                "words for the job ('take a screenshot', 'look up a person'). "
                "Returns the full schema of the best matches, at most three; call the one "
                "you want with `use_tool`. A reply with no matches means there is no such "
                "tool here: do not invent a name."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "A few words for the job the tool should do.",
                    }
                },
                "required": ["query"],
            },
            purpose="Find a tool that is not in the tool list, by what it does.",
            keywords=["find", "search", "tool", "look up"],
        )
        self._index = index
        self._reachable = tuple(reachable)

    async def execute(self, query: str = "", **_: Any) -> ToolResult:
        matches = self._index.search(str(query or ""))
        if not matches:
            payload: dict[str, Any] = {
                "matches": [],
                "note": (
                    f"No tool matches {query!r}. There is no such tool among the ones "
                    "reachable here; do not invent a name or guess one. Reachable "
                    "through the bridge: " + ", ".join(self._reachable) + "."
                ),
            }
            return ToolResult(output=json.dumps(payload, ensure_ascii=False))
        payload = {
            "matches": [
                {
                    "name": tool.name,
                    "purpose": tool.purpose or tool.description.strip().split("\n")[0],
                    "schema": tool.to_param(),
                }
                for tool in matches
            ],
            "note": (
                "These tools are not in your tool list. Call one with `use_tool`, "
                "passing its name and the arguments its schema names."
            ),
        }
        return ToolResult(output=json.dumps(payload, ensure_ascii=False))


class UseTool(BaseTool):
    """``use_tool``: run one named tool through the caller's own guard.

    The refusal categories are kept distinct in the failure text,
    because the model (and the reader of the audit trail) should be
    able to tell a tool that does not exist from one that exists but
    may not be reached this way, and both from one outside this
    caller's surface.
    """

    _universe: dict[str, BaseTool] = PrivateAttr()
    _surface: frozenset[str] = PrivateAttr()
    _guard: GuardLike = PrivateAttr()

    def __init__(
        self,
        universe: dict[str, BaseTool],
        surface: frozenset[str],
        guard: GuardLike,
    ) -> None:
        super().__init__(
            name="use_tool",
            description=(
                "Run a tool that is not in your tool list, by name: `name` is the tool "
                "(find it with `find_tools` first if you do not know it), `arguments` "
                "the object its schema names. The call goes through the same approval "
                "as a direct call. Sending tools are never run this way; they are in "
                "the tool list under their own names."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "The tool to run."},
                    "arguments": {
                        "type": "object",
                        "description": "The tool's arguments, as its schema names them.",
                    },
                },
                "required": ["name"],
            },
            purpose="Run a tool that is not in the tool list, by name.",
            keywords=["use", "run", "call", "tool"],
            risk=RiskLevel.MODERATE,
        )
        self._universe = universe
        self._surface = surface
        self._guard = guard

    # -- the outer guard sees the target call's own assessment, so a
    # -- wrapper that judges calls (a preset's gate, a ceiling) judges
    # -- the real thing, not the envelope.
    def assess(self, args: dict[str, Any]) -> CallAssessment:
        tool, inner_args = self._target(args)
        if tool is not None:
            try:
                inner = tool.assess(inner_args)
            except Exception:  # noqa: BLE001 - the guard's own assess path reports it
                inner = None
            if inner is not None:
                return inner.model_copy(update={"summary": f"use_tool: {inner.summary}"})
        name = str(args.get("name") or "?")
        return CallAssessment(risk=RiskLevel.MODERATE, summary=f"use_tool({name})")

    def _target(self, args: dict[str, Any]) -> tuple[BaseTool | None, dict[str, Any]]:
        name = str(args.get("name") or "")
        raw = args.get("arguments")
        inner: dict[str, Any] = raw if isinstance(raw, dict) else {}
        return self._universe.get(name), inner

    def family_risk(self, args: dict[str, Any]) -> RiskLevel:
        # The family this call belongs to is the named tool's: a
        # ceiling measuring a read measures the read, not the envelope.
        name = str(args.get("name") or "")
        target = self._universe.get(name)
        return target.risk if target is not None else self.risk

    async def execute(self, name: str = "", arguments: Any = None, **_: Any) -> ToolResult:
        name = str(name or "")
        if not name:
            return ToolResult.fail("use_tool needs the name of the tool to run")
        if name in META_NAMES:
            return ToolResult.fail(
                f"the bridge tools cannot be called through use_tool: call {name} directly"
            )
        reason = exempt_reason(name)
        if reason is not None:
            return ToolResult.fail(
                f"'{name}' never runs through the tool bridge ({reason}); "
                "it is listed directly, so call it by its own name"
            )
        tool = self._universe.get(name)
        if tool is None:
            return ToolResult.fail(
                f"unknown tool '{name}': this agent has no such tool. "
                "Use find_tools to see what can be reached"
            )
        if name not in self._surface:
            return ToolResult.fail(
                f"'{name}' is outside the tool surface of this caller: "
                "it is either listed directly or not offered here"
            )
        inner_args = self._arguments(arguments)
        if inner_args is None:
            return ToolResult.fail(
                f"bad arguments for use_tool: the arguments for {name} must be an object"
            )
        call = ToolCall(
            function=Function(name=name, arguments=json.dumps(inner_args, ensure_ascii=False))
        )
        return await self._guard.guard(call, tool)

    @staticmethod
    def _arguments(arguments: Any) -> dict[str, Any] | None:
        if arguments is None:
            return {}
        if isinstance(arguments, dict):
            return arguments
        if isinstance(arguments, str):
            try:
                parsed = json.loads(arguments)
            except json.JSONDecodeError:
                return None
            return parsed if isinstance(parsed, dict) else None
        return None


# -------------------------------------------------------------------- bridge


class ToolBridge:
    """One agent's bridged view of its tool collection.

    Built once, when the agent is built: the view (direct and exempt
    tools in their original order, then ``find_tools`` and
    ``use_tool``) and its parameter list are fixed for the agent's
    life, which is what keeps the list on every call of a
    conversation byte for byte the same.
    """

    def __init__(self, collection: ToolCollection, guard: GuardLike) -> None:
        direct: list[BaseTool] = []
        bridged: list[BaseTool] = []
        for tool in collection:
            if classify_tool(tool) is BridgeClass.BRIDGED:
                bridged.append(tool)
            else:
                direct.append(tool)
        self.bridged_names: tuple[str, ...] = tuple(t.name for t in bridged)
        self.index = ToolIndex(bridged)
        find = FindTools(self.index, self.bridged_names)
        use = UseTool(
            universe={t.name: t for t in collection},
            surface=frozenset(self.bridged_names),
            guard=guard,
        )
        view = ToolCollection(*direct)
        view.add(find, use)
        self.view = view
        self._params = view.to_params()

    def params(self) -> list[dict[str, Any]]:
        """The tool list for the model: the same list, every call."""
        return self._params

    def get(self, name: str) -> BaseTool | None:
        return self.view.get(name)

    def names(self) -> list[str]:
        return [t.name for t in self.view]


def context_window(settings: Settings) -> int | None:
    """The chosen model's context window in tokens, or None.

    Today this is always None, and the module docstring of the
    settings says why: nothing in the repository records a model's
    window.  The provider catalogue carries capabilities, not
    windows, and the ``[llm]`` settings carry none either.  When a
    source exists, it is read here, in this one place.
    """
    return None


def bridge_active(cfg: ToolBridgeSettings, window: int | None) -> bool:
    """The bridge's one switch, over the settings and the window.

    Explicitly on is on.  Otherwise ``auto`` engages it only when a
    window is actually known, a positive threshold is set, and the
    window is below it: an unknown window never engages it, because
    a guessed window would switch the bridge on a fiction.
    """
    if cfg.enabled:
        return True
    return bool(
        cfg.auto
        and cfg.window_threshold > 0
        and window is not None
        and window < cfg.window_threshold
    )


def build_tool_bridge(
    collection: ToolCollection, guard: GuardLike, settings: Settings
) -> ToolBridge | None:
    """The agent's bridge, or None when the switch is off.

    None is the common case, and it is a promise: with the bridge
    off, nothing about the agent's tool list or dispatch changes.
    """
    if not bridge_active(settings.tool_bridge, context_window(settings)):
        return None
    return ToolBridge(collection, guard)


__all__ = [
    "BRIDGED_NAMES",
    "DIRECT_NAMES",
    "EXEMPT_NAMES",
    "META_NAMES",
    "REGISTERED_NAMES",
    "BridgeClass",
    "FindTools",
    "GuardLike",
    "ToolBridge",
    "ToolIndex",
    "UseTool",
    "bridge_active",
    "build_tool_bridge",
    "classify_name",
    "classify_tool",
    "context_window",
    "exempt_reason",
]

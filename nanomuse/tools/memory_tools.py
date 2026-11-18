"""Memory tools: remember / recall / forget."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from nanomuse.memory import MemoryStore
from nanomuse.schema import RiskLevel, ToolResult
from nanomuse.tools.base import BaseTool, CallAssessment, int_arg

RETIRED_MEMORY_ERROR = "This text was retired by the owner. Review memory exclusions first."


def _short(value: Any, limit: int = 80) -> str:
    text = str(value or "").strip().replace("\n", " ")
    return text if len(text) <= limit else text[: limit - 1] + "…"


class MemoryTool(BaseTool):
    enabled: Callable[[], bool] | None = None

    def memory_disabled(self) -> bool:
        return self.enabled is not None and not self.enabled()


class Remember(MemoryTool):
    name: str = "remember"
    description: str = (
        "Save a durable fact about the user or their preferences for future sessions "
        "(e.g. 'prefers window seats', 'partner is vegetarian', 'works at Acme, timezone UTC+8'). "
        "Keep it short and factual. When a fact has changed (they moved, changed jobs), pass "
        "`replaces` with the id of the memory it supersedes instead of adding a second one. "
        "Never store passwords or payment details here."
        " If an owner exclusion rejects the write, stop. Do not rephrase or use another store."
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "content": {"type": "string"},
            "category": {
                "type": "string",
                "description": "profile | preference | contact | project | routine | other",
            },
            "replaces": {
                "type": "string",
                "description": "id (m_xxxxxxxx) of an existing memory this one updates",
            },
        },
        "required": ["content"],
    }
    risk: RiskLevel = RiskLevel.SAFE
    store: MemoryStore

    def assess(self, args: dict[str, Any]) -> CallAssessment:
        a = super().assess(args)
        verb = "update memory" if args.get("replaces") else "remember"
        a.summary = f"{verb}: {_short(args.get('content'))}"
        return a

    async def execute(
        self, content: str = "", category: str = "general", replaces: str = "", **_: Any
    ) -> ToolResult:
        if self.memory_disabled():
            return ToolResult.fail("Memory is disabled for this space")
        if not self.store.text_allowed(content):
            return ToolResult.fail(RETIRED_MEMORY_ERROR)
        try:
            if replaces:
                old = self.store.get(replaces)
                if old is None:
                    return ToolResult.fail(f"no memory with id {replaces}")
                change = self.store.replace(
                    [replaces], content, category=category or old.category, action="rewrite"
                )
                if change is None or change.after is None:
                    return ToolResult.fail("memory content is empty")
                return ToolResult(
                    output=f"Updated {replaces} → {change.after.id}: {change.after.content}"
                )
            # The same fact in other words: update that line rather than keep two.
            for _score, twin in self.store.similar(content, threshold=0.8, limit=1):
                if twin.content.strip() == content.strip():
                    break  # an exact repeat: add() hands back the existing line
                change = self.store.replace(
                    [twin.id], content, category=category or twin.category, action="rewrite"
                )
                if change is not None and change.after is not None:
                    return ToolResult(
                        output=f"Updated {twin.id} → {change.after.id}: {change.after.content} "
                        f"(was: {twin.content})"
                    )
            item = self.store.add(content, category=category or "general")
        except ValueError as exc:
            return ToolResult.fail(str(exc))
        note = ""
        similar = [
            (s, m)
            for s, m in self.store.similar(content, threshold=0.4, limit=2)
            if m.id != item.id
        ]
        if similar:
            note = (
                " Similar memories: "
                + "; ".join(f"[{m.id}] {m.content}" for _, m in similar)
                + "; if this replaces one of them, call remember again with replaces=<id>."
            )
        return ToolResult(output=f"Remembered {item.id}: {item.content}.{note}")


class Recall(MemoryTool):
    name: str = "recall"
    description: str = "Search long-term memory for facts about the user relevant to `query`."
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {"query": {"type": "string"}, "limit": {"type": "integer"}},
        "required": ["query"],
    }
    risk: RiskLevel = RiskLevel.SAFE
    reads_private_data: bool = True
    store: MemoryStore

    def assess(self, args: dict[str, Any]) -> CallAssessment:
        a = super().assess(args)
        a.summary = f"recall: {_short(args.get('query'))}"
        return a

    async def execute(self, query: str = "", limit: int = 10, **_: Any) -> ToolResult:
        if self.memory_disabled():
            return ToolResult.fail("Memory is disabled for this space")
        items = await self.store.search_async(query, limit=int_arg(limit, 10, 1, 50))
        if not items:
            return ToolResult(output="No matching memories.")
        return ToolResult(output="\n".join(i.render() for i in items))


class Forget(MemoryTool):
    name: str = "forget"
    description: str = (
        "Delete memories. Provide `memory_id` (e.g. m_1a2b3c4d) to delete one, or `query` to delete "
        "every memory containing that text. Use when the user asks you to forget something."
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {"memory_id": {"type": "string"}, "query": {"type": "string"}},
    }
    risk: RiskLevel = RiskLevel.MODERATE
    store: MemoryStore

    def assess(self, args: dict[str, Any]) -> CallAssessment:
        a = super().assess(args)
        target = args.get("memory_id") or args.get("query") or "?"
        a.summary = f"forget: {_short(target)}"
        return a

    async def execute(
        self, memory_id: str | None = None, query: str | None = None, **_: Any
    ) -> ToolResult:
        if self.memory_disabled():
            return ToolResult.fail("Memory is disabled for this space")
        if memory_id:
            ok = self.store.forget(memory_id)
            return ToolResult(
                output=f"Forgot {memory_id}." if ok else f"No memory with id {memory_id}."
            )
        if query:
            n = self.store.forget_matching(query)
            return ToolResult(
                output=f"Forgot {n} memor{'y' if n == 1 else 'ies'} matching '{query}'."
            )
        return ToolResult.fail("provide memory_id or query")


__all__ = ["Forget", "Recall", "Remember"]

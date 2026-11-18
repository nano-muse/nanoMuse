"""Memory tools: remember / recall / forget."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from nanomuse.llm.base import model_id
from nanomuse.memory import MemoryItem, MemoryStore, resolve_conflict
from nanomuse.schema import RiskLevel, ToolResult
from nanomuse.tools.base import BaseTool, CallAssessment, int_arg


def _short(value: Any, limit: int = 80) -> str:
    text = str(value or "").strip().replace("\n", " ")
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _provenance(item: MemoryItem) -> str:
    bits = []
    if item.model:
        bits.append(f"written by {item.model}")
    if item.confidence is not None:
        bits.append(f"confidence {item.confidence:.2f}")
    return f" ({'; '.join(bits)})" if bits else ""


class Remember(BaseTool):
    name: str = "remember"
    description: str = (
        "Save a durable fact about the user or their preferences for future sessions "
        "(e.g. 'prefers window seats', 'partner is vegetarian', 'works at Acme, timezone UTC+8'). "
        "Keep it short and factual. When a fact has changed (they moved, changed jobs), pass "
        "`replaces` with the id of the memory it supersedes instead of adding a second one. "
        "Never store passwords or payment details here."
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
            "confidence": {
                "type": "number",
                "minimum": 0,
                "maximum": 1,
                "description": "how sure the writer is that this is a durable fact, 0.0 to 1.0; omit when unknown",
            },
        },
        "required": ["content"],
    }
    risk: RiskLevel = RiskLevel.SAFE
    store: MemoryStore
    # The configured model id (from settings), used only when a call names no
    # execution model of its own; "" means unknown. Never a key or an address.
    model: str = ""

    def _writer(self) -> str:
        """The model writing in this run: the execution model of the task the call
        belongs to, which is the client the turn actually runs on (a per-run
        override included), not the configured default this tool was built with.
        Outside a task, the configured model stands."""
        from nanomuse.sentinel.gate import current_task

        task = current_task()
        if task is not None and task.execution_llm is not None:
            return model_id(task.execution_llm)
        return self.model

    def assess(self, args: dict[str, Any]) -> CallAssessment:
        a = super().assess(args)
        # what is remembered stays and shapes every later turn: a change, not a read
        a.risk = RiskLevel.MODERATE
        verb = "update memory" if args.get("replaces") else "remember"
        a.summary = f"{verb}: {_short(args.get('content'))}"
        return a

    async def execute(
        self,
        content: str = "",
        category: str = "general",
        replaces: str = "",
        confidence: float | None = None,
        **_: Any,
    ) -> ToolResult:
        writer = self._writer()
        try:
            if replaces:
                old = self.store.get(replaces)
                if old is None:
                    return ToolResult.fail(f"no memory with id {replaces}")
                change = self.store.replace(
                    [replaces],
                    content,
                    category=category or old.category,
                    action="rewrite",
                    model=writer,
                    confidence=confidence,
                )
                if change is None or change.after is None:
                    return ToolResult.fail("memory content is empty")
                return ToolResult(
                    output=f"Updated {replaces} → {change.after.id}: {change.after.content}"
                )
            # The same fact in other words: the stated rule decides, and its answer
            # is honoured as given. When the existing line wins, on any ground, it
            # is kept as it is; when nothing separates the two, both are kept and
            # the new wording is stored as a line of its own below; only when the
            # new wording wins does it replace the existing line.
            for _score, twin in self.store.similar(content, threshold=0.8, limit=1):
                if twin.content.strip() == content.strip():
                    break  # an exact repeat: add() hands back the existing line
                candidate = MemoryItem(
                    id="",
                    content=content,
                    category=category or twin.category,
                    # full precision: the candidate is the statement being made
                    # now, so it is newer than the stored line it is compared
                    # with (stored lines carry second precision, and a tie at
                    # that precision would misread the two as simultaneous)
                    created_at=datetime.now(UTC).isoformat(),
                    source="agent",
                    model=writer,
                    confidence=confidence,
                )
                winner, reason = resolve_conflict(candidate, twin)
                if reason == "keep-both":
                    break  # nothing separates them: both lines stay, see add() below
                if winner is twin:
                    return ToolResult(
                        output=(
                            f"Kept {twin.id}: {twin.content} (the existing memory wins: {reason})"
                        )
                    )
                change = self.store.replace(
                    [twin.id],
                    content,
                    category=category or twin.category,
                    action="rewrite",
                    model=writer,
                    confidence=confidence,
                )
                if change is not None and change.after is not None:
                    return ToolResult(
                        output=f"Updated {twin.id} → {change.after.id}: {change.after.content} "
                        f"(was: {twin.content})"
                    )
            item = self.store.add(
                content,
                category=category or "general",
                model=writer,
                confidence=confidence,
            )
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


class Recall(BaseTool):
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
        items = await self.store.search_async(query, limit=int_arg(limit, 10, 1, 50))
        if not items:
            return ToolResult(output="No matching memories.")
        return ToolResult(output="\n".join(i.render() + _provenance(i) for i in items))


class Forget(BaseTool):
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
        # Name what was forgotten: the result is what the person sees in the chat,
        # and the deletion is in the memory changes, where it can be undone.
        if memory_id:
            item = self.store.get(memory_id)
            if item is None:
                return ToolResult(output=f"No memory with id {memory_id}.")
            self.store.forget(memory_id)
            return ToolResult(
                output=(
                    f"Forgot {item.id}: {item.content}. "
                    "The deletion is in the memory changes and can be undone."
                )
            )
        if query:
            items = self.store.matching(query)
            if not items:
                return ToolResult(output=f"No memories matched '{query}'.")
            self.store.forget_matching(query)
            lines = "\n".join(i.render() for i in items)
            return ToolResult(
                output=(
                    f"Forgot {len(items)} memor{'y' if len(items) == 1 else 'ies'} "
                    f"matching '{query}':\n{lines}\n"
                    "The deletion is in the memory changes and can be undone."
                )
            )
        return ToolResult.fail("provide memory_id or query")


__all__ = ["Forget", "Recall", "Remember"]

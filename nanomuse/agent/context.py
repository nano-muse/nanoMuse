"""Pack request copies without changing saved history or splitting tool exchanges."""

from __future__ import annotations

from typing import Any

from nanomuse.llm.budget import BudgetExceeded, estimate_tokens
from nanomuse.logger import logger
from nanomuse.schema import Message, Role


def fit_context(
    messages: list[Message],
    tools: list[dict[str, Any]] | None,
    limit: int,
    protected: list[Message],
) -> list[Message]:
    if not limit:
        return messages
    groups: list[list[Message]] = []
    for message in messages:
        if message.role == Role.TOOL and groups and groups[-1][0].tool_calls:
            groups[-1].append(message)
        else:
            groups.append([message])
    pinned = {m.meta.get("request_id", id(m)) for m in protected}

    # Tool output is untrusted data, not an instruction. Keep a labelled head and tail.
    # Never truncate system/user text or function arguments to make a request fit.
    def flatten() -> list[Message]:
        return [m for group in groups for m in group]

    def shorten(message: Message, output_chars: int) -> Message:
        content = message.content or ""
        if message.role != Role.TOOL or len(content) <= output_chars:
            return message
        shortened = (
            content[: output_chars // 2]
            + "\n[Tool output shortened for context budget]\n"
            + content[-output_chars // 2 :]
        )
        logger.info(
            "Context budget shortened tool result {}: {} -> {} characters",
            message.tool_call_id or "unknown",
            len(content),
            len(shortened),
        )
        return message.model_copy(update={"content": shortened})

    for output_chars in (4096, 1024, 256):
        if estimate_tokens(flatten(), tools) <= limit:
            return flatten()
        for i, group in enumerate(groups):
            groups[i] = [shorten(m, output_chars) for m in group]
    while estimate_tokens(flatten(), tools) > limit:
        removable = next(
            (
                i
                for i, group in enumerate(groups[:-1])
                if group[0].role != Role.SYSTEM
                and not any(m.meta.get("request_id", id(m)) in pinned for m in group)
            ),
            None,
        )
        if removable is None:
            raise BudgetExceeded("context")
        del groups[removable]
    return flatten()

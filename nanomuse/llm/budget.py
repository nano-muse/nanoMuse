"""Task-scoped accounting for the Agent and its nested screen operators.

Text is estimated at four UTF-8 bytes per token and a CJK character at one and a half
tokens, including request overhead; pictures use a fixed estimate. Reported usage replaces an
estimate when available. This bounds application requests, not a provider's invoice or retries
hidden inside a client.
"""

from __future__ import annotations

import asyncio
import json
import math
import time
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from typing import Any

from nanomuse.config import TaskBudgetSettings
from nanomuse.llm.base import BaseLLM
from nanomuse.schema import LLMResponse, Message


class BudgetExceeded(RuntimeError):
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(f"Task stopped: {reason} budget reached.")

    def message(self, language: str = "") -> str:
        if language.lower().startswith("zh"):
            reason = {"token": "token", "cost": "费用", "time": "时间", "context": "上下文"}
            return f"任务已停止：达到{reason.get(self.reason, self.reason)}预算。"
        return str(self)


def estimate_tokens(messages: list[Message], tools: list[dict[str, Any]] | None = None) -> int:
    """A provider-independent approximation, not a count of raw bytes or exact tokens.

    A CJK character is three UTF-8 bytes but one to two tokens from real tokenizers, so
    counting it at the byte rule's three quarters packs a window to twice what the model
    takes. It counts for one and a half here — the estimate decides what fits and cannot
    err low; the relay's own fallback count (cloud/nanomuse_cloud/service.py) gives it a
    whole token for the same reason.
    """
    wire = [m.to_openai(include_reasoning=True) for m in messages]
    text = json.dumps([wire, tools or []], ensure_ascii=False)
    cjk = sum(1 for ch in text if "一" <= ch <= "鿿")
    size = len(text.encode("utf-8")) - 3 * cjk
    return (size + 3) // 4 + (3 * cjk + 1) // 2 + 4096 * sum(len(m.images or []) for m in messages)


# Client labels that are not model ids: a wrapper or a protocol name
# must never be priced as if it were the model that made the call.
_NOT_A_MODEL = {"", "base", "chatgpt", "openai", "openai_responses", "prompt_tools"}


def llm_model(llm: BaseLLM) -> str:
    """The model one call is actually made with, for cost accounting.

    The client's own settings name it; a wrapper (the prompt adapter,
    a recording client) delegates to the wrapped client's settings, so
    unwrapping follows ``inner`` until a settings model or a direct
    ``model`` attribute is found.  Only then does the client's
    ``name`` count, and only when it is a model id rather than a
    wrapper or protocol label: the prompt adapter's name, for
    example, is never a model.
    """
    current: Any = llm
    seen: set[int] = set()
    fallback = ""
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        settings = getattr(current, "settings", None)
        model = getattr(settings, "model", None) if settings is not None else None
        if model:
            return str(model)
        direct = getattr(current, "model", None)
        if isinstance(direct, str) and direct:
            return direct
        if not fallback:
            name = str(getattr(current, "name", "") or "")
            if name not in _NOT_A_MODEL:
                fallback = name
        inner = getattr(current, "inner", None)
        current = inner if isinstance(inner, BaseLLM) else None
    return fallback or "unknown"


@dataclass
class TaskBudget:
    limits: TaskBudgetSettings
    started: float = field(default_factory=time.monotonic)
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    calls: int = 0
    estimated_calls: int = 0
    stopped: str = ""
    # Usage split by the model that actually made each call.  A task
    # is not one model: the parent call and a nested call (a screen
    # operator on the hands model, a tool's own call on a cheaper
    # model) share this budget, and pricing the whole task at the
    # parent's rates misstates both.
    by_model: dict[str, dict[str, int]] = field(default_factory=dict)

    def fail(self, reason: str) -> None:
        self.stopped = reason
        raise BudgetExceeded(reason)

    def check(self) -> None:
        if self.stopped:
            self.fail(self.stopped)
        if self.limits.max_seconds and time.monotonic() - self.started >= self.limits.max_seconds:
            self.fail("time")
        if self.limits.max_total_tokens and self.total_tokens >= self.limits.max_total_tokens:
            self.fail("token")
        if self.limits.max_cost_usd and self.cost_usd >= self.limits.max_cost_usd:
            self.fail("cost")

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    @property
    def metered(self) -> bool:
        """Whether tokens or money are counted; without either, a request is not measured."""
        return bool(self.limits.max_total_tokens or self.limits.max_cost_usd)

    @property
    def limited(self) -> bool:
        """Whether any limit is set at all; with none, the task is accounted but never stopped."""
        return self.metered or bool(self.limits.max_seconds)

    def allowance(self, incoming: int, requested: int) -> int:
        self.check()
        remaining = requested
        if self.limits.max_total_tokens:
            remaining = min(remaining, self.limits.max_total_tokens - self.total_tokens - incoming)
            if remaining < 1:
                self.fail("token")
        if self.limits.max_cost_usd:
            room = self.limits.max_cost_usd - self.cost_usd - self.price(incoming, 0)
            if room <= 0:
                self.fail("cost")
            if self.limits.output_usd_per_million:
                remaining = min(
                    remaining, math.floor(room * 1e6 / self.limits.output_usd_per_million)
                )
            if remaining < 1:
                self.fail("cost")
        return remaining

    def price(self, incoming: int, outgoing: int) -> float:
        return (
            incoming * self.limits.input_usd_per_million
            + outgoing * self.limits.output_usd_per_million
        ) / 1e6

    def record(
        self, incoming: int, outgoing: int, estimated: bool, model: str | None = None
    ) -> None:
        self.input_tokens += incoming
        self.output_tokens += outgoing
        self.cost_usd += self.price(incoming, outgoing)
        self.estimated_calls += int(estimated)
        if model is not None:
            usage = self.by_model.setdefault(model, {"input_tokens": 0, "output_tokens": 0})
            usage["input_tokens"] += incoming
            usage["output_tokens"] += outgoing

    def snapshot(self) -> dict[str, Any]:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "cost_usd": self.cost_usd,
            "calls": self.calls,
            "estimated_calls": self.estimated_calls,
            "elapsed_seconds": time.monotonic() - self.started,
            "stopped": self.stopped,
            "by_model": {model: dict(usage) for model, usage in self.by_model.items()},
        }


_current: ContextVar[TaskBudget | None] = ContextVar("nanomuse_task_budget", default=None)


def begin(limits: TaskBudgetSettings, *, inherit: bool = True) -> Token:
    return _current.set((_current.get() if inherit else None) or TaskBudget(limits))


def end(token: Token) -> None:
    _current.reset(token)


def current() -> TaskBudget | None:
    return _current.get()


def _usage(usage: dict[str, Any], *keys: str) -> int | None:
    for key in keys:
        value = usage.get(key)
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            return value
    return None


async def ask(llm: BaseLLM, messages: list[Message], **kwargs: Any) -> LLMResponse:
    budget = current()
    if budget is None:
        return await llm.ask(messages, **kwargs)
    # The estimate serializes the whole request; it is made only when tokens or money are
    # counted. Without either, the output limit stays as the call set it, and what the
    # provider reports is still recorded.
    if budget.metered:
        incoming = estimate_tokens(messages, kwargs.get("tools"))
        requested = int(
            kwargs.get("max_tokens")
            or getattr(getattr(llm, "settings", None), "max_tokens", 4096)
            or 4096
        )
        cap = budget.allowance(incoming, requested)
        kwargs["max_tokens"] = cap
    else:
        incoming = cap = 0
        budget.check()
    budget.calls += 1
    timeout = (
        budget.limits.max_seconds - (time.monotonic() - budget.started)
        if budget.limits.max_seconds
        else None
    )
    deadline = asyncio.timeout(max(0, timeout) if timeout is not None else None)
    model = llm_model(llm)
    try:
        async with deadline:
            response = await llm.ask(messages, **kwargs)
    except TimeoutError:
        budget.record(incoming, cap, True, model=model)
        if deadline.expired():
            budget.fail("time")
        raise
    except BaseException:
        # A failed/aborted stream may already have been billed. Reserve its full cap.
        budget.record(incoming, cap, True, model=model)
        raise
    used_in = _usage(response.usage, "input_tokens", "prompt_tokens")
    used_out = _usage(response.usage, "output_tokens", "completion_tokens")
    budget.record(
        used_in if used_in is not None else incoming,
        used_out if used_out is not None else cap,
        used_in is None or used_out is None,
        model=model,
    )
    return response


async def ask_complete(llm: BaseLLM, messages: list[Message], **kwargs: Any) -> LLMResponse:
    return await llm.ask_complete(messages, **kwargs)

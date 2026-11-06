"""Provider-agnostic LLM interface."""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any

from nanomuse.schema import LLMResponse, Message

DeltaCallback = Callable[[str], None]

_THINK_RE = re.compile(r"<think>(.*?)</think>", re.DOTALL)

# What endpoints say when they cannot do function calling for this model:
# Ollama: "registry.ollama.ai/library/gemma3:4b does not support tools";
# vLLM: '"auto" tool choice requires --enable-auto-tool-choice ...';
# others: "tools are not supported", "function calling is not supported".
_NO_TOOLS_RE = re.compile(
    r"(does not|doesn'?t|is not|isn'?t|are not|aren'?t|not) support(ed)?\b[^.]{0,40}\b(tool|function)"
    r"|\b(tool|function)[^.]{0,40}\b(not supported|unsupported|not available)"
    r"|enable-auto-tool-choice",
    re.IGNORECASE,
)


class ToolsUnsupported(Exception):
    """The endpoint rejected the request because of the ``tools`` field.

    Providers raise this instead of the raw 400 so the prompt-mode fallback can
    take over (``tool_mode = "auto"``).
    """


def says_no_tools(message: str) -> bool:
    return bool(_NO_TOOLS_RE.search(message or ""))


class BaseLLM(ABC):
    """A chat model that may or may not support native tool calling."""

    name: str = "base"
    supports_native_tools: bool = True
    # Whether the model takes images: None until a message with pictures has been sent,
    # False once the endpoint refused image content (``llm.vision = "auto"`` then sends
    # text only, with a note in place of each picture).
    vision_available: bool | None = None

    @abstractmethod
    async def ask(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str = "auto",
        on_delta: DeltaCallback | None = None,
        on_reasoning_delta: DeltaCallback | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        """Send a conversation and get one assistant turn back.

        ``tools`` are OpenAI-style function schemas
        (``{"type": "function", "function": {...}}``).
        ``on_delta`` receives visible text as it streams. ``on_reasoning_delta``
        receives the model's live reasoning, when the provider exposes it.
        ``max_tokens`` overrides the configured budget for this one call.
        """

    def roomier_max_tokens(self) -> int:
        """A budget for a second try when the first answer was cut off: four times the
        configured one, 16k at least — enough for a reasoning model to think and answer."""
        configured = getattr(getattr(self, "settings", None), "max_tokens", None) or 0
        return max(16384, 4 * int(configured))

    async def ask_complete(self, messages: list[Message], **kwargs: Any) -> LLMResponse:
        """``ask``, tried once more with room when the answer was cut off.

        A reasoning model can spend the whole ``max_tokens`` thinking and hand back an
        empty or half-written answer with ``finish_reason == "length"``. The callers
        that want a JSON list (ideas, memory tidy-up) cannot use a fragment, so the
        second try gets ``roomier_max_tokens()``.
        """
        # Imported here to keep the provider interface independent during module loading.
        # Auxiliary model calls made inside tools inherit an active task's accounting too.
        from nanomuse.llm.budget import ask

        response = await ask(self, messages, **kwargs)
        if response.finish_reason == "length":
            kwargs["max_tokens"] = self.roomier_max_tokens()
            response = await ask(self, messages, **kwargs)
        return response

    async def close(self) -> None:  # pragma: no cover - default no-op
        return None


def split_think(content: str | None) -> tuple[str | None, str | None]:
    """Extract ``<think>...</think>`` blocks from non-streamed content.

    Returns ``(visible_content, reasoning)``.
    """
    if not content:
        return content, None
    reasoning_parts = _THINK_RE.findall(content)
    if not reasoning_parts:
        # Unterminated <think> (model ran out of tokens): treat the rest as reasoning.
        if "<think>" in content:
            head, _, tail = content.partition("<think>")
            return head.strip() or None, tail.strip() or None
        return content, None
    visible = _THINK_RE.sub("", content).strip()
    return visible or None, "\n".join(p.strip() for p in reasoning_parts) or None


class ThinkStreamFilter:
    """Streams visible text while diverting ``<think>...</think>`` to ``reasoning``.

    Handles tags that are split across deltas.
    """

    OPEN = "<think>"
    CLOSE = "</think>"

    def __init__(self) -> None:
        self.in_think = False
        self._buf = ""
        self._reasoning: list[str] = []

    @staticmethod
    def _partial_suffix(text: str, tag: str) -> int:
        for k in range(len(tag) - 1, 0, -1):
            if text.endswith(tag[:k]):
                return k
        return 0

    def feed(self, text: str) -> str:
        self._buf += text
        out: list[str] = []
        while self._buf:
            tag = self.CLOSE if self.in_think else self.OPEN
            idx = self._buf.find(tag)
            if idx == -1:
                keep = self._partial_suffix(self._buf, tag)
                chunk, self._buf = (
                    self._buf[: len(self._buf) - keep],
                    self._buf[len(self._buf) - keep :],
                )
                if self.in_think:
                    self._reasoning.append(chunk)
                else:
                    out.append(chunk)
                break
            chunk, self._buf = self._buf[:idx], self._buf[idx + len(tag) :]
            if self.in_think:
                self._reasoning.append(chunk)
            else:
                out.append(chunk)
            self.in_think = not self.in_think
        return "".join(out)

    def flush(self) -> str:
        rest, self._buf = self._buf, ""
        if self.in_think:
            self._reasoning.append(rest)
            return ""
        return rest

    @property
    def reasoning(self) -> str | None:
        text = "".join(self._reasoning).strip()
        return text or None


def proxied_http(proxy: str, timeout: float) -> Any:
    """The HTTP client for an OpenAI SDK client: through ``[llm] proxy`` when it is set (the
    environment's ``HTTPS_PROXY`` ignored), else the SDK's own defaults (which honour the
    environment); either way with the response hook that keeps the id nanoMuse Cloud gives
    a turn (:func:`nanomuse.llm.session.note_response`). Built from the SDK's own class,
    since the SDK may ship its own copy of httpx."""
    from openai import DefaultAsyncHttpxClient

    from nanomuse.llm import session

    async def on_response(response: Any) -> None:
        session.note_response(response)

    kw: dict[str, Any] = {"timeout": timeout, "event_hooks": {"response": [on_response]}}
    if proxy:
        kw.update(proxy=proxy, trust_env=False)
    return DefaultAsyncHttpxClient(**kw)


# ------------------------------------------------------------------ the relay's view of a call
#
# A call to nanoMuse Cloud carries where it sits (the X-NanoMuse-* headers, relay 0.31); a
# call to any other provider is sent up afterwards as a turn on the person's own key, when
# the account is signed in (nanomuse.telemetry). Both clients begin and end a call here.


class CallContext:
    """What one model call is told about itself before it goes, and what is done after."""

    __slots__ = ("headers", "number", "to_cloud", "where")

    def __init__(self, to_cloud: bool, number: int, headers: dict[str, str], where: dict[str, Any]):
        self.to_cloud = to_cloud
        self.number = number
        self.headers = headers
        self.where = where


def begin_call(base_url: str | None) -> CallContext:
    """Count the call in its turn; the relay's headers when the slot is the relay."""
    from nanomuse.llm import session

    number = session.next_call()
    session.clear_last_turn()
    to_cloud = session.is_cloud(base_url)
    where = session.provenance(number)
    headers = session.relay_headers(number) if to_cloud else {}
    return CallContext(to_cloud, number, headers, where)


def end_call(
    ctx: CallContext,
    *,
    settings: Any,
    params: dict[str, Any],
    response: LLMResponse,
    messages: list[dict[str, Any]] | None = None,
) -> None:
    """After the answer: a Cloud call's response names the turn the relay kept; any other
    provider's turn goes up to the record (and, with *Help improve* on, the training view)
    under an id of our own. The response carries the id either way."""
    from nanomuse.llm import session

    if ctx.to_cloud:
        response.request_id, response.turn_source = session.last_turn()
        return
    from nanomuse.telemetry import telemetry, turn_body

    if not telemetry.ready or not telemetry.upload_turns:
        return
    import uuid

    turn_id = uuid.uuid4().hex[:16]
    message: dict[str, Any] = {"role": "assistant", "content": response.content}
    if response.reasoning:
        message["reasoning_content"] = response.reasoning
    if response.tool_calls:
        message["tool_calls"] = [
            {
                "id": tc.id,
                "type": "function",
                "function": {"name": tc.function.name, "arguments": tc.function.arguments},
            }
            for tc in response.tool_calls
        ]
    if response.finish_reason:
        message["finish_reason"] = response.finish_reason
    if messages is None:
        # the Chat shape as sent; a Responses client passes the same conversation in it
        messages = params.get("messages") if isinstance(params.get("messages"), list) else None
    if not messages:
        return
    telemetry.own_turn(
        turn_body(
            turn_id=turn_id,
            model=str(params.get("model") or getattr(settings, "model", "") or ""),
            provider=provider_id(settings),
            messages=messages,
            response=message,
            usage=response.usage,
            conversation=session.current_conversation() or "",
            extra=params,
            provenance=ctx.where,
        )
    )
    session.note_own_turn(turn_id)
    response.request_id, response.turn_source = turn_id, "own"


def provider_id(settings: Any) -> str:
    """The catalogue id a slot means (``openrouter``, ``bailian``), the entry whose endpoint
    its address is, else its protocol word; never the URL or the key."""
    provider = str(getattr(settings, "provider", "") or "")
    try:
        from nanomuse.llm import catalogue

        cat = catalogue.load()
        entry = cat.by_base_url(getattr(settings, "base_url", None)) or cat.get(provider)
        if entry is not None:
            return str(entry.id)
    except Exception:  # noqa: BLE001 - the id is a label
        pass
    return provider or "openai"


__all__ = [
    "BaseLLM",
    "CallContext",
    "DeltaCallback",
    "ThinkStreamFilter",
    "ToolsUnsupported",
    "begin_call",
    "end_call",
    "provider_id",
    "proxied_http",
    "says_no_tools",
    "split_think",
]

"""Chat Completions ↔ the Codex Responses endpoint, for the ChatGPT sign-in.

Two users: :class:`CodexLLM`, the in-process backend behind ``provider = "chatgpt"``, and the
loopback proxy (``nanomuse chatgpt proxy``, ``nanomuse/llm/chatgpt_proxy.py``) that lets any
OpenAI-compatible client — the desktop app — use the sign-in. Both go through the same two
functions: :func:`to_codex` turns a Chat Completions request body into a Codex Responses body;
:class:`StreamState` turns the Responses SSE events back into Chat Completions chunks. The
rules are spelled out in the runtime team's ``CONTRACT-chatgpt.md``.
"""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
from loguru import logger

from nanomuse import __version__
from nanomuse.config import DEFAULT_DATA_DIR, LLMSettings
from nanomuse.llm.base import BaseLLM, DeltaCallback
from nanomuse.llm.chatgpt import (
    DEFAULT_MODEL,
    ORIGINATOR,
    RESPONSES_URL,
    Auth,
    ChatGPTError,
    Limits,
    Token,
    TokenStore,
    classify_http,
    classify_transport,
    http_client,
)
from nanomuse.llm.vision import content_parts, has_images, without_images
from nanomuse.schema import Function, LLMResponse, Message, ToolCall

#: what a Chat Completions request may carry that the Codex backend rejects or ignores
_DROPPED = ("temperature", "max_tokens", "max_completion_tokens", "top_p", "n", "stop",
            "response_format", "presence_penalty", "frequency_penalty", "logprobs", "seed",
            "stream_options", "user")  # fmt: skip


# --------------------------------------------------------------------------- request
def _obj(value: Any) -> dict[str, Any]:
    """``value`` when it is a JSON object, else an empty one."""
    return value if isinstance(value, dict) else {}


def _text(content: Any) -> str:
    """A message's content as one string (a list of parts → the text parts joined)."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        out = []
        for part in content:
            if isinstance(part, dict) and part.get("type") in ("text", "input_text", "output_text"):
                out.append(str(part.get("text") or ""))
            elif isinstance(part, str):
                out.append(part)
        return "".join(out)
    return str(content)


def _user_parts(content: Any) -> list[dict[str, Any]]:
    if isinstance(content, str) or content is None:
        return [{"type": "input_text", "text": content or ""}]
    parts: list[dict[str, Any]] = []
    for part in content if isinstance(content, list) else [content]:
        if isinstance(part, str):
            parts.append({"type": "input_text", "text": part})
            continue
        if not isinstance(part, dict):
            continue
        kind = part.get("type")
        if kind in ("text", "input_text"):
            parts.append({"type": "input_text", "text": str(part.get("text") or "")})
        elif kind in ("image_url", "input_image"):
            image = part.get("image_url")
            url = image.get("url") if isinstance(image, dict) else image
            detail = image.get("detail") if isinstance(image, dict) else part.get("detail")
            parts.append(
                {"type": "input_image", "image_url": str(url or ""), "detail": detail or "auto"}
            )
    return parts or [{"type": "input_text", "text": ""}]


def _arguments(value: Any) -> str:
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value if value is not None else {}, ensure_ascii=False)
    except (TypeError, ValueError):
        return "{}"


def to_codex(body: dict[str, Any]) -> dict[str, Any]:
    """A Chat Completions request body → the Codex Responses body (always streaming)."""
    instructions: list[str] = []
    items: list[dict[str, Any]] = []
    for m in body.get("messages") or []:
        if not isinstance(m, dict):
            continue
        role = str(m.get("role") or "user")
        if role in ("system", "developer"):
            if text := _text(m.get("content")):
                instructions.append(text)
        elif role == "user":
            items.append({"role": "user", "content": _user_parts(m.get("content"))})
        elif role == "assistant":
            if text := _text(m.get("content")):
                items.append(
                    {
                        "type": "message",
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": text}],
                        "status": "completed",
                    }
                )
            for call in m.get("tool_calls") or []:
                if not isinstance(call, dict):
                    continue
                fn = _obj(call.get("function"))
                items.append(
                    {
                        "type": "function_call",
                        "call_id": str(call.get("id") or ""),
                        "name": str(fn.get("name") or call.get("name") or ""),
                        "arguments": _arguments(fn.get("arguments")),
                    }
                )
        elif role == "tool":
            content = m.get("content")
            output = content if isinstance(content, str) else _arguments(content)
            items.append(
                {
                    "type": "function_call_output",
                    "call_id": str(m.get("tool_call_id") or ""),
                    "output": output,
                }
            )
    out: dict[str, Any] = {
        "model": str(body.get("model") or DEFAULT_MODEL),
        "store": False,
        "stream": True,
        "instructions": "\n\n".join(instructions),
        "input": items,
        # the shape Codex itself sends for the gpt-5 family (nanobot does the same)
        "text": {"verbosity": "medium"},
        "tool_choice": _tool_choice(body.get("tool_choice")),
        "parallel_tool_calls": True,
        "include": ["reasoning.encrypted_content"],
        "reasoning": {"summary": "auto"},
    }
    if effort := body.get("reasoning_effort"):
        out["reasoning"]["effort"] = str(effort)
    if cache_key := body.get("prompt_cache_key"):
        # one conversation keeps hitting the same cache; the proxy's clients may pass it
        out["prompt_cache_key"] = str(cache_key)
    tools = [_tool(t) for t in body.get("tools") or [] if isinstance(t, dict)]
    if tools:
        out["tools"] = [t for t in tools if t]
    return out


def _tool(tool: dict[str, Any]) -> dict[str, Any] | None:
    fn: dict[str, Any] | None = _obj(tool.get("function")) or None
    if fn is None:
        if tool.get("type") == "function" and tool.get("name"):
            return {**tool, "strict": tool.get("strict", False)}
        return None
    return {
        "type": "function",
        "name": str(fn.get("name") or ""),
        "description": str(fn.get("description") or ""),
        "parameters": fn.get("parameters") or {"type": "object", "properties": {}},
        "strict": bool(fn.get("strict", False)),
    }


def _tool_choice(choice: Any) -> Any:
    if isinstance(choice, dict):
        fn = choice.get("function")
        name = fn.get("name") if isinstance(fn, dict) else choice.get("name")
        if name:
            return {"type": "function", "name": str(name)}
        return "auto"
    if choice in ("auto", "none", "required"):
        return choice
    return "auto"


def headers_for(token: Token) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token.access}",
        "chatgpt-account-id": token.account_id,
        "OpenAI-Beta": "responses=experimental",
        "originator": ORIGINATOR,
        "User-Agent": f"nanoMuse/{__version__}",
        "accept": "text/event-stream",
        "content-type": "application/json",
    }


# --------------------------------------------------------------------------- response
@dataclass
class ToolCallBuffer:
    index: int
    call_id: str
    name: str
    arguments: str = ""
    announced: bool = False


@dataclass
class StreamState:
    """Folds Codex Responses SSE events into Chat Completions chunks (and keeps the totals
    for the non-streaming answer)."""

    model: str
    id: str = field(default_factory=lambda: "chatcmpl-" + uuid.uuid4().hex[:24])
    created: int = field(default_factory=lambda: int(time.time()))
    content: list[str] = field(default_factory=list)
    reasoning: list[str] = field(default_factory=list)
    calls: dict[str, ToolCallBuffer] = field(default_factory=dict)
    finish_reason: str | None = None
    usage: dict[str, int] = field(default_factory=dict)
    error: dict[str, Any] | None = None
    done: bool = False

    def _chunk(self, delta: dict[str, Any], finish: str | None = None) -> dict[str, Any]:
        return {
            "id": self.id,
            "object": "chat.completion.chunk",
            "created": self.created,
            "model": self.model,
            "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
        }

    def feed(self, event: dict[str, Any]) -> list[dict[str, Any]]:
        """One SSE event → zero or more Chat Completions chunks."""
        kind = str(event.get("type") or "")
        if kind == "response.output_text.delta":
            text = str(event.get("delta") or "")
            if not text:
                return []
            self.content.append(text)
            return [self._chunk({"content": text})]
        if kind in ("response.reasoning_summary_text.delta", "response.reasoning_text.delta"):
            text = str(event.get("delta") or "")
            if not text:
                return []
            self.reasoning.append(text)
            return [self._chunk({"reasoning_content": text})]
        if kind == "response.output_item.added":
            item = _obj(event.get("item"))
            if item.get("type") == "function_call" and item.get("call_id"):
                call_id = str(item["call_id"])
                buf: ToolCallBuffer = ToolCallBuffer(
                    index=len(self.calls),
                    call_id=call_id,
                    name=str(item.get("name") or ""),
                    arguments=str(item.get("arguments") or ""),
                    announced=True,
                )
                self.calls[call_id] = buf
                return [
                    self._chunk(
                        {
                            "tool_calls": [
                                {
                                    "index": buf.index,
                                    "id": call_id,
                                    "type": "function",
                                    "function": {"name": buf.name, "arguments": buf.arguments},
                                }
                            ]
                        }
                    )
                ]
            return []
        if kind == "response.function_call_arguments.delta":
            call_id = str(event.get("call_id") or "")
            known = self.calls.get(call_id)
            delta = str(event.get("delta") or "")
            if known is None or not delta:
                return []
            known.arguments += delta
            return [
                self._chunk(
                    {
                        "tool_calls": [
                            {"index": known.index, "function": {"arguments": delta}},
                        ]
                    }
                )
            ]
        if kind == "response.function_call_arguments.done":
            call_id = str(event.get("call_id") or "")
            known = self.calls.get(call_id)
            if known is not None and event.get("arguments") is not None:
                known.arguments = str(event["arguments"])
            return []
        if kind == "response.output_item.done":
            item = _obj(event.get("item"))
            if item.get("type") == "function_call" and item.get("call_id"):
                call_id = str(item["call_id"])
                known = self.calls.get(call_id)
                if known is None:
                    # never announced (no `added` event): one chunk with the whole call
                    whole = ToolCallBuffer(
                        index=len(self.calls),
                        call_id=call_id,
                        name=str(item.get("name") or ""),
                        arguments=str(item.get("arguments") or ""),
                        announced=True,
                    )
                    self.calls[call_id] = whole
                    return [
                        self._chunk(
                            {
                                "tool_calls": [
                                    {
                                        "index": whole.index,
                                        "id": call_id,
                                        "type": "function",
                                        "function": {
                                            "name": whole.name,
                                            "arguments": whole.arguments,
                                        },
                                    }
                                ]
                            }
                        )
                    ]
                if item.get("arguments") is not None:
                    known.arguments = str(item["arguments"])
            return []
        if kind in ("response.completed", "response.incomplete"):
            response = _obj(event.get("response"))
            self.usage = _usage(response.get("usage"))
            self.done = True
            if kind == "response.incomplete":
                details = response.get("incomplete_details") or {}
                reason = details.get("reason") if isinstance(details, dict) else ""
                self.finish_reason = "length" if reason == "max_output_tokens" else "stop"
            else:
                self.finish_reason = "tool_calls" if self.calls else "stop"
            final = self._chunk({}, self.finish_reason)
            final["usage"] = dict(self.usage)
            return [final]
        if kind in ("response.failed", "error"):
            detail = _obj(event.get("error")) or _obj(_obj(event.get("response")).get("error"))
            message = str(detail.get("message") or event.get("message") or "upstream error")
            self.error = {
                "message": message,
                "type": str(detail.get("type") or "upstream"),
                "code": detail.get("code"),
            }
            self.finish_reason = "error"
            self.done = True
            final = self._chunk({}, "error")
            final["error"] = self.error
            return [final]
        return []

    # -- the folded answer
    def tool_calls(self) -> list[dict[str, Any]]:
        return [
            {
                "id": buf.call_id,
                "type": "function",
                "function": {"name": buf.name, "arguments": buf.arguments},
            }
            for buf in sorted(self.calls.values(), key=lambda b: b.index)
        ]

    def completion(self) -> dict[str, Any]:
        """The whole answer as one Chat Completions object."""
        message: dict[str, Any] = {"role": "assistant", "content": "".join(self.content) or None}
        if self.reasoning:
            message["reasoning_content"] = "".join(self.reasoning)
        if self.calls:
            message["tool_calls"] = self.tool_calls()
        return {
            "id": self.id,
            "object": "chat.completion",
            "created": self.created,
            "model": self.model,
            "choices": [{"index": 0, "message": message, "finish_reason": self.finish_reason}],
            "usage": dict(self.usage),
        }


def _usage(raw: Any) -> dict[str, int]:
    if not isinstance(raw, dict):
        return {}
    prompt = int(raw.get("input_tokens") or 0)
    completion = int(raw.get("output_tokens") or 0)
    return {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": int(raw.get("total_tokens") or prompt + completion),
    }


async def sse_events(lines: AsyncIterator[str]) -> AsyncIterator[dict[str, Any]]:
    """The JSON objects in a ``text/event-stream``; ``[DONE]`` and blanks are skipped."""
    data: list[str] = []
    async for raw in lines:
        line = raw.rstrip("\r\n")
        if line == "":
            if data:
                payload = "\n".join(data)
                data = []
                if payload.strip() == "[DONE]":
                    continue
                try:
                    obj = json.loads(payload)
                except json.JSONDecodeError:
                    continue
                if isinstance(obj, dict):
                    yield obj
            continue
        if line.startswith(":"):
            continue
        if line.startswith("data:"):
            data.append(line[5:].lstrip())
    if data:
        try:
            obj = json.loads("\n".join(data))
        except json.JSONDecodeError:
            return
        if isinstance(obj, dict):
            yield obj


class UpstreamError(Exception):
    """The Codex endpoint answered with an HTTP error before any event. ``code`` is the
    classified kind (``quota``, ``rate_limited``, ``region_blocked``, ``upstream``, …)."""

    def __init__(
        self,
        status: int,
        message: str,
        retry_after: str | None = None,
        code: str = "upstream",
    ):
        super().__init__(message)
        self.status = status
        self.message = message
        self.retry_after = retry_after
        self.code = code

    @classmethod
    def from_error(cls, err: ChatGPTError) -> UpstreamError:
        after = str(err.retry_after) if err.retry_after is not None else None
        return cls(err.status or 502, err.message, after, err.code)


class CodexClient:
    """Sends a Codex Responses body with the sign-in's token and yields the SSE events.

    A 401 refreshes the token once and sends again; the second 401 is the caller's. The
    ``x-codex-*`` headers of every answer are kept in :attr:`limits` (what is left of the
    plan's windows); a request that never gets an answer is a :class:`ChatGPTError`
    ``unreachable``, never the socket's text."""

    def __init__(
        self,
        auth: Auth,
        http: httpx.AsyncClient | None = None,
        url: str = RESPONSES_URL,
        timeout: float = 180.0,
        proxy: str | None = None,
    ):
        self.auth = auth
        self.url = url
        self._http = http
        self._own = http is None
        self.timeout = timeout
        self.proxy = proxy or None
        #: the plan's usage windows from the last answer that carried them
        self.limits: Limits | None = None

    @property
    def http(self) -> httpx.AsyncClient:
        if self._http is None:
            self._http = http_client(httpx.Timeout(self.timeout, connect=20.0), self.proxy)
        return self._http

    async def close(self) -> None:
        if self._own and self._http is not None:
            await self._http.aclose()
            self._http = None

    async def events(self, body: dict[str, Any]) -> AsyncIterator[dict[str, Any]]:
        token = await self.auth.token()
        for attempt in (1, 2):
            req = self.http.build_request(
                "POST", self.url, json=body, headers=headers_for(token), timeout=self.timeout
            )
            try:
                response = await self.http.send(req, stream=True)
            except httpx.HTTPError as exc:
                raise classify_transport(exc) from exc
            limits = Limits.from_headers(response.headers)
            if limits is not None:
                self.limits = limits
            if response.status_code == 401 and attempt == 1:
                await response.aclose()
                logger.info("Codex answered 401; refreshing the ChatGPT token once")
                token = await self.auth.token(force_refresh=True)
                continue
            if response.status_code != 200:
                text = (await response.aread()).decode("utf-8", "replace")
                await response.aclose()
                raise UpstreamError.from_error(
                    classify_http(response.status_code, text, response.headers)
                )
            try:
                async for event in sse_events(response.aiter_lines()):
                    yield event
            except httpx.HTTPError as exc:
                raise classify_transport(exc) from exc
            finally:
                await response.aclose()
            return


# --------------------------------------------------------------------------- the backend
class CodexLLM(BaseLLM):
    """``provider = "chatgpt"``: the runtime talks to the Codex endpoint itself, with the
    stored sign-in. ``base_url``/``api_key`` in the slot are ignored (a warning once)."""

    name = "chatgpt"
    supports_native_tools = True
    # every model behind the sign-in reads pictures
    vision_available: bool | None = True

    def __init__(
        self,
        settings: LLMSettings,
        data_dir: Path | None = None,
        client: CodexClient | None = None,
    ):
        self.settings = settings
        if settings.base_url or settings.api_key:
            logger.warning(
                'provider = "chatgpt" uses the sign-in from `nanomuse chatgpt login`; '
                "base_url and api_key in this slot are ignored"
            )
        if settings.vision == "off":
            self.vision_available = False
        if client is None:
            store = TokenStore.in_dir(data_dir or DEFAULT_DATA_DIR)
            proxy = settings.proxy or None
            client = CodexClient(Auth(store, proxy=proxy), timeout=settings.timeout, proxy=proxy)
        self.client = client
        self.model = settings.model or DEFAULT_MODEL

    async def close(self) -> None:
        await self.client.close()

    async def ask(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str = "auto",
        on_delta: DeltaCallback | None = None,
        on_reasoning_delta: DeltaCallback | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        with_images = has_images(messages) and self.vision_available is not False
        wire = messages if with_images or not has_images(messages) else without_images(messages)
        chat_messages = []
        for m in wire:
            d = m.to_openai(include_reasoning=False)
            if with_images and m.images:
                d["content"] = content_parts(m)
            chat_messages.append(d)
        body: dict[str, Any] = {"model": self.model, "messages": chat_messages}
        if tools:
            body["tools"] = tools
            body["tool_choice"] = tool_choice
        codex_body = to_codex(body)
        if self.settings.extra_body:
            codex_body.update(self.settings.extra_body)
        state = StreamState(model=self.model)
        try:
            async for event in self.client.events(codex_body):
                for chunk in state.feed(event):
                    delta = chunk["choices"][0]["delta"]
                    if on_delta and delta.get("content"):
                        on_delta(str(delta["content"]))
                    if on_reasoning_delta and delta.get("reasoning_content"):
                        on_reasoning_delta(str(delta["reasoning_content"]))
                if state.done:
                    break
        except UpstreamError as exc:
            raise RuntimeError(f"ChatGPT: {exc.message}") from exc
        except ChatGPTError as exc:
            raise RuntimeError(f"ChatGPT: {exc.message}") from exc
        if state.error:
            raise RuntimeError(f"ChatGPT: {state.error['message']}")
        return LLMResponse(
            content="".join(state.content).strip() or None,
            tool_calls=[
                ToolCall(
                    id=c["id"],
                    function=Function(
                        name=c["function"]["name"], arguments=c["function"]["arguments"]
                    ),
                )
                for c in state.tool_calls()
            ],
            reasoning="".join(state.reasoning).strip() or None,
            finish_reason=state.finish_reason or "stop",
            usage=dict(state.usage),
            model=self.model,
        )


__all__ = [
    "CodexClient",
    "CodexLLM",
    "StreamState",
    "UpstreamError",
    "headers_for",
    "sse_events",
    "to_codex",
]

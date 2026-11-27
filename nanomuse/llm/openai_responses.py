"""OpenAI Responses API–compatible provider (``POST {base_url}/responses``).

Useful for OpenAI's Responses endpoint and for "agent app" gateways that expose
a Responses-shaped API. Some of those gateways silently ignore client-side
``tools`` (no error, the model just never calls one); pair this provider with
``tool_mode = "prompt"`` in that case — ``auto`` can only catch endpoints that
*reject* tools.
"""

from __future__ import annotations

from typing import Any

import openai
from openai import AsyncOpenAI
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from nanomuse.config import LLMSettings
from nanomuse.llm.base import (
    BaseLLM,
    DeltaCallback,
    ThinkStreamFilter,
    ToolsUnsupported,
    begin_call,
    end_call,
    proxied_http,
    says_no_tools,
    split_think,
)
from nanomuse.llm.openai_chat import PartialStreamError
from nanomuse.llm.session import client_headers, new_fallback, session_id
from nanomuse.llm.vision import content_parts, has_images, model_takes_images, without_images
from nanomuse.logger import logger
from nanomuse.schema import Function, LLMResponse, Message, Role, ToolCall, new_id

try:  # the SDK's error classes carry a response of the HTTP library the SDK is built on
    import httpx2 as _httpx  # openai 3.x
except ImportError:  # pragma: no cover — openai 1.x
    import httpx as _httpx  # type: ignore[no-redef]

_RETRYABLE = (
    openai.APIConnectionError,
    openai.APITimeoutError,
    openai.RateLimitError,
    openai.InternalServerError,
)

_BAD_RESPONSE_CODES = {
    "bad_request",
    "bio_policy",
    "data_residency_mismatch",
    "empty_image_file",
    "failed_to_download_image",
    "image_content_policy_violation",
    "image_file_too_large",
    "image_file_not_found",
    "image_parse_error",
    "image_too_large",
    "image_too_small",
    "invalid_base64_image",
    "invalid_image",
    "invalid_image_format",
    "invalid_image_mode",
    "invalid_image_url",
    "invalid_prompt",
    "invalid_request_error",
    "misalignment_policy_violation",
    "unsupported_image_media_type",
}


def _response_failure(error: Any) -> openai.APIError:
    """Turn a streamed Responses failure into the SDK class used by normal HTTP failures."""
    code = str(getattr(error, "code", "") or "")
    message = str(getattr(error, "message", "") or error or "response failed")
    request = _httpx.Request("POST", "https://api.openai.invalid/v1/responses")
    body = {"error": {"code": code, "message": message}}
    if code in ("rate_limit", "rate_limit_exceeded"):
        return openai.RateLimitError(
            message, response=_httpx.Response(429, request=request), body=body
        )
    if code in _BAD_RESPONSE_CODES:
        return openai.BadRequestError(
            message, response=_httpx.Response(400, request=request), body=body
        )
    return openai.InternalServerError(
        message, response=_httpx.Response(500, request=request), body=body
    )


def _to_responses_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for t in tools:
        fn = t.get("function", t)
        out.append(
            {
                "type": "function",
                "name": fn["name"],
                "description": fn.get("description", ""),
                "parameters": fn.get("parameters", {"type": "object", "properties": {}}),
            }
        )
    return out


def _to_input_items(
    messages: list[Message], with_images: bool = False
) -> tuple[str | None, list[dict[str, Any]]]:
    instructions: list[str] = []
    items: list[dict[str, Any]] = []
    call_id_counts: dict[str, int] = {}
    used_call_ids: set[str] = set()
    pending_outputs: dict[str, list[str]] = {}
    for m in messages:
        if m.role == Role.SYSTEM:
            if m.content:
                instructions.append(m.content)
        elif m.role == Role.USER:
            content: Any = (
                content_parts(m, image_type="input_image")
                if with_images and m.images
                else (m.content or "")
            )
            items.append({"role": "user", "content": content})
        elif m.role == Role.ASSISTANT:
            if m.content:
                items.append({"role": "assistant", "content": m.content})
            for tc in m.tool_calls or []:
                raw_id = tc.id
                wire_id = raw_id[:64]
                occurrence = call_id_counts.get(wire_id, 0) + 1
                while True:
                    suffix = "" if occurrence == 1 else f"-{occurrence}"
                    call_id = f"{wire_id[: 64 - len(suffix)]}{suffix}"
                    if call_id not in used_call_ids:
                        break
                    occurrence += 1
                call_id_counts[wire_id] = occurrence
                used_call_ids.add(call_id)
                pending_outputs.setdefault(raw_id, []).append(call_id)
                items.append(
                    {
                        "type": "function_call",
                        "call_id": call_id,
                        "name": tc.function.name,
                        "arguments": tc.function.wire_arguments(),
                    }
                )
        elif m.role == Role.TOOL:
            raw_id = m.tool_call_id or ""
            queued = pending_outputs.get(raw_id)
            call_id = queued.pop(0) if queued else raw_id[:64]
            items.append(
                {
                    "type": "function_call_output",
                    "call_id": call_id,
                    "output": m.content or "",
                }
            )
    return ("\n\n".join(instructions) or None), items


class OpenAIResponsesLLM(BaseLLM):
    name = "openai_responses"
    supports_native_tools = True

    def __init__(self, settings: LLMSettings, session_header: str = ""):
        self.settings = settings
        # a vendor that wants one id per conversation (the catalogue's `session_header`)
        # also wants the client's own name rather than the SDK's
        self.session_header = session_header
        self._session_fallback = new_fallback()
        self.client = AsyncOpenAI(
            api_key=settings.api_key or "EMPTY",
            base_url=settings.base_url or None,
            timeout=settings.timeout,
            max_retries=0,
            default_headers=client_headers(settings.extra_headers, session_header) or None,
            http_client=proxied_http(settings.proxy, settings.timeout),
        )
        if settings.vision == "auto":
            self.vision_available = model_takes_images(settings.model)

    async def ask(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str = "auto",
        on_delta: DeltaCallback | None = None,
        on_reasoning_delta: DeltaCallback | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        pictures = has_images(messages)
        with_images = (
            pictures and self.settings.vision != "off" and self.vision_available is not False
        )
        instructions, items = _to_input_items(
            messages if with_images or not pictures else without_images(messages), with_images
        )
        params: dict[str, Any] = {
            "model": self.settings.model,
            "input": items,
            "temperature": self.settings.temperature,
            "max_output_tokens": max_tokens or self.settings.max_tokens,
        }
        if instructions:
            params["instructions"] = instructions
        if tools:
            params["tools"] = _to_responses_tools(tools)
            params["tool_choice"] = tool_choice
        if self.settings.extra_body:
            params["extra_body"] = self.settings.extra_body
        call = begin_call(self.settings.base_url)
        extra_headers = dict(call.headers)
        if self.session_header:
            extra_headers[self.session_header] = session_id(self._session_fallback)
        if extra_headers:
            params["extra_headers"] = extra_headers

        try:
            resp = await self._send(params, on_delta, on_reasoning_delta)
        except openai.BadRequestError as e:
            if tools and says_no_tools(str(e)):
                raise ToolsUnsupported(str(e)) from e
            if with_images and self.settings.vision == "auto":
                logger.warning(
                    "the endpoint rejected a message with images ({}); sending text only "
                    'from now on; set llm.vision = "off" to skip the attempt',
                    str(e).splitlines()[0][:200],
                )
                self.vision_available = False
                params["input"] = _to_input_items(without_images(messages), False)[1]
                resp = await self._send(params, on_delta, on_reasoning_delta)
                end_call(
                    call,
                    settings=self.settings,
                    params=params,
                    response=resp,
                    messages=self._chat_shape(without_images(messages), False),
                )
                return resp
            raise
        if with_images and self.vision_available is None:
            self.vision_available = True
        end_call(
            call,
            settings=self.settings,
            params=params,
            response=resp,
            messages=self._chat_shape(
                messages if with_images or not pictures else without_images(messages), with_images
            ),
        )
        return resp

    def _chat_shape(self, messages: list[Message], with_images: bool) -> list[dict[str, Any]]:
        """The conversation in the Chat Completions shape the record keeps, whichever
        protocol carried it."""
        out = []
        for m in messages:
            d = m.to_openai(include_reasoning=self.settings.pass_reasoning)
            if with_images and m.images:
                d["content"] = content_parts(m)
            out.append(d)
        return out

    async def _send(
        self,
        params: dict[str, Any],
        on_delta: DeltaCallback | None,
        on_reasoning_delta: DeltaCallback | None = None,
    ) -> LLMResponse:
        async for attempt in AsyncRetrying(
            retry=retry_if_exception_type(_RETRYABLE),
            stop=stop_after_attempt(max(1, self.settings.max_retries + 1)),
            wait=wait_exponential(multiplier=2, min=2, max=60),
            reraise=True,
        ):
            with attempt:
                if attempt.retry_state.attempt_number > 1:
                    logger.warning(
                        "LLM retry {}/{}",
                        attempt.retry_state.attempt_number - 1,
                        self.settings.max_retries,
                    )
                if self.settings.stream:
                    return await self._ask_stream(params, on_delta, on_reasoning_delta)
                return await self._ask_once(params)
        raise RuntimeError("unreachable")  # pragma: no cover

    async def close(self) -> None:
        await self.client.close()

    # ------------------------------------------------------------------ internals
    def _parse(self, resp: Any) -> LLMResponse:
        texts: list[str] = []
        reasoning: list[str] = []
        tool_calls: list[ToolCall] = []
        for item in getattr(resp, "output", None) or []:
            itype = getattr(item, "type", None)
            if itype == "message":
                for part in getattr(item, "content", None) or []:
                    if getattr(part, "type", None) in ("output_text", "text"):
                        texts.append(getattr(part, "text", "") or "")
            elif itype == "function_call":
                tool_calls.append(
                    ToolCall(
                        id=getattr(item, "call_id", None) or getattr(item, "id", None) or new_id(),
                        function=Function(
                            name=getattr(item, "name", ""),
                            arguments=getattr(item, "arguments", "") or "{}",
                        ),
                    )
                )
            elif itype == "reasoning":
                for s in getattr(item, "summary", None) or []:
                    reasoning.append(getattr(s, "text", "") or "")
        content, think = split_think("".join(texts).strip() or None)
        usage = resp.usage.model_dump(exclude_none=True) if getattr(resp, "usage", None) else {}
        # the budget ran out (a reasoning model thinking): the same "length" the Chat API says
        details = getattr(resp, "incomplete_details", None)
        cut = getattr(resp, "status", None) == "incomplete" and (
            getattr(details, "reason", None) in (None, "max_output_tokens")
        )
        return LLMResponse(
            content=content,
            tool_calls=tool_calls,
            reasoning="\n".join(r for r in reasoning if r) or think,
            finish_reason="tool_calls" if tool_calls else ("length" if cut else "stop"),
            usage=usage,
            model=getattr(resp, "model", None),
        )

    async def _ask_once(self, params: dict[str, Any]) -> LLMResponse:
        resp = await self.client.responses.create(**params, stream=False)
        return self._parse(resp)

    async def _ask_stream(
        self,
        params: dict[str, Any],
        on_delta: DeltaCallback | None,
        on_reasoning_delta: DeltaCallback | None = None,
    ) -> LLMResponse:
        stream = await self.client.responses.create(**params, stream=True)
        think = ThinkStreamFilter()
        final: Any = None
        streamed: list[str] = []
        shown_reasoning = False
        try:
            async for event in stream:
                etype = getattr(event, "type", "")
                if etype == "response.output_text.delta":
                    visible = think.feed(getattr(event, "delta", "") or "")
                    if visible:
                        streamed.append(visible)
                        if on_delta:
                            on_delta(visible)
                elif etype in (
                    "response.reasoning_summary_text.delta",
                    "response.reasoning_text.delta",
                ):
                    piece = getattr(event, "delta", "") or ""
                    if piece and on_reasoning_delta:
                        shown_reasoning = True
                        on_reasoning_delta(piece)
                elif etype in ("response.completed", "response.incomplete"):
                    final = getattr(event, "response", None)
                elif etype == "response.failed":
                    err = getattr(getattr(event, "response", None), "error", None)
                    raise _response_failure(err)
        except Exception as exc:
            # what the person already saw is not shown twice: text, or the thinking streamed live
            if streamed or shown_reasoning:
                raise PartialStreamError(
                    "the model stream failed after visible text was shown; it was not retried"
                ) from exc
            raise
        tail = think.flush()
        if tail:
            streamed.append(tail)
            if on_delta:
                on_delta(tail)
        if final is not None:
            parsed = self._parse(final)
            if parsed.content is None and streamed:
                parsed.content = "".join(streamed).strip() or None
            parsed.reasoning = parsed.reasoning or think.reasoning
            return parsed
        return LLMResponse(content="".join(streamed).strip() or None, reasoning=think.reasoning)


__all__ = ["OpenAIResponsesLLM"]

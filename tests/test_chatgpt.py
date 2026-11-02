"""The ChatGPT sign-in: the token store, refresh, the Codex translation, the CLI.

Nothing here reaches the network: the token endpoint and the Codex endpoint are
``httpx.MockTransport`` handlers, the tokens are made-up JWTs with the claims we read.
"""

from __future__ import annotations

import asyncio
import base64
import json
import stat
import sys
import time
from pathlib import Path
from typing import Any

import httpx
import pytest
from typer.testing import CliRunner

from nanomuse.config import LLMSettings
from nanomuse.llm.chatgpt import (
    REGION_CODE,
    Auth,
    ChatGPTError,
    Limits,
    Token,
    TokenStore,
    account_from,
    classify_http,
    classify_transport,
    failure_line,
    plan_label,
)
from nanomuse.llm.codex import CodexClient, CodexLLM, StreamState, sse_events, to_codex
from nanomuse.schema import Message

TOKEN_URL = "https://auth.test/oauth/token"
RESPONSES_URL = "https://codex.test/responses"


def _b64(data: dict[str, Any]) -> str:
    return base64.urlsafe_b64encode(json.dumps(data).encode()).rstrip(b"=").decode()


def jwt(account: str = "acct-1", plan: str = "plus", nonce: str = "a") -> str:
    """A token with the two claims the runtime reads; nothing is verified."""
    claims = {
        "https://api.openai.com/auth": {
            "chatgpt_account_id": account,
            "chatgpt_plan_type": plan,
        },
        "nonce": nonce,
    }
    return f"{_b64({'alg': 'none'})}.{_b64(claims)}.sig"


def token(expires_in: int = 3600, nonce: str = "a") -> Token:
    now = int(time.time())
    return Token(
        access=jwt(nonce=nonce),
        refresh="rt-" + nonce,
        expires_at=now + expires_in,
        account_id="acct-1",
        plan="plus",
        label="ChatGPT Plus",
        obtained_at=now,
    )


def sse(events: list[dict[str, Any]]) -> bytes:
    return b"".join(f"data: {json.dumps(e)}\n\n".encode() for e in events) + b"data: [DONE]\n\n"


# ----------------------------------------------------------------------------- claims
def test_the_claims_and_the_plan_label():
    assert account_from(jwt("acc", "pro")) == ("acc", "pro")
    assert account_from("not.a.jwt") == ("", "")
    assert plan_label("plus") == "ChatGPT Plus"
    assert plan_label("team") == "ChatGPT Team"
    assert plan_label("") == "ChatGPT" and plan_label("free") == "ChatGPT"
    assert plan_label("enterprise") == "ChatGPT Enterprise"


def test_a_token_payload_without_an_account_is_refused():
    with pytest.raises(ChatGPTError) as exc:
        Token.from_payload({"access_token": f"{_b64({})}.{_b64({'sub': 'x'})}.s"})
    assert exc.value.code == "no_account"
    with pytest.raises(ChatGPTError) as exc:
        Token.from_payload({})
    assert exc.value.code == "exchange_failed"


# ----------------------------------------------------------------------------- the store
def test_the_store_is_written_0600_and_never_shows_the_tokens(tmp_path: Path):
    store = TokenStore.in_dir(tmp_path / "data")
    assert store.load() is None
    store.save(token())
    assert store.path.name == "chatgpt.json"
    if sys.platform != "win32":
        assert stat.S_IMODE(store.path.stat().st_mode) == 0o600
    loaded = store.load()
    assert loaded is not None and loaded.label == "ChatGPT Plus"
    public = loaded.public()
    assert "access" not in public and "refresh" not in public
    assert public["plan"] == "plus" and public["expires_in"] > 3500
    assert store.clear() is True and store.load() is None
    assert store.clear() is False


@pytest.mark.asyncio
async def test_refresh_happens_at_the_margin_with_the_new_token_stored(tmp_path: Path):
    store = TokenStore.in_dir(tmp_path)
    store.save(token(expires_in=30, nonce="old"))
    calls: list[dict[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == TOKEN_URL
        form = dict(p.split("=", 1) for p in request.content.decode().split("&"))
        calls.append(form)
        return httpx.Response(
            200,
            json={"access_token": jwt(nonce="new"), "refresh_token": "rt-new", "expires_in": 3600},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        auth = Auth(store, http=http, token_url=TOKEN_URL)
        fresh = await auth.token()
        assert len(calls) == 1
        assert calls[0]["grant_type"] == "refresh_token" and calls[0]["refresh_token"] == "rt-old"
        assert fresh.refresh == "rt-new" and fresh.expires_in > 3500
        assert store.load().access == fresh.access
        # good for an hour: no second call
        assert (await auth.token()).access == fresh.access
        assert len(calls) == 1


@pytest.mark.asyncio
async def test_a_refused_refresh_clears_the_store(tmp_path: Path):
    store = TokenStore.in_dir(tmp_path)
    store.save(token(expires_in=10))

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "invalid_grant"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        auth = Auth(store, http=http, token_url=TOKEN_URL)
        with pytest.raises(ChatGPTError) as exc:
            await auth.token()
    assert exc.value.code == "not_signed_in"
    assert store.load() is None
    assert not auth.signed_in()


@pytest.mark.asyncio
async def test_the_loop_keeps_turning_while_another_process_holds_the_lock(tmp_path: Path):
    """A sibling process refreshing the token holds ``chatgpt.lock``; the wait for it must
    not stall the event loop (other chats keep streaming), and the token it wrote is used."""
    import threading

    store = TokenStore.in_dir(tmp_path)
    store.save(token(expires_in=10, nonce="old"))
    held = threading.Event()
    release = threading.Event()

    def other_process() -> None:
        with store.lock():  # the same lock, from a thread: the kernel sees another holder
            held.set()
            release.wait(5)
            store.save(token(expires_in=3600, nonce="theirs"))

    threading.Thread(target=other_process, daemon=True).start()
    assert held.wait(5)
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(500)

    ticks = 0

    async def ticker() -> None:
        nonlocal ticks
        while True:
            await asyncio.sleep(0.01)
            ticks += 1

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        auth = Auth(store, http=http, token_url=TOKEN_URL)
        beat = asyncio.create_task(ticker())
        refresh = asyncio.create_task(auth.token())
        await asyncio.sleep(0.3)
        # the ticker beats every 10 ms; a loaded runner stretches a beat far past that,
        # so the count itself is not the point — only that beats keep coming at all
        # while the refresh waits for the lock. A blocked loop delivers none.
        assert not refresh.done(), "the refresh finished without the lock"
        before = ticks
        await asyncio.sleep(0.3)
        assert not refresh.done() and ticks > before, "the wait for the lock blocked the loop"
        release.set()
        fresh = await asyncio.wait_for(refresh, 5)
        beat.cancel()
    # the other process's token is taken as it is: no second refresh over the wire
    assert fresh.access == token(nonce="theirs").access and calls == 0


def test_a_second_handle_waits_for_the_lock_and_takes_it_after(tmp_path: Path):
    """The lock is exclusive across handles on both platforms, which is the whole point: on
    Windows the same file opened twice is two holders, as it is on POSIX."""
    import threading

    store = TokenStore.in_dir(tmp_path)
    held = threading.Event()
    release = threading.Event()
    took_it = threading.Event()

    def holder() -> None:
        with store.lock():
            held.set()
            release.wait(5)

    def waiter() -> None:
        held.wait(5)
        with store.lock():
            took_it.set()

    threading.Thread(target=holder, daemon=True).start()
    threading.Thread(target=waiter, daemon=True).start()
    assert held.wait(5)
    time.sleep(0.3)
    assert not took_it.is_set(), "the second handle took a lock somebody was holding"
    release.set()
    assert took_it.wait(5), "the second handle never got the lock after it was released"


# ----------------------------------------------------------------------------- translation
def test_chat_completions_to_the_codex_responses_body():
    body = {
        "model": "gpt-5.6-sol",
        "temperature": 0.3,
        "max_tokens": 100,
        "top_p": 0.9,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": "Be brief."},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "What is this?"},
                    {
                        "type": "image_url",
                        "image_url": {"url": "data:image/png;base64,AAAA", "detail": "low"},
                    },
                ],
            },
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "lookup", "arguments": '{"q": "x"}'},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "call_1", "content": "42"},
            {"role": "assistant", "content": "It is 42."},
            {"role": "user", "content": "thanks"},
        ],
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": "lookup",
                    "description": "Look up",
                    "parameters": {"type": "object", "properties": {"q": {"type": "string"}}},
                },
            }
        ],
        "tool_choice": {"type": "function", "function": {"name": "lookup"}},
    }
    out = to_codex(body)
    assert out["model"] == "gpt-5.6-sol"
    assert out["instructions"] == "Be brief."
    assert out["store"] is False and out["stream"] is True
    assert out["parallel_tool_calls"] is True
    assert out["include"] == ["reasoning.encrypted_content"]
    for dropped in ("temperature", "max_tokens", "max_output_tokens", "top_p", "response_format"):
        assert dropped not in out
    assert out["input"] == [
        {
            "role": "user",
            "content": [
                {"type": "input_text", "text": "What is this?"},
                {"type": "input_image", "image_url": "data:image/png;base64,AAAA", "detail": "low"},
            ],
        },
        {"type": "function_call", "call_id": "call_1", "name": "lookup", "arguments": '{"q": "x"}'},
        {"type": "function_call_output", "call_id": "call_1", "output": "42"},
        {
            "type": "message",
            "role": "assistant",
            "content": [{"type": "output_text", "text": "It is 42."}],
            "status": "completed",
        },
        {"role": "user", "content": [{"type": "input_text", "text": "thanks"}]},
    ]
    assert out["tools"] == [
        {
            "type": "function",
            "name": "lookup",
            "description": "Look up",
            "parameters": {"type": "object", "properties": {"q": {"type": "string"}}},
            "strict": False,
        }
    ]
    assert out["tool_choice"] == {"type": "function", "name": "lookup"}
    # arguments given as an object become a JSON string; a tool result in parts is encoded
    out2 = to_codex(
        {
            "messages": [
                {
                    "role": "assistant",
                    "tool_calls": [{"id": "c", "function": {"name": "f", "arguments": {"a": 1}}}],
                },
                {"role": "tool", "tool_call_id": "c", "content": [{"type": "text", "text": "ok"}]},
            ],
            "reasoning_effort": "low",
        }
    )
    assert out2["input"][0]["arguments"] == '{"a": 1}'
    assert json.loads(out2["input"][1]["output"]) == [{"type": "text", "text": "ok"}]
    assert out2["reasoning"] == {"summary": "auto", "effort": "low"}
    assert "tools" not in out2 and out2["model"] == "gpt-5.6-sol"


def test_to_codex_dedupes_call_ids_and_keeps_outputs_paired():
    def call(call_id: str) -> dict[str, Any]:
        return {
            "id": call_id,
            "type": "function",
            "function": {"name": "echo", "arguments": "{}"},
        }

    long_id = "x" * 70
    out = to_codex(
        {
            "messages": [
                {
                    "role": "assistant",
                    "tool_calls": [call("call_same"), call("call_same"), call("call_same-2")],
                },
                {"role": "tool", "tool_call_id": "call_same", "content": "first"},
                {"role": "tool", "tool_call_id": "call_same", "content": "second"},
                {"role": "tool", "tool_call_id": "call_same-2", "content": "natural suffix"},
                {
                    "role": "assistant",
                    "tool_calls": [call("call_same"), call(long_id), call(long_id)],
                },
                {"role": "tool", "tool_call_id": "call_same", "content": "third"},
                {"role": "tool", "tool_call_id": long_id, "content": "long first"},
                {"role": "tool", "tool_call_id": long_id, "content": "long second"},
            ]
        }
    )

    items = out["input"]
    calls = [item["call_id"] for item in items if item.get("type") == "function_call"]
    outputs = [item["call_id"] for item in items if item.get("type") == "function_call_output"]
    assert calls == [
        "call_same",
        "call_same-2",
        "call_same-2-2",
        "call_same-3",
        "x" * 64,
        f"{'x' * 62}-2",
    ]
    assert outputs == calls
    assert len(calls) == len(set(calls))
    assert all(len(call_id) <= 64 for call_id in calls)


@pytest.mark.asyncio
async def test_the_responses_stream_becomes_chat_completions_chunks():
    events = [
        {"type": "response.created", "response": {"id": "resp_1"}},
        {"type": "response.reasoning_summary_text.delta", "delta": "thinking"},
        {"type": "response.output_text.delta", "delta": "Hel"},
        {"type": "response.output_text.delta", "delta": "lo"},
        {
            "type": "response.output_item.added",
            "item": {
                "type": "function_call",
                "call_id": "call_9",
                "name": "lookup",
                "arguments": "",
            },
        },
        {"type": "response.function_call_arguments.delta", "call_id": "call_9", "delta": '{"q":'},
        {"type": "response.function_call_arguments.delta", "call_id": "call_9", "delta": " 1}"},
        {
            "type": "response.completed",
            "response": {"usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}},
        },
    ]

    async def lines():
        for line in sse(events).decode().split("\n"):
            yield line

    state = StreamState(model="gpt-5.6-sol")
    chunks: list[dict[str, Any]] = []
    async for event in sse_events(lines()):
        chunks.extend(state.feed(event))
    deltas = [c["choices"][0]["delta"] for c in chunks]
    assert deltas[0] == {"reasoning_content": "thinking"}
    assert deltas[1] == {"content": "Hel"} and deltas[2] == {"content": "lo"}
    assert deltas[3]["tool_calls"] == [
        {
            "index": 0,
            "id": "call_9",
            "type": "function",
            "function": {"name": "lookup", "arguments": ""},
        }
    ]
    assert deltas[4]["tool_calls"] == [{"index": 0, "function": {"arguments": '{"q":'}}]
    final = chunks[-1]
    assert final["choices"][0]["finish_reason"] == "tool_calls"
    assert final["usage"] == {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
    assert all(c["object"] == "chat.completion.chunk" for c in chunks)
    done = state.completion()
    assert done["choices"][0]["message"]["content"] == "Hello"
    assert done["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"] == '{"q": 1}'
    assert done["choices"][0]["finish_reason"] == "tool_calls"


def test_a_cut_off_answer_and_an_upstream_failure():
    state = StreamState(model="m")
    state.feed({"type": "response.output_text.delta", "delta": "half"})
    [final] = state.feed(
        {
            "type": "response.incomplete",
            "response": {"incomplete_details": {"reason": "max_output_tokens"}, "usage": {}},
        }
    )
    assert final["choices"][0]["finish_reason"] == "length"
    failed = StreamState(model="m")
    [err] = failed.feed({"type": "response.failed", "response": {"error": {"message": "boom"}}})
    assert err["choices"][0]["finish_reason"] == "error" and err["error"]["message"] == "boom"


@pytest.mark.asyncio
async def test_a_401_refreshes_the_token_once_and_retries(tmp_path: Path):
    store = TokenStore.in_dir(tmp_path)
    store.save(token(nonce="old"))
    seen: list[tuple[str, str]] = []  # (url, bearer)

    def handler(request: httpx.Request) -> httpx.Response:
        bearer = request.headers.get("authorization", "").removeprefix("Bearer ")
        seen.append((str(request.url), bearer))
        if str(request.url) == TOKEN_URL:
            return httpx.Response(
                200, json={"access_token": jwt(nonce="new"), "refresh_token": "rt-new"}
            )
        if bearer == jwt(nonce="old"):
            return httpx.Response(401, json={"error": {"message": "expired"}})
        assert request.headers["chatgpt-account-id"] == "acct-1"
        assert request.headers["originator"] == "nanomuse"
        assert request.headers["openai-beta"] == "responses=experimental"
        body = json.loads(request.content)
        assert body["store"] is False and body["instructions"].startswith("You are")
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=sse(
                [
                    {"type": "response.output_text.delta", "delta": "OK"},
                    {"type": "response.completed", "response": {"usage": {"input_tokens": 1}}},
                ]
            ),
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = CodexClient(
            Auth(store, http=http, token_url=TOKEN_URL), http=http, url=RESPONSES_URL
        )
        llm = CodexLLM(LLMSettings(provider="chatgpt"), client=client)
        reply = await llm.ask([Message.system("You are a test."), Message.user("Say OK")])
    assert reply.content == "OK" and reply.finish_reason == "stop"
    assert reply.usage["prompt_tokens"] == 1
    assert [u for u, _ in seen] == [RESPONSES_URL, TOKEN_URL, RESPONSES_URL]
    assert seen[0][1] == jwt(nonce="old") and seen[2][1] == jwt(nonce="new")
    assert store.load().refresh == "rt-new"


@pytest.mark.asyncio
async def test_a_second_401_is_an_error_and_keeps_the_store(tmp_path: Path):
    store = TokenStore.in_dir(tmp_path)
    store.save(token(nonce="old"))

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == TOKEN_URL:
            return httpx.Response(200, json={"access_token": jwt(nonce="new")})
        return httpx.Response(401, json={"error": {"message": "still no"}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = CodexClient(
            Auth(store, http=http, token_url=TOKEN_URL), http=http, url=RESPONSES_URL
        )
        llm = CodexLLM(LLMSettings(provider="chatgpt"), client=client)
        with pytest.raises(RuntimeError, match="ChatGPT: The ChatGPT sign-in is no longer valid"):
            await llm.ask([Message.user("hi")])
    assert store.load() is not None


# ----------------------------------------------------------------------------- failures
def test_the_failures_are_classified_into_plain_sentences():
    # OpenAI refuses the region: the code in the body
    err = classify_http(403, json.dumps({"error": {"code": REGION_CODE, "message": "no"}}))
    assert err.code == "region_blocked" and "region" in err.message and err.status == 403
    # an HTML page where JSON was due (an interception page) is "unreachable", not a 403 to read
    assert classify_http(403, "<!DOCTYPE html><html>blocked</html>").code == "region_blocked"
    assert classify_http(503, "<html><body>captive portal</body></html>").code == "unreachable"
    # the plan has nothing left: OpenAI's own words are kept after ours
    quota = classify_http(
        429,
        json.dumps({"error": {"code": "usage_limit_reached", "message": "Resets in 3 hours."}}),
        {"retry-after": "7200"},
    )
    assert quota.code == "quota" and quota.retry_after == 7200
    assert quota.message.startswith("The ChatGPT plan has nothing left")
    assert "Resets in 3 hours." in quota.message
    # a burst limit is not a spent plan
    burst = classify_http(429, json.dumps({"error": {"type": "rate_limit_exceeded"}}))
    assert burst.code == "rate_limited" and burst.retry_after is None
    assert classify_http(401, "").code == "not_signed_in"
    other = classify_http(500, json.dumps({"error": {"message": "server fell over"}}))
    assert other.code == "upstream" and other.message == "server fell over" and other.status == 500
    assert classify_http(502, "").message == "the Codex endpoint answered HTTP 502"
    # the transport: no answer at all → one sentence that names the host, never the socket text
    unreachable = classify_transport(httpx.ConnectError("[Errno 111] Connection refused"))
    assert (
        unreachable.code == "unreachable" and "chatgpt.com cannot be reached" in unreachable.message
    )
    assert "Errno" not in unreachable.message
    assert classify_transport(httpx.ReadTimeout("slow")).message.endswith("(timed out)")
    assert failure_line("unreachable", chinese=True).startswith("这个网络连不上")
    assert failure_line("nothing") == ""
    assert unreachable.public() == {"code": "unreachable", "message": unreachable.message}
    assert quota.public()["retry_after"] == 7200 and quota.public()["status"] == 429


def test_the_plan_usage_windows_from_headers_and_from_the_usage_endpoint():
    assert Limits.from_headers({"content-type": "text/event-stream"}) is None
    limits = Limits.from_headers(
        {
            "x-codex-primary-used-percent": "40",
            "x-codex-primary-window-minutes": "300",
            "x-codex-primary-reset-after-seconds": "3600",
            "x-codex-secondary-used-percent": "12.5",
            "x-codex-secondary-window-minutes": "10080",
            "x-codex-secondary-reset-after-seconds": "90000",
        }
    )
    assert limits is not None and limits.primary is not None and limits.secondary is not None
    assert limits.primary.used_percent == 40 and limits.primary.window_minutes == 300
    assert limits.secondary.used_percent == 12 and limits.left_percent == 60
    usage = Limits.from_usage(
        {
            "plan_type": "Plus",
            "rate_limit": {
                "limit_reached": False,
                "primary_window": {
                    "used_percent": 90,
                    "limit_window_seconds": 18000,
                    "reset_after_seconds": 1200,
                },
            },
        }
    )
    assert usage.plan == "plus" and usage.primary is not None and usage.secondary is None
    assert usage.primary.window_minutes == 300 and usage.left_percent == 10
    assert usage.public()["primary"]["resets_in_s"] == 1200
    assert Limits.from_usage("nonsense").empty and Limits().left_percent is None


@pytest.mark.asyncio
async def test_an_unreachable_host_is_one_sentence_and_the_headers_carry_the_windows(
    tmp_path: Path,
):
    store = TokenStore.in_dir(tmp_path)
    store.save(token())
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise httpx.ConnectError(
                "failed to connect to chatgpt.com/203.0.113.5 (port 443) after 30000ms"
            )
        return httpx.Response(
            200,
            headers={
                "content-type": "text/event-stream",
                "x-codex-primary-used-percent": "25",
                "x-codex-primary-window-minutes": "300",
                "x-codex-primary-reset-after-seconds": "600",
            },
            content=sse(
                [
                    {"type": "response.output_text.delta", "delta": "OK"},
                    {"type": "response.completed", "response": {"usage": {}}},
                ]
            ),
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = CodexClient(
            Auth(store, http=http, token_url=TOKEN_URL), http=http, url=RESPONSES_URL
        )
        llm = CodexLLM(LLMSettings(provider="chatgpt"), client=client)
        with pytest.raises(RuntimeError) as info:
            await llm.ask([Message.user("hi")])
        assert "chatgpt.com cannot be reached from this network" in str(info.value)
        assert "203.0.113.5" not in str(info.value) and "port 443" not in str(info.value)
        assert client.limits is None
        reply = await llm.ask([Message.user("hi")])
    assert reply.content == "OK"
    assert client.limits is not None and client.limits.primary is not None
    assert client.limits.primary.used_percent == 25 and client.limits.left_percent == 75


def test_the_request_carries_the_codex_shape_and_the_proxy_setting():
    body = to_codex({"model": "gpt-5.4", "messages": [{"role": "user", "content": "hi"}]})
    assert body["text"] == {"verbosity": "medium"} and "prompt_cache_key" not in body
    cached = to_codex({"messages": [], "prompt_cache_key": "conv-1"})
    assert cached["prompt_cache_key"] == "conv-1"
    # `[llm] proxy` reaches the client that talks to chatgpt.com, and the token refresh
    llm = CodexLLM(
        LLMSettings(provider="chatgpt", proxy="http://127.0.0.1:7890"),
        data_dir=Path("/nonexistent"),
    )
    assert llm.client.proxy == "http://127.0.0.1:7890"
    assert llm.client.auth.proxy == "http://127.0.0.1:7890"
    plain = CodexLLM(LLMSettings(provider="chatgpt"), data_dir=Path("/nonexistent"))
    assert plain.client.proxy is None


@pytest.mark.asyncio
async def test_the_proxy_app_reports_the_usage_and_the_failure_codes(tmp_path: Path):
    from httpx import ASGITransport

    from nanomuse.llm.chatgpt_proxy import make_app

    store = TokenStore.in_dir(tmp_path)
    store.save(token())
    usage_url = "https://codex.test/usage"

    def upstream(request: httpx.Request) -> httpx.Response:
        if str(request.url) == usage_url:
            assert request.headers["chatgpt-account-id"] == "acct-1"
            return httpx.Response(
                200,
                json={
                    "plan_type": "plus",
                    "rate_limit": {
                        "primary_window": {
                            "used_percent": 70,
                            "limit_window_seconds": 18000,
                            "reset_after_seconds": 100,
                        }
                    },
                },
            )
        return httpx.Response(
            429,
            json={"error": {"code": "usage_limit_reached", "message": "Try again in 2 hours."}},
            headers={"retry-after": "7200"},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(upstream)) as http:
        app = make_app(
            store,
            "local-token",
            http=http,
            responses_url=RESPONSES_URL,
            usage_url=usage_url,
            token_url=TOKEN_URL,
        )
        async with httpx.AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://proxy",
            headers={"Authorization": "Bearer local-token"},
        ) as local:
            usage = (await local.get("/v1/usage")).json()
            assert usage["signed_in"] is True and usage["label"] == "ChatGPT Plus"
            assert usage["limits"]["left_percent"] == 30 and usage["limits"]["plan"] == "plus"
            r = await local.post(
                "/v1/chat/completions",
                json={"model": "gpt-5.4", "messages": [{"role": "user", "content": "hi"}]},
            )
            assert r.status_code == 429 and r.headers["retry-after"] == "7200"
            err = r.json()["error"]
            assert err["code"] == "quota" and "nothing left" in err["message"]
            assert "Try again in 2 hours." in err["message"]
            assert (
                await local.get("/v1/usage", headers={"Authorization": "Bearer x"})
            ).status_code == 401


def test_the_cli_usage_refuses_when_signed_out(cli_home: Path):
    from nanomuse.cli import app

    out = CliRunner().invoke(app, ["chatgpt", "usage", "--json"])
    assert out.exit_code == 1
    assert json.loads(out.stdout.strip())["code"] == "not_signed_in"


# ----------------------------------------------------------------------------- the CLI
@pytest.fixture()
def cli_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A home of its own: no ./config/config.toml, no ~/.nanomuse, a temporary data dir."""
    from nanomuse import config as config_module

    for var in ("NANOMUSE_CONFIG", "DEEPSEEK_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(config_module, "DEFAULT_DATA_DIR", tmp_path / "home")
    data = tmp_path / "data"
    monkeypatch.setenv("NANOMUSE_DATA_DIR", str(data))
    return data


def test_the_cli_status_and_logout_as_json(cli_home: Path):
    from nanomuse.cli import app

    runner = CliRunner()
    out = runner.invoke(app, ["chatgpt", "status", "--json"])
    assert out.exit_code == 0, out.output
    view = json.loads(out.stdout.strip())
    assert view["signed_in"] is False and view["label"] == "" and view["expires_at"] == 0
    assert view["models"] == [
        "gpt-6.1-sol",
        "gpt-6-sol",
        "gpt-6-luna",
        "gpt-6-astra",
        "gpt-5.6-sol",
        "gpt-5.4",
        "gpt-5.4-mini",
    ]
    assert view["path"] == str(cli_home / "chatgpt.json")

    TokenStore.in_dir(cli_home).save(token())
    out = runner.invoke(app, ["chatgpt", "status", "--json"])
    view = json.loads(out.stdout.strip())
    assert view["signed_in"] is True and view["label"] == "ChatGPT Plus" and view["plan"] == "plus"
    assert view["account_id"] == "acct-1" and 3500 < view["expires_in"] <= 3600
    assert "access" not in view and jwt() not in out.output and "rt-a" not in out.output

    out = runner.invoke(app, ["chatgpt", "logout", "--json"])
    assert json.loads(out.stdout.strip()) == {"ok": True, "was_signed_in": True}
    assert not (cli_home / "chatgpt.json").exists()
    out = runner.invoke(app, ["chatgpt", "logout", "--json"])
    assert json.loads(out.stdout.strip()) == {"ok": True, "was_signed_in": False}


def test_the_cli_status_in_words(cli_home: Path):
    from nanomuse.cli import app

    runner = CliRunner()
    out = runner.invoke(app, ["chatgpt", "status"])
    assert out.exit_code == 0 and "not signed in" in out.output
    TokenStore.in_dir(cli_home).save(token())
    out = runner.invoke(app, ["chatgpt", "status"])
    assert "ChatGPT Plus" in out.output and "expires in" in out.output


def test_the_cli_proxy_refuses_when_signed_out(cli_home: Path):
    from nanomuse.cli import app

    out = CliRunner().invoke(app, ["chatgpt", "proxy", "--json"])
    assert out.exit_code == 1
    assert json.loads(out.stdout.strip())["code"] == "not_signed_in"


@pytest.mark.asyncio
async def test_the_login_flow_against_a_local_fake(tmp_path: Path):
    """The whole PKCE flow with a fake token endpoint: the port, the callback, the exchange."""
    from urllib.parse import parse_qs, urlparse

    from nanomuse.llm.chatgpt import LoginFlow

    store = TokenStore.in_dir(tmp_path)
    exchanged: list[dict[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        form = dict(p.split("=", 1) for p in request.content.decode().split("&"))
        exchanged.append(form)
        return httpx.Response(
            200, json={"access_token": jwt(), "refresh_token": "rt", "expires_in": 60}
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        flow = LoginFlow(store, token_url=TOKEN_URL, port=0, http=http)
        assert await flow.listen() is True
        query = parse_qs(urlparse(flow.url).query)
        assert query["code_challenge_method"] == ["S256"] and query["state"] == [flow.state]
        assert query["originator"] == ["nanomuse"] and query["redirect_uri"] == [flow.redirect_uri]
        port = flow._server.sockets[0].getsockname()[1]  # type: ignore[union-attr]

        async def browser() -> None:
            await asyncio.sleep(0.05)
            async with httpx.AsyncClient() as real:
                r = await real.get(
                    f"http://127.0.0.1:{port}/auth/callback?code=abc&state={flow.state}"
                )
                assert r.status_code == 200 and "Signed in" in r.text

        browser_task = asyncio.create_task(browser())
        result = await flow.wait(timeout=5)
        await browser_task
        assert result.code == "abc" and result.state == flow.state
        stored = await flow.finish(result)
    assert stored.label == "ChatGPT Plus" and store.load() is not None
    assert exchanged[0]["grant_type"] == "authorization_code"
    assert exchanged[0]["code"] == "abc" and exchanged[0]["code_verifier"] == flow.verifier
    # a callback with another state is refused before anything is exchanged
    other = LoginFlow(store, token_url=TOKEN_URL, port=0)
    with pytest.raises(ChatGPTError) as exc:
        await other.finish(
            LoginFlow._parse_callback("http://localhost:1455/auth/callback?code=x&state=y")
        )
    assert exc.value.code == "state_mismatch"

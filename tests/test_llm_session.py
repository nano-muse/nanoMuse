"""A vendor that wants one id per conversation (OpenCode Go's ``x-opencode-session``) gets it,
with nanoMuse's own user agent; every other vendor gets neither."""

from __future__ import annotations

import json
import uuid
from typing import Any

import httpx
import pytest
from openai import AsyncOpenAI

from nanomuse import __version__
from nanomuse.config import LLMSettings, Settings
from nanomuse.llm import openai_chat as chat_mod
from nanomuse.llm import openai_responses as responses_mod
from nanomuse.llm import session
from nanomuse.llm.factory import create_llm, session_header
from nanomuse.schema import LLMResponse, Message

GO = "https://opencode.ai/zen/go/v1"


class Wire:
    """Every request the chat clients send, answered with one short reply."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        body = json.loads(request.content)
        if request.url.path.endswith("/responses"):
            return httpx.Response(
                200,
                json={
                    "id": "r",
                    "object": "response",
                    "created_at": 0,
                    "model": body["model"],
                    "status": "completed",
                    "output": [
                        {
                            "type": "message",
                            "id": "m",
                            "role": "assistant",
                            "status": "completed",
                            "content": [{"type": "output_text", "text": "ok", "annotations": []}],
                        }
                    ],
                    "parallel_tool_calls": False,
                    "tool_choice": "auto",
                    "tools": [],
                },
            )
        return httpx.Response(
            200,
            json={
                "id": "x",
                "object": "chat.completion",
                "created": 0,
                "model": body["model"],
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "ok"},
                        "finish_reason": "stop",
                    }
                ],
            },
        )

    def headers(self, name: str) -> list[str | None]:
        return [r.headers.get(name) for r in self.requests]


@pytest.fixture()
def wire(monkeypatch: pytest.MonkeyPatch) -> Wire:
    w = Wire()

    def make(**kw: Any) -> AsyncOpenAI:
        kw["http_client"] = httpx.AsyncClient(transport=httpx.MockTransport(w.handler))
        return AsyncOpenAI(**kw)

    monkeypatch.setattr(chat_mod, "AsyncOpenAI", make)
    monkeypatch.setattr(responses_mod, "AsyncOpenAI", make)
    return w


def slot(**kw: Any) -> LLMSettings:
    base = {"api_key": "k", "model": "deepseek-v4.1-flash", "stream": False, "tool_mode": "native"}
    return LLMSettings(**{**base, **kw})


async def test_go_calls_carry_the_conversation_and_name_nanomuse(wire: Wire):
    llm = create_llm(slot(provider="opencode-go", base_url=None))
    with session.conversation("thread-1"):
        await llm.ask([Message.user("hi")])
        await llm.ask([Message.user("again")])
    with session.conversation("thread-2"):
        await llm.ask([Message.user("another chat")])
    assert str(wire.requests[0].url) == f"{GO}/chat/completions"
    assert wire.headers("x-opencode-session") == ["thread-1", "thread-1", "thread-2"]
    assert wire.headers("user-agent") == [f"nanoMuse/{__version__}"] * 3


async def test_a_call_outside_a_conversation_carries_the_clients_own_stable_id(wire: Wire):
    llm = create_llm(slot(provider="opencode-go", base_url=None))
    await llm.ask([Message.user("Reply with the single word OK.")])
    await llm.ask([Message.user("Reply with the single word OK.")])
    first, second = wire.headers("x-opencode-session")
    assert first == second and uuid.UUID(first or "")


async def test_an_openai_shaped_slot_pointed_at_go_sends_it_too(wire: Wire):
    assert session_header("openai", GO) == "x-opencode-session"
    llm = create_llm(slot(provider="openai", base_url=GO + "/"))
    with session.conversation("t"):
        await llm.ask([Message.user("hi")])
    assert wire.headers("x-opencode-session") == ["t"]


async def test_the_responses_client_sends_it_as_well(wire: Wire):
    llm = create_llm(slot(provider="openai_responses", base_url=GO, model="gpt-5.6-luna"))
    with session.conversation("t"):
        await llm.ask([Message.user("hi")])
    assert wire.requests[0].url.path.endswith("/responses")
    assert wire.headers("x-opencode-session") == ["t"]


async def test_other_vendors_get_neither_header(wire: Wire):
    for provider, base_url in (("opencode-zen", None), ("deepseek", None), ("openai", None)):
        llm = create_llm(slot(provider=provider, base_url=base_url))
        with session.conversation("t"):
            await llm.ask([Message.user("hi")])
    assert wire.headers("x-opencode-session") == [None, None, None]
    assert not any((ua or "").startswith("nanoMuse/") for ua in wire.headers("user-agent"))


async def test_a_user_agent_the_person_set_stands(wire: Wire):
    llm = create_llm(
        slot(provider="opencode-go", base_url=None, extra_headers={"User-Agent": "x/1"})
    )
    with session.conversation("t"):
        await llm.ask([Message.user("hi")])
    assert wire.headers("user-agent") == ["x/1"]
    assert wire.headers("x-opencode-session") == ["t"]


def test_an_id_that_is_no_header_value_is_sent_as_a_stable_uuid():
    with session.conversation("a thread with spaces · 对话"):
        once = session.session_id("fallback")
        assert session.session_id("fallback") == once
    assert uuid.UUID(once)
    with session.conversation("thread_9f2"):
        assert session.session_id("fallback") == "thread_9f2"
    assert session.session_id("fallback") == "fallback"


async def test_the_agent_loop_names_its_conversation_for_every_call(settings: Settings):
    from nanomuse.agent import MuseAgent
    from nanomuse.llm import MockLLM
    from nanomuse.sentinel import AuditLog, Sentinel
    from nanomuse.tools import Terminate, ToolCollection
    from nanomuse.ui import HeadlessUI

    seen: list[str | None] = []

    def reply(_: list[Message]) -> LLMResponse:
        seen.append(session.current_conversation())
        return LLMResponse(content="done", finish_reason="stop")

    ui = HeadlessUI()
    audit = AuditLog(settings.audit_file)
    sentinel = Sentinel(settings.sentinel, audit, ui)

    def agent(conversation_id: str | None) -> MuseAgent:
        llm = MockLLM([reply, reply])
        return MuseAgent(
            settings, llm, ToolCollection(Terminate()), sentinel, ui, audit,
            conversation_id=conversation_id,
        )  # fmt: skip

    threaded = agent("thread-7")
    await threaded.run("hi")
    alone = agent(None)
    await alone.run("hi")
    await alone.run("and again")
    assert seen[0] == "thread-7"
    # without a thread, one id for the agent's whole life
    assert seen[1] == seen[2] == alone.session_id and seen[1] != "thread-7"
    # and nothing once the turn is over
    assert session.current_conversation() is None

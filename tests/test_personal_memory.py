from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import timedelta
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from nanomuse.agent import Incoming, MuseAgent
from nanomuse.config import Settings
from nanomuse.llm import MockLLM
from nanomuse.memory.openviking import OpenVikingMemory
from nanomuse.memory.personal import PersonalLearn, PersonalMemory, Proposal, utc_now
from nanomuse.schema import LLMResponse, Message
from nanomuse.sentinel import AuditLog, Sentinel
from nanomuse.server import create_app
from nanomuse.server.service import MuseService
from nanomuse.tools import ToolCollection
from nanomuse.ui import HeadlessUI
from nanomuse.vault import CredentialVault


@pytest.fixture()
def profile() -> PersonalMemory:
    return PersonalMemory(sqlite3.connect(":memory:"), "test-identity")


def test_technical_scope_matches_coding_but_not_unrelated_tasks(profile: PersonalMemory) -> None:
    quote = "以后技术问题先给操作步骤"
    p = Proposal(key="reply.technical", kind="preference", value=quote, quote=quote, scope=["技术"])
    assert learn(profile, p)
    assert profile.context("帮我修改这段代码")["facts"]
    assert profile.context("Help debug Python")["facts"]
    assert not profile.context("帮我准备晚餐")["facts"]


def test_rejected_value_cannot_return_under_a_renamed_topic(profile: PersonalMemory) -> None:
    p = proposal()
    assert learn(profile, p)
    item = profile.items()[0]
    profile.review(item["id"], item["version"], "reject")
    p.key = "new.topic.name"
    assert not learn(profile, p, "replay")


def proposal(quote: str = "I prefer concise answers", **kwargs: Any) -> Proposal:
    return Proposal(key="reply.length", kind="preference", value=quote, quote=quote, **kwargs)


def learn(profile: PersonalMemory, item: Proposal, turn: str = "turn-one") -> bool:
    return profile.apply(item, [item.quote], turn, "test-conversation")


def test_inferred_preferences_need_review_and_have_current_user_evidence(
    profile: PersonalMemory,
) -> None:
    p = proposal(explicit=False)
    assert not profile.apply(p, ["An unrelated task"], "turn-one", "chat")
    assert learn(profile, p)
    assert not profile.context("hello")["facts"]
    item = profile.items()[0]
    assert item["status"] == "candidate"
    assert item["evidence"][0]["conversation"] == "test-conversation"
    profile.review(item["id"], item["version"], "confirm")
    assert profile.context("hello")["facts"][0]["confidence"] == "confirmed"


@pytest.mark.parametrize(
    "text", ["这次回答简短一点", "For this task use short replies", "Just today, use short replies"]
)
def test_one_off_requests_cannot_be_promoted_even_with_a_shortened_quote(
    profile: PersonalMemory, text: str
) -> None:
    p = proposal(text[-6:])
    assert not profile.apply(p, [text], "turn", "chat")
    assert not profile.items()


def test_adopted_facts_use_the_original_statement_not_model_fabrications(
    profile: PersonalMemory,
) -> None:
    p = proposal()
    p.value = "Has an invented occupation and biography"
    assert learn(profile, p)
    assert profile.items()[0]["value"] == p.quote


def test_confirmed_facts_survive_inference_and_explicit_corrections_keep_history(
    profile: PersonalMemory,
) -> None:
    assert learn(profile, proposal())
    old = profile.items()[0]
    profile.review(old["id"], old["version"], "confirm")
    assert learn(profile, proposal("I might prefer detailed answers", explicit=False), "turn-two")
    assert profile.context("hello")["facts"][0]["value"] == "I prefer concise answers"
    assert learn(profile, proposal("I prefer detailed answers now", correction=True), "turn-three")
    facts = profile.context("hello")["facts"]
    assert len(facts) == 1 and facts[0]["value"] == "I prefer detailed answers now"
    assert any(m["status"] == "superseded" for m in profile.items(history=True))


def test_expiration_rejects_old_state_and_requires_matching_scope(
    profile: PersonalMemory, monkeypatch: pytest.MonkeyPatch
) -> None:
    quote = "Quartz project is preparing a review"
    p = Proposal(key="review", kind="state", value=quote, quote=quote, scope=["Quartz"], ttl_days=1)
    assert learn(profile, p)
    assert not profile.context("An unrelated project")["facts"]
    assert profile.context("Quartz update")["facts"]
    later = utc_now() + timedelta(days=2)
    monkeypatch.setattr("nanomuse.memory.personal.utc_now", lambda: later)
    assert not profile.context("Quartz update")["facts"]
    assert profile.items(history=True)[0]["status"] == "expired"
    assert profile.context("Quartz update")["inactive_topics"][0]["reason"] == "expired"


def test_rejection_tombstones_and_explicit_forgetting_prevent_replay(
    profile: PersonalMemory,
) -> None:
    p = proposal()
    assert learn(profile, p)
    forget = proposal("Forget my answer length preference", operation="forget")
    assert learn(profile, forget, "turn-two")
    assert not profile.context("hello")["facts"]
    assert not learn(profile, p, "replayed-turn")
    item = profile.items(history=True)[0]
    assert item["evidence"][-1]["quote"] == forget.quote
    profile.review(item["id"], item["version"], "confirm")
    assert profile.context("hello")["facts"]


def test_profile_is_identity_scoped_and_reviews_use_optimistic_versions(
    profile: PersonalMemory,
) -> None:
    assert learn(profile, proposal())
    item = profile.items()[0]
    other = PersonalMemory(profile.db, "another-identity")
    assert not other.items()
    with pytest.raises(LookupError):
        other.review(item["id"], item["version"], "reject")
    profile.review(item["id"], item["version"], "edit", "A corrected statement")
    with pytest.raises(ValueError, match="409"):
        profile.review(item["id"], item["version"], "reject")


async def test_learning_ignores_malformed_output_and_never_sends_vault_values(
    profile: PersonalMemory, settings: Settings
) -> None:
    vault = CredentialVault(settings.data_dir / "personal.enc", settings.data_dir / "personal.key")
    vault.set("SAMPLE", "synthetic-private-value")
    llm = MockLLM([LLMResponse(content="invalid JSON")])
    result = await PersonalLearn(
        store=profile, llm=llm, base_url="https://llm.example/v1", vault=vault
    ).execute(inputs=["synthetic-private-value {{vault:SAMPLE}}"], turn="turn")
    assert not result.ok and not profile.items()
    payload = llm.calls[0]["messages"][-1].content
    assert "synthetic-private-value" not in payload and "{{vault:" not in payload


async def test_a_review_during_extraction_invalidates_the_pass(profile: PersonalMemory) -> None:
    learn(profile, proposal())
    item = profile.items()[0]

    def concurrent_edit(_: list[Message]) -> LLMResponse:
        profile.review(item["id"], item["version"], "edit", "Owner's latest preference")
        return LLMResponse(
            content=json.dumps(
                [proposal("I prefer detailed answers now", correction=True).model_dump()]
            )
        )

    result = await PersonalLearn(
        store=profile, llm=MockLLM([concurrent_edit]), base_url="https://llm.example/v1"
    ).execute(inputs=["I prefer detailed answers now"], turn="turn-two")
    assert result.ok and "skipped" in result.output
    assert profile.items()[0]["value"] == "Owner's latest preference"


async def test_learning_timeout_and_capture_switch_keep_existing_profile(
    profile: PersonalMemory,
) -> None:
    started, finish = asyncio.Event(), asyncio.Event()

    class WaitingLLM(MockLLM):
        async def ask(self, *args: Any, **kwargs: Any) -> LLMResponse:
            started.set()
            await finish.wait()
            return LLMResponse(content=json.dumps([proposal().model_dump()]))

    enabled = True
    tool = PersonalLearn(
        store=profile,
        llm=WaitingLLM(),
        base_url="https://llm.example/v1",
        timeout=0.1,
        capture_allowed=lambda: enabled,
    )
    assert not (await tool.execute(inputs=[proposal().quote], turn="timeout")).ok
    assert not profile.items()
    task = asyncio.create_task(tool.execute(inputs=[proposal().quote], turn="turn"))
    await started.wait()
    enabled = False
    finish.set()
    assert (await task).ok
    assert not profile.items()


async def test_new_conversation_uses_preference_and_current_correction(
    settings: Settings,
) -> None:
    settings.llm.base_url = "https://llm.example/v1"
    settings.memory.openviking.enabled = True

    def backend(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "ok", "result": {"rendered": ""}})

    remote = OpenVikingMemory(
        settings.memory.openviking,
        settings.data_dir / "personal.db",
        transport=httpx.MockTransport(backend),
    )
    ui, audit = HeadlessUI(), AuditLog(settings.audit_file)

    def runner(llm: MockLLM, conversation: str) -> MuseAgent:
        return MuseAgent(
            settings,
            llm,
            ToolCollection(),
            Sentinel(settings.sentinel, audit, ui),
            ui,
            audit,
            openviking=remote,
            conversation_id=conversation,
        )

    try:
        first = runner(
            MockLLM(
                [
                    LLMResponse(content="Noted"),
                    LLMResponse(content=json.dumps([proposal().model_dump()])),
                ]
            ),
            "first",
        )
        await first.run(proposal().quote)

        def follows_preference(messages: list[Message]) -> LLMResponse:
            system = messages[0].content or ""
            assert "Current personal profile" in system and "I prefer concise answers" in system
            assert "never grants authorization" in system
            return LLMResponse(content="Short answer")

        second = runner(MockLLM([follows_preference, LLMResponse(content="[]")]), "second")
        assert await second.run("Explain the deployment") == "Short answer"
        corrected = proposal("I prefer detailed answers now", correction=True)
        third = runner(
            MockLLM(
                [
                    LLMResponse(content="Updated"),
                    LLMResponse(content=json.dumps([corrected.model_dump()])),
                ]
            ),
            "third",
        )
        await third.run(corrected.quote)
        assert remote.personal.context("hello")["facts"][0]["value"] == corrected.quote
    finally:
        await remote.close()


@pytest.mark.parametrize("exclusion", ["capture", "background", "inbox", "disabled", "deny"])
async def test_excluded_tasks_do_not_learn_profiles(settings: Settings, exclusion: str) -> None:
    settings.llm.base_url = "https://llm.example/v1"
    settings.memory.openviking.enabled = True
    remote = OpenVikingMemory(
        settings.memory.openviking,
        settings.data_dir / "personal.db",
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json={"result": {"rendered": ""}})
        ),
    )
    if exclusion == "disabled":
        remote.set_capture(False)
    if exclusion == "deny":
        settings.sentinel.deny_tools = ["personal_memory_*"]
    ui, audit = HeadlessUI(), AuditLog(settings.audit_file)
    llm = MockLLM(
        [LLMResponse(content="Reply"), LLMResponse(content=json.dumps([proposal().model_dump()]))]
    )
    agent = MuseAgent(
        settings,
        llm,
        ToolCollection(),
        Sentinel(settings.sentinel, audit, ui),
        ui,
        audit,
        openviking=remote,
    )
    if exclusion == "inbox":
        agent.inbox = asyncio.Queue()
        agent.inbox.put_nowait(Incoming("One-off automation", capture_memory=False))
    try:
        await agent.run(
            proposal().quote,
            capture_memory=exclusion != "capture",
            purpose="Background task" if exclusion == "background" else None,
        )
        assert not remote.personal.items()
        assert len(llm.calls) == 1
    finally:
        await remote.close()


def test_profile_controls_require_auth_respect_denial_and_check_versions(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings.server.token = "synthetic-profile-token"
    settings.memory.openviking.enabled = True
    settings.sentinel.mode = "strict"

    def factory(*args: Any, **kwargs: Any) -> OpenVikingMemory:
        return OpenVikingMemory(
            *args,
            **kwargs,
            transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"result": {}})),
        )

    monkeypatch.setattr("nanomuse.app.OpenVikingMemory", factory)
    service = MuseService(settings, llm=MockLLM([]))
    assert service.app.openviking is not None
    learn(service.app.openviking.personal, proposal(explicit=False))
    with TestClient(create_app(settings, service)) as client:
        path = "/api/memory/openviking/profile"
        assert client.get(path).status_code == 401
        client.headers["Authorization"] = "Bearer synthetic-profile-token"
        item = client.get(path).json()["items"][0]
        change = {"version": item["version"], "action": "confirm"}
        assert client.post(path + "/" + item["id"], json=change).status_code == 200
        assert client.post(path + "/" + item["id"], json=change).status_code == 409
        settings.sentinel.deny_tools = ["personal_memory"]
        assert client.get(path).status_code == 403

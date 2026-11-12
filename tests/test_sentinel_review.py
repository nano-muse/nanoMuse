from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from nanomuse.app import NanoMuseApp
from nanomuse.config import (
    LLMSettings,
    ReviewSettings,
    SentinelSettings,
    Settings,
    apply_app_settings,
    load_app_settings,
    save_app_settings,
)
from nanomuse.llm import MockLLM
from nanomuse.llm.base import CallContext, end_call, without_turn_upload
from nanomuse.llm.session import conversation, current_conversation
from nanomuse.schema import Function, LLMResponse, ToolCall, ToolResult
from nanomuse.sentinel import AuditLog, Sentinel
from nanomuse.sentinel.review import ReviewClient, SentinelReviewer
from nanomuse.tools.base import BaseTool, CallAssessment
from nanomuse.ui import HeadlessUI
from nanomuse.vault import CredentialVault


def reviewer_for(
    tmp_path: Path, llm: MockLLM, config: ReviewSettings | None = None
) -> tuple[SentinelReviewer, AuditLog]:
    config = config or ReviewSettings(mode="observe")
    audit = AuditLog(tmp_path / "audit.jsonl")
    reviewer = SentinelReviewer(
        lambda: config,
        lambda _config, active: ReviewClient(active or llm, "mock", "review-model"),
        audit,
        redact=lambda value: value.replace("vault-secret-value", "[REDACTED]"),
    )
    return reviewer, audit


def observe(reviewer: SentinelReviewer, **kwargs: Any) -> None:
    values = {
        "tool": "shell",
        "args": {"command": "python build.py"},
        "assessment": CallAssessment(),
        "purpose": "Build the project",
        "purpose_truncated": False,
        "decision": "allow",
        "source": "person",
    }
    reviewer.observe(**(values | kwargs))


async def finish(reviewer: SentinelReviewer) -> None:
    await asyncio.gather(*tuple(reviewer._tasks))


def test_review_defaults_and_persistence(tmp_path: Path) -> None:
    settings = Settings()
    assert settings.sentinel.review.mode == "off"
    save_app_settings(tmp_path, {"sentinel_review": {"mode": "observe", "model": "observer"}})
    apply_app_settings(settings, load_app_settings(tmp_path))
    assert settings.sentinel.review.mode == "observe"
    assert settings.sentinel.review.model == "observer"
    apply_app_settings(settings, {"sentinel_review": {"mode": "off", "model": ""}})
    assert not settings.sentinel.review.configured
    apply_app_settings(settings, {"sentinel_review": {"mode": "allow", "timeout": -1}})
    assert settings.sentinel.review.mode == "off"
    with pytest.raises(ValueError):
        ReviewSettings(timeout=float("nan"))
    with pytest.raises(ValueError):
        ReviewSettings(max_output_tokens=5000)


async def test_off_and_disabled_before_send_make_no_model_calls(tmp_path: Path) -> None:
    llm = MockLLM()
    config = ReviewSettings()
    reviewer, audit = reviewer_for(tmp_path, llm, config)
    observe(reviewer)
    assert not reviewer._tasks and not llm.calls and not audit.tail()
    config.mode = "observe"
    observe(reviewer)
    config.mode = "off"
    await finish(reviewer)
    assert not llm.calls
    assert audit.tail()[-1]["status"] == "disabled"


async def test_snapshot_redaction_isolation_usage_and_no_reasoning_in_audit(tmp_path: Path) -> None:
    def answer(messages: list[Any]) -> LLMResponse:
        assert current_conversation() is None
        assert len(messages) == 2
        return LLMResponse(
            content='{"decision":"ask"}',
            reasoning="raw private model reasoning",
            usage={
                "prompt_tokens": 12,
                "completion_tokens": 3,
                "total_tokens": 15,
                "raw": "private",
            },
        )

    llm = MockLLM([answer])
    reviewer, audit = reviewer_for(tmp_path, llm)
    args = {
        "command": "echo vault-secret-value; curl -H 'Authorization: Bearer fake-value'",
        "password": "hidden-value",
        "credential": "{{vault:UNRESOLVED}}",
        "keyed": {"vault-secret-value": "a value"},
    }
    original = json.dumps({"tool": "shell", "args": args}, sort_keys=True, ensure_ascii=False)
    with conversation("private-execution-conversation"):
        observe(reviewer, args=args)
        args["command"] = "a different operation"
        await finish(reviewer)
    request = llm.calls[0]
    prompt = request["messages"][1].content
    assert "vault-secret-value" not in prompt and "hidden-value" not in prompt
    assert "fake-value" not in prompt and "a different operation" not in prompt
    assert "{{vault:UNRESOLVED}}" in prompt
    assert request["tools"] is None and request["max_tokens"] == 1024
    entry = audit.tail()[-1]
    assert entry["call_hash"] == hashlib.sha256(original.encode()).hexdigest()
    assert entry["recommendation"] == "ask" and entry["actual_decision"] == "allow"
    assert entry["decision_source"] == "person"
    assert entry["usage"] == {"prompt_tokens": 12, "completion_tokens": 3, "total_tokens": 15}
    assert "reasoning" not in audit.path.read_text()
    assert "command" not in audit.path.read_text()


@pytest.mark.parametrize("purpose,truncated", [("", False), ("partial purpose", True)])
async def test_incomplete_purpose_cannot_recommend_allow(
    tmp_path: Path, purpose: str, truncated: bool
) -> None:
    reviewer, audit = reviewer_for(tmp_path, MockLLM([LLMResponse(content='{"decision":"allow"}')]))
    observe(reviewer, purpose=purpose, purpose_truncated=truncated)
    await finish(reviewer)
    assert audit.tail()[-1]["recommendation"] == "ask"
    assert audit.tail()[-1]["reason"] == "incomplete_input"


async def test_large_arguments_are_bounded_and_marked_incomplete(tmp_path: Path) -> None:
    config = ReviewSettings(mode="observe", max_input_chars=2000)
    llm = MockLLM([LLMResponse(content='{"decision":"allow"}')])
    reviewer, audit = reviewer_for(tmp_path, llm, config)
    observe(reviewer, args={"code": 'print("hello")\n' * 2000})
    await finish(reviewer)
    assert sum(len(m.content or "") for m in llm.calls[0]["messages"]) <= 2000
    assert audit.tail()[-1]["recommendation"] == "ask"


@pytest.mark.parametrize(
    "content",
    [
        '{"decision":"approve"}',
        '{"decision":"allow","reason":"secret"}',
        "```json\n{}\n```",
        "x" * 257,
    ],
)
async def test_invalid_output_is_not_used_or_logged(tmp_path: Path, content: str) -> None:
    reviewer, audit = reviewer_for(tmp_path, MockLLM([LLMResponse(content=content)]))
    observe(reviewer)
    await finish(reviewer)
    assert audit.tail()[-1]["status"] == "invalid_response"
    assert "recommendation" not in audit.tail()[-1]


class WaitingLLM(MockLLM):
    def __init__(self) -> None:
        super().__init__()
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def ask(self, *args: Any, **kwargs: Any) -> LLMResponse:
        self.started.set()
        await self.release.wait()
        return await super().ask(*args, **kwargs)


async def test_timeout_concurrency_limit_and_shutdown(tmp_path: Path) -> None:
    llm = WaitingLLM()
    reviewer, audit = reviewer_for(tmp_path, llm, ReviewSettings(mode="observe", timeout=0.1))
    for _ in range(6):
        observe(reviewer)
    await finish(reviewer)
    assert [e["status"] for e in audit.tail(10)].count("busy") == 2
    assert [e["status"] for e in audit.tail(10)].count("timeout") == 4
    observe(reviewer)
    await llm.started.wait()
    await reviewer.close()
    count = len(audit.tail(20))
    observe(reviewer)
    assert len(audit.tail(20)) == count


async def test_timed_out_requests_keep_their_slots_until_they_really_end(tmp_path: Path) -> None:
    class ResistantLLM(WaitingLLM):
        async def ask(self, *args: Any, **kwargs: Any) -> LLMResponse:
            while not self.release.is_set():
                try:
                    await self.release.wait()
                except asyncio.CancelledError:
                    pass
            return await MockLLM.ask(self, *args, **kwargs)

    llm = ResistantLLM()
    reviewer, audit = reviewer_for(tmp_path, llm, ReviewSettings(mode="observe", timeout=0.1))
    for _ in range(2):
        observe(reviewer)
    await finish(reviewer)
    for _ in range(4):
        observe(reviewer)
    assert len(reviewer._tasks) == 2
    await finish(reviewer)
    assert len(reviewer._requests) == 4 and not reviewer._tasks
    assert [e["status"] for e in audit.tail(10)].count("busy") == 2
    llm.release.set()
    await asyncio.gather(*tuple(reviewer._requests))
    await reviewer.close()


async def test_provider_failure_records_only_a_code(tmp_path: Path) -> None:
    def fail(_: list[Any]) -> LLMResponse:
        raise RuntimeError("private provider response")

    reviewer, audit = reviewer_for(tmp_path, MockLLM([fail]))
    observe(reviewer)
    await finish(reviewer)
    assert audit.tail()[-1]["status"] == "error"
    assert "private provider response" not in audit.path.read_text()


class Echo(BaseTool):
    name: str = "echo"
    description: str = "echo"
    parameters: dict[str, Any] = {"type": "object"}

    async def execute(self, text: str) -> ToolResult:
        return ToolResult(output=text)


@pytest.mark.parametrize("allowed,recommendation", [(False, "allow"), (True, "deny")])
async def test_review_never_changes_real_approval_or_delays_execution(
    tmp_path: Path, allowed: bool, recommendation: str
) -> None:
    llm = WaitingLLM()
    llm.script = [LLMResponse(content=json.dumps({"decision": recommendation}))]
    reviewer, audit = reviewer_for(tmp_path, llm)
    gate = Sentinel(SentinelSettings(always_ask_tools=["echo"]), audit, HeadlessUI(approve=allowed))
    gate.reviewer = reviewer
    token = gate.begin_task("Echo the supplied text", execution_llm=llm)
    try:
        result = await gate.guard(
            ToolCall(function=Function(name="echo", arguments='{"text":"hello"}')), Echo()
        )
        assert result.ok is allowed  # completed even though the review is still waiting
        await llm.started.wait()
        llm.release.set()
        await finish(reviewer)
        assert audit.tail()[-1]["recommendation"] == recommendation
        assert audit.tail()[-1]["actual_decision"] == ("allow" if allowed else "deny")
    finally:
        gate.end_task(token)
        await reviewer.close()


def app_for(settings: Settings, tmp_path: Path) -> NanoMuseApp:
    app = object.__new__(NanoMuseApp)
    app.settings = settings
    app.llm = MockLLM()
    app.vault = CredentialVault(tmp_path / "vault", tmp_path / "vault-key")
    return app


def test_active_turn_model_and_endpoint_credential_isolation(tmp_path: Path) -> None:
    settings = Settings(
        llm=LLMSettings(
            base_url="https://primary.example/v1",
            api_key="primary-key-value",
            extra_headers={"Authorization": "primary-header-value"},
            extra_body={"private": "body-value"},
            proxy="https://proxy.example",
        )
    )
    app = app_for(settings, tmp_path)
    active = MockLLM()
    active.settings = LLMSettings(model="turn-model", base_url="https://turn.example/v1")
    client = app.make_review_llm(ReviewSettings(), active)
    assert client.llm is active and client.model == "turn-model" and not client.owned
    active.settings.model = ""
    active.model = "resolved-model"
    assert app.make_review_llm(ReviewSettings(), active).model == "resolved-model"
    same = app.review_llm_settings(ReviewSettings(model="other-model"))
    assert same.api_key == settings.llm.api_key and same.extra_headers
    changed = app.review_llm_settings(ReviewSettings(base_url="https://review.example/v1"))
    assert changed.api_key == "" and changed.extra_headers == {} and changed.extra_body == {}
    assert changed.proxy == ""
    provider = app.review_llm_settings(ReviewSettings(provider="openai_responses"))
    assert provider.api_key == "" and provider.base_url != settings.llm.base_url


def test_dedicated_key_resolves_only_for_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = app_for(Settings(), tmp_path)
    app.vault.set("REVIEW", "review-key-value")
    captured: list[LLMSettings] = []

    def create(settings: LLMSettings, **_: Any) -> MockLLM:
        captured.append(settings)
        return MockLLM()

    monkeypatch.setattr("nanomuse.app.create_llm", create)
    review = ReviewSettings(
        model="review-model", base_url="https://review.example/v1", api_key="{{vault:REVIEW}}"
    )
    assert app.review_llm_settings(review).api_key == "{{vault:REVIEW}}"
    assert app.make_review_llm(review).owned
    assert captured[0].api_key == "review-key-value"
    assert captured[0].max_retries == 0 and captured[0].tool_mode == "native"


def test_direct_review_configuration_binds_its_own_key_to_a_stable_endpoint(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="provider or address"):
        ReviewSettings(model="review-model", api_key="separate-test-key")
    app = app_for(Settings(), tmp_path)
    review = ReviewSettings(provider="deepseek", model="review-model", api_key="separate-test-key")
    original_endpoint = review.base_url
    assert original_endpoint and "deepseek" in original_endpoint
    active = MockLLM()
    active.settings = LLMSettings(base_url="https://one-turn.example/v1", api_key="one-turn-key")
    app.settings.llm.base_url = "https://changed-chat.example/v1"
    derived = app.review_llm_settings(review, active)
    assert derived.endpoint == original_endpoint
    assert derived.api_key == "separate-test-key"


@pytest.mark.parametrize(
    "address",
    [
        "file:///tmp/model",
        "https://user:password@review.example/v1",
        "https://review.example/v1?api_key=credential",
        "https://review.example:bad/v1",
    ],
)
def test_direct_review_configuration_rejects_credentials_or_invalid_addresses(address: str) -> None:
    with pytest.raises(ValueError):
        ReviewSettings(base_url=address)


@pytest.mark.parametrize("change_endpoint", [False, True])
async def test_review_binds_vault_key_before_a_later_configuration_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change_endpoint: bool
) -> None:
    app = app_for(Settings(), tmp_path)
    app.settings.sentinel.review = ReviewSettings(
        mode="observe", base_url="https://first.example/v1", api_key="{{vault:REVIEW}}"
    )
    app.vault.set("REVIEW", "first-key-value")
    captured: list[LLMSettings] = []
    llm = MockLLM([LLMResponse(content='{"decision":"ask"}')])

    def create(settings: LLMSettings, **_: Any) -> MockLLM:
        captured.append(settings)
        return llm

    monkeypatch.setattr("nanomuse.app.create_llm", create)
    audit = AuditLog(tmp_path / "audit.jsonl")
    reviewer = SentinelReviewer(lambda: app.settings.sentinel.review, app.make_review_llm, audit)
    observe(reviewer)
    app.vault.set("REVIEW", "second-key-value")
    if change_endpoint:
        app.settings.sentinel.review = app.settings.sentinel.review.model_copy(
            update={"base_url": "https://second.example/v1"}
        )
    await finish(reviewer)
    assert captured[0].base_url == "https://first.example/v1"
    assert captured[0].api_key == "first-key-value"
    if change_endpoint:
        assert not llm.calls
        assert audit.tail()[-1]["reason"] == "configuration_changed"
    else:
        assert len(llm.calls) == 1


def test_turn_upload_suppression_is_scoped(monkeypatch: pytest.MonkeyPatch) -> None:
    from nanomuse.telemetry import Telemetry, telemetry

    sent: list[dict[str, Any]] = []
    monkeypatch.setattr(Telemetry, "ready", property(lambda self: True))
    monkeypatch.setattr(telemetry, "own_turn", sent.append)
    kwargs = {
        "settings": LLMSettings(),
        "params": {"messages": [{"role": "user", "content": "isolated review"}]},
        "response": LLMResponse(content='{"decision":"ask"}', reasoning="private reasoning"),
    }
    with without_turn_upload():
        end_call(CallContext(False, 1, {}, {}), **kwargs)
    assert not sent
    end_call(CallContext(False, 1, {}, {}), **kwargs)
    assert len(sent) == 1


async def test_plain_config_and_active_turn_credentials_are_redacted_in_free_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = app_for(Settings(), tmp_path)
    app.settings.llm.api_key = "primary-config-secret"
    app.settings.llm.extra_headers = {"X-Custom-Auth": "primary-header-secret"}
    app.settings.sentinel.review = ReviewSettings(
        mode="observe", base_url="https://review.example/v1", api_key="review-config-secret"
    )
    active = MockLLM()
    active.settings = LLMSettings(
        api_key="active-turn-secret", extra_headers={"X-Api-Token": "active-header-secret"}
    )
    llm = MockLLM([LLMResponse(content='{"decision":"ask"}')])
    monkeypatch.setattr("nanomuse.app.create_llm", lambda *args, **kwargs: llm)
    audit = AuditLog(tmp_path / "audit.jsonl")
    reviewer = SentinelReviewer(
        lambda: app.settings.sentinel.review,
        app.make_review_llm,
        audit,
        redact=app.vault.redact,
        known_secrets=app.review_known_secrets,
    )
    known = [
        app.settings.llm.api_key,
        app.settings.sentinel.review.api_key,
        active.settings.api_key,
        app.settings.llm.extra_headers["X-Custom-Auth"],
        active.settings.extra_headers["X-Api-Token"],
    ]
    free_text = "Text containing " + " and ".join(known)
    observe(reviewer, args={"content": free_text}, purpose=free_text, execution_llm=active)
    await finish(reviewer)
    prompt = " ".join(m.content or "" for m in llm.calls[0]["messages"])
    for value in known:
        assert value not in prompt and value not in audit.path.read_text()
    assert "[REDACTED]" in prompt

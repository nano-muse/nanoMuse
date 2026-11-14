"""The decision layer: parsing and validation, fail open, the ledger, the log.

All backends are local doubles (the MockLLM client or hand-rolled
classes); nothing here touches the network.  The agent-loop tests pin
the shadow contract: with the layer on, the run's answer, the main
model's calls and the budget are all exactly what they are with it
off, and the only trace is one line in the decision log.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from nanomuse.agent.core import MuseAgent
from nanomuse.config import DeciderSettings, Settings, load_settings
from nanomuse.cost import recording
from nanomuse.cost.ledger import CostLedger, PriceEntry
from nanomuse.cost.recording import TaskCostRecorder
from nanomuse.llm import decider as decider_module
from nanomuse.llm.decider import (
    CheapestModelBackend,
    ChoiceQuestion,
    Decider,
    DecideRequest,
    DeciderFailure,
    YesNoQuestion,
    difficulty_question,
    state_hash,
)
from nanomuse.llm.mock import MockLLM
from nanomuse.schema import LLMResponse
from nanomuse.sentinel import AuditLog, Sentinel
from nanomuse.tools import Terminate, ToolCollection
from nanomuse.ui import HeadlessUI

STATE = "sort the project files by size and delete the duplicates"


def backend_replying(
    payload: object, *, usage: dict[str, int] | None = None
) -> CheapestModelBackend:
    text = payload if isinstance(payload, str) else json.dumps(payload)
    llm = MockLLM(
        [
            LLMResponse(
                content=text,
                usage=usage or {"input_tokens": 120, "output_tokens": 30},
            )
        ]
    )
    return CheapestModelBackend(llm, model="mock")


def make_decider(
    tmp_path: Path,
    backend: object,
    *,
    enabled: bool = True,
    timeout: float = 1.5,
) -> Decider:
    return Decider(
        backend,  # type: ignore[arg-type]
        settings=DeciderSettings(enabled=enabled, timeout_seconds=timeout),
        log_path=tmp_path / "decider-log.jsonl",
    )


def log_lines(tmp_path: Path) -> list[dict]:
    path = tmp_path / "decider-log.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


# ------------------------------------------------------------------ the three kinds


async def test_choice_answer_parses(tmp_path: Path) -> None:
    backend = backend_replying(
        {"answers": [{"key": "full", "probabilities": {"quick": 0.15, "full": 0.85}}]}
    )
    decider = make_decider(tmp_path, backend)
    request = DecideRequest(
        state=STATE,
        questions=[
            ChoiceQuestion(
                instructions="How deep should the work go?",
                options={"quick": "a short answer", "full": "a careful pass"},
            )
        ],
    )
    outcome = await decider.decide("routing", request)
    assert outcome.failure is None
    (answer,) = outcome.answers or []
    assert answer.key == "full"  # type: ignore[attr-defined]
    assert answer.p_top == pytest.approx(0.85)  # type: ignore[attr-defined]
    assert answer.margin == pytest.approx(0.70)  # type: ignore[attr-defined]
    (line,) = log_lines(tmp_path)
    assert line["seam"] == "routing"
    assert line["kind"] == "choice"
    assert line["choice"] == "full"
    assert line["p_top"] == pytest.approx(0.85)
    assert line["margin"] == pytest.approx(0.70)
    assert line["ok"] is True


async def test_score_answer_is_the_probability_weighted_mean(tmp_path: Path) -> None:
    backend = backend_replying({"answers": [{"probabilities": [0.05, 0.1, 0.15, 0.3, 0.4]}]})
    decider = make_decider(tmp_path, backend)
    request = DecideRequest(state=STATE, questions=[difficulty_question()])
    outcome = await decider.decide("task_difficulty", request)
    assert outcome.failure is None
    (answer,) = outcome.answers or []
    assert answer.score == pytest.approx(0.725)  # type: ignore[attr-defined]
    (line,) = log_lines(tmp_path)
    assert line["kind"] == "score"
    assert line["score"] == pytest.approx(0.725)
    assert line["choice"] is None


async def test_yesno_answer_parses(tmp_path: Path) -> None:
    backend = backend_replying({"answers": [{"p_yes": 0.8}]})
    decider = make_decider(tmp_path, backend)
    request = DecideRequest(
        state=STATE,
        questions=[YesNoQuestion(instructions="Does this need a tool?")],
    )
    outcome = await decider.decide("triage", request)
    assert outcome.failure is None
    (answer,) = outcome.answers or []
    assert answer.yes is True  # type: ignore[attr-defined]
    assert answer.p_top == pytest.approx(0.8)  # type: ignore[attr-defined]


async def test_several_questions_answer_in_one_call(tmp_path: Path) -> None:
    backend = backend_replying(
        {
            "answers": [
                {"key": "a", "probabilities": {"a": 0.9, "b": 0.1}},
                {"p_yes": 0.25},
            ]
        }
    )
    decider = make_decider(tmp_path, backend)
    request = DecideRequest(
        state=STATE,
        questions=[
            ChoiceQuestion(instructions="Which shelf?", options={"a": "top", "b": "bottom"}),
            YesNoQuestion(instructions="Urgent?"),
        ],
    )
    outcome = await decider.decide("triage", request)
    assert outcome.failure is None
    assert len(outcome.answers or []) == 2
    assert len(log_lines(tmp_path)) == 2


async def test_fenced_json_still_parses(tmp_path: Path) -> None:
    backend = backend_replying('```json\n{"answers": [{"p_yes": 0.1}]}\n```')
    decider = make_decider(tmp_path, backend)
    request = DecideRequest(state=STATE, questions=[YesNoQuestion(instructions="Urgent?")])
    outcome = await decider.decide("triage", request)
    assert outcome.failure is None
    (answer,) = outcome.answers or []
    assert answer.yes is False  # type: ignore[attr-defined]


# ------------------------------------------------------------------ validation


@pytest.mark.parametrize(
    "payload",
    [
        # the chosen key was never offered
        {"answers": [{"key": "c", "probabilities": {"a": 0.5, "b": 0.5}}]},
        # the distribution does not cover exactly the offered options
        {"answers": [{"key": "a", "probabilities": {"a": 1.0}}]},
        # a probability outside [0, 1]
        {"answers": [{"key": "a", "probabilities": {"a": 1.2, "b": -0.2}}]},
        # the probabilities do not sum to 1 within 0.1
        {"answers": [{"key": "a", "probabilities": {"a": 0.3, "b": 0.2}}]},
        # the chosen option is not the most probable one
        {"answers": [{"key": "a", "probabilities": {"a": 0.2, "b": 0.8}}]},
        # a probability that is not a number
        {"answers": [{"key": "a", "probabilities": {"a": "high", "b": 0.5}}]},
    ],
)
async def test_choice_validation_failures_are_malformed(tmp_path: Path, payload: dict) -> None:
    backend = backend_replying(payload)
    decider = make_decider(tmp_path, backend)
    request = DecideRequest(
        state=STATE,
        questions=[ChoiceQuestion(instructions="Which?", options={"a": "first", "b": "second"})],
    )
    outcome = await decider.decide("routing", request)
    assert outcome.answers is None
    assert outcome.failure is DeciderFailure.MALFORMED
    (line,) = log_lines(tmp_path)
    assert line["ok"] is False
    assert line["failure"] == "malformed"


@pytest.mark.parametrize(
    "payload",
    [
        # one probability per level, no more, no fewer
        {"answers": [{"probabilities": [0.5, 0.5]}]},
        # the levels do not sum to 1
        {"answers": [{"probabilities": [0.1, 0.1, 0.1, 0.1, 0.1]}]},
    ],
)
async def test_score_validation_failures_are_malformed(tmp_path: Path, payload: dict) -> None:
    backend = backend_replying(payload)
    decider = make_decider(tmp_path, backend)
    request = DecideRequest(state=STATE, questions=[difficulty_question()])
    outcome = await decider.decide("task_difficulty", request)
    assert outcome.answers is None
    assert outcome.failure is DeciderFailure.MALFORMED


@pytest.mark.parametrize(
    "payload",
    [
        {"answers": [{"p_yes": 1.5}]},  # outside [0, 1]
        {"answers": [{"p_yes": True}]},  # a boolean is not a probability
        {"answers": [{"p_no": 0.5}]},  # the field the question asked for is missing
    ],
)
async def test_yesno_validation_failures_are_malformed(tmp_path: Path, payload: dict) -> None:
    backend = backend_replying(payload)
    decider = make_decider(tmp_path, backend)
    request = DecideRequest(state=STATE, questions=[YesNoQuestion(instructions="Urgent?")])
    outcome = await decider.decide("triage", request)
    assert outcome.answers is None
    assert outcome.failure is DeciderFailure.MALFORMED


@pytest.mark.parametrize(
    "payload",
    [
        "the answer is probably yes",  # not JSON at all
        {"answers": []},  # fewer answers than questions
        {"answer": {"p_yes": 0.5}},  # the envelope is wrong
        ["p_yes"],  # the reply is not an object
    ],
)
async def test_unparseable_replies_are_malformed(tmp_path: Path, payload: object) -> None:
    backend = backend_replying(payload)
    decider = make_decider(tmp_path, backend)
    request = DecideRequest(state=STATE, questions=[YesNoQuestion(instructions="Urgent?")])
    outcome = await decider.decide("triage", request)
    assert outcome.answers is None
    assert outcome.failure is DeciderFailure.MALFORMED


# ------------------------------------------------------------------ fail open


class _RaisingBackend:
    name = "raising"
    model = "mock"

    async def ask_decision(self, request: DecideRequest) -> tuple[str, dict[str, int]]:
        raise RuntimeError("the provider is down")


class _SlowBackend:
    name = "slow"
    model = "mock"

    async def ask_decision(self, request: DecideRequest) -> tuple[str, dict[str, int]]:
        await asyncio.sleep(10)
        return "{}", {"input_tokens": 1, "output_tokens": 1}


class _CountingBackend:
    name = "counting"
    model = "mock"

    def __init__(self) -> None:
        self.calls = 0

    async def ask_decision(self, request: DecideRequest) -> tuple[str, dict[str, int]]:
        self.calls += 1
        return '{"answers": [{"p_yes": 0.5}]}', {"input_tokens": 1, "output_tokens": 1}


async def test_disabled_never_calls_and_never_logs(tmp_path: Path) -> None:
    backend = _CountingBackend()
    decider = make_decider(tmp_path, backend, enabled=False)
    request = DecideRequest(state=STATE, questions=[YesNoQuestion(instructions="Urgent?")])
    outcome = await decider.decide("triage", request)
    assert outcome.answers is None
    assert outcome.failure is DeciderFailure.DISABLED
    assert backend.calls == 0
    assert log_lines(tmp_path) == []


async def test_no_backend_is_no_key(tmp_path: Path) -> None:
    decider = make_decider(tmp_path, None)
    request = DecideRequest(state=STATE, questions=[YesNoQuestion(instructions="Urgent?")])
    outcome = await decider.decide("triage", request)
    assert outcome.answers is None
    assert outcome.failure is DeciderFailure.NO_KEY
    (line,) = log_lines(tmp_path)
    assert line["failure"] == "no_key"


async def test_backend_error_fails_open(tmp_path: Path) -> None:
    decider = make_decider(tmp_path, _RaisingBackend())
    request = DecideRequest(state=STATE, questions=[YesNoQuestion(instructions="Urgent?")])
    outcome = await decider.decide("triage", request)
    assert outcome.answers is None
    assert outcome.failure is DeciderFailure.BACKEND_ERROR
    (line,) = log_lines(tmp_path)
    assert line["failure"] == "backend_error"


async def test_timeout_fails_open(tmp_path: Path) -> None:
    decider = make_decider(tmp_path, _SlowBackend(), timeout=0.1)
    request = DecideRequest(state=STATE, questions=[YesNoQuestion(instructions="Urgent?")])
    outcome = await decider.decide("triage", request)
    assert outcome.answers is None
    assert outcome.failure is DeciderFailure.TIMEOUT
    assert outcome.latency_ms >= 90
    (line,) = log_lines(tmp_path)
    assert line["failure"] == "timeout"


async def test_build_decider_without_a_key_has_no_backend(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path)
    settings.llm.api_key = ""  # the default endpoint needs a key it does not have
    settings.decider.enabled = True
    decider = decider_module.build_decider(settings)
    outcome = await decider.decide(
        "task_difficulty",
        DecideRequest(state=STATE, questions=[difficulty_question()]),
    )
    assert outcome.failure is DeciderFailure.NO_KEY


# ------------------------------------------------------------------ the ledger and the log


@pytest.fixture
def ledger(tmp_path: Path):
    books = CostLedger(prices={"mock": PriceEntry("mock", 1.0, 2.0)})
    recorder = TaskCostRecorder(ledger=books, device_id="test-device")
    recording.install(recorder)
    try:
        yield books
    finally:
        recording.install(None)


async def test_a_decision_is_recorded_in_the_cost_ledger(
    tmp_path: Path, ledger: CostLedger
) -> None:
    backend = backend_replying({"answers": [{"p_yes": 0.8}]})
    decider = make_decider(tmp_path, backend)
    request = DecideRequest(state=STATE, questions=[YesNoQuestion(instructions="Urgent?")])
    outcome = await decider.decide("triage", request)
    assert outcome.failure is None
    (entry,) = ledger.entries
    assert entry.task_id == "decider:triage"
    assert entry.model == "mock"
    assert entry.input_tokens == 120
    assert entry.output_tokens == 30
    assert entry.cost_usd == pytest.approx((120 * 1 + 30 * 2) / 1_000_000)


async def test_a_malformed_answer_still_records_the_call(
    tmp_path: Path, ledger: CostLedger
) -> None:
    backend = backend_replying("not json")
    decider = make_decider(tmp_path, backend)
    request = DecideRequest(state=STATE, questions=[YesNoQuestion(instructions="Urgent?")])
    outcome = await decider.decide("triage", request)
    assert outcome.failure is DeciderFailure.MALFORMED
    assert len(ledger.entries) == 1  # the call happened and was billed


async def test_usage_falls_back_to_an_estimate(tmp_path: Path, ledger: CostLedger) -> None:
    backend = backend_replying({"answers": [{"p_yes": 0.8}]}, usage={})
    decider = make_decider(tmp_path, backend)
    request = DecideRequest(state=STATE, questions=[YesNoQuestion(instructions="Urgent?")])
    outcome = await decider.decide("triage", request)
    assert outcome.failure is None
    (entry,) = ledger.entries
    assert entry.input_tokens > 0
    assert entry.output_tokens > 0


async def test_the_log_never_holds_the_state(tmp_path: Path) -> None:
    marker = "a very particular phrase nobody would guess"
    backend = backend_replying({"answers": [{"p_yes": 0.8}]})
    decider = make_decider(tmp_path, backend)
    state = f"please handle {marker} for me"
    request = DecideRequest(state=state, questions=[YesNoQuestion(instructions="Urgent?")])
    await decider.decide("triage", request)
    raw = (tmp_path / "decider-log.jsonl").read_text()
    assert marker not in raw
    (line,) = log_lines(tmp_path)
    assert line["state_hash"] == state_hash(state)
    assert len(line["state_hash"]) == 16
    assert line["latency_ms"] >= 0


# ------------------------------------------------------------------ configuration


def test_decider_settings_defaults() -> None:
    cfg = DeciderSettings()
    assert cfg.enabled is False
    assert cfg.mode == "shadow"
    assert cfg.threshold == 0.6
    assert cfg.timeout_seconds == 1.5
    assert cfg.model == ""
    assert Settings().decider.enabled is False


def test_decider_settings_parse_from_toml(tmp_path: Path) -> None:
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        """
[decider]
enabled = true
threshold = 0.75
timeout_seconds = 2.5
model = "some-cheap-model"
"""
    )
    parsed = load_settings(cfg).decider
    assert parsed.enabled is True
    assert parsed.mode == "shadow"
    assert parsed.threshold == 0.75
    assert parsed.timeout_seconds == 2.5
    assert parsed.model == "some-cheap-model"


# ------------------------------------------------------------------ the shadow hook


def make_agent(settings: Settings, script: list) -> tuple[MuseAgent, MockLLM]:
    ui = HeadlessUI()
    audit = AuditLog(settings.audit_file)
    sentinel = Sentinel(settings.sentinel, audit, ui)
    llm = MockLLM(script)
    agent = MuseAgent(settings, llm, ToolCollection(Terminate()), sentinel, ui, audit)
    return agent, llm


def enable_shadow(settings: Settings, monkeypatch: pytest.MonkeyPatch, decider: Decider) -> None:
    settings.decider.enabled = True
    settings.decider.mode = "shadow"
    monkeypatch.setattr("nanomuse.agent.core.build_decider", lambda _settings: decider)


async def test_shadow_hook_logs_the_would_be_tier_and_changes_nothing(
    settings: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    backend = backend_replying({"answers": [{"probabilities": [0.0, 0.0, 0.0, 0.2, 0.8]}]})
    decider = make_decider(tmp_path, backend)
    enable_shadow(settings, monkeypatch, decider)
    agent, llm = make_agent(settings, [LLMResponse(content="the main answer")])
    result = await agent.run("do the hard thing")
    assert result == "the main answer"
    assert len(llm.calls) == 1  # the main model ran exactly as it would have
    assert agent.last_budget["calls"] == 1  # only the main call is in the task budget
    (line,) = log_lines(tmp_path)
    assert line["seam"] == "task_difficulty"
    assert line["score"] == pytest.approx(0.95)
    assert line["would_choose"] == "escalated"


async def test_shadow_hook_low_score_would_stay_default(
    settings: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    backend = backend_replying({"answers": [{"probabilities": [0.9, 0.1, 0.0, 0.0, 0.0]}]})
    decider = make_decider(tmp_path, backend)
    enable_shadow(settings, monkeypatch, decider)
    agent, _llm = make_agent(settings, [LLMResponse(content="a small answer")])
    result = await agent.run("say hello")
    assert result == "a small answer"
    (line,) = log_lines(tmp_path)
    assert line["would_choose"] == "default"


async def test_shadow_hook_backend_failure_still_runs_the_task(
    settings: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    decider = make_decider(tmp_path, _RaisingBackend())
    enable_shadow(settings, monkeypatch, decider)
    agent, _llm = make_agent(settings, [LLMResponse(content="still fine")])
    result = await agent.run("do it anyway")
    assert result == "still fine"
    (line,) = log_lines(tmp_path)
    assert line["failure"] == "backend_error"
    assert line["would_choose"] is None


async def test_disabled_hook_builds_nothing_and_logs_nothing(
    settings: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbidden(_settings: Settings) -> Decider:
        raise AssertionError("build_decider ran while the layer is disabled")

    monkeypatch.setattr("nanomuse.agent.core.build_decider", forbidden)
    agent, llm = make_agent(settings, [LLMResponse(content="plain run")])
    result = await agent.run("an ordinary task")
    assert result == "plain run"
    assert len(llm.calls) == 1
    assert not (settings.data_dir / "decider-log.jsonl").exists()

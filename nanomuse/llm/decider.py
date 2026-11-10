"""A fast decision layer in the shape of TypeSafe's Jev, run in shadow mode.

The decider answers small questions about a task before the real work
starts: a choice among named options, a score against graded criteria,
or a yes/no.  It never does the task itself.  Answers carry a full
probability distribution, and the distribution is validated the way
OpenMausBot validates Jev's answers: the options are a closed set,
every probability is a finite number in [0, 1], the probabilities sum
to 1 within 0.1, and the chosen answer is the most probable one.  An
answer that fails validation counts as no decision.

Fail open is the whole posture: disabled, no key, a timeout, a backend
error or a malformed answer all return "no decision" with the failure
kind named, and the caller runs exactly as it would have without the
decider.  The decider never approves or refuses anything; approval
stays with the Sentinel.

Every call that reaches a model is recorded in the cost ledger
through ``nanomuse.cost.recording`` under the backend's own model,
the same channel a finished task uses, so a decision costs what the
ledger says it costs.  One line per question is appended to the
decision log (``decider-log.jsonl`` in the data directory): seam,
outcome, the top probability and its margin, latency, and a 16
character hash of the state.  The state's text is never logged.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any, Protocol

from nanomuse.config import DeciderSettings, Settings
from nanomuse.cost import recording as cost_recording
from nanomuse.llm.base import BaseLLM, split_think
from nanomuse.llm.budget import estimate_tokens
from nanomuse.logger import logger
from nanomuse.schema import LLMResponse, Message

#: how far the probabilities of one answer may drift from summing to 1
#: (the model rounds to two decimals; the same tolerance Jev's answers get)
_SUM_TOLERANCE = 0.1
#: a rival option may tie the chosen one, but may not beat it by more than this
_ARGMAX_TOLERANCE = 1e-9


class DeciderFailure(Enum):
    """Why a decision did not happen; every kind means "use the caller's own rule"."""

    DISABLED = "disabled"
    NO_KEY = "no_key"
    TIMEOUT = "timeout"
    BACKEND_ERROR = "backend_error"
    MALFORMED = "malformed"


class QuestionKind(Enum):
    CHOICE = "choice"
    SCORE = "score"
    YESNO = "yesno"


@dataclass(frozen=True)
class ChoiceQuestion:
    instructions: str
    options: dict[str, str]  # option key -> what picking it means
    kind: QuestionKind = field(default=QuestionKind.CHOICE, init=False)


@dataclass(frozen=True)
class ScoreQuestion:
    instructions: str
    criteria: list[str]  # 2 to 10 graded levels, lowest first; level i is worth i / (n - 1)
    kind: QuestionKind = field(default=QuestionKind.SCORE, init=False)


@dataclass(frozen=True)
class YesNoQuestion:
    instructions: str
    yes_criteria: str = ""
    no_criteria: str = ""
    kind: QuestionKind = field(default=QuestionKind.YESNO, init=False)


Question = ChoiceQuestion | ScoreQuestion | YesNoQuestion


@dataclass(frozen=True)
class DecideRequest:
    state: str
    questions: list[Question]


def _top_and_margin(probabilities: list[float]) -> tuple[float, float]:
    ordered = sorted(probabilities, reverse=True)
    top = ordered[0]
    second = ordered[1] if len(ordered) > 1 else 0.0
    return top, top - second


@dataclass(frozen=True)
class ChoiceAnswer:
    key: str
    probabilities: dict[str, float]

    @property
    def p_top(self) -> float:
        return max(self.probabilities.values())

    @property
    def margin(self) -> float:
        return _top_and_margin(list(self.probabilities.values()))[1]


@dataclass(frozen=True)
class ScoreAnswer:
    score: float
    probabilities: list[float]  # one per criterion level, in order

    @property
    def p_top(self) -> float:
        return max(self.probabilities)

    @property
    def margin(self) -> float:
        return _top_and_margin(self.probabilities)[1]


@dataclass(frozen=True)
class YesNoAnswer:
    yes: bool
    p_yes: float

    @property
    def p_top(self) -> float:
        return max(self.p_yes, 1.0 - self.p_yes)

    @property
    def margin(self) -> float:
        return abs(self.p_yes - (1.0 - self.p_yes))


Answer = ChoiceAnswer | ScoreAnswer | YesNoAnswer


@dataclass(frozen=True)
class DecideOutcome:
    """One decide() result: ``answers`` is None exactly when ``failure`` is set."""

    answers: list[Answer] | None
    failure: DeciderFailure | None
    latency_ms: int


class DeciderBackend(Protocol):
    """What answers the questions: one model call returning strict JSON text.

    ``model`` names the model the ledger records the call under.  An
    implementation may raise anything; the decider turns it into a
    backend_error failure.
    """

    name: str
    model: str

    async def ask_decision(self, request: DecideRequest) -> tuple[str, dict[str, int]]:
        """Return (response text, {"input_tokens": n, "output_tokens": n})."""
        ...


_SYSTEM_PROMPT = (
    "You are a fast decision classifier. You never do the task described in the "
    "state; you only answer the questions about it. Reply with one JSON object "
    'and nothing else: {"answers": [...]} with one answer per question, in '
    'order. A choice answer is {"key": <one of the option keys>, '
    '"probabilities": {<every option key>: <probability>}}. A score answer is '
    '{"probabilities": [<one probability per level, in order>]}. A yes/no '
    'answer is {"p_yes": <probability of yes>}. Probabilities are numbers '
    "between 0 and 1 and sum to 1."
)


def _prompt_body(request: DecideRequest) -> str:
    lines = ["State:", request.state, "", "Questions:"]
    for number, question in enumerate(request.questions, 1):
        if isinstance(question, ChoiceQuestion):
            lines.append(f"{number}. choice: {question.instructions}")
            for key, meaning in question.options.items():
                lines.append(f"   - {key}: {meaning}")
        elif isinstance(question, ScoreQuestion):
            lines.append(f"{number}. score: {question.instructions}")
            for level, criterion in enumerate(question.criteria):
                lines.append(f"   - level {level}: {criterion}")
        else:
            lines.append(f"{number}. yes/no: {question.instructions}")
            if question.yes_criteria:
                lines.append(f"   - yes means: {question.yes_criteria}")
            if question.no_criteria:
                lines.append(f"   - no means: {question.no_criteria}")
    return "\n".join(lines)


def _usage_of(response: LLMResponse, messages: list[Message]) -> dict[str, int]:
    """The call's token counts: what the provider reported, else the budget
    module's estimate for the request and four bytes per token for the reply."""
    usage = response.usage or {}

    def pick(*keys: str) -> int | None:
        for key in keys:
            value = usage.get(key)
            if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                return value
        return None

    incoming = pick("input_tokens", "prompt_tokens")
    outgoing = pick("output_tokens", "completion_tokens")
    if incoming is None:
        incoming = estimate_tokens(messages)
    if outgoing is None:
        outgoing = (len((response.content or "").encode("utf-8")) + 3) // 4
    return {"input_tokens": incoming, "output_tokens": outgoing}


class CheapestModelBackend:
    """The decision asked of the runtime's cheap model slot, as strict JSON.

    ``llm`` is any client built for the decision (temperature 0, a small
    token budget).  The call goes through the client as usual, so the
    relay's call context applies; the ledger entry is the decider's own,
    written by :class:`Decider` from the usage reported here.
    """

    name = "cheapest-model"

    def __init__(self, llm: BaseLLM, model: str) -> None:
        self._llm = llm
        self.model = model

    async def ask_decision(self, request: DecideRequest) -> tuple[str, dict[str, int]]:
        messages = [Message.system(_SYSTEM_PROMPT), Message.user(_prompt_body(request))]
        response = await self._llm.ask(messages, tools=None, max_tokens=512)
        text, _reasoning = split_think(response.content)
        return (text or ""), _usage_of(response, messages)


class _Malformed(Exception):
    """The answer text is not a valid answer to the questions asked."""


def _as_probability(raw: Any) -> float:
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise _Malformed(f"not a number: {raw!r}")
    value = float(raw)
    if not math.isfinite(value) or value < 0 or value > 1:
        raise _Malformed(f"probability out of range: {value}")
    return value


def _check_distribution(values: list[float]) -> None:
    if abs(sum(values) - 1.0) > _SUM_TOLERANCE:
        raise _Malformed(f"probabilities sum to {sum(values)}, not 1")


def _parse_choice(question: ChoiceQuestion, raw: Any) -> ChoiceAnswer:
    if not isinstance(raw, dict):
        raise _Malformed("a choice answer is an object")
    key = raw.get("key")
    raw_probs = raw.get("probabilities")
    if not isinstance(key, str) or key not in question.options:
        raise _Malformed(f"chosen key {key!r} is not one of the options")
    if not isinstance(raw_probs, dict) or set(raw_probs) != set(question.options):
        raise _Malformed("probabilities must cover exactly the options offered")
    probabilities = {name: _as_probability(raw_probs[name]) for name in question.options}
    _check_distribution(list(probabilities.values()))
    if any(
        probabilities[other] > probabilities[key] + _ARGMAX_TOLERANCE
        for other in probabilities
        if other != key
    ):
        raise _Malformed("the chosen option is not the most probable one")
    return ChoiceAnswer(key=key, probabilities=probabilities)


def _parse_score(question: ScoreQuestion, raw: Any) -> ScoreAnswer:
    if not isinstance(raw, dict):
        raise _Malformed("a score answer is an object")
    raw_probs = raw.get("probabilities")
    if not isinstance(raw_probs, list) or len(raw_probs) != len(question.criteria):
        raise _Malformed("a score needs one probability per criterion level")
    probabilities = [_as_probability(value) for value in raw_probs]
    _check_distribution(probabilities)
    levels = len(probabilities)
    score = sum(p * (i / (levels - 1)) for i, p in enumerate(probabilities))
    return ScoreAnswer(score=score, probabilities=probabilities)


def _parse_yesno(raw: Any) -> YesNoAnswer:
    if not isinstance(raw, dict):
        raise _Malformed("a yes/no answer is an object")
    p_yes = _as_probability(raw.get("p_yes"))
    return YesNoAnswer(yes=p_yes >= 0.5, p_yes=p_yes)


def _parse_answers(text: str, questions: list[Question]) -> list[Answer]:
    body = text.strip()
    if body.startswith("```"):
        body = body.strip("`")
        if body.startswith("json"):
            body = body[4:]
        body = body.strip()
    try:
        data = json.loads(body)
    except ValueError as exc:
        raise _Malformed(f"not JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise _Malformed("the reply is not a JSON object")
    raw_answers = data.get("answers")
    if not isinstance(raw_answers, list) or len(raw_answers) != len(questions):
        raise _Malformed("the reply does not answer every question")
    answers: list[Answer] = []
    for question, raw in zip(questions, raw_answers, strict=True):
        if isinstance(question, ChoiceQuestion):
            answers.append(_parse_choice(question, raw))
        elif isinstance(question, ScoreQuestion):
            answers.append(_parse_score(question, raw))
        else:
            answers.append(_parse_yesno(raw))
    return answers


def state_hash(state: str) -> str:
    """The 16 character hash the decision log keeps in place of the state."""
    return hashlib.sha256(state.encode("utf-8")).hexdigest()[:16]


class Decider:
    """Asks a backend small questions and validates the answers; fails open.

    ``log_path`` is the decision log file (None keeps no log).  The one
    hard cap is the configured timeout: a slower backend is a timeout
    failure, never a slower run.
    """

    def __init__(
        self,
        backend: DeciderBackend | None,
        *,
        settings: DeciderSettings,
        log_path: Path | None = None,
    ) -> None:
        self._backend = backend
        self._settings = settings
        self._log_path = log_path

    @property
    def enabled(self) -> bool:
        return self._settings.enabled

    async def decide(
        self,
        seam: str,
        request: DecideRequest,
        *,
        annotate: Callable[[DecideOutcome], dict[str, Any]] | None = None,
    ) -> DecideOutcome:
        """One decision, or the named failure that stands in for it.

        ``annotate`` may add fields to the log line from the outcome
        (the agent loop adds which tier a shadow score would have
        picked).  Nothing in here raises: every failure is a value.
        """
        if not self._settings.enabled:
            return DecideOutcome(None, DeciderFailure.DISABLED, 0)
        if not request.questions:
            return DecideOutcome([], None, 0)
        started = time.monotonic()
        if self._backend is None:
            outcome = DecideOutcome(None, DeciderFailure.NO_KEY, 0)
            self._log(seam, request, outcome, annotate)
            return outcome
        answers: list[Answer] | None = None
        failure: DeciderFailure | None = None
        try:
            text, usage = await asyncio.wait_for(
                self._backend.ask_decision(request),
                timeout=self._settings.timeout_seconds,
            )
        except TimeoutError:
            failure = DeciderFailure.TIMEOUT
        except Exception:  # noqa: BLE001 - fail open: any backend error is no decision
            logger.exception("decider backend failed")
            failure = DeciderFailure.BACKEND_ERROR
        else:
            # The call reached a model and was billed, whatever its
            # answer turns out to be worth; the timeout and error paths
            # report no usage, so there is nothing honest to record.
            self._record_cost(seam, usage)
            try:
                answers = _parse_answers(text, request.questions)
            except _Malformed:
                failure = DeciderFailure.MALFORMED
        latency_ms = int((time.monotonic() - started) * 1000)
        outcome = DecideOutcome(answers, failure, latency_ms)
        self._log(seam, request, outcome, annotate)
        return outcome

    def _record_cost(self, seam: str, usage: dict[str, int]) -> None:
        if self._backend is None:
            return
        try:
            cost_recording.record_finished_task(
                task_id=f"decider:{seam}",
                model=self._backend.model,
                snapshot={
                    "input_tokens": usage["input_tokens"],
                    "output_tokens": usage["output_tokens"],
                },
            )
        except Exception:  # noqa: BLE001 - bookkeeping never breaks a run
            logger.exception("decider cost recording failed")

    def _log(
        self,
        seam: str,
        request: DecideRequest,
        outcome: DecideOutcome,
        annotate: Callable[[DecideOutcome], dict[str, Any]] | None,
    ) -> None:
        if self._log_path is None:
            return
        extra: dict[str, Any] = {}
        if annotate is not None:
            try:
                extra = annotate(outcome) or {}
            except Exception:  # noqa: BLE001 - a bad annotation loses its fields, not the line
                extra = {}
        base: dict[str, Any] = {
            "ts": datetime.now(UTC).isoformat(),
            "seam": seam,
            "latency_ms": outcome.latency_ms,
            "state_hash": state_hash(request.state),
        }
        lines: list[dict[str, Any]] = []
        if outcome.answers is None:
            failure = outcome.failure.value if outcome.failure else "unknown"
            lines.append({**base, "ok": False, "failure": failure, **extra})
        else:
            for question, answer in zip(request.questions, outcome.answers, strict=True):
                line: dict[str, Any] = {
                    **base,
                    "ok": True,
                    "kind": question.kind.value,
                    "choice": answer.key if isinstance(answer, ChoiceAnswer) else None,
                    "score": answer.score if isinstance(answer, ScoreAnswer) else None,
                    "p_top": round(answer.p_top, 4),
                    "margin": round(answer.margin, 4),
                    **extra,
                }
                lines.append(line)
        try:
            self._log_path.parent.mkdir(parents=True, exist_ok=True)
            with self._log_path.open("a", encoding="utf-8") as handle:
                for line in lines:
                    handle.write(json.dumps(line, ensure_ascii=False) + "\n")
        except Exception:  # noqa: BLE001 - the log observes; it never interferes
            logger.exception("decider log write failed")


def difficulty_question() -> ScoreQuestion:
    """The run-entry question: how much work is this task, on a 0 to 1 scale."""
    return ScoreQuestion(
        instructions=(
            "Rate how much work the task in the state needs, from a trivial "
            "lookup to open-ended project work."
        ),
        criteria=[
            "a greeting, a yes or no question, or reading back one known fact",
            "a short answer, or one simple tool call",
            "a few steps with two or three tool calls",
            "multi-step work across several tools, with checking along the way",
            "open-ended project work, many steps, long running",
        ],
    )


def build_decider(settings: Settings) -> Decider:
    """The decider for a run, from the [decider] settings.

    The backend is the [llm] slot at temperature 0: the slot as
    configured, or with the [decider] model in place of its model.  A
    slot that cannot answer (no key, not a local endpoint, no ChatGPT
    sign-in) leaves the decider backendless, and its calls fail open
    as no_key rather than failing the run.
    """
    cfg = settings.decider
    backend: DeciderBackend | None = None
    if cfg.enabled:
        from nanomuse.llm.factory import create_llm, llm_ready

        slot = settings.llm.model_copy(update={"temperature": 0.0})
        if cfg.model:
            slot = slot.model_copy(update={"model": cfg.model})
        try:
            if llm_ready(slot, data_dir=settings.data_dir):
                backend = CheapestModelBackend(
                    create_llm(slot, data_dir=settings.data_dir), model=slot.model
                )
        except Exception:  # noqa: BLE001 - an unbuildable backend is no_key, not a crash
            logger.exception("decider backend could not be built")
            backend = None
    return Decider(backend, settings=cfg, log_path=settings.decider_log_file)


__all__ = [
    "CheapestModelBackend",
    "ChoiceAnswer",
    "ChoiceQuestion",
    "DecideOutcome",
    "DecideRequest",
    "Decider",
    "DeciderBackend",
    "DeciderFailure",
    "Question",
    "QuestionKind",
    "ScoreAnswer",
    "ScoreQuestion",
    "YesNoAnswer",
    "YesNoQuestion",
    "build_decider",
    "difficulty_question",
    "state_hash",
]

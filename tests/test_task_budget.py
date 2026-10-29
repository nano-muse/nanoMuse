from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest
from pydantic import ValidationError

from nanomuse.agent import MuseAgent
from nanomuse.agent.context import fit_context
from nanomuse.config import Settings, TaskBudgetSettings
from nanomuse.llm import MockLLM
from nanomuse.llm import budget as budgets
from nanomuse.logger import logger
from nanomuse.schema import AgentState, Function, LLMResponse, Message, Role, ToolCall, ToolResult
from nanomuse.sentinel import AuditLog, Sentinel
from nanomuse.tools.base import BaseTool, ToolCollection
from nanomuse.ui import HeadlessUI


class Counter(BaseTool):
    name: str = "counter"
    description: str = "Record one action"
    ran: int = 0

    async def execute(self, **kwargs: Any) -> ToolResult:
        self.ran += 1
        return ToolResult(output="recorded")


def make_agent(settings: Settings, llm: MockLLM) -> tuple[MuseAgent, Counter]:
    ui = HeadlessUI()
    audit = AuditLog(settings.audit_file)
    tool = Counter()
    return MuseAgent(
        settings, llm, ToolCollection(tool), Sentinel(settings.sentinel, audit, ui), ui, audit
    ), tool


def test_budget_configuration_requires_finite_nonnegative_limits_and_prices():
    for data in (
        {"max_total_tokens": -1},
        {"max_seconds": float("nan")},
        {"max_cost_usd": 1},
        {"input_usd_per_million": -1},
    ):
        with pytest.raises(ValidationError):
            TaskBudgetSettings(**data)


async def test_preflight_refuses_unaffordable_request_without_calling_model(settings: Settings):
    settings.agent.budget = TaskBudgetSettings(max_total_tokens=1)
    llm = MockLLM([])
    agent, tool = make_agent(settings, llm)
    assert "token budget" in await agent.run("go")
    assert not llm.calls and tool.ran == 0
    assert agent.state == AgentState.FINISHED and budgets.current() is None
    assert agent.last_budget["stopped"] == "token"


async def test_reported_usage_stops_actions_and_repairs_tool_pairs(settings: Settings):
    settings.agent.budget = TaskBudgetSettings(max_total_tokens=20000)
    call = ToolCall(function=Function(name="counter"))
    llm = MockLLM(
        [LLMResponse(tool_calls=[call], usage={"prompt_tokens": 20000, "completion_tokens": 1})]
    )
    agent, tool = make_agent(settings, llm)
    assert "token budget" in await agent.run("go")
    assert tool.ran == 0 and len(llm.calls) == 1
    assert any(m.role == Role.TOOL and m.tool_call_id == call.id for m in agent.messages)
    assert any(m.role == Role.TOOL and "budget" in (m.content or "") for m in agent.messages)
    assert any(kind == "tool_result" for kind, _ in agent.ui.events)
    assert agent.last_budget["total_tokens"] == 20001
    settings.agent.budget = TaskBudgetSettings()
    llm.script = [LLMResponse(content="next")]
    assert await agent.run("continue") == "next"


async def test_cost_reserves_input_and_caps_output():
    messages = [Message.user("hi")]
    incoming = budgets.estimate_tokens(messages)
    settings = TaskBudgetSettings(
        max_cost_usd=(incoming + 7.5) / 1e6, input_usd_per_million=1, output_usd_per_million=1
    )
    llm = MockLLM([LLMResponse(content="ok", usage={"input_tokens": 2, "output_tokens": 3})])
    token = budgets.begin(settings)
    try:
        await budgets.ask(llm, messages)
        assert llm.calls[0]["max_tokens"] == 7
        assert budgets.current().cost_usd == pytest.approx(5 / 1e6)
    finally:
        budgets.end(token)


async def test_missing_usage_reserves_full_output_and_retry_shares_budget():
    messages = [Message.user("hi")]
    incoming = budgets.estimate_tokens(messages)
    token = budgets.begin(TaskBudgetSettings(max_total_tokens=incoming + 12))
    llm = MockLLM([LLMResponse(finish_reason="length")])
    try:
        with pytest.raises(budgets.BudgetExceeded):
            await budgets.ask_complete(llm, messages)
        assert len(llm.calls) == 1 and llm.calls[0]["max_tokens"] == 12
        assert budgets.current().estimated_calls == 1
    finally:
        budgets.end(token)


async def test_without_a_limit_nothing_is_estimated_capped_or_logged(settings: Settings):
    # the default: no limit set — the request goes as the call made it, the provider's
    # figures are still counted, and the audit log gets no task_budget line
    messages = [Message.user("hi")]
    token = budgets.begin(TaskBudgetSettings())
    llm = MockLLM([LLMResponse(content="ok", usage={"prompt_tokens": 7, "completion_tokens": 3})])
    try:
        await budgets.ask(llm, messages)
        assert llm.calls[0]["max_tokens"] is None
        assert budgets.current().snapshot()["total_tokens"] == 10
        assert budgets.current().estimated_calls == 0
    finally:
        budgets.end(token)
    agent, _ = make_agent(settings, MockLLM([LLMResponse(content="done")]))
    assert await agent.run("go") == "done"
    assert agent.last_budget["calls"] == 1
    lines = [json.loads(line) for line in settings.audit_file.read_text().splitlines()]
    assert not [e for e in lines if e["event"] == "task_budget"]
    # a limit in force: the line is written, whether or not it was reached
    settings.agent.budget = TaskBudgetSettings(max_seconds=600)
    agent, _ = make_agent(settings, MockLLM([LLMResponse(content="done")]))
    assert await agent.run("go") == "done"
    lines = [json.loads(line) for line in settings.audit_file.read_text().splitlines()]
    assert [e["stopped"] for e in lines if e["event"] == "task_budget"] == [""]


async def test_nested_scope_inherits_budget_and_parallel_tasks_are_isolated():
    async def work() -> int:
        token = budgets.begin(TaskBudgetSettings(max_total_tokens=50000), inherit=False)
        try:
            parent = budgets.current()
            inner = budgets.begin(TaskBudgetSettings(max_total_tokens=1))
            try:
                assert budgets.current() is parent
                await budgets.ask(
                    MockLLM([LLMResponse(usage={"input_tokens": 2, "output_tokens": 3})]),
                    [Message.user("x")],
                )
            finally:
                budgets.end(inner)
            await asyncio.sleep(0)
            return parent.total_tokens
        finally:
            budgets.end(token)

    assert await asyncio.gather(work(), work()) == [5, 5]
    assert budgets.current() is None


async def test_deadline_cancels_model_without_a_paid_wrapup(settings: Settings):
    class SlowLLM(MockLLM):
        cancelled = False

        async def ask(self, *args: Any, **kwargs: Any) -> LLMResponse:
            try:
                await asyncio.sleep(60)
            finally:
                self.cancelled = True
            return LLMResponse()

    settings.agent.budget = TaskBudgetSettings(max_seconds=0.02)
    llm = SlowLLM()
    agent, _ = make_agent(settings, llm)
    assert "time budget" in await agent.run("go")
    assert llm.cancelled and agent.last_budget["calls"] == 1
    assert budgets.current() is None


def test_context_budget_preserves_constraints_pairs_and_saved_history():
    request = Message.user("Never send this file. Only read it.")
    call = ToolCall(function=Function(name="read", arguments=json.dumps({"path": "notes.txt"})))
    result = Message.tool("HEAD" + "x" * 30000 + "TAIL", call.id)
    history = [
        Message.system("policy"),
        Message.user("old" * 1000),
        request,
        Message.assistant(tool_calls=[call]),
        result,
    ]
    packed = fit_context(history, None, 1300, [request])
    assert budgets.estimate_tokens(packed) <= 1300
    assert request in packed and result.content.endswith("TAIL") and len(result.content) > 30000
    assert packed[-1].tool_call_id == packed[-2].tool_calls[0].id
    assert "shortened" in packed[-1].content


def test_indivisible_context_is_refused_instead_of_dropping_instructions():
    request = Message.user("Do not send. " * 1000)
    with pytest.raises(budgets.BudgetExceeded, match="context"):
        fit_context([Message.system("policy"), request], None, 100, [request])


async def test_cost_limit_refuses_input_before_model_call():
    llm = MockLLM([])
    token = budgets.begin(TaskBudgetSettings(max_cost_usd=0.000001, input_usd_per_million=1))
    try:
        with pytest.raises(budgets.BudgetExceeded, match="cost"):
            await budgets.ask(llm, [Message.user("input")])
        assert not llm.calls
    finally:
        budgets.end(token)


async def test_failed_request_keeps_its_reservation():
    class FailingLLM(MockLLM):
        async def ask(self, *args: Any, **kwargs: Any) -> LLMResponse:
            raise RuntimeError("fixture transport failed")

    messages = [Message.user("input")]
    token = budgets.begin(TaskBudgetSettings(max_total_tokens=10000))
    try:
        with pytest.raises(RuntimeError, match="fixture transport"):
            await budgets.ask(FailingLLM(), messages, max_tokens=10)
        assert budgets.current().total_tokens == budgets.estimate_tokens(messages) + 10
        assert budgets.current().estimated_calls == 1
    finally:
        budgets.end(token)


async def test_provider_timeout_is_not_reported_as_task_deadline(settings: Settings):
    class TimedOutLLM(MockLLM):
        async def ask(self, *args: Any, **kwargs: Any) -> LLMResponse:
            raise TimeoutError("fixture provider timeout")

    agent, _ = make_agent(settings, TimedOutLLM())
    with pytest.raises(TimeoutError, match="fixture provider timeout"):
        await agent.run("go")
    assert agent.last_budget["stopped"] == "" and budgets.current() is None


async def test_current_user_request_survives_message_count_trimming(settings: Settings):
    settings.agent.max_context_messages = 1
    settings.agent.max_context_tokens = 20000
    calls = [ToolCall(function=Function(name="counter")) for _ in range(3)]
    llm = MockLLM(
        [*[LLMResponse(tool_calls=[call]) for call in calls], LLMResponse(content="done")]
    )
    agent, _ = make_agent(settings, llm)
    instruction = "Only count. Never send anything."
    assert await agent.run(instruction) == "done"
    assert len(llm.calls) == 4
    for request in llm.calls:
        assert sum(m.content == instruction for m in request["messages"]) == 1
        assert budgets.estimate_tokens(request["messages"], request["tools"]) <= 20000


async def test_deadline_cancels_tool_and_keeps_history_valid(settings: Settings):
    class SlowCounter(Counter):
        cancelled: bool = False

        async def execute(self, **kwargs: Any) -> ToolResult:
            try:
                await asyncio.sleep(60)
            finally:
                self.cancelled = True
            return ToolResult(output="done")

    settings.agent.budget = TaskBudgetSettings(max_seconds=0.03)
    call = ToolCall(function=Function(name="counter"))
    llm = MockLLM([LLMResponse(tool_calls=[call])])
    agent, _ = make_agent(settings, llm)
    tool = SlowCounter()
    agent.tools = ToolCollection(tool)
    assert "time budget" in await agent.run("go")
    assert tool.cancelled and len(llm.calls) == 1
    assert any(m.tool_call_id == call.id for m in agent.messages)


async def test_budget_stop_uses_the_chinese_request_language(settings: Settings):
    settings.agent.budget = TaskBudgetSettings(max_total_tokens=1)
    agent, _ = make_agent(settings, MockLLM([]))
    assert "任务已停止" in await agent.run("帮我计算")


def test_long_english_context_is_estimated_as_tokens_not_bytes():
    request = Message.user("Read the report and preserve the original file. " * 3000)
    messages = [Message.system("policy"), request]
    raw_size = len(
        json.dumps(
            [[m.to_openai(include_reasoning=True) for m in messages], []], ensure_ascii=False
        ).encode("utf-8")
    )
    estimate = budgets.estimate_tokens(messages)
    assert raw_size > 100000
    assert 30000 < estimate < 40000
    assert fit_context(messages, None, 50000, [request]) == messages


def test_estimate_includes_tool_schemas_and_image_allowance():
    messages = [Message.user("look")]
    tools = [
        {"type": "function", "function": {"name": "read", "description": "Read a file. " * 100}}
    ]
    text_estimate = budgets.estimate_tokens(messages)
    assert budgets.estimate_tokens(messages, tools) > text_estimate
    pictured = [Message.user("look", images=["fixture.png"])]
    assert budgets.estimate_tokens(pictured) == text_estimate + 4096


def test_shortening_is_logged_without_tool_output_text():
    request = Message.user("Read only")
    call = ToolCall(function=Function(name="read"))
    original = "PRIVATE_OUTPUT_MARKER" * 2000
    result = Message.tool(original, call.id)
    records: list[str] = []
    sink = logger.add(
        lambda message: records.append(str(message)), format="{message}", level="INFO"
    )
    try:
        fit_context(
            [Message.system("policy"), request, Message.assistant(tool_calls=[call]), result],
            None,
            1200,
            [request],
        )
    finally:
        logger.remove(sink)
    notices = [record for record in records if "Context budget shortened tool result" in record]
    assert notices and all(call.id in record and "characters" in record for record in notices)
    assert all("PRIVATE_OUTPUT_MARKER" not in record for record in notices)
    assert result.content == original

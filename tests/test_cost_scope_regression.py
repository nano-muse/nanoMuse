"""Regression tests for the cost recorder review on PR #920.

Two defects: the recorder and its budget gate leaked between app
instances through a process-wide install, and a nested call made with
a different (cheaper) model was priced as the parent task's model
because the task budget only kept one aggregate pair of token counts.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from nanomuse.agent import MuseAgent
from nanomuse.app import NanoMuseApp
from nanomuse.config import LLMSettings, PriceSettings, Settings
from nanomuse.cost import recording
from nanomuse.cost.gate import CostGateBlocked, current_month
from nanomuse.cost.ledger import CostLedger, PriceEntry
from nanomuse.cost.recording import TaskCostRecorder
from nanomuse.llm import MockLLM
from nanomuse.llm import budget as budgets
from nanomuse.schema import Function, LLMResponse, Message, ToolCall, ToolResult
from nanomuse.sentinel import AuditLog, Sentinel
from nanomuse.tools.base import BaseTool, ToolCollection
from nanomuse.ui import HeadlessUI

MONTH = "2026-10"


def _app(
    tmp_path: Path, name: str, device_id: str, *, mode: str = "off", budget: float = 100.0
) -> NanoMuseApp:
    settings = Settings(data_dir=tmp_path / name)
    settings.agent.workspace = tmp_path / name / "workspace"
    settings.llm.model = "mock"
    settings.llm.api_key = "test"
    settings.llm.stream = False
    settings.cost.device_id = device_id
    settings.cost.mode = mode  # type: ignore[assignment]
    settings.cost.monthly_budget_usd = budget
    settings.cost.prices = {"mock": PriceSettings(input_per_million=2.0, output_per_million=8.0)}
    llm = MockLLM([LLMResponse(content="ok", usage={"input_tokens": 1000, "output_tokens": 500})])
    return NanoMuseApp(settings, ui=HeadlessUI(), llm=llm)  # type: ignore[arg-type]


def test_two_apps_do_not_share_the_cost_recorder(tmp_path: Path) -> None:
    first = _app(tmp_path, "one", "first-device")
    second = _app(tmp_path, "two", "second-device")
    try:
        asyncio.run(first.agent.run("say something"))
        assert first.cost_ledger is not None
        assert second.cost_ledger is not None
        assert len(first.cost_ledger.entries) == 1
        assert first.cost_ledger.entries[0].device_id == "first-device"
        assert second.cost_ledger.entries == []

        asyncio.run(second.agent.run("say something else"))
        assert len(second.cost_ledger.entries) == 1
        assert second.cost_ledger.entries[0].device_id == "second-device"
        assert len(first.cost_ledger.entries) == 1
    finally:
        recording.install(None)


def test_one_apps_hard_gate_does_not_block_another_app(tmp_path: Path) -> None:
    blocked = _app(tmp_path, "blocked", "blocked-device", mode="hard", budget=5.0)
    free = _app(tmp_path, "free", "free-device", mode="hard")
    try:
        assert blocked.cost_ledger is not None
        # Put only the first app over its monthly budget.
        blocked.cost_ledger.record(
            task_id="old",
            device_id="blocked-device",
            model="mock",
            input_tokens=1_000_000,
            output_tokens=500_000,
            month=current_month(),
        )
        # Sanity: its own gate is over budget, the other app's is not.
        assert blocked.cost_ledger.month_total(current_month()) == 6.0
        with pytest.raises(CostGateBlocked):
            asyncio.run(blocked.agent.run("this must not run"))
        # The other app, under its own budget, still runs and records
        # into its own ledger only.
        asyncio.run(free.agent.run("say something"))
        assert free.cost_ledger is not None
        assert len(free.cost_ledger.entries) == 1
        assert len(blocked.cost_ledger.entries) == 1
    finally:
        recording.install(None)


class NestedCallTool(BaseTool):
    name: str = "nested_call"
    description: str = "Make a nested model call with a cheaper model"

    async def execute(self, **kwargs: Any) -> ToolResult:
        cheap = MockLLM(
            [LLMResponse(content="sub", usage={"input_tokens": 1000, "output_tokens": 500})]
        )
        cheap.settings = LLMSettings(model="cheap")  # type: ignore[attr-defined]
        await budgets.ask(cheap, [Message.user("subtask")])
        return ToolResult(output="nested done")


def test_nested_call_is_priced_by_its_actual_model(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path)
    settings.llm.model = "expensive"
    ui = HeadlessUI()
    audit = AuditLog(settings.audit_file)
    call = ToolCall(function=Function(name="nested_call", arguments="{}"))
    parent = MockLLM(
        [
            LLMResponse(tool_calls=[call], usage={"input_tokens": 1000, "output_tokens": 500}),
            LLMResponse(content="done", usage={"input_tokens": 1000, "output_tokens": 500}),
        ]
    )
    parent.settings = LLMSettings(model="expensive")  # type: ignore[attr-defined]
    agent = MuseAgent(
        settings,
        parent,
        ToolCollection(NestedCallTool()),
        Sentinel(settings.sentinel, audit, ui),
        ui,
        audit,
    )
    book = CostLedger(
        prices={
            "expensive": PriceEntry("expensive", 10.0, 10.0),
            "cheap": PriceEntry("cheap", 1.0, 1.0),
        }
    )
    recording.install(TaskCostRecorder(book, device_id="test-box"))
    try:
        asyncio.run(agent.run("do the task"))
    finally:
        recording.install(None)
    # The parent made two calls (2000 in, 1000 out at 10 USD per
    # million) and the nested tool made one call with the cheap model
    # (1000 in, 500 out at 1 USD per million). Each is priced by the
    # model that actually made it, as its own ledger entry.
    assert book.by_model() == {"expensive": pytest.approx(0.03), "cheap": pytest.approx(0.0015)}
    assert len(book.entries) == 2
    by_model_entries = {entry.model: entry for entry in book.entries}
    assert by_model_entries["expensive"].input_tokens == 2000
    assert by_model_entries["expensive"].output_tokens == 1000
    assert by_model_entries["cheap"].input_tokens == 1000
    assert by_model_entries["cheap"].output_tokens == 500

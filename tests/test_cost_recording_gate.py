"""Phase 6 (D): the ledger fed from real runs, persisted, and the budget gate.

The recorder turns a finished task's budget snapshot into a ledger
entry, the persistent ledger keeps entries across restarts, and the
gate has three modes: off (record only), warn (alert, work continues),
hard (refuse new tasks over the monthly budget, one approved override
at a time).
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from nanomuse.agent import MuseAgent
from nanomuse.config import Settings
from nanomuse.cost import recording
from nanomuse.cost.gate import CostGateBlocked, MonthlyBudgetGate, current_month
from nanomuse.cost.ledger import CostLedger, PriceEntry
from nanomuse.cost.recording import TaskCostRecorder
from nanomuse.cost.store import PersistentCostLedger
from nanomuse.llm import MockLLM
from nanomuse.schema import LLMResponse
from nanomuse.sentinel import AuditLog, Sentinel
from nanomuse.tools.base import ToolCollection
from nanomuse.ui import HeadlessUI

PRICES = {"mock": PriceEntry("mock", 2.0, 8.0)}
MONTH = "2026-10"


def snapshot(input_tokens: int = 1_000_000, output_tokens: int = 500_000) -> dict:
    return {"input_tokens": input_tokens, "output_tokens": output_tokens, "cost_usd": 0.0}


# ---------------------------------------------------------------- persistence


def test_persistent_ledger_survives_a_reopen(tmp_path: Path) -> None:
    path = tmp_path / "cost_ledger.jsonl"
    book = PersistentCostLedger(path, prices=PRICES, monthly_budget_usd=5.0)
    book.record(
        task_id="t1",
        device_id="phone",
        model="mock",
        input_tokens=1_000_000,
        output_tokens=500_000,
        month=MONTH,
    )
    assert book.month_total(MONTH) == 6.0
    assert len(book.alerts) == 1  # crossed the 5 USD budget

    reopened = PersistentCostLedger(path, prices=PRICES, monthly_budget_usd=5.0)
    assert reopened.month_total(MONTH) == 6.0
    assert reopened.by_task() == {"t1": 6.0}
    assert len(reopened.alerts) == 1  # recomputed on replay, not duplicated


def test_persistent_ledger_skips_a_damaged_line(tmp_path: Path) -> None:
    path = tmp_path / "cost_ledger.jsonl"
    book = PersistentCostLedger(path, prices=PRICES)
    book.record(
        task_id="t1",
        device_id="phone",
        model="mock",
        input_tokens=10,
        output_tokens=10,
        month=MONTH,
    )
    with path.open("a", encoding="utf-8") as handle:
        handle.write("{not json\n")
    reopened = PersistentCostLedger(path, prices=PRICES)
    assert len(reopened.entries) == 1
    assert reopened.skipped_lines == 1


# ---------------------------------------------------------------- recorder


def test_recorder_turns_a_snapshot_into_a_priced_entry() -> None:
    book = CostLedger(prices=PRICES)
    recorder = TaskCostRecorder(book, device_id="desktop")
    entry = recorder.record_finished_task(
        task_id="conv-1", model="mock", snapshot=snapshot(), month=MONTH
    )
    assert entry is not None
    assert entry.cost_usd == 6.0
    assert entry.device_id == "desktop"
    assert book.by_model() == {"mock": 6.0}


def test_recorder_skips_a_task_that_made_no_calls() -> None:
    book = CostLedger(prices=PRICES)
    recorder = TaskCostRecorder(book)
    assert (
        recorder.record_finished_task(
            task_id="t", model="mock", snapshot=snapshot(0, 0), month=MONTH
        )
        is None
    )
    assert book.entries == []


# ---------------------------------------------------------------- gate modes


def over_budget_ledger() -> CostLedger:
    book = CostLedger(prices=PRICES, monthly_budget_usd=5.0)
    book.record(
        task_id="t1",
        device_id="d",
        model="mock",
        input_tokens=1_000_000,
        output_tokens=500_000,
        month=MONTH,
    )
    return book


def test_gate_off_never_blocks() -> None:
    MonthlyBudgetGate(over_budget_ledger(), mode="off").check_before_task(MONTH)


def test_gate_warn_alerts_without_blocking() -> None:
    gate = MonthlyBudgetGate(over_budget_ledger(), mode="warn")
    gate.check_before_task(MONTH)  # does not raise
    assert gate.pending_alert(MONTH) is not None
    assert "budget" in (gate.pending_alert(MONTH) or "")


def test_gate_hard_blocks_and_names_the_numbers() -> None:
    gate = MonthlyBudgetGate(over_budget_ledger(), mode="hard")
    with pytest.raises(CostGateBlocked) as caught:
        gate.check_before_task(MONTH)
    assert caught.value.spent_usd == 6.0
    assert caught.value.budget_usd == 5.0


def test_gate_hard_override_lets_exactly_one_task_past() -> None:
    gate = MonthlyBudgetGate(over_budget_ledger(), mode="hard")
    gate.override_once()
    gate.check_before_task(MONTH)  # the approved one passes
    with pytest.raises(CostGateBlocked):
        gate.check_before_task(MONTH)  # and the gate is shut again


def test_gate_without_a_budget_never_blocks() -> None:
    book = CostLedger(prices=PRICES)  # no monthly budget set
    book.record(
        task_id="t",
        device_id="d",
        model="mock",
        input_tokens=10_000_000,
        output_tokens=0,
        month=MONTH,
    )
    MonthlyBudgetGate(book, mode="hard").check_before_task(MONTH)


# ---------------------------------------------------------------- agent wiring


def test_a_real_run_lands_in_the_ledger(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path)
    settings.llm.model = "mock"  # the configured model is what the ledger names
    ui = HeadlessUI()
    audit = AuditLog(settings.audit_file)
    llm = MockLLM([LLMResponse(content="ok", usage={"input_tokens": 1000, "output_tokens": 500})])
    agent = MuseAgent(
        settings, llm, ToolCollection(), Sentinel(settings.sentinel, audit, ui), ui, audit
    )
    book = CostLedger(prices={"mock": PriceEntry("mock", 2.0, 8.0)})
    recording.install(TaskCostRecorder(book, device_id="test-box"))
    try:
        asyncio.run(agent.run("say something"))
    finally:
        recording.install(None)
    assert len(book.entries) == 1
    entry = book.entries[0]
    assert entry.device_id == "test-box"
    assert entry.model == "mock"
    assert entry.input_tokens > 0
    assert entry.cost_usd > 0


def test_a_prompt_mode_run_records_the_configured_model(tmp_path: Path) -> None:
    # In prompt mode the llm is the prompt adapter, whose name is
    # "prompt_tools".  The ledger must still name (and price) the
    # configured model; pricing by the adapter's name recorded real
    # runs at zero cost.
    from nanomuse.llm.prompt_tools import PromptToolAdapter

    settings = Settings(data_dir=tmp_path)
    settings.llm.model = "mock"
    ui = HeadlessUI()
    audit = AuditLog(settings.audit_file)
    inner = MockLLM([LLMResponse(content="ok", usage={"input_tokens": 1000, "output_tokens": 500})])
    llm = PromptToolAdapter(inner)
    assert llm.name == "prompt_tools"
    agent = MuseAgent(
        settings, llm, ToolCollection(), Sentinel(settings.sentinel, audit, ui), ui, audit
    )
    book = CostLedger(prices={"mock": PriceEntry("mock", 2.0, 8.0)})
    recording.install(TaskCostRecorder(book, device_id="test-box"))
    try:
        asyncio.run(agent.run("say something"))
    finally:
        recording.install(None)
    assert len(book.entries) == 1
    entry = book.entries[0]
    assert entry.model == "mock"
    assert entry.cost_usd == pytest.approx(0.006)  # 1000 in, 500 out at [2.0, 8.0]


def test_hard_gate_refuses_a_run_before_it_starts(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path)
    ui = HeadlessUI()
    audit = AuditLog(settings.audit_file)
    agent = MuseAgent(
        settings, MockLLM(), ToolCollection(), Sentinel(settings.sentinel, audit, ui), ui, audit
    )
    book = CostLedger(prices=PRICES, monthly_budget_usd=5.0)
    book.record(
        task_id="t1",
        device_id="d",
        model="mock",
        input_tokens=1_000_000,
        output_tokens=500_000,
        month=current_month(),
    )
    gate = MonthlyBudgetGate(book, mode="hard")
    recording.install(TaskCostRecorder(book, gate=gate))
    try:
        with pytest.raises(CostGateBlocked):
            asyncio.run(agent.run("this must not run"))
    finally:
        recording.install(None)

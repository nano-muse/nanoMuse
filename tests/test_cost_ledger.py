"""Cost ledger tests: three views, one budget alert, priced by table."""

from __future__ import annotations

from nanomuse.cost.ledger import CostLedger, PriceEntry

PRICES = {
    "qwen": PriceEntry("qwen", 2.0, 8.0),
    "gpt": PriceEntry("gpt", 5.0, 15.0),
}


def ledger(budget: float | None = None) -> CostLedger:
    return CostLedger(prices=PRICES, monthly_budget_usd=budget)


def test_costs_are_priced_from_the_table() -> None:
    entry = ledger().record(
        task_id="t1",
        device_id="phone",
        model="qwen",
        input_tokens=1_000_000,
        output_tokens=500_000,
        month="2026-10",
    )
    assert entry.cost_usd == 2.0 + 4.0


def test_an_unpriced_model_costs_zero_rather_than_guessing() -> None:
    entry = ledger().record(
        task_id="t1",
        device_id="phone",
        model="unknown",
        input_tokens=1000,
        output_tokens=1000,
        month="2026-10",
    )
    assert entry.cost_usd == 0.0


def test_three_views_sum_the_same_entries_three_ways() -> None:
    book = ledger()
    book.record(
        task_id="t1",
        device_id="phone",
        model="qwen",
        input_tokens=1_000_000,
        output_tokens=0,
        month="2026-10",
    )
    book.record(
        task_id="t1",
        device_id="desk",
        model="gpt",
        input_tokens=0,
        output_tokens=1_000_000,
        month="2026-10",
    )
    book.record(
        task_id="t2",
        device_id="phone",
        model="gpt",
        input_tokens=1_000_000,
        output_tokens=0,
        month="2026-10",
    )
    assert book.by_task() == {"t1": 17.0, "t2": 5.0}
    assert book.by_device() == {"phone": 7.0, "desk": 15.0}
    assert book.by_model() == {"qwen": 2.0, "gpt": 20.0}
    assert book.month_total("2026-10") == 22.0
    assert book.month_total("2026-09") == 0.0


def test_the_budget_alert_fires_once_per_month_at_the_threshold() -> None:
    book = ledger(budget=10.0)
    book.record(
        task_id="t1",
        device_id="phone",
        model="qwen",
        input_tokens=1_000_000,
        output_tokens=0,
        month="2026-10",
    )
    assert book.alerts == []
    book.record(
        task_id="t1",
        device_id="phone",
        model="qwen",
        input_tokens=4_000_000,
        output_tokens=0,
        month="2026-10",
    )
    assert len(book.alerts) == 1
    assert book.alerts[0].month == "2026-10"
    assert book.alerts[0].spent_usd == 10.0
    book.record(
        task_id="t1",
        device_id="phone",
        model="qwen",
        input_tokens=1_000_000,
        output_tokens=0,
        month="2026-10",
    )
    assert len(book.alerts) == 1
    book.record(
        task_id="t1",
        device_id="phone",
        model="qwen",
        input_tokens=5_000_000,
        output_tokens=0,
        month="2026-11",
    )
    assert len(book.alerts) == 2


def test_an_alert_is_a_record_not_a_block() -> None:
    book = ledger(budget=1.0)
    book.record(
        task_id="t1",
        device_id="phone",
        model="qwen",
        input_tokens=1_000_000,
        output_tokens=0,
        month="2026-10",
    )
    assert len(book.alerts) == 1
    assert len(book.entries) == 1
    book.record(
        task_id="t2",
        device_id="phone",
        model="qwen",
        input_tokens=1_000_000,
        output_tokens=0,
        month="2026-10",
    )
    assert len(book.entries) == 2


def test_no_budget_means_no_alerts() -> None:
    book = ledger()
    book.record(
        task_id="t1",
        device_id="phone",
        model="gpt",
        input_tokens=10_000_000,
        output_tokens=0,
        month="2026-10",
    )
    assert book.alerts == []


def test_rows_round_trip_as_json_fixture_rows() -> None:
    book = ledger()
    book.record(
        task_id="t1",
        device_id="phone",
        model="qwen",
        input_tokens=500_000,
        output_tokens=250_000,
        month="2026-10",
    )
    row = book.to_rows()[0]
    assert row == {
        "task_id": "t1",
        "device_id": "phone",
        "model": "qwen",
        "input_tokens": 500_000,
        "output_tokens": 250_000,
        "cost_usd": 3.0,
        "month": "2026-10",
    }

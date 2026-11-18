"""Cost ledger v1: what each task, device and model cost, in one place.

Every model call the agent makes is one ledger entry: who ran it
(task), where it ran (device), what ran it (model), and what it cost.
Costs come from a price table of per-million-token rates, so a ledger
built from fixtures is exactly reproducible.  Three views aggregate
the same entries three ways, and a monthly budget raises one alert
record when spending reaches its threshold.  The alert is a record,
not a block: the ledger reports, it never refuses work.

No vendor bill is read here.  The entries themselves are real:
``nanomuse.cost.recording`` feeds this ledger from finished runs and
``nanomuse.cost.store`` persists it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PriceEntry:
    """Per-million-token rates for one model, in USD."""

    model: str
    input_per_million: float
    output_per_million: float

    def cost(self, input_tokens: int, output_tokens: int) -> float:
        return (
            input_tokens * self.input_per_million + output_tokens * self.output_per_million
        ) / 1_000_000


@dataclass
class LedgerEntry:
    task_id: str
    device_id: str
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    month: str  # "YYYY-MM"


@dataclass
class BudgetAlert:
    month: str
    threshold_usd: float
    spent_usd: float
    message: str


class CostLedger:
    """Append-only entries plus three aggregation views and a budget."""

    def __init__(
        self,
        prices: dict[str, PriceEntry] | None = None,
        monthly_budget_usd: float | None = None,
    ) -> None:
        self._prices = prices or {}
        self.monthly_budget_usd = monthly_budget_usd
        self.entries: list[LedgerEntry] = []
        self.alerts: list[BudgetAlert] = []
        self._alerted_months: set[str] = set()

    def record(
        self,
        *,
        task_id: str,
        device_id: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        month: str,
    ) -> LedgerEntry:
        price = self._prices.get(model)
        cost = price.cost(input_tokens, output_tokens) if price else 0.0
        entry = LedgerEntry(
            task_id=task_id,
            device_id=device_id,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost,
            month=month,
        )
        self.entries.append(entry)
        self._check_budget(month)
        return entry

    def by_task(self) -> dict[str, float]:
        return self._sum_by("task_id")

    def by_device(self) -> dict[str, float]:
        return self._sum_by("device_id")

    def by_model(self) -> dict[str, float]:
        return self._sum_by("model")

    def _sum_by(self, key: str) -> dict[str, float]:
        totals: dict[str, float] = {}
        for entry in self.entries:
            totals[getattr(entry, key)] = totals.get(getattr(entry, key), 0.0) + entry.cost_usd
        return totals

    def month_total(self, month: str) -> float:
        return sum(e.cost_usd for e in self.entries if e.month == month)

    def _check_budget(self, month: str) -> None:
        if self.monthly_budget_usd is None or month in self._alerted_months:
            return
        spent = self.month_total(month)
        if spent >= self.monthly_budget_usd:
            self._alerted_months.add(month)
            self.alerts.append(
                BudgetAlert(
                    month=month,
                    threshold_usd=self.monthly_budget_usd,
                    spent_usd=spent,
                    message=(
                        f"monthly spend {spent:.2f} USD reached the "
                        f"{self.monthly_budget_usd:.2f} USD budget for {month}"
                    ),
                )
            )

    def to_rows(self) -> list[dict[str, Any]]:
        return [field_row(e) for e in self.entries]


def field_row(entry: LedgerEntry) -> dict[str, Any]:
    return {
        "task_id": entry.task_id,
        "device_id": entry.device_id,
        "model": entry.model,
        "input_tokens": entry.input_tokens,
        "output_tokens": entry.output_tokens,
        "cost_usd": round(entry.cost_usd, 6),
        "month": entry.month,
    }

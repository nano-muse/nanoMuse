"""The monthly budget gate: off, warn, or hard.

The ledger has always reported spending and raised an alert record at
the budget line; it never refused work.  This gate is the step added
on top, in three modes the person chooses:

- ``off``: no gate.  The ledger still records.
- ``warn``: crossing the budget surfaces the alert (the ledger's own
  alert record) and work continues.  This is the ledger's old
  behaviour, kept for people who only want to be told.
- ``hard``: once the month's recorded spend reaches the budget, a new
  task is refused before it starts, with :class:`CostGateBlocked`.
  The refusal is a budget fact, not a judgement: the message names the
  month, the budget and the spend.  A person who has seen the numbers
  can lift the gate for exactly one task with :meth:`override_once`
  (the approval flows call this when the owner approves continuing);
  the override is consumed by the next check, never stored.

The gate reads the ledger, so it only knows about recorded spend.
With no monthly budget set there is nothing to gate on, in any mode.
"""

from __future__ import annotations

import time
from typing import Literal

from nanomuse.cost.ledger import CostLedger

GateMode = Literal["off", "warn", "hard"]
GATE_MODES: tuple[str, ...] = ("off", "warn", "hard")


class CostGateBlocked(RuntimeError):
    """Raised in hard mode when a task would start over the monthly budget."""

    def __init__(self, month: str, budget_usd: float, spent_usd: float) -> None:
        self.month = month
        self.budget_usd = budget_usd
        self.spent_usd = spent_usd
        super().__init__(
            f"monthly budget reached: {spent_usd:.2f} USD spent in {month} "
            f"against a {budget_usd:.2f} USD budget; the cost gate is set to hard, "
            "so new tasks are refused until the budget is raised, the mode is "
            "changed, or one task is approved past it"
        )


def current_month(now: float | None = None) -> str:
    """The local ``YYYY-MM`` a timestamp belongs to."""
    return time.strftime("%Y-%m", time.localtime(time.time() if now is None else now))


class MonthlyBudgetGate:
    """Checks one ledger's month totals against its budget, per the mode."""

    def __init__(self, ledger: CostLedger, mode: GateMode = "off") -> None:
        if mode not in GATE_MODES:
            raise ValueError(f"unknown cost gate mode: {mode!r} (expected one of {GATE_MODES})")
        self.ledger = ledger
        self.mode: GateMode = mode
        self._override_armed = False

    @property
    def budget_usd(self) -> float | None:
        return self.ledger.monthly_budget_usd or None

    def over_budget(self, month: str) -> bool:
        budget = self.budget_usd
        return budget is not None and self.ledger.month_total(month) >= budget

    def override_once(self) -> None:
        """Let the next hard-mode check pass, exactly once."""
        self._override_armed = True

    def check_before_task(self, month: str | None = None) -> None:
        """Refuse a new task in hard mode when the month is over budget.

        Warn and off modes never raise here; warn mode's signal is the
        ledger's alert record, read through :meth:`pending_alert`.
        """
        if self.mode != "hard":
            return
        month = month or current_month()
        if not self.over_budget(month):
            return
        if self._override_armed:
            self._override_armed = False
            return
        budget = self.budget_usd
        assert budget is not None  # over_budget() already established this
        raise CostGateBlocked(month, budget, self.ledger.month_total(month))

    def pending_alert(self, month: str | None = None) -> str | None:
        """The alert message for ``month`` when warn mode should surface one."""
        if self.mode != "warn":
            return None
        month = month or current_month()
        for alert in self.ledger.alerts:
            if alert.month == month:
                return alert.message
        return None

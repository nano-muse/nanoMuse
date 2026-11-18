"""Feeding the ledger from real runs, and the gate hooks the agent calls.

The agent loop already meters every task (``nanomuse.llm.budget``):
when a run ends it holds a snapshot of input tokens, output tokens and
the task's own priced cost.  This module is the bridge from that
snapshot to the cost ledger:

- :class:`TaskCostRecorder` turns one finished task's snapshot into a
  ledger entry.  The entry is priced by the ledger's own price table,
  so the ledger stays the one place prices live; a model missing from
  the table records zero, as the ledger has always done, rather than
  guessing.
- The app installs one recorder at startup (from the ``[cost]``
  settings) with :func:`install`.  The agent loop calls
  :func:`preflight` before a run and :func:`record_finished_task`
  after one, and both are no-ops when nothing is installed, so a
  runtime with no cost settings behaves exactly as before.
- Recording never breaks a run: a ledger failure is swallowed by the
  caller in the agent loop, which treats cost recording as bookkeeping,
  not as part of the task.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from nanomuse.cost.gate import MonthlyBudgetGate, current_month
from nanomuse.cost.ledger import CostLedger, LedgerEntry


@dataclass
class TaskCostRecorder:
    """Records finished tasks into one ledger, under one device's name."""

    ledger: CostLedger
    device_id: str = "this-device"
    gate: MonthlyBudgetGate | None = None

    def record_finished_task(
        self,
        *,
        task_id: str,
        model: str,
        snapshot: dict[str, Any],
        month: str | None = None,
    ) -> LedgerEntry | None:
        """One ledger entry from a task budget snapshot.

        A task that made no metered calls (no tokens in or out) leaves
        no entry: the ledger counts model calls, and a task with none
        cost nothing to record.
        """
        input_tokens = int(snapshot.get("input_tokens") or 0)
        output_tokens = int(snapshot.get("output_tokens") or 0)
        if input_tokens == 0 and output_tokens == 0:
            return None
        return self.ledger.record(
            task_id=task_id or "task",
            device_id=self.device_id,
            model=model or "unknown",
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            month=month or current_month(),
        )


_installed: TaskCostRecorder | None = None


def install(recorder: TaskCostRecorder | None) -> None:
    """Install (or clear, with ``None``) the process-wide recorder."""
    global _installed
    _installed = recorder


def installed() -> TaskCostRecorder | None:
    return _installed


def preflight(month: str | None = None) -> None:
    """The hard gate's check, called before a task starts.

    Raises :class:`~nanomuse.cost.gate.CostGateBlocked` only when a
    recorder with a hard-mode gate is installed and the month is over
    budget.  Otherwise a no-op.
    """
    recorder = _installed
    if recorder is None or recorder.gate is None:
        return
    recorder.gate.check_before_task(month)


def record_finished_task(
    *, task_id: str, model: str, snapshot: dict[str, Any], month: str | None = None
) -> LedgerEntry | None:
    """Record through the installed recorder, if there is one."""
    recorder = _installed
    if recorder is None:
        return None
    return recorder.record_finished_task(
        task_id=task_id, model=model, snapshot=snapshot, month=month
    )

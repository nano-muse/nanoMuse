"""Feeding the ledger from real runs, and the gate hooks the agent calls.

The agent loop already meters every task (``nanomuse.llm.budget``):
when a run ends it holds a snapshot of input tokens, output tokens and
the task's own priced cost.  This module is the bridge from that
snapshot to the cost ledger:

- :class:`TaskCostRecorder` turns one finished task's snapshot into
  ledger entries.  An entry is priced by the ledger's own price
  table, so the ledger stays the one place prices live; a model
  missing from the table records zero, as the ledger has always
  done, rather than guessing.  A snapshot that splits usage by model
  (``by_model``, from the task budget) becomes one entry per model,
  each priced by the model that actually made those calls: a nested
  call on a cheaper model is not priced as the parent task's model.
- The recorder belongs to one app.  The app builds one recorder at
  startup (from the ``[cost]`` settings) and hands it to the agents
  it creates; an agent with its own recorder uses that one and no
  other, so two apps in one process keep separate ledgers and
  separate budget gates.  :func:`install` remains only as a fallback
  for an agent built without a recorder of its own, and the app no
  longer uses it.  Both paths are no-ops when there is no recorder,
  so a runtime with no cost settings behaves exactly as before.
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

    def preflight(self, month: str | None = None) -> None:
        """This recorder's gate check, called before a task starts.

        Raises :class:`~nanomuse.cost.gate.CostGateBlocked` only when
        this recorder's gate is in hard mode and its own ledger is
        over budget.  Otherwise a no-op.
        """
        if self.gate is None:
            return
        self.gate.check_before_task(month)

    def record_finished_task(
        self,
        *,
        task_id: str,
        model: str,
        snapshot: dict[str, Any],
        month: str | None = None,
    ) -> LedgerEntry | None:
        """Ledger entries from a task budget snapshot.

        A snapshot that splits usage by model becomes one entry per
        model, priced by that model; the entry for ``model`` (the
        task's own model) is returned when there is one, otherwise
        the first entry.  Without a split the snapshot's totals
        become the one entry they always were, under ``model``.

        A task that made no metered calls (no tokens in or out) leaves
        no entry: the ledger counts model calls, and a task with none
        cost nothing to record.
        """
        month = month or current_month()
        by_model = snapshot.get("by_model")
        if isinstance(by_model, dict) and by_model:
            entries: list[LedgerEntry] = []
            for actual_model, usage in by_model.items():
                if not isinstance(usage, dict):
                    continue
                input_tokens = int(usage.get("input_tokens") or 0)
                output_tokens = int(usage.get("output_tokens") or 0)
                if input_tokens == 0 and output_tokens == 0:
                    continue
                entries.append(
                    self.ledger.record(
                        task_id=task_id or "task",
                        device_id=self.device_id,
                        model=str(actual_model) or "unknown",
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                        month=month,
                    )
                )
            if not entries:
                return None
            for entry in entries:
                if entry.model == model:
                    return entry
            return entries[0]
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
            month=month,
        )


_installed: TaskCostRecorder | None = None


def install(recorder: TaskCostRecorder | None) -> None:
    """Install (or clear, with ``None``) the fallback recorder.

    Only an agent built without a recorder of its own reads this.
    The app does not install its recorder here: a process-wide slot
    is shared by every app in the process, so the last app built
    would take the others' entries and its gate would answer for
    them.
    """
    global _installed
    _installed = recorder


def installed() -> TaskCostRecorder | None:
    return _installed


def preflight(month: str | None = None) -> None:
    """The fallback recorder's gate check, called before a task starts.

    Raises :class:`~nanomuse.cost.gate.CostGateBlocked` only when a
    recorder with a hard-mode gate is installed and the month is over
    budget.  Otherwise a no-op.
    """
    recorder = _installed
    if recorder is None:
        return
    recorder.preflight(month)


def record_finished_task(
    *, task_id: str, model: str, snapshot: dict[str, Any], month: str | None = None
) -> LedgerEntry | None:
    """Record through the fallback recorder, if there is one."""
    recorder = _installed
    if recorder is None:
        return None
    return recorder.record_finished_task(
        task_id=task_id, model=model, snapshot=snapshot, month=month
    )

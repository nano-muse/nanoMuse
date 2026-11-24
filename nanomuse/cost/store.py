"""Persistence for the cost ledger: one JSON object per entry, appended.

The ledger itself (``nanomuse/cost/ledger.py``) is in-memory.  A monthly
budget only means something across restarts, so the real wiring keeps
every entry in a JSONL file under the data directory: append on record,
replay on open.  A line that does not parse is skipped and counted, the
same posture the audit log takes with lines written before signing: a
damaged tail never makes the whole ledger unreadable.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from nanomuse.cost.ledger import CostLedger, LedgerEntry, PriceEntry, field_row


class PersistentCostLedger(CostLedger):
    """A cost ledger whose entries survive a restart.

    Opens the JSONL file at ``path`` (created on first record), replays
    every stored row into memory, and appends each new entry as it is
    recorded.  Budget alerts are recomputed during replay, so a month
    that crossed its budget before the restart still shows its alert.
    """

    def __init__(
        self,
        path: Path,
        prices: dict[str, PriceEntry] | None = None,
        monthly_budget_usd: float | None = None,
    ) -> None:
        super().__init__(prices=prices, monthly_budget_usd=monthly_budget_usd)
        self.path = Path(path)
        self.skipped_lines = 0
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        for line in self.path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row: dict[str, Any] = json.loads(line)
                entry = LedgerEntry(
                    task_id=str(row["task_id"]),
                    device_id=str(row["device_id"]),
                    model=str(row["model"]),
                    input_tokens=int(row["input_tokens"]),
                    output_tokens=int(row["output_tokens"]),
                    cost_usd=float(row["cost_usd"]),
                    month=str(row["month"]),
                )
            except (ValueError, KeyError, TypeError):
                self.skipped_lines += 1
                continue
            self.entries.append(entry)
            # Recompute the alert state for this month without alerting twice.
            self._check_budget(entry.month)

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
        entry = super().record(
            task_id=task_id,
            device_id=device_id,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            month=month,
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(field_row(entry), ensure_ascii=False) + "\n")
        return entry

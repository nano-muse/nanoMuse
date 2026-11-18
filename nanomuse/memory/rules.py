"""Owner-reviewed text exclusions, shared by every memory retrieval path."""

from __future__ import annotations

import json
import sqlite3
from typing import Any


def contains_text(value: Any, term: str) -> bool:
    """Match actual strings, including quoted text, rather than JSON escaping or field names."""
    if isinstance(value, str):
        return term.casefold() in value.casefold()
    if isinstance(value, dict):
        return any(contains_text(item, term) for item in value.values())
    if isinstance(value, (list, tuple)):
        return any(contains_text(item, term) for item in value)
    return False


class MemoryRules:
    def __init__(self, db: sqlite3.Connection, owner: str, space: str):
        self.db, self.owner, self.space = db, owner, space
        db.execute(
            "CREATE TABLE IF NOT EXISTS memory_rules (owner TEXT, space TEXT, term TEXT, "
            "replacement TEXT NOT NULL, PRIMARY KEY(owner, space, term))"
        )
        if "fact_id" not in {row[1] for row in db.execute("PRAGMA table_info(memory_rules)")}:
            db.execute("ALTER TABLE memory_rules ADD COLUMN fact_id TEXT NOT NULL DEFAULT ''")
        db.execute(
            "CREATE TABLE IF NOT EXISTS memory_operations (owner TEXT, space TEXT, id TEXT, report TEXT, PRIMARY KEY(owner, space, id))"
        )
        db.commit()

    def items(self) -> list[dict[str, str]]:
        return [
            {"term": row[0], "replacement": row[1], **({"fact_id": row[2]} if row[2] else {})}
            for row in self.db.execute(
                "SELECT term, replacement, fact_id FROM memory_rules WHERE owner = ? AND space = ? "
                "ORDER BY term",
                (self.owner, self.space),
            )
        ]

    def allows(self, text: Any) -> bool:
        return not any(contains_text(text, item["term"]) for item in self.items())

    def add(self, term: str, replacement: str = "", fact_id: str = "") -> None:
        with self.db:
            self.db.execute(
                "INSERT OR REPLACE INTO memory_rules VALUES (?, ?, ?, ?, ?)",
                (self.owner, self.space, term.casefold(), replacement, fact_id),
            )

    def remove(self, term: str) -> None:
        with self.db:
            self.db.execute(
                "DELETE FROM memory_rules WHERE owner = ? AND space = ? AND term = ?",
                (self.owner, self.space, term.casefold()),
            )

    def replace_all(self, items: list[dict[str, Any]]) -> None:
        with self.db:
            self.db.execute(
                "DELETE FROM memory_rules WHERE owner = ? AND space = ?", (self.owner, self.space)
            )
            self.db.executemany(
                "INSERT INTO memory_rules VALUES (?, ?, ?, ?, ?)",
                [
                    (
                        self.owner,
                        self.space,
                        item["term"].casefold(),
                        item.get("replacement", ""),
                        item.get("fact_id", ""),
                    )
                    for item in items
                ],
            )

    def save_report(self, report: dict[str, Any]) -> None:
        with self.db:
            self.db.execute(
                "INSERT OR REPLACE INTO memory_operations VALUES (?, ?, ?, ?)",
                (self.owner, self.space, report["id"], json.dumps(report)),
            )
            self.db.execute(
                "DELETE FROM memory_operations WHERE owner = ? AND space = ? AND id NOT IN (SELECT id FROM memory_operations WHERE owner = ? AND space = ? ORDER BY rowid DESC LIMIT 20)",
                (self.owner, self.space, self.owner, self.space),
            )

    def last_report(self) -> dict[str, Any] | None:
        row = self.db.execute(
            "SELECT report FROM memory_operations WHERE owner = ? AND space = ? ORDER BY rowid DESC LIMIT 1",
            (self.owner, self.space),
        ).fetchone()
        return json.loads(row[0]) if row else None

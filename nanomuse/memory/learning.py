"""Durable personal-profile learning jobs, independent of a chat's lifetime."""

from __future__ import annotations

import hashlib
import json
import time
from typing import Any

from nanomuse.memory.personal import PersonalMemory
from nanomuse.schema import RiskLevel, ToolResult
from nanomuse.tools.base import BaseTool


class LearningQueue:
    def __init__(self, store: PersonalMemory):
        self.store = store
        self.db = store.db
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS learning_jobs (id TEXT PRIMARY KEY, namespace TEXT, payload TEXT, generation INTEGER, state TEXT DEFAULT 'pending', attempts INTEGER DEFAULT 0, due REAL DEFAULT 0)"
        )
        self.db.commit()

    def enqueue(self, inputs: list[str], turn: str, conversation: str) -> None:
        inputs = [text for text in inputs if self.store.text_allowed(text)]
        if not inputs:
            return
        namespace = self.store.namespace
        job = hashlib.sha256((namespace + turn).encode()).hexdigest()
        if self.db.execute("SELECT 1 FROM learning_jobs WHERE id = ?", (job,)).fetchone():
            return
        inputs = [text[:8000] for text in inputs[-8:]]
        while sum(map(len, inputs)) > 32000:
            inputs.pop(0)
        count = self.db.execute(
            "SELECT count(*) FROM learning_jobs WHERE namespace = ? AND state = 'pending'",
            (namespace,),
        ).fetchone()[0]
        if count >= 1000:
            raise ValueError("Personal learning queue is full")
        with self.db:
            self.db.execute(
                "INSERT OR IGNORE INTO learning_jobs(id, namespace, payload, generation) VALUES (?, ?, ?, ?)",
                (
                    job,
                    namespace,
                    json.dumps(
                        {"inputs": inputs, "turn": turn, "conversation": conversation},
                        ensure_ascii=False,
                    ),
                    self.store.generation(),
                ),
            )

    def next(self) -> tuple[str, dict[str, Any], int] | None:
        row = self.db.execute(
            "SELECT id, payload, generation FROM learning_jobs WHERE namespace = ? AND state = 'pending' AND due <= ? ORDER BY rowid LIMIT 1",
            (self.store.namespace, time.time()),
        ).fetchone()
        return (row[0], json.loads(row[1]), row[2]) if row else None

    def finish(self, job: str, success: bool) -> None:
        with self.db:
            if success:
                self.db.execute(
                    "DELETE FROM learning_jobs WHERE id = ? AND namespace = ?",
                    (job, self.store.namespace),
                )
            else:
                self.db.execute(
                    "UPDATE learning_jobs SET attempts = attempts + 1, state = CASE WHEN attempts >= 4 THEN 'failed' ELSE 'pending' END, due = ? WHERE id = ? AND namespace = ?",
                    (time.time() + 30, job, self.store.namespace),
                )

    def status(self) -> dict[str, int]:
        counts = dict(
            self.db.execute(
                "SELECT state, count(*) FROM learning_jobs WHERE namespace = ? GROUP BY state",
                (self.store.namespace,),
            )
        )
        return {"pending": counts.get("pending", 0), "failed": counts.get("failed", 0)}

    def retry(self) -> None:
        with self.db:
            self.db.execute(
                "UPDATE learning_jobs SET state = 'pending', attempts = 0, due = 0 WHERE namespace = ?",
                (self.store.namespace,),
            )


class PersonalEnqueue(BaseTool):
    name: str = "personal_memory_enqueue"
    description: str = "Queue grounded user evidence for later personal-profile learning"
    risk: RiskLevel = RiskLevel.MODERATE
    reads_private_data: bool = True
    queue: LearningQueue

    async def execute(
        self, inputs: list[str] | None = None, turn: str = "", conversation: str = "", **_: Any
    ) -> ToolResult:
        if inputs and turn:
            try:
                self.queue.enqueue(inputs, turn, conversation)
            except ValueError:
                return ToolResult.fail("Personal learning queue is full")
        return ToolResult(output="Personal learning queued")

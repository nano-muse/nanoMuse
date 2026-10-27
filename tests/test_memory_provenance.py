"""Memory provenance (phase 1): which model wrote a line, and how sure it was.

An old database without the new columns upgrades in place; a line's provenance
survives merges, drops and restores; and ``resolve_conflict`` picks a winner by
the documented rules instead of silently merging two lines that disagree.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from nanomuse.memory.store import MemoryItem, MemoryStore, resolve_conflict


def _item(**overrides: object) -> MemoryItem:
    base: dict[str, object] = {
        "id": "m_1",
        "content": "lives in Berlin",
        "category": "fact",
        "created_at": "2026-01-01T00:00:00+00:00",
        "source": "agent",
    }
    base.update(overrides)
    return MemoryItem(**base)  # type: ignore[arg-type]


def test_an_old_database_upgrades_in_place(tmp_path: Path) -> None:
    path = tmp_path / "mem.db"
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE memories (id TEXT PRIMARY KEY, content TEXT NOT NULL, "
        "category TEXT NOT NULL DEFAULT 'general', created_at TEXT NOT NULL, "
        "source TEXT NOT NULL DEFAULT 'agent', updated_at TEXT NOT NULL DEFAULT '')"
    )
    conn.execute(
        "INSERT INTO memories VALUES ('m_old', 'lives in Berlin', 'fact', "
        "'2026-01-01T00:00:00+00:00', 'agent', '')"
    )
    conn.commit()
    conn.close()
    store = MemoryStore(path)
    item = store.get("m_old")
    assert item is not None
    assert item.content == "lives in Berlin"
    assert item.model == "" and item.confidence is None
    columns = {r[1] for r in store._conn.execute("PRAGMA table_info(memories)")}
    assert {"model", "confidence"} <= columns
    store.close()


def test_provenance_round_trips(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "mem.db")
    item = store.add("lives in Berlin", model="qwen3.6-27b", confidence=0.8)
    assert item.model == "qwen3.6-27b" and item.confidence == 0.8
    again = store.get(item.id)
    assert again is not None and again.model == "qwen3.6-27b" and again.confidence == 0.8
    store.close()
    reopened = MemoryStore(tmp_path / "mem.db")
    found = reopened.get(item.id)
    assert found is not None and found.model == "qwen3.6-27b" and found.confidence == 0.8
    reopened.close()


def test_confidence_out_of_range_is_refused(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "mem.db")
    with pytest.raises(ValueError, match="between 0.0 and 1.0"):
        store.add("lives in Berlin", confidence=1.5)
    item = store.add("lives in Berlin")
    with pytest.raises(ValueError, match="between 0.0 and 1.0"):
        store.update(item.id, "lives in Berlin", confidence=-0.1)
    store.close()


def test_update_keeps_provenance_unless_told_otherwise(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "mem.db")
    item = store.add("lives in Berlin", model="qwen3.6-27b", confidence=0.8)
    updated = store.update(item.id, "lives in Munich")
    assert updated is not None
    assert updated.model == "qwen3.6-27b" and updated.confidence == 0.8
    rewritten = store.update(item.id, "lives in Hamburg", model="gpt-6", confidence=0.9)
    assert rewritten is not None
    assert rewritten.model == "gpt-6" and rewritten.confidence == 0.9
    store.close()


def test_a_merge_inherits_provenance(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "mem.db")
    first = store.add("likes window seats", model="qwen3.6-27b", confidence=0.7)
    second = store.add("prefers a window seat on flights", model="gpt-6", confidence=0.6)
    change = store.replace(
        [first.id, second.id], "likes window seats, especially on flights", reason="merge"
    )
    assert change is not None and change.after is not None
    assert change.after.model == "qwen3.6-27b" and change.after.confidence == 0.7
    store.close()


def test_a_restore_keeps_provenance(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "mem.db")
    item = store.add("lives in Berlin", model="qwen3.6-27b", confidence=0.8)
    change = store.drop(item.id, reason="stale")
    assert change is not None and store.get(item.id) is None
    restored = store.restore(change.id)
    assert restored is not None
    back = store.get(item.id)
    assert back is not None
    assert back.model == "qwen3.6-27b" and back.confidence == 0.8
    again = store.restore(change.id)
    assert again is not None and again.restored
    assert store.count() == 1
    store.close()


def test_a_forget_can_be_undone_with_provenance(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "mem.db")
    item = store.add("lives in Berlin", model="qwen3.6-27b", confidence=0.8)
    assert store.forget(item.id)
    change = store.history()[0]
    store.restore(change.id)
    back = store.get(item.id)
    assert back is not None and back.model == "qwen3.6-27b" and back.confidence == 0.8
    store.close()


def test_an_old_log_entry_without_provenance_restores(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "mem.db")
    before = {
        "id": "m_old",
        "content": "lives in Berlin",
        "category": "fact",
        "created_at": "2026-01-01T00:00:00+00:00",
        "source": "agent",
        "updated_at": "",
    }
    store._conn.execute(
        "INSERT INTO memory_log (id, at, action, before, after, reason, restored) "
        "VALUES ('c_1', '2026-01-02T00:00:00+00:00', 'drop', ?, NULL, '', 0)",
        (json.dumps([before]),),
    )
    store._conn.commit()
    restored = store.restore("c_1")
    assert restored is not None
    back = store.get("m_old")
    assert back is not None and back.model == "" and back.confidence is None
    store.close()


def test_a_line_the_person_wrote_wins() -> None:
    agent = _item(source="agent", updated_at="2026-06-01T00:00:00+00:00", confidence=0.95)
    person = _item(id="m_2", source="user", updated_at="2026-01-01T00:00:00+00:00")
    winner, reason = resolve_conflict(agent, person)
    assert winner is person and reason == "user-overrides"


def test_an_explicit_correction_wins() -> None:
    old = _item(content="lives in Berlin", updated_at="2026-06-01T00:00:00+00:00")
    new = _item(
        id="m_2",
        content="no longer lives in Berlin",
        updated_at="2026-01-01T00:00:00+00:00",
    )
    winner, reason = resolve_conflict(old, new)
    assert winner is new and reason == "negation"


def test_a_newer_fact_wins_over_an_older_one() -> None:
    old = _item(updated_at="2026-01-01T00:00:00+00:00", confidence=0.9)
    new = _item(id="m_2", updated_at="2026-06-01T00:00:00+00:00", confidence=0.5)
    winner, reason = resolve_conflict(old, new)
    assert winner is new and reason == "newer"


def test_a_higher_confidence_wins_when_nothing_else_separates_them() -> None:
    low = _item(confidence=0.4)
    high = _item(id="m_2", confidence=0.9)
    winner, reason = resolve_conflict(low, high)
    assert winner is high and reason == "higher-confidence"


def test_nothing_separating_them_keeps_both() -> None:
    first = _item(confidence=0.7)
    second = _item(id="m_2", confidence=0.7)
    winner, reason = resolve_conflict(first, second)
    assert winner is first and reason == "keep-both"

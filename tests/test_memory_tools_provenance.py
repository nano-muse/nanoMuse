"""The remember tool records who wrote a memory; recall shows it; conflicts defer
to the line that wins on principle instead of silently rewriting it."""

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from nanomuse.config import LLMSettings, SentinelSettings
from nanomuse.llm.base import BaseLLM, DeltaCallback
from nanomuse.memory import MemoryStore
from nanomuse.schema import LLMResponse, Message
from nanomuse.sentinel import AuditLog, Sentinel
from nanomuse.tools import memory_tools
from nanomuse.tools.memory_tools import Recall, Remember
from nanomuse.ui import HeadlessUI

_PINNED = "2026-06-01T00:00:00+00:00"


class _FixedDateTime(datetime):
    """The candidate's clock, pinned so a conflict test does not depend on
    whether the run crosses a second boundary."""

    @classmethod
    def now(cls, tz: Any = None) -> datetime:
        return datetime(2026, 6, 1, tzinfo=UTC)


def _pin_twin_time(store: MemoryStore, item_id: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """Give the stored twin and the candidate the same effective time, so the
    conflict rule is decided by the step under test, not by the clock."""
    store._conn.execute(
        "UPDATE memories SET created_at = ?, updated_at = ? WHERE id = ?",
        (_PINNED, _PINNED, item_id),
    )
    store._conn.commit()
    monkeypatch.setattr(memory_tools, "datetime", _FixedDateTime)


class _RunLLM(BaseLLM):
    """A stand-in for the client of one run: it runs as ``model``, whatever the
    configured default says."""

    name = "stub"

    def __init__(self, model: str):
        self.settings = LLMSettings(model=model)

    async def ask(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str = "auto",
        on_delta: DeltaCallback | None = None,
        on_reasoning_delta: DeltaCallback | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        return LLMResponse(content="")


@pytest.mark.asyncio
async def test_remember_records_model_and_confidence(tmp_path: Path):
    store = MemoryStore(tmp_path / "m.db")
    tool = Remember(store=store, model="qwen3.6-27b")
    out = await tool.execute(content="Prefers window seats", confidence=0.9)
    assert out.output.startswith("Remembered")
    (item,) = store.all()
    assert item.model == "qwen3.6-27b" and item.confidence == 0.9
    recall = await Recall(store=store).execute(query="seats")
    assert "written by qwen3.6-27b" in recall.output
    assert "confidence 0.90" in recall.output


@pytest.mark.asyncio
async def test_remember_without_model_leaves_provenance_unknown(tmp_path: Path):
    store = MemoryStore(tmp_path / "m.db")
    await Remember(store=store).execute(content="Prefers window seats")
    (item,) = store.all()
    assert item.model == "" and item.confidence is None
    recall = await Recall(store=store).execute(query="seats")
    assert "written by" not in recall.output


@pytest.mark.asyncio
async def test_remember_replace_updates_provenance(tmp_path: Path):
    store = MemoryStore(tmp_path / "m.db")
    old = store.add("Lives in Shanghai", category="profile", model="old-model")
    out = await Remember(store=store, model="new-model").execute(
        content="Lives in Beijing", replaces=old.id, confidence=0.8
    )
    assert out.output.startswith("Updated")
    (item,) = store.all()
    assert item.model == "new-model" and item.confidence == 0.8


@pytest.mark.asyncio
async def test_remember_keeps_user_written_twin(tmp_path: Path):
    store = MemoryStore(tmp_path / "m.db")
    store.add(
        "Partner is vegetarian and does not eat fish",
        category="people",
        source="user",
        model="",
    )
    out = await Remember(store=store, model="qwen3.6-27b").execute(
        content="Partner is vegetarian, does not eat fish", category="people"
    )
    assert out.output.startswith("Kept") and "user-overrides" in out.output
    assert store.count() == 1 and not store.history()
    (item,) = store.all()
    assert item.content == "Partner is vegetarian and does not eat fish"


@pytest.mark.asyncio
async def test_remember_replaces_agent_twin_with_new_provenance(tmp_path: Path):
    store = MemoryStore(tmp_path / "m.db")
    store.add(
        "Partner is vegetarian and does not eat fish",
        category="people",
        model="old-model",
    )
    out = await Remember(store=store, model="new-model").execute(
        content="Partner is vegetarian, does not eat fish",
        category="people",
        confidence=0.7,
    )
    assert out.output.startswith("Updated")
    (item,) = store.all()
    assert item.model == "new-model" and item.confidence == 0.7


@pytest.mark.asyncio
async def test_remember_keeps_explicit_correction_twin(tmp_path: Path):
    store = MemoryStore(tmp_path / "m.db")
    store.add("Works at Acme in the Shanghai office every day, no longer")
    out = await Remember(store=store, model="qwen3.6-27b").execute(
        content="Works at Acme in the Shanghai office every day"
    )
    assert out.output.startswith("Kept") and "negation" in out.output
    assert store.count() == 1 and not store.history()


@pytest.mark.asyncio
async def test_remember_records_the_per_run_model_not_the_configured_default(tmp_path: Path):
    # A run on a one-turn override (the worker swaps the agent's client for the
    # turn; the sentinel task carries that client as the execution model): the
    # line must name the model that actually ran, not the configured default
    # the tool was built with.
    store = MemoryStore(tmp_path / "m.db")
    gate = Sentinel(
        SentinelSettings(),
        AuditLog(tmp_path / "audit.jsonl"),
        HeadlessUI(),
        persistent_approvals_file=tmp_path / "approvals.json",
    )
    tool = Remember(store=store, model="configured-default")
    token = gate.begin_task("test", execution_llm=_RunLLM("per-run-override"))
    try:
        out = await tool.execute(content="Prefers window seats", confidence=0.9)
    finally:
        gate.end_task(token)
    assert out.output.startswith("Remembered")
    (item,) = store.all()
    assert item.model == "per-run-override" and item.confidence == 0.9


@pytest.mark.asyncio
async def test_remember_rewrite_without_confidence_keeps_it_unknown(tmp_path: Path):
    store = MemoryStore(tmp_path / "m.db")
    old = store.add("Lives in Shanghai", model="old-model", confidence=0.9)
    out = await Remember(store=store, model="new-model").execute(
        content="Lives in Beijing", replaces=old.id
    )
    assert out.output.startswith("Updated")
    (item,) = store.all()
    assert item.model == "new-model"
    # the new writer gave no confidence: unknown stays unknown, the replaced
    # line's 0.9 is not inherited
    assert item.confidence is None


@pytest.mark.asyncio
async def test_remember_keeps_a_twin_that_wins_on_confidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    store = MemoryStore(tmp_path / "m.db")
    twin = store.add(
        "Partner is vegetarian and does not eat fish",
        category="people",
        model="careful-model",
        confidence=0.95,
    )
    # same effective time as the candidate, so the stated rule reaches the
    # confidence step and the existing line wins it
    _pin_twin_time(store, twin.id, monkeypatch)
    out = await Remember(store=store, model="hasty-model").execute(
        content="Partner is vegetarian, does not eat fish", category="people", confidence=0.3
    )
    assert out.output.startswith("Kept") and "higher-confidence" in out.output
    (item,) = store.all()
    assert item.id == twin.id and item.model == "careful-model" and item.confidence == 0.95
    assert not store.history()


@pytest.mark.asyncio
async def test_remember_keeps_both_when_nothing_separates_them(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    store = MemoryStore(tmp_path / "m.db")
    twin = store.add(
        "Partner is vegetarian and does not eat fish",
        category="people",
        model="first-model",
        confidence=0.7,
    )
    _pin_twin_time(store, twin.id, monkeypatch)
    out = await Remember(store=store, model="second-model").execute(
        content="Partner is vegetarian, does not eat fish", category="people", confidence=0.7
    )
    # resolve_conflict says keep-both: the new wording is stored as its own line
    # instead of silently replacing the existing one
    assert out.output.startswith("Remembered")
    assert store.count() == 2 and not store.history()
    models = {item.model for item in store.all()}
    assert models == {"first-model", "second-model"}


@pytest.mark.asyncio
async def test_remember_rejects_out_of_range_confidence(tmp_path: Path):
    store = MemoryStore(tmp_path / "m.db")
    out = await Remember(store=store).execute(content="Prefers window seats", confidence=1.5)
    assert out.error
    assert store.count() == 0

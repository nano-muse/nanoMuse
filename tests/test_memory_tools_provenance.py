"""The remember tool records who wrote a memory; recall shows it; conflicts defer
to the line that wins on principle instead of silently rewriting it."""

from pathlib import Path

import pytest

from nanomuse.memory import MemoryStore
from nanomuse.tools.memory_tools import Recall, Remember


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
async def test_remember_rejects_out_of_range_confidence(tmp_path: Path):
    store = MemoryStore(tmp_path / "m.db")
    out = await Remember(store=store).execute(content="Prefers window seats", confidence=1.5)
    assert out.error
    assert store.count() == 0

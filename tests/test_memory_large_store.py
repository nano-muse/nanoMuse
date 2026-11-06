from __future__ import annotations

import sqlite3
from pathlib import Path

from nanomuse.memory import MemoryStore, similarity
from nanomuse.memory.embeddings import MemoryIndex


def large_store(tmp_path: Path) -> tuple[MemoryStore, str]:
    store = MemoryStore(tmp_path / "memory.db")
    old = store.add("The landlord is Bob Li; 房东喜欢茶")
    store._conn.execute("UPDATE memories SET created_at='2000-01-01' WHERE id=?", (old.id,))
    store._conn.executemany(
        "INSERT INTO memories (id,content,created_at) VALUES (?,?,?)",
        [(f"filler-{i}", f"Unrelated record {i}", "2026-01-01") for i in range(1500)],
    )
    store._conn.commit()
    return store, old.id


def test_old_english_and_chinese_memories_remain_searchable(tmp_path: Path):
    store, old = large_store(tmp_path)
    assert len(store.all()) == 1000
    assert len(store.all(limit=None)) == 1501
    for query in ("landlord", "房东"):
        assert store.search(query, limit=1)[0].id == old
        assert old in {m.id for m in store.relevant(query, limit=2)}
    assert store.search("landlord", limit=0) == []
    assert store.relevant("landlord", limit=0) == []


def test_search_cache_tracks_edits_forgets_restores_and_external_writes(tmp_path: Path):
    store, old = large_store(tmp_path)
    assert store.search("landlord")[0].id == old
    store.update(old, "Prefers jasmine tea")
    assert not store.search("landlord")
    assert store.search("jasmine")[0].id == old
    store.forget(old)
    assert not store.search("jasmine")
    store.restore(store.history()[0].id)
    assert store.search("jasmine")[0].id == old
    with sqlite3.connect(store.path) as external:
        external.execute("UPDATE memories SET content='Prefers oolong tea' WHERE id=?", (old,))
    assert not store.search("jasmine")
    found = store.search("oolong")[0]
    found.content = "caller changed its own copy"
    assert store.search("oolong")[0].content == "Prefers oolong tea"


def test_similar_reads_the_whole_store_through_the_search_index(tmp_path: Path):
    store, old = large_store(tmp_path)
    (score, found) = store.similar("房东喜欢茶 Bob Li landlord", threshold=0.3, limit=1)[0]
    assert found.id == old
    assert score == similarity("房东喜欢茶 Bob Li landlord", found.content)
    # the fillers differ in a one-character word only, which the tokens drop: all alike
    assert store.similar("Unrelated record 7", threshold=0.99, limit=1)[0][0] == 1.0
    assert store.similar("", limit=1) == [] and store.similar("landlord", limit=0) == []
    found.content = "caller changed its own copy"
    assert store.similar("房东喜欢茶", threshold=0.3, limit=1)[0][1].content != found.content


class LocalEmbedder:
    model = "fixture"
    usable = True

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [[1.0, 0.0] if ("landlord" in t or "房东" in t) else [0.0, 1.0] for t in texts]


async def test_semantic_recall_keeps_old_vectors_and_reuses_them(tmp_path: Path):
    store, old = large_store(tmp_path)
    index = MemoryIndex(store, LocalEmbedder())  # type: ignore[arg-type]
    assert (await index.search("房东", limit=1))[0].id == old
    assert len(store.vectors("fixture")) == 1501
    store.add("One more unrelated memory")
    assert (await index.closest("房东", limit=1))[0][1].id == old
    assert old in store.vectors("fixture")

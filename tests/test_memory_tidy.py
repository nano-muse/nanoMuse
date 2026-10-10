"""Tidying memory: the model proposes, the code checks, every change can be undone."""

from __future__ import annotations

from pathlib import Path

import pytest

from nanomuse.llm import MockLLM
from nanomuse.memory import MemoryStore, tidy
from nanomuse.memory.consolidate import plan
from nanomuse.schema import LLMResponse
from nanomuse.tools.memory_tools import Remember


def seeded(tmp_path: Path) -> MemoryStore:
    store = MemoryStore(tmp_path / "m.db")
    store.add("Prefers window seats", "preference")
    store.add("Likes a window seat on flights", "preference")
    store.add("Lives in Shanghai", "profile")
    store.add("Moved to Beijing in March 2026", "profile")
    store.add("Asked for the weather in Kyoto today", "general")
    store.add("Partner is vegetarian", "people", source="user")
    for i in range(6):
        store.add(f"Project {i}: uses Python and Postgres", "project")
    return store


def test_plan_checks_every_proposal(tmp_path: Path):
    store = seeded(tmp_path)
    items = store.all()
    ids = {m.content: m.id for m in items}
    reply = f"""```json
[
 {{"op": "merge", "ids": ["{ids["Prefers window seats"]}", "{ids["Likes a window seat on flights"]}"], "content": "Prefers window seats on flights", "category": "preference"}},
 {{"op": "merge", "ids": ["{ids["Lives in Shanghai"]}", "{ids["Moved to Beijing in March 2026"]}"], "content": "Lives in Beijing, moved from Shanghai in March 2026", "category": "profile"}},
 {{"op": "merge", "ids": ["{ids["Project 0: uses Python and Postgres"]}", "{ids["Project 1: uses Python and Postgres"]}"], "content": "Projects 0 and 1 use Python, Postgres and Kubernetes"}},
 {{"op": "drop", "id": "{ids["Asked for the weather in Kyoto today"]}", "reason": "one-off request"}},
 {{"op": "drop", "id": "{ids["Partner is vegetarian"]}", "reason": "duplicate"}},
 {{"op": "drop", "id": "m_nope"}},
 {{"op": "rewrite", "id": "{ids["Lives in Shanghai"]}", "content": "x"}}
]
```"""
    ops, skipped = plan(items, reply)
    assert [o["op"] for o in ops] == ["merge", "merge", "drop"]
    assert ops[1]["content"] == "Lives in Beijing, moved from Shanghai in March 2026"
    # refused: a merge that invents "Kubernetes", a drop of a line the user wrote, an unknown id, an unknown op
    assert len(skipped) == 4
    assert any("adds words" in s for s in skipped)
    assert any("the user wrote it" in s for s in skipped)
    assert any("unknown id" in s for s in skipped)
    assert any("unknown op" in s for s in skipped)


def test_plan_stays_within_the_budget_and_keeps_cjk_honest(tmp_path: Path):
    store = MemoryStore(tmp_path / "m.db")
    for i in range(10):
        store.add(f"line {i}")
    store.add("住在上海", "profile")
    store.add("2026年搬到了北京", "profile")
    items = store.all()
    ids = {m.content: m.id for m in items}
    ok = plan(
        items,
        f'[{{"op":"merge","ids":["{ids["住在上海"]}","{ids["2026年搬到了北京"]}"],"content":"住在北京，2026年从上海搬来"}}]',
    )[0]
    assert len(ok) == 1
    bad = plan(
        items,
        f'[{{"op":"merge","ids":["{ids["住在上海"]}","{ids["2026年搬到了北京"]}"],"content":"住在北京，在腾讯工作"}}]',
    )
    assert bad[0] == [] and "adds words" in bad[1][0]
    # 12 lines → a pass takes out four at most: the fifth drop waits for the next one
    drops = "".join(f'{{"op":"drop","id":"{ids[f"line {i}"]}","reason":"x"}},' for i in range(5))
    ops, skipped = plan(items, f"[{drops[:-1]}]")
    assert len(ops) == 4 and "enough for one pass" in skipped[0]


@pytest.mark.asyncio
async def test_tidy_applies_logs_and_dry_runs(tmp_path: Path):
    store = seeded(tmp_path)
    ids = {m.content: m.id for m in store.all()}
    proposal = (
        f'[{{"op": "merge", "ids": ["{ids["Prefers window seats"]}", "{ids["Likes a window seat on flights"]}"],'
        f' "content": "Prefers window seats on flights"}},'
        f' {{"op": "drop", "id": "{ids["Asked for the weather in Kyoto today"]}", "reason": "one-off"}}]'
    )
    llm = MockLLM([LLMResponse(content=proposal), LLMResponse(content=proposal)])

    planned = await tidy(store, llm, dry_run=True)
    assert planned.changed == 0 and len(planned.planned) == 2 and store.count() == 12
    assert planned.lines()[0].startswith("Would merge")
    assert "by the user" in llm.calls[0]["messages"][0].content  # the model sees who wrote what

    report = await tidy(store, llm)
    assert report.changed == 2 and store.count() == 10
    assert store.get(ids["Asked for the weather in Kyoto today"]) is None
    merged = next(m for m in store.all() if m.content == "Prefers window seats on flights")
    assert merged.category == "preference"
    assert [c.action for c in store.history()] == ["drop", "merge"]
    lines = report.lines()
    assert lines[0].startswith("Merged") and lines[1].startswith("Dropped")

    # nothing proposed → nothing changed, nothing logged
    llm.script.append(LLMResponse(content="[]"))
    assert (await tidy(store, llm)).changed == 0 and len(store.history()) == 2


@pytest.mark.asyncio
async def test_remember_updates_instead_of_duplicating(tmp_path: Path):
    store = MemoryStore(tmp_path / "m.db")
    tool = Remember(store=store)
    first = await tool.execute(content="Lives in Shanghai", category="profile")
    assert first.output.startswith("Remembered")
    old_id = store.all()[0].id

    # a changed fact: the model names the line it supersedes
    out = await tool.execute(content="Lives in Beijing", category="profile", replaces=old_id)
    assert out.output.startswith("Updated") and store.count() == 1
    assert store.all()[0].content == "Lives in Beijing" and store.history()[0].action == "rewrite"
    assert (await tool.execute(content="x", replaces="m_nope")).error

    # the same fact in other words replaces the line; a related fact is kept and pointed out
    await tool.execute(content="Partner is vegetarian and does not eat fish", category="people")
    out = await tool.execute(content="Partner is vegetarian, does not eat fish", category="people")
    assert out.output.startswith("Updated") and store.count() == 2
    out = await tool.execute(content="Partner is vegetarian, eats fish now", category="people")
    assert out.output.startswith("Remembered") and store.count() == 3
    assert "Similar memories" in out.output and "replaces=" in out.output
    # an exact repeat is the existing line, no log entry
    n = len(store.history())
    out = await tool.execute(content="Partner is vegetarian, eats fish now", category="people")
    assert out.output.startswith("Remembered") and store.count() == 3 and len(store.history()) == n


def test_tidy_summary_follows_the_reply_language():
    from nanomuse.memory import MemoryChange, MemoryItem, TidyReport
    from nanomuse.server.service import _tidy_summary

    def item(content: str) -> MemoryItem:
        return MemoryItem(
            id="m_1", content=content, category="profile", created_at="", source="agent"
        )

    zh_report = TidyReport(
        merged=[
            MemoryChange(
                id="c1",
                at="",
                action="merge",
                before=[item("住在上海"), item("搬到了北京")],
                after=item("从上海搬到了北京"),
            )
        ],
        dropped=[
            MemoryChange(
                id="c2", at="", action="drop", before=[item("问过今天的天气")], reason="一次性请求"
            )
        ],
    )
    zh = _tidy_summary(zh_report, "auto")
    assert zh.startswith("我整理了一下记忆，合并了 1 条，删除了 1 条：")
    assert "- 合并 “住在上海” + “搬到了北京” → “从上海搬到了北京”" in zh
    assert "- 删除 “问过今天的天气” (一次性请求)" in zh and "最近的改动" in zh

    en_report = TidyReport(
        dropped=[
            MemoryChange(id="c3", at="", action="drop", before=[item("Asked for the weather")])
        ]
    )
    en = _tidy_summary(en_report, "auto")
    assert (
        en.startswith("I tidied your memory: dropped 1:")
        and "Dropped “Asked for the weather”" in en
    )
    # a fixed reply language wins over the script of the memories
    assert _tidy_summary(en_report, "中文").startswith("我整理了一下记忆，删除了 1 条：")
    assert _tidy_summary(zh_report, "English").startswith(
        "I tidied your memory: merged 1 line and dropped 1:"
    )


def test_the_guard_judges_every_script_and_refuses_what_it_cannot_judge():
    """#270: the tokenizer was ASCII only, so a Russian merge had nothing to compare
    against and the guard approved anything, invented facts included."""
    from nanomuse.memory import MemoryItem
    from nanomuse.memory.consolidate import _no_new_words

    def item(content: str) -> MemoryItem:
        return MemoryItem(id="m", content=content, category="fact", created_at="", source="user")

    ru = [item("Живёт в Шанхае"), item("Переехал в Пекин в марте")]
    # invented facts, in Russian: refused
    assert not _no_new_words("Владеет тремя кошками и любит верховую езду", ru)
    # invented facts in English against Russian sources: refused
    assert not _no_new_words("owns three cats", ru)
    # an honest merge that keeps the newer fact; the case endings change, the words do not
    assert _no_new_words("Живёт в Пекине, переехал из Шанхая в марте", ru)
    assert _no_new_words("ЖИВЁТ В ПЕКИНЕ (ПЕРЕЕХАЛ ИЗ ШАНХАЯ)", ru)
    # a shared stem is not a shared prefix: a different word is still new
    assert not _no_new_words("Предпочитает окна", [item("Его предпочтения: окна у прохода")])
    # the same word in two case forms of a five-letter noun passes (марте, марта)
    assert _no_new_words("С марта живёт в Пекине", ru)
    # nothing to compare: letters that make no word, on either side, mean no
    assert not _no_new_words("a b", [item("Lives in Shanghai")])
    assert not _no_new_words("Lives in Shanghai", [item("x")])
    # the English behaviour is as before
    en = [item("Lives in Shanghai"), item("Moved to Beijing in March 2026")]
    assert _no_new_words("Lives in Beijing, moved from Shanghai in March 2026", en)
    assert not _no_new_words("Lives in Beijing and owns three cats", en)
    # and so is the CJK one
    assert _no_new_words("住在北京，从上海搬来", [item("住在上海"), item("搬到北京")])
    assert not _no_new_words("住在北京，养了三只猫", [item("住在上海"), item("搬到北京")])


def test_tokens_and_similarity_cover_cyrillic_and_the_other_alphabets():
    from nanomuse.memory.store import similarity, tokenize

    assert tokenize("Пользователь предпочитает окна у прохода") == {
        "пользователь",
        "предпочитает",
        "окна",
        "прохода",
    }
    # case folding, not lowercasing: a final sigma folds to the ordinary one
    assert tokenize("Ο χρήστης μένει στην Αθήνα") == {"χρήστησ", "μένει", "στην", "αθήνα"}
    assert tokenize("يعيش في القاهرة") == {"يعيش", "في", "القاهرة"}
    assert tokenize("Déménagé à Zürich") == {"déménagé", "zürich"}
    assert tokenize("住在上海 since 2024") == {"住在", "在上", "上海", "since", "2024"}
    assert similarity("Живёт в Шанхае", "Живёт в Шанхае") == 1.0
    different = similarity("Живёт в Шанхае", "Переехал в Пекин в марте")
    assert different == 0.0
    shared = similarity("Живёт в Шанхае", "Живёт в Пекине")
    assert 0.0 < shared < 0.5

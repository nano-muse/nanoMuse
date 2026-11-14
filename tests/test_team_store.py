"""The squad task ledger: assignments on disk, the enqueue guards,
the lifecycle, and the startup reconcile.

The red lines pinned here: a terminal state is written once and can
never be overwritten; work never flows back to an ancestor; an open
brief is never handed out twice under the same parent; and a restart
never re-runs an assignment that already acted on the outside world.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nanomuse.config import Settings
from nanomuse.llm import MockLLM
from nanomuse.server.service import MuseService
from nanomuse.team.squad import Squad
from nanomuse.team.store import (
    RESULT_LIMIT,
    AlreadySettled,
    Assignment,
    AssignmentNotFound,
    EnqueueRefused,
    GuardReason,
    InvalidTransition,
    SquadStore,
    ledger_evidence,
    reconcile_on_startup,
)


def make_store(tmp_path: Path, **kwargs: object) -> SquadStore:
    return SquadStore(tmp_path / "squad.db", **kwargs)  # type: ignore[arg-type]


def make_root(store: SquadStore, brief: str = "root task") -> Assignment:
    return store.create_root(origin="user", brief=brief)


# ---------------------------------------------------------------------- basics


def test_a_root_and_a_child_round_trip_with_their_fields(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    root = store.create_root(
        origin="telegram", mode="work", role="steward", brief="plan the week", level="moderate"
    )
    child = store.enqueue(
        parent_id=root.id, origin="user", mode="consult", role="research", brief="find flights"
    )
    assert root.parent_id is None and root.depth == 0 and root.status == "queued"
    assert root.level == "moderate"
    assert child.parent_id == root.id and child.depth == 1
    assert child.origin == "user" and child.mode == "consult" and child.role == "research"
    # a child that names no level of its own inherits its parent's
    assert child.level == "moderate" and child.outcome == "" and child.result == ""
    assert child.created_at and child.settled_at == ""
    assert store.get(child.id) == child
    assert store.children(root.id) == [child]
    assert {a.id for a in store.open_assignments()} == {root.id, child.id}
    kinds = [e.kind for e in store.events(child.id)]
    assert kinds == ["enqueued"]


def test_the_ledger_survives_closing_and_reopening(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    root = make_root(store)
    child = store.enqueue(parent_id=root.id, origin="user", brief="check the numbers")
    store.settle(child.id, "completed", outcome="done", result="all match")
    store.close()

    reopened = make_store(tmp_path)
    kept = reopened.get(child.id)
    assert kept is not None
    assert kept.status == "completed" and kept.outcome == "done" and kept.result == "all match"
    assert kept.settled_at != ""
    assert reopened.open_assignments() == [reopened.get(root.id)]  # type: ignore[list-item]


def test_bad_origin_mode_or_brief_is_a_plain_value_error(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    root = make_root(store)
    with pytest.raises(ValueError):
        store.create_root(origin="mars", brief="x")
    with pytest.raises(ValueError):
        store.enqueue(parent_id=root.id, origin="user", mode="sideways", brief="x")
    with pytest.raises(ValueError):
        store.enqueue(parent_id=root.id, origin="user", brief="   ")


# ---------------------------------------------------------------------- lifecycle


def test_the_lifecycle_walks_its_legal_moves(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    root = make_root(store)
    assert store.transition(root.id, "running").status == "running"
    assert store.transition(root.id, "waiting").status == "waiting"
    assert store.transition(root.id, "needs_input").status == "needs_input"
    assert store.transition(root.id, "running").status == "running"
    done = store.settle(root.id, "completed", outcome="shipped", result="v1 is out")
    assert done.status == "completed" and done.settled_at != ""
    kinds = [e.kind for e in store.events(root.id)]
    assert kinds == ["enqueued", "status", "status", "status", "status", "settled"]


def test_illegal_moves_and_terminal_shortcuts_are_refused(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    root = make_root(store)
    with pytest.raises(InvalidTransition):
        store.transition(root.id, "waiting")  # queued may not wait
    with pytest.raises(InvalidTransition):
        store.transition(root.id, "completed")  # terminal goes through settle
    with pytest.raises(ValueError):
        store.transition(root.id, "exploded")
    with pytest.raises(ValueError):
        store.settle(root.id, "running")  # settle needs a terminal state
    with pytest.raises(AssignmentNotFound):
        store.transition("a_missing", "running")


def test_a_terminal_state_is_written_exactly_once(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    root = make_root(store)
    store.settle(root.id, "failed", outcome="gave up", result="no route")
    with pytest.raises(AlreadySettled):
        store.settle(root.id, "failed", outcome="gave up")
    with pytest.raises(AlreadySettled):
        store.settle(root.id, "completed", outcome="actually fine")
    kept = store.get(root.id)
    assert kept is not None
    assert kept.status == "failed" and kept.outcome == "gave up" and kept.result == "no route"
    with pytest.raises(InvalidTransition):
        store.transition(root.id, "running")


def test_a_result_is_capped_and_the_cut_is_marked(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    root = make_root(store)
    settled = store.settle(root.id, "completed", result="x" * (RESULT_LIMIT + 500))
    assert len(settled.result) == RESULT_LIMIT
    assert settled.result.endswith("[truncated]")


# ---------------------------------------------------------------------- guards


def test_enqueue_under_a_missing_parent_is_refused_by_name(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    with pytest.raises(EnqueueRefused) as caught:
        store.enqueue(parent_id="a_missing", origin="user", brief="orphan work")
    assert caught.value.reason is GuardReason.PARENT_NOT_FOUND


def test_enqueue_under_a_settled_parent_is_refused_by_name(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    root = make_root(store)
    store.settle(root.id, "cancelled")
    with pytest.raises(EnqueueRefused) as caught:
        store.enqueue(parent_id=root.id, origin="user", brief="too late")
    assert caught.value.reason is GuardReason.PARENT_SETTLED


def test_work_never_flows_back_to_an_ancestor(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    root = store.create_root(origin="user", brief="root", assignment_id="a_root")
    child = store.enqueue(parent_id=root.id, origin="user", brief="child", assignment_id="a_kid")
    with pytest.raises(EnqueueRefused) as caught:
        store.enqueue(parent_id=child.id, origin="user", brief="loop back", assignment_id="a_root")
    assert caught.value.reason is GuardReason.ANCESTOR_CYCLE
    with pytest.raises(EnqueueRefused) as caught:
        store.enqueue(parent_id=root.id, origin="user", brief="self parent", assignment_id="a_root")
    assert caught.value.reason is GuardReason.ANCESTOR_CYCLE


def test_an_open_brief_is_never_handed_out_twice_under_one_parent(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    root = make_root(store)
    other = store.create_root(origin="user", brief="another root")
    first = store.enqueue(parent_id=root.id, origin="user", brief="search the web")
    with pytest.raises(EnqueueRefused) as caught:
        store.enqueue(parent_id=root.id, origin="user", brief="search the web")
    assert caught.value.reason is GuardReason.DUPLICATE_BRIEF
    # the same brief under a different parent is a different hand-out
    store.enqueue(parent_id=other.id, origin="user", brief="search the web")
    # and once the first settles, the brief is free again
    store.settle(first.id, "completed")
    store.enqueue(parent_id=root.id, origin="user", brief="search the web")


def test_depth_is_capped_at_two_by_default(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    root = make_root(store)
    child = store.enqueue(parent_id=root.id, origin="user", brief="level one")
    grandchild = store.enqueue(parent_id=child.id, origin="user", brief="level two")
    assert grandchild.depth == 2
    with pytest.raises(EnqueueRefused) as caught:
        store.enqueue(parent_id=grandchild.id, origin="user", brief="level three")
    assert caught.value.reason is GuardReason.MAX_DEPTH


def test_a_root_tree_size_cap_counts_assignments_and_refuses_past_it(tmp_path: Path) -> None:
    store = make_store(tmp_path, max_per_root=3)
    root = make_root(store)
    store.enqueue(parent_id=root.id, origin="user", brief="one")
    store.enqueue(parent_id=root.id, origin="user", brief="two")
    assert store.tree_size(root.id) == 3
    assert store.descendant_count(root.id) == 2
    with pytest.raises(EnqueueRefused) as caught:
        store.enqueue(parent_id=root.id, origin="user", brief="three")
    assert caught.value.reason is GuardReason.ROOT_BUDGET
    # a second root has its own budget
    other = store.create_root(origin="user", brief="another root")
    store.enqueue(parent_id=other.id, origin="user", brief="one")


# ---------------------------------------------------------------------- reconcile


def test_reconcile_spares_an_unacted_assignment_exactly_once(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    root = make_root(store)
    first = reconcile_on_startup(store)
    assert first.retry_marked == [root.id] and first.interrupted == []
    kept = store.get(root.id)
    assert kept is not None and kept.status == "queued"  # still open, only marked
    assert store.retry_marks(root.id) == 1

    second = reconcile_on_startup(store)
    assert second.interrupted == [root.id] and second.retry_marked == []
    kept = store.get(root.id)
    assert kept is not None
    assert kept.status == "failed" and kept.outcome == "interrupted" and kept.settled_at != ""


def test_reconcile_interrupts_at_once_what_already_acted(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    acted = make_root(store, brief="already sent something")
    quiet = store.create_root(origin="user", brief="never started")
    report = reconcile_on_startup(store, evidence=lambda a: a.id == acted.id)
    assert report.interrupted == [acted.id]
    assert report.retry_marked == [quiet.id]
    kept = store.get(acted.id)
    assert kept is not None and kept.status == "failed" and kept.outcome == "interrupted"
    kinds = [e.kind for e in store.events(acted.id)]
    assert kinds == ["enqueued", "settled", "reconcile"]


def test_reconcile_leaves_settled_assignments_alone(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    root = make_root(store)
    store.settle(root.id, "completed", outcome="done")
    report = reconcile_on_startup(store, evidence=lambda a: True)
    assert report.interrupted == [] and report.retry_marked == []
    kept = store.get(root.id)
    assert kept is not None and kept.status == "completed"


def test_ledger_evidence_reads_the_cost_ledger_by_assignment_id(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    acted = make_root(store, brief="spent money")
    quiet = store.create_root(origin="user", brief="no calls")
    ledger = tmp_path / "cost_ledger.jsonl"
    rows = [
        {
            "task_id": acted.id,
            "device_id": "d",
            "model": "m",
            "input_tokens": 3,
            "output_tokens": 4,
            "cost_usd": 0.001,
            "month": "2026-11",
        },
        {
            "task_id": "someone-else",
            "device_id": "d",
            "model": "m",
            "input_tokens": 1,
            "output_tokens": 1,
            "cost_usd": 0.001,
            "month": "2026-11",
        },
    ]
    ledger.write_text(
        "\n".join(json.dumps(r) for r in rows) + "\nnot json at all\n", encoding="utf-8"
    )
    evidence = ledger_evidence(ledger)
    assert evidence(acted) is True
    assert evidence(quiet) is False
    missing = ledger_evidence(tmp_path / "no_such_file.jsonl")
    assert missing(acted) is False


# ---------------------------------------------------------------------- squad wiring


def test_a_dispatch_lands_in_the_ledger_and_on_the_bus(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    squad = Squad.form(store=store)
    assert squad.dispatch("research", "search", {"q": "x"}) is True
    frames = squad.bus.drain("specialist:research")
    assert len(frames) == 1 and frames[0].action == "search"
    root_id = squad.root_assignment_id
    assert root_id is not None
    root = store.get(root_id)
    assert root is not None and root.role == "steward" and root.origin == "user"
    children = store.children(root_id)
    assert len(children) == 1
    child = children[0]
    assert child.role == "research" and child.brief == "search"
    # the default hand-out is consult since the execution step: a body
    # that names no mode asks and does not act
    assert child.mode == "consult" and child.status == "queued" and child.depth == 1


def test_a_dispatch_mode_comes_from_the_body_when_it_is_a_real_mode(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    squad = Squad.form(store=store)
    assert squad.dispatch("verify", "check", {"mode": "consult"}) is True
    assert squad.dispatch("verify", "report", {"mode": "sideways"}) is True
    children = store.children(squad.root_assignment_id or "")
    # a real mode in the body wins; anything else falls back to the
    # consult default, never to work
    assert {c.brief: c.mode for c in children} == {"check": "consult", "report": "consult"}


def test_a_duplicate_open_dispatch_is_refused_and_not_sent(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    squad = Squad.form(store=store)
    assert squad.dispatch("research", "search", {}) is True
    squad.bus.drain("specialist:research")
    assert squad.dispatch("research", "search", {}) is False
    assert squad.bus.drain("specialist:research") == []
    child = store.children(squad.root_assignment_id or "")[0]
    store.settle(child.id, "completed")
    assert squad.dispatch("research", "search", {}) is True


def test_a_squad_without_a_store_records_nothing(tmp_path: Path) -> None:
    squad = Squad.form()
    assert squad.dispatch("research", "search", {}) is True
    assert squad.root_assignment_id is None
    single = Squad.single(store=make_store(tmp_path))
    assert single.dispatch("research", "search", {}) is False
    assert single.root_assignment_id is None


# ---------------------------------------------------------------------- server wiring


async def test_the_server_reconciles_the_ledger_once_at_start(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    root = make_root(store)
    service = MuseService(Settings(data_dir=tmp_path), llm=MockLLM([]))
    assert service.squad_store is not None
    assert store.retry_marks(root.id) == 0
    await service.start()
    try:
        assert service.squad_reconcile is not None
        assert service.squad_reconcile.retry_marked == [root.id]
        assert store.retry_marks(root.id) == 1
        await service.start()
        assert store.retry_marks(root.id) == 1
    finally:
        await service.stop()


def test_no_ledger_on_disk_wires_and_reconciles_nothing(tmp_path: Path) -> None:
    service = MuseService(Settings(data_dir=tmp_path), llm=MockLLM([]))
    assert service.squad_store is None
    assert service.squad_reconcile is None
    assert not (tmp_path / "squad.db").exists()


def test_squad_settings_default_to_a_depth_of_two_and_no_root_cap(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path)
    assert settings.squad.max_depth == 2
    assert settings.squad.max_per_root == 0
    assert settings.squad_db == tmp_path / "squad.db"

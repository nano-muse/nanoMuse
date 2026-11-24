"""Background delivery without a preceding user turn; connectors and models use synthetic data."""

import asyncio
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from nanomuse.llm import MockLLM
from nanomuse.schema import LLMResponse
from nanomuse.server import context_review, context_sources
from nanomuse.server.context_sources import ContextSample
from nanomuse.server.service import MuseService


def choice(reason, *quotes):
    def answer(messages):
        records = json.loads(messages[-1].content)["records"]
        return LLMResponse(
            content=json.dumps(
                {
                    "reason": reason,
                    "evidence": [
                        {"id": next(r["id"] for r in records if quote in r["text"]), "quote": quote}
                        for quote in quotes
                    ],
                }
            ),
            finish_reason="stop",
        )

    return answer


@pytest.mark.parametrize("initial", ["", "Draft complete."])
async def test_selected_mcp_changes_can_start_the_first_conversation(settings, tmp_path, initial):
    board = tmp_path / "progress.txt"
    board.write_text(initial, "utf-8")
    quote = "Printing is blocked until the cover proof is approved."
    llm = MockLLM([choice("blocker", quote)])
    service = MuseService(settings, llm=llm)
    watch = service.context_watch
    now = datetime.now().astimezone().replace(hour=12, minute=0)
    try:
        await service.connections.add_mcp(
            {
                "name": "proofs",
                "command": sys.executable,
                "args": [str(Path(__file__).with_name("mcp_context_server.py")), str(board)],
            }
        )
        before = watch.view()["revision"]
        with pytest.raises(ValueError, match="listed"):
            watch.configure(before, False, False, ["board://work/updates"], False)
        options = await watch.resources()
        key = next(o["id"] for o in options if "Team updates" in o["label"])
        watch.configure(before, False, False, [key], False)
        await watch.poll(now)
        assert not llm.calls and not watch.view()["unavailable"]
        board.write_text("Draft complete.\n" + quote, "utf-8")
        await watch.poll(now.replace(hour=3))
        assert not llm.calls
        await watch.poll(now)
        main = service.threads["main"]
        rows = [e for e in main.timeline.events if e.get("source") == "connected_context"]
        assert len(rows) == 1 and quote in rows[0]["text"] and rows[0]["type"] == "assistant"
        assert not any(e["type"] == "user" for e in main.timeline.events)
        assert main.agent.sentinel.tainted_for("main")
        assert llm.calls[0]["tools"] is None
        # Another tick and a service restart both see the durable receipt.
        await watch.poll(now + timedelta(minutes=20))
        restored = MuseService(settings, llm=llm)
        assert restored.context_watch.view()["resources"][0]["id"] == key
        assert restored.threads["main"].agent.sentinel.tainted_for("main")
        assert quote in restored.threads["main"].agent.messages[-1].content
        assert len(llm.calls) == 1
        assert quote not in watch._file("local").read_text("utf-8")
    finally:
        await service.connections.remove_mcp("proofs")


async def test_unmentioned_mail_can_be_matched_with_local_context_only_if_enabled(
    settings, monkeypatch
):
    settings.connectors.email.enabled = True
    settings.connectors.email.imap_host = "localhost"
    settings.connectors.email.address = "fixture-account"
    now = datetime.now().astimezone().replace(hour=12)
    quote = "The print shop needs the cover proof before it can start."
    goal = "Prepare the field guide cover proof"
    llm = MockLLM([choice("blocker", quote, goal)])
    svc = MuseService(settings, llm=llm)
    svc.app.goals.create(goal)
    watch = svc.context_watch
    cursors = []

    async def mailbox(watcher, cursor):
        cursors.append(cursor)
        if not cursor:
            return [], {"uid": 1}
        return [ContextSample("mail", "message2", "Proof", quote, now.isoformat())], {"uid": 2}

    monkeypatch.setattr(context_sources, "mail_samples", mailbox)
    await watch.poll(now)
    assert not cursors
    watch.configure(watch.view()["revision"], True, False, [], True)
    await watch.poll(now)
    assert cursors == [{}] and not llm.calls
    await watch.poll(now)
    assert cursors[-1] == {"uid": 1}
    delivery = svc.threads["main"].timeline.events[-1]
    assert (
        delivery["source"] == "connected_context"
        and goal in delivery["text"]
        and quote in delivery["text"]
    )
    settings.connectors.email.address = "other-fixture"
    assert not watch.view()["mail"]
    await watch.poll(now + timedelta(days=1))
    assert len(cursors) == 2


async def test_revoked_while_model_running_never_posts_or_restores_the_cursor(
    settings, monkeypatch
):
    settings.connectors.email.enabled = True
    settings.connectors.email.imap_host = "localhost"
    svc = MuseService(settings, llm=MockLLM())
    watch = svc.context_watch
    now = datetime.now().astimezone().replace(hour=12)
    watch.configure(watch.view()["revision"], True, False, [], False)

    async def mailbox(watcher, cursor):
        if not cursor:
            return [], {"uid": 10}
        return [ContextSample("mail", "m", "Review", "Please review the proof.")], {"uid": 11}

    monkeypatch.setattr(context_sources, "mail_samples", mailbox)
    entered, release = asyncio.Event(), asyncio.Event()

    async def delayed(*args, **kwargs):
        entered.set()
        await release.wait()
        return context_review.Finding("Would you like help?", (), (), "result")

    monkeypatch.setattr(context_review, "review", delayed)
    await watch.poll(now)
    running = asyncio.create_task(watch.poll(now))
    await asyncio.wait_for(entered.wait(), 3)
    watch.configure(watch.view()["revision"], False, False, [], False)
    release.set()
    await running
    assert not any(
        e.get("source") == "connected_context" for e in svc.threads["main"].timeline.events
    )
    assert "cursor" not in watch._load("local")


def test_shared_goals_are_never_offered_to_another_cloud_account(settings, monkeypatch):
    svc = MuseService(settings, llm=MockLLM())
    svc.app.goals.create("Publisher proofs")
    watch = svc.context_watch
    now = datetime.now().astimezone()
    assert any(r.kind == "goal" for r in watch._local(now).values())
    monkeypatch.setattr(type(svc.hub), "signed_in", property(lambda _: True))
    for account in ("first", "second"):
        svc.hub.data["cloud"] = {"account_id": account}
        svc.sync.state["account_id"] = account
        svc.sync.state["owners"]["main"] = account
        assert svc._chat_followup_scope() == f"account:{account}"
        assert not watch.view()["local_goals"]
        assert all(r.kind != "goal" for r in watch._local(now).values())
    monkeypatch.setattr(type(svc.hub), "signed_in", property(lambda _: False))
    assert all(r.kind != "goal" for r in watch._local(now).values())


async def test_account_change_during_first_read_invalidates_even_a_return_to_local(
    settings, monkeypatch
):
    settings.connectors.email.enabled = True
    settings.connectors.email.imap_host = "localhost"
    svc = MuseService(settings, llm=MockLLM())
    watch = svc.context_watch
    now = datetime.now().astimezone().replace(hour=12)
    watch.configure(watch.view()["revision"], True, False, [], False)
    before = watch.view()["revision"]
    entered, resume = asyncio.Event(), asyncio.Event()

    async def slow_read(watcher, cursor):
        entered.set()
        await resume.wait()
        return [], {"uid": 52}

    async def signed_out():
        assert not svc._chat_followup_scope()

    monkeypatch.setattr(context_sources, "mail_samples", slow_read)
    monkeypatch.setattr(svc.hub.cloud, "sign_out", signed_out)
    pending = asyncio.create_task(watch.poll(now))
    await asyncio.wait_for(entered.wait(), 3)
    await svc.hub.sign_out()
    resume.set()
    await pending
    assert watch.view()["revision"] != before and svc._chat_followup_scope() == "local"
    assert "cursor" not in watch._load("local")


def test_disagreeing_cloud_and_synced_account_has_no_access(settings, monkeypatch):
    svc = MuseService(settings, llm=MockLLM())
    monkeypatch.setattr(type(svc.hub), "signed_in", property(lambda _: True))
    svc.sync.state["account_id"] = "first"
    svc.sync.state["owners"]["main"] = "first"
    svc.hub.data["cloud"] = {"account_id": "second"}
    assert not svc._chat_followup_scope()


async def test_each_calendar_establishes_its_own_silent_baseline(settings):
    from nanomuse.calendar import FeedState
    from nanomuse.calendar.ics import Event
    from nanomuse.config import CalendarFeedSettings

    now = datetime.now().astimezone().replace(hour=12)
    svc = MuseService(settings, llm=MockLLM())
    cal = svc.app.calendar
    cal.settings.enabled = True
    cal.settings.feeds = [CalendarFeedSettings(name=n, url="unused") for n in ("Desk", "Studio")]
    cal.states["Desk"] = FeedState("Desk", [], now.timestamp())
    cal.states["Studio"] = FeedState("Studio", [], 0, error="temporarily offline")
    watch = svc.context_watch
    watch.configure(watch.view()["revision"], False, True, [], False)
    await watch.poll(now)
    assert watch.view()["unavailable"]
    meeting = Event(
        "slot",
        "Studio booking",
        now + timedelta(hours=1),
        now + timedelta(hours=2),
        calendar="Studio",
    )
    cal.states["Studio"] = FeedState("Studio", [meeting], now.timestamp())
    await watch.poll(now)
    assert not svc.app.llm.calls and not watch.view()["unavailable"]
    assert len(watch._load("local")["calendar_seen"]) == 1

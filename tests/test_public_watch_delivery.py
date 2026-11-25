"""Only opted-in public-only reviews enter the ordinary account conversation sync."""

import asyncio
import json
from datetime import datetime, timedelta

import httpx
import pytest

from nanomuse.llm import MockLLM
from nanomuse.schema import LLMResponse
from nanomuse.server import context_review, context_sources
from nanomuse.server.api import create_app
from nanomuse.server.context_sources import ContextSample
from nanomuse.server.service import MuseService

QUOTE = "The print dialog now loses the selected page range."
URL = "https://github.com/sample/project/issues/3"


def make_service(settings, monkeypatch):
    def choose(messages):
        rows = json.loads(messages[-1].content)["records"]
        item = next(r for r in rows if r["kind"] == "public_watch")
        return LLMResponse(
            content=json.dumps(
                {
                    "reason": "triage_issue",
                    "evidence": [{"id": item["id"], "quote": QUOTE}],
                }
            ),
            finish_reason="stop",
        )

    service = MuseService(settings, llm=MockLLM([choose]))
    monkeypatch.setattr(type(service.hub), "signed_in", property(lambda _: True))
    service.hub.data["cloud"] = {"account_id": "first-account"}
    service.sync.state["account_id"] = "first-account"
    service.sync.state["owners"]["main"] = "first-account"
    monkeypatch.setattr(service.sync, "push_soon", lambda *args, **kwargs: None)
    monkeypatch.setattr(service.sync, "pull_soon", lambda: None)
    return service


def configure(svc, **edit):
    watches = svc.context_watch.watches
    return watches.configure(watches.view()["revision"], **edit)


def new_change(svc, now):
    configure(svc, kind="github_repo", target="sample/project")
    watches = svc.context_watch.watches
    scope = svc._chat_followup_scope()
    state = watches._load(scope)
    row = next(iter(state["watches"].values()))
    row.update(
        seen=["new-issue"],
        next=(now + timedelta(hours=4)).timestamp(),
        pending={"new-issue": {"text": QUOTE, "url": URL, "at": now.timestamp()}},
    )
    watches._save(scope, state)


def noon():
    return datetime.now().astimezone().replace(hour=12, minute=0)


def wire(svc):
    return [r for _, r in svc.sync._unsynced(svc.threads["main"], "main-cid")]


async def test_only_opted_in_public_review_pushes_a_single_normal_assistant_message(
    settings, monkeypatch
):
    svc = make_service(settings, monkeypatch)
    now = noon()
    watch = svc.context_watch
    configure(svc, share_public_updates=True)
    watch.configure(watch.view()["revision"], False, False, [], True)
    svc.ui.emit(
        dict(
            type="user",
            thread="main",
            text="Personal unrelated draft text.",
            id="private-chat",
            ts=(now - timedelta(hours=1)).isoformat(),
            synced=True,
        )
    )
    new_change(svc, now)
    await watch.poll(now)
    records = json.loads(svc.app.llm.calls[0]["messages"][-1].content)["records"]
    assert {row["kind"] for row in records} == {"public_watch"}
    outreach = svc.threads["main"].timeline.events[-1]
    assert outreach["source"] == "shared_public_watch" and URL in outreach["text"]
    assert svc.threads["main"].agent.sentinel.tainted_for("main")
    packets = []

    async def relay_push(device, conversations, messages):
        packets.extend(messages)
        return {"rejected": []}

    monkeypatch.setattr(svc.sync.client, "push", relay_push)
    await svc.sync.push()
    await svc.sync.push()
    assert len(packets) == 1
    message = packets[0]
    assert message["role"] == "assistant" and message["text"] == outreach["text"]
    assert set(message) == {"mid", "cid", "role", "text", "created_at"}


@pytest.mark.parametrize(
    "sharing,sync_on,mixed", [(False, True, False), (True, False, False), (True, True, True)]
)
async def test_private_mixed_and_sync_off_reviews_never_backfill(
    settings, monkeypatch, sharing, sync_on, mixed
):
    settings.connectors.email.enabled = True
    settings.connectors.email.imap_host = "localhost"
    settings.connectors.email.address = "fixture-account"
    svc = make_service(settings, monkeypatch)
    svc.sync.state["enabled"] = sync_on
    configure(svc, share_public_updates=sharing)
    now = noon()
    if mixed:
        watch = svc.context_watch
        watch.configure(watch.view()["revision"], True, False, [], False)

        async def mailbox(_watcher, _cursor):
            return [
                ContextSample(
                    "mail",
                    "private",
                    "Proof",
                    "The printing deadline moved to Monday.",
                    now.isoformat(),
                )
            ], {"uid": 2}

        monkeypatch.setattr(context_sources, "mail_samples", mailbox)
    new_change(svc, now)
    await svc.context_watch.poll(now)
    assert svc.threads["main"].timeline.events[-1]["source"] == "connected_context"
    if mixed:
        rows = json.loads(svc.app.llm.calls[0]["messages"][-1].content)["records"]
        assert {row["kind"] for row in rows} == {"public_watch", "mail"}
    svc.sync.state["enabled"] = True
    configure(svc, share_public_updates=True)
    assert not wire(svc)


async def test_revocation_prevents_queued_public_message_even_after_reenabling_or_account_switch(
    settings, monkeypatch
):
    svc = make_service(settings, monkeypatch)
    configure(svc, share_public_updates=True)
    now = noon()
    new_change(svc, now)
    await svc.context_watch.poll(now)
    assert len(wire(svc)) == 1
    configure(svc, share_public_updates=False)
    assert wire(svc) == []
    configure(svc, share_public_updates=True)
    assert wire(svc) == []
    svc.sync.state.update(owners={"main": "another-account"}, account_id="another-account")
    svc.hub.data["cloud"] = {"account_id": "another-account"}
    configure(svc, share_public_updates=True)
    assert wire(svc) == []


async def test_setting_change_during_model_review_cancels_delivery(settings, monkeypatch):
    svc = make_service(settings, monkeypatch)
    now = noon()
    configure(svc, share_public_updates=True)
    new_change(svc, now)
    entered, resume = asyncio.Event(), asyncio.Event()
    review = context_review.review

    async def delayed(*args, **kwargs):
        entered.set()
        await resume.wait()
        return await review(*args, **kwargs)

    monkeypatch.setattr(context_review, "review", delayed)
    polling = asyncio.create_task(svc.context_watch.poll(now))
    await asyncio.wait_for(entered.wait(), 2)
    configure(svc, share_public_updates=False)
    configure(svc, share_public_updates=True)
    resume.set()
    await polling
    assert not svc.threads["main"].timeline.events
    assert svc.context_watch.watches.pending(svc._chat_followup_scope(), now)


async def test_api_opt_in_is_separate_from_watch_master_switch(settings, monkeypatch):
    service = make_service(settings, monkeypatch)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(settings, service)), base_url="http://test"
    ) as client:
        client.headers["Authorization"] = "Bearer " + service.token
        path = "/api/feed/watches"
        start = (await client.get(path)).json()
        assert start["can_share"] and not start["share_public_updates"]
        saved = (
            await client.put(
                path, json={"revision": start["revision"], "share_public_updates": True}
            )
        ).json()
        assert saved["enabled"] and saved["share_public_updates"]
        paused = (
            await client.put(path, json={"revision": saved["revision"], "enabled": False})
        ).json()
        assert not paused["enabled"] and paused["share_public_updates"]
        assert (
            await client.put(
                path, json={"revision": start["revision"], "share_public_updates": False}
            )
        ).status_code == 400

"""Exercise discovery, account choices, baseline, evidence review and real main-chat delivery."""

import asyncio
import json
from datetime import datetime, timedelta

import httpx

from nanomuse.llm import MockLLM
from nanomuse.schema import LLMResponse
from nanomuse.server import context_review, context_sources, public_sources
from nanomuse.server.api import create_app
from nanomuse.server.public_sources import PublicItem
from nanomuse.server.service import MuseService


def post(service, text, time, key, **extra):
    service.ui.emit(
        dict(type="user", thread="main", id=key, text=text, ts=time.isoformat(), **extra)
    )


def noon():
    return datetime.now().astimezone().replace(hour=12, minute=0, second=0, microsecond=0)


def configure(watches, **change):
    return watches.configure(watches.view()["revision"], **change)


async def test_owned_project_checks_then_starts_a_chat_about_one_new_issue(settings, monkeypatch):
    calls = []
    old = PublicItem(
        "sample:1", "The welcome page needs a link", "https://github.com/sample/draw/issues/1"
    )
    new = PublicItem(
        "sample:2",
        "Printing fails when the diagram has two pages",
        "https://github.com/sample/draw/issues/2",
    )
    batch = [old]

    async def read(kind, target, *, now):
        calls.append((kind, target))
        return batch

    def decision(messages):
        records = json.loads(messages[-1].content)["records"]
        record = next(r for r in records if r["changed"])
        assert old.text not in str(records) and record["following"] == "sample/draw"
        return LLMResponse(
            content=json.dumps(
                {"reason": "triage_issue", "evidence": [{"id": record["id"], "quote": new.text}]}
            ),
            finish_reason="stop",
        )

    monkeypatch.setattr(public_sources, "fetch_public", read)
    llm = MockLLM([decision])
    svc = MuseService(settings, llm=llm)
    watch = svc.context_watch
    now = noon()
    post(svc, "我维护的项目是 https://github.com/sample/draw", now - timedelta(hours=1), "turn-one")
    await watch.poll(now)
    assert calls == [("github_repo", "sample/draw")]
    assert watch.watches.view()["watches"][0]["status"] == "active" and not llm.calls
    batch.insert(0, new)
    await watch.poll(now + timedelta(hours=2))
    assert len(calls) == 1
    await watch.poll(now + timedelta(hours=4))
    delivery = svc.threads["main"].timeline.events[-1]
    assert delivery["type"] == "assistant" and delivery["source"] == "connected_context"
    assert new.text in delivery["text"] and new.url in delivery["text"]
    assert llm.calls[0]["tools"] is None
    assert svc.threads["main"].agent.sentinel.tainted_for("main")
    restored = MuseService(settings, llm=llm)
    await restored.context_watch.poll(now + timedelta(days=1))
    assert len(llm.calls) == 1
    assert not restored.context_watch.watches.pending("local", now + timedelta(days=1))


async def test_repeated_distinct_mentions_only_suggest_and_do_not_override_stop(
    settings, monkeypatch
):
    svc = MuseService(settings, llm=MockLLM())
    watch = svc.context_watch
    now = noon()
    calls = []

    async def reader(*args, **kwargs):
        calls.append(args)
        return []

    monkeypatch.setattr(public_sources, "fetch_public", reader)
    link = "https://github.com/sample/draw"
    post(svc, "看看这个 " + link, now - timedelta(hours=3), "a")
    post(svc, "这周又提到了 " + link, now - timedelta(hours=2), "b", synced=True)
    await watch.poll(now)
    assert watch.watches.view()["watches"] == []
    post(svc, link + " has a useful example", now - timedelta(hours=1), "c")
    await watch.poll(now)
    (suggestion,) = watch.watches.view()["watches"]
    assert suggestion["status"] == "suggested" and not calls
    configure(watch.watches, watch_id=suggestion["id"], action="confirm")
    await watch.poll(now)
    assert calls == [("github_repo", "sample/draw")]
    configure(watch.watches, watch_id=suggestion["id"], action="dismiss")
    post(svc, "I maintain " + link, now, "d")
    await watch.poll(now + timedelta(days=1))
    assert len(calls) == 1 and watch.watches.view()["watches"] == []


async def test_watches_from_an_inbox_never_claim_its_senders_identity(settings, monkeypatch):
    settings.connectors.email.enabled = True
    settings.connectors.email.imap_host = "localhost"
    svc = MuseService(settings, llm=MockLLM())
    watch = svc.context_watch
    watch.configure(watch.view()["revision"], True, False, [], False)
    candidates = context_sources.connected_candidates("My GitHub account is sample-owner")
    assert len(candidates) == 1
    sample = context_sources.ContextSample("mail", "message", "note", "OK", candidates=candidates)

    async def mailbox(*args):
        return [sample], {"uid": 2}

    monkeypatch.setattr(context_sources, "mail_samples", mailbox)
    await watch.poll(noon().replace(hour=4))
    assert [(r["status"], r["target"]) for r in watch.watches.view()["watches"]] == [
        ("suggested", "sample-owner")
    ]


async def test_pause_during_network_read_and_stop_during_judgment(settings, monkeypatch):
    svc = MuseService(settings, llm=MockLLM())
    watch = svc.context_watch
    now = noon()
    row = configure(watch.watches, kind="research_topic", target="water filtration")["watches"][0]
    entered, release = asyncio.Event(), asyncio.Event()

    async def slow(*args, **kwargs):
        entered.set()
        await release.wait()
        return []

    monkeypatch.setattr(public_sources, "fetch_public", slow)
    task = asyncio.create_task(watch.poll(now))
    await asyncio.wait_for(entered.wait(), 5)
    configure(watch.watches, watch_id=row["id"], action="pause")
    release.set()
    await task
    assert watch.watches.view()["watches"][0]["last_checked"] is None
    configure(watch.watches, watch_id=row["id"], action="resume")
    await watch.poll(now)

    async def fresh(*args, **kwargs):
        return [
            PublicItem("paper", "Portable filtration with solar power", "https://openalex.org/W2")
        ]

    async def decide(*args, **kwargs):
        configure(watch.watches, enabled=False)
        return context_review.Finding("unwanted", ("R1",), (), "key")

    monkeypatch.setattr(public_sources, "fetch_public", fresh)
    monkeypatch.setattr(context_review, "review", decide)
    await watch.poll(now + timedelta(days=1))
    assert not watch.watches.pending("local", now)
    assert not any(e.get("outreach_day") for e in svc.threads["main"].timeline.events)


async def test_transient_failure_empty_baseline_and_quiet_hours(settings, monkeypatch):
    svc = MuseService(settings, llm=MockLLM())
    watch = svc.context_watch
    configure(watch.watches, kind="github_user", target="sample-owner")
    early = noon().replace(hour=1)
    responses = iter([TimeoutError(), [], [PublicItem("issue", "New issue for audio routing", "")]])

    async def reader(*args, **kwargs):
        value = next(responses)
        if isinstance(value, Exception):
            raise value
        return value

    monkeypatch.setattr(public_sources, "fetch_public", reader)
    await watch.poll(early)
    assert watch.watches.view()["watches"][0]["unavailable"]
    await watch.poll(early + timedelta(minutes=5))
    assert watch.watches.view()["watches"][0]["last_checked"] is None
    await watch.poll(early + timedelta(minutes=20))
    assert not watch.watches.view()["watches"][0]["unavailable"]
    await watch.poll(early + timedelta(hours=5))
    assert len(watch.watches.pending("local", early + timedelta(hours=5))) == 1
    assert not svc.app.llm.calls


async def test_http_controls_bind_scholar_to_exact_identifier_and_reject_stale_edits(settings):
    svc = MuseService(settings, llm=MockLLM())
    app = create_app(settings, svc)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        api = "/api/feed/watches"
        assert (await client.get(api)).status_code == 401
        client.headers["Authorization"] = "Bearer " + svc.token
        first = (await client.get(api)).json()

        async def add(rev):
            return await client.post(
                api, json={"revision": rev, "kind": "scholar_profile", "target": "Abcd1234"}
            )

        state = (await add(first["revision"])).json()
        assert (await add(first["revision"])).status_code == 400
        row = state["watches"][0]
        assert row["status"] == "suggested"
        uri = api + "/" + row["id"]
        body = {"revision": state["revision"], "action": "confirm"}
        assert (await client.patch(uri, json=body)).status_code == 400
        body.update(kind="research_work", target="10.1234/Sample")
        confirmed = (await client.patch(uri, json=body)).json()
        assert [(r["status"], r["target"]) for r in confirmed["watches"]] == [
            ("active", "10.1234/sample")
        ]
        disabled = (
            await client.put(api, json={"revision": confirmed["revision"], "enabled": False})
        ).json()
        assert not disabled["enabled"]


async def test_publisher_changes_have_the_same_chat_flow_and_a_replaced_feed_resets(
    settings, monkeypatch
):
    from nanomuse.server import public_feed

    now = noon()
    site = "https://example.org/museum"
    stream = site + "/announcements"
    entry = PublicItem(
        "registration", "Registration opened for the museum night tour", site + "/night-tour"
    )
    reading = (stream, [])

    async def read(target, *, now):
        assert target == site
        return reading

    monkeypatch.setattr(public_feed, "fetch_feed", read)

    def choose(messages):
        records = json.loads(messages[-1].content)["records"]
        change = next(r for r in records if r["changed"])
        return LLMResponse(
            content=json.dumps(
                {"reason": "review_update", "evidence": [{"id": change["id"], "quote": entry.text}]}
            ),
            finish_reason="stop",
        )

    llm = MockLLM([choose])
    svc = MuseService(settings, llm=llm)
    watch = svc.context_watch
    post(svc, "请持续关注这个网站 " + site, now - timedelta(hours=1), "t")
    await watch.poll(now)
    assert watch.watches.view()["watches"][0]["last_checked"]
    reading = (stream, [entry])
    await watch.poll(now + timedelta(hours=4))
    assert entry.url in svc.threads["main"].timeline.events[-1]["text"]
    reading = (site + "/new-feed", [PublicItem("archive", "An old exhibition was announced", site)])
    await watch.poll(now + timedelta(days=1))
    assert not watch.watches.pending("local", now + timedelta(days=1)) and len(llm.calls) == 1


async def test_connected_url_can_corroborate_chat_but_cannot_activate_on_its_own(
    settings, monkeypatch
):
    from nanomuse.server.watch_discovery import reference_watches

    settings.connectors.email.enabled = True
    settings.connectors.email.imap_host = "localhost"
    svc = MuseService(settings, llm=MockLLM())
    watch = svc.context_watch
    watch.configure(watch.view()["revision"], True, False, [], False)
    link = "https://github.com/sample/draw"
    text = link + "/issues/31"
    refs = tuple(reference_watches(text + "\nhttps://github.com/another/project"))
    assert len(refs) == 2

    async def mailbox(*args):
        return [context_sources.ContextSample("mail", "s", "notes", "Noted.", references=refs)], {
            "uid": 3
        }

    monkeypatch.setattr(context_sources, "mail_samples", mailbox)
    now = noon()
    post(svc, "Look at " + link, now - timedelta(hours=1), "one")
    await watch.poll(now)
    (row,) = watch.watches.view()["watches"]
    assert (row["target"], row["status"], row["origin"]) == (
        "sample/draw",
        "suggested",
        "connected",
    )


async def test_waiting_evidence_tracks_a_corrected_title_and_retires_a_closed_issue(monkeypatch):
    from nanomuse.server.public_watches import refresh_row

    now = noon()
    batch = []

    async def read(*args, **kwargs):
        return batch

    monkeypatch.setattr(public_sources, "fetch_public", read)
    row = {"kind": "github_repo", "target": "sample/draw"}
    await refresh_row(row, now)
    batch = [PublicItem("issue", "Printing requires a driver", "")]
    await refresh_row(row, now + timedelta(hours=4))
    (change,) = row["pending"].values()
    batch = [PublicItem("issue", "Printing works without a driver", "")]
    await refresh_row(row, now + timedelta(hours=8))
    assert list(row["pending"].values()) == [{**change, "text": batch[0].text}]
    batch.clear()
    await refresh_row(row, now + timedelta(hours=12))
    assert row["pending"] == {}

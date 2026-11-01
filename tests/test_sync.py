"""Conversation sync on the runtime (contract C7): the engine against an in-memory relay —
push after a turn, pull into threads and the agent's history, the main chat as one
conversation, tombstones, the switch — and the ``@<device>`` mention in the composer."""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import Callable, Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from nanomuse.cloud import CloudClient, CloudError
from nanomuse.config import Settings
from nanomuse.llm import MockLLM
from nanomuse.schema import LLMResponse
from nanomuse.server import create_app
from nanomuse.server.events import MAIN_THREAD
from nanomuse.server.service import MuseService
from nanomuse.sync import engine as engine_mod
from nanomuse.sync.mention import parse_mention, system_note

DEVICES = [
    {"id": "pc-self", "name": "Desk", "kind": "computer", "online": True},
    {"id": "phone-1", "name": "Pixel 8", "kind": "phone", "online": True},
    {"id": "mac-1", "name": "Mac mini", "kind": "computer", "online": False},
    {"id": "mac-2", "name": "MacBook", "kind": "computer", "online": True},
]


def wait_for(pred: Callable[[], Any], timeout: float = 8.0, interval: float = 0.03) -> Any:
    deadline = time.time() + timeout
    while time.time() < deadline:
        value = pred()
        if value:
            return value
        time.sleep(interval)
    raise AssertionError("condition not met in time")


def settled(service: MuseService) -> bool:
    """No push or pull of the engine's is scheduled or on the wire. The engine writes its
    state (a cid, an owner) *before* the request reaches the relay and marks the rows after,
    so a test that reads that state — or swaps the relay's store — while a push is in flight
    races the event loop; wait for this first. A push schedules the pull that follows it,
    and a pull that applied rows the push after that, before it finishes, so the chain is
    covered."""
    sync = service.sync
    return all(t is None or t.done() for t in (sync._push_task, sync._pull_task))


# ----------------------------------------------------------------------------- the mention
def test_mention_takes_a_device_name_off_the_front() -> None:
    m = parse_mention("@Pixel 8 open the calendar", DEVICES, "pc-self")
    assert m is not None and m.device_id == "phone-1" and m.text == "open the calendar"
    # case-insensitive, a comma after the name, the longest full name wins
    m = parse_mention("  @mac mini, list ~/Downloads", DEVICES, "pc-self")
    assert m is not None and m.device_id == "mac-1" and m.text == "list ~/Downloads"
    # the first word as a prefix of exactly one name
    m = parse_mention("@pix what's on screen", DEVICES, "pc-self")
    assert m is not None and m.device_id == "phone-1" and m.text == "what's on screen"
    # "Mac" starts two names; the one online is meant
    m = parse_mention("@mac hello", DEVICES, "pc-self")
    assert m is not None and m.device_id == "mac-2"
    # this device is never a target; an unknown name is an ordinary message
    assert parse_mention("@Desk hi", DEVICES, "pc-self") is None
    assert parse_mention("@nobody hi", DEVICES, "pc-self") is None
    assert parse_mention("hello @Pixel 8", DEVICES, "pc-self") is None
    assert parse_mention("@", DEVICES, "pc-self") is None
    assert "Pixel 8 (id phone-1)" in system_note(
        "Pixel 8", "phone-1"
    ) and "`delegate`" in system_note("x", "y")


# ----------------------------------------------------------------------------- a relay in memory
class FakeSyncRelay:
    """The relay's /v1/sync/* as the engine sees them, with the contract's rules."""

    def __init__(self) -> None:
        self.cloud = SimpleNamespace(api_key="")
        self.enabled = True
        self.seq = 0
        self.convs: dict[str, dict[str, Any]] = {}
        self.msgs: dict[str, dict[str, Any]] = {}
        self.pushes: list[dict[str, Any]] = []
        self.pulls: list[dict[str, Any]] = []
        self.working_calls: list[dict[str, Any]] = []
        self.calls: list[str] = []
        self.fail: CloudError | None = None
        self.fail_working: CloudError | None = None
        self.names = {"phone-1": "Pixel 8", "pc-self": "Desk"}

        self._stores: dict[str, tuple[int, dict[str, Any], dict[str, Any]]] = {}
        self._account = ""

    def switch_account(self, account: str) -> None:
        """Another account's store (the relay keeps one per account; C10)."""
        self._stores[self._account] = (self.seq, self.convs, self.msgs)
        self.seq, self.convs, self.msgs = self._stores.get(account) or (0, {}, {})
        self._account = account

    def _next(self) -> int:
        self.seq += 1
        return self.seq

    def _check(self, what: str) -> None:
        self.calls.append(what)
        if self.fail is not None:
            exc, self.fail = self.fail, None
            raise exc
        if not self.enabled and what in ("push", "changes", "delete_conversation"):
            raise CloudError(409, "sync_off", "off")

    # -- what a test seeds
    def add_conversation(
        self, cid: str, kind: str = "side", title: str = "A chat", device: str = "phone-1"
    ) -> None:
        self.convs[cid] = {
            "cid": cid,
            "kind": kind,
            "title": title,
            "device": device,
            "device_name": self.names.get(device, ""),
            "created_at": 1738000000,
            "updated_at": 1738000000,
            "deleted": False,
            "seq": self._next(),
        }

    def add_message(
        self, cid: str, role: str, text: str, device: str = "phone-1", created_at: int = 1738000050
    ) -> str:
        mid = str(uuid.uuid4())
        self.msgs[mid] = {
            "mid": mid,
            "cid": cid,
            "seq": self._next(),
            "device": device,
            "device_name": self.names.get(device, ""),
            "role": role,
            "text": text,
            "truncated": False,
            "attachments": [],
            "created_at": created_at,
            "deleted": False,
        }
        return mid

    def tombstone_conversation(self, cid: str) -> None:
        self.convs[cid].update(deleted=True, title="", seq=self._next())
        for mid in [m for m, v in self.msgs.items() if v["cid"] == cid]:
            del self.msgs[mid]

    def tombstone_message(self, mid: str) -> None:
        self.msgs[mid].update(deleted=True, text="", seq=self._next())

    # -- the API
    async def state(self) -> dict[str, Any]:
        self._check("state")
        return {
            "enabled": self.enabled,
            "cursor": self.seq,
            "counts": {
                "conversations": sum(1 for c in self.convs.values() if not c["deleted"]),
                "messages": len(self.msgs),
            },
            "limits": {"messages": 20000, "text_bytes": 16384},
        }

    async def set_enabled(self, enabled: bool) -> dict[str, Any]:
        self._check("set_enabled")
        self.enabled = enabled
        if not enabled:
            self.convs.clear()
            self.msgs.clear()
        return await self.state()

    async def changes(
        self, since: int = 0, limit: int = 500, scope: str = "all", tail: int = 0
    ) -> dict[str, Any]:
        self._check("changes")
        self.pulls.append({"since": since, "limit": limit, "scope": scope, "tail": tail})
        convs = [c for c in self.convs.values() if scope != "main" or c["kind"] == "main"]
        cids = {c["cid"] for c in convs}
        msgs = [m for m in self.msgs.values() if m["cid"] in cids]
        if tail and since == 0:
            # C9: the newest `tail` messages with their conversations, cursor at the end
            msgs.sort(key=lambda m: m["seq"])
            kept = msgs[-tail:]
            parents = {m["cid"] for m in kept}
            return {
                "cursor": self.seq,
                "more": False,
                "skipped": len(msgs) - len(kept),
                "conversations": [dict(c) for c in convs if c["cid"] in parents],
                "messages": [dict(m) for m in kept],
            }
        rows = [("c", c) for c in convs if c["seq"] > since] + [
            ("m", m) for m in msgs if m["seq"] > since
        ]
        rows.sort(key=lambda x: x[1]["seq"])
        more = len(rows) > limit
        rows = rows[:limit]
        conversations = [dict(r) for k, r in rows if k == "c"]
        have = {c["cid"] for c in conversations}
        for k, r in rows:  # every message's conversation rides along
            if k == "m" and r["cid"] not in have and r["cid"] in self.convs:
                conversations.append(dict(self.convs[r["cid"]]))
                have.add(r["cid"])
        return {
            "cursor": rows[-1][1]["seq"] if more else self.seq,
            "more": more,
            "conversations": conversations,
            "messages": [dict(r) for k, r in rows if k == "m"],
        }

    async def working(
        self, cid: str, working: bool, device: str, state: str = "", detail: str = ""
    ) -> None:
        self._check("working")
        if self.fail_working is not None:
            raise self.fail_working
        if cid not in self.convs:
            raise CloudError(404, "no_conversation", "none")
        call = {"cid": cid, "working": working, "device": device}
        if working and state:
            call["state"] = state
        if working and detail:
            call["detail"] = detail
        self.working_calls.append(call)

    async def push(
        self, device: str, conversations: list[dict[str, Any]], messages: list[dict[str, Any]]
    ) -> dict[str, Any]:
        self._check("push")
        self.pushes.append({"device": device, "conversations": conversations, "messages": messages})
        accepted, rejected, redirected = 0, [], {}
        for c in conversations:
            cid = c["cid"]
            if cid not in self.convs:
                if c.get("kind") == "main":
                    main = next(
                        (
                            x
                            for x in self.convs.values()
                            if x["kind"] == "main" and not x["deleted"]
                        ),
                        None,
                    )
                    if main is not None:
                        redirected[cid] = main["cid"]
                        rejected.append(
                            {"cid": cid, "reason": "main_exists", "cid_main": main["cid"]}
                        )
                        continue
                self.convs[cid] = {
                    "cid": cid,
                    "kind": c.get("kind", "side"),
                    "title": c.get("title", ""),
                    "device": device,
                    "device_name": self.names.get(device, ""),
                    "created_at": c.get("created_at", 0),
                    "updated_at": c.get("updated_at", 0),
                    "deleted": bool(c.get("deleted")),
                    "seq": self._next(),
                }
                accepted += 1
            elif c.get("deleted"):
                self.tombstone_conversation(cid)
                accepted += 1
            elif c.get("title") != self.convs[cid]["title"]:
                self.convs[cid].update(title=c.get("title", ""), seq=self._next())
                accepted += 1
        for m in messages:
            if m["cid"] in redirected:
                rejected.append(
                    {"mid": m["mid"], "reason": "main_exists", "cid_main": redirected[m["cid"]]}
                )
                continue
            if m["mid"] in self.msgs:
                continue
            if m["cid"] not in self.convs:
                rejected.append({"mid": m["mid"], "reason": "unknown_cid"})
                continue
            self.msgs[m["mid"]] = {
                "mid": m["mid"],
                "cid": m["cid"],
                "seq": self._next(),
                "device": device,
                "device_name": self.names.get(device, ""),
                "role": m["role"],
                "text": m.get("text", ""),
                "truncated": False,
                "attachments": m.get("attachments") or [],
                "created_at": m.get("created_at", 0),
                "deleted": False,
            }
            accepted += 1
        return {"cursor": self.seq, "accepted": accepted, "rejected": rejected}

    async def delete_conversation(self, cid: str) -> dict[str, Any]:
        self._check("delete_conversation")
        if cid not in self.convs:
            raise CloudError(404, "no_conversation", "none")
        self.tombstone_conversation(cid)
        return {"cursor": self.seq, "deleted": True}

    async def wipe(self) -> dict[str, Any]:
        self._check("wipe")
        self.convs.clear()
        self.msgs.clear()
        return await self.state()


@pytest.fixture()
def synced(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> Iterator[tuple[TestClient, MuseService, MockLLM, FakeSyncRelay]]:
    """A signed-in runtime (a key in the vault, the hub switched off so no socket opens) whose
    sync engine talks to the fake relay; pushes go out a few milliseconds after a turn. Side
    chats are switched on here (C9 default is off; the C9 tests below cover the default)."""
    settings.server.token = "secret-token"
    settings.hub.enabled = False
    settings.hub.device_id = "pc-self"
    settings.hub.name = "Desk"
    settings.sync.side_chats = True
    settings.cloud.base_url = "http://127.0.0.1:9"  # never reached: every relay call is faked

    async def fake_models(self: CloudClient) -> list[dict[str, Any]]:
        return []

    monkeypatch.setattr(CloudClient, "models", fake_models)
    monkeypatch.setattr(engine_mod, "PUSH_DELAY_S", 0.05)
    llm = MockLLM([])
    service = MuseService(settings, llm=llm)
    service.app.vault.set("NANOMUSE_CLOUD_KEY", "test-key")
    relay = FakeSyncRelay()
    service.sync.client = relay  # type: ignore[assignment]
    app = create_app(settings, service)
    with TestClient(app) as client:
        client.headers["Authorization"] = "Bearer secret-token"
        # start() scheduled the first pull on the app's loop; it lands before a test adds rows
        # to the relay, or on a slow machine it takes them and the test's own pull applies 0
        wait_for(lambda: relay.pulls)
        yield client, service, llm, relay


def _events(client: TestClient, thread: str) -> list[dict[str, Any]]:
    return client.get(f"/api/threads/{thread}/events").json()["events"]


# ----------------------------------------------------------------------------- push
def test_a_finished_turn_is_pushed_as_the_main_conversation(synced) -> None:
    client, service, llm, relay = synced
    llm.script.append(LLMResponse(content="Hello from the desk", finish_reason="stop"))
    r = client.post(f"/api/threads/{MAIN_THREAD}/send", json={"text": "hi there"})
    assert r.status_code == 200
    wait_for(lambda: len(relay.msgs) == 2)
    main = next(c for c in relay.convs.values() if c["kind"] == "main")
    assert main["title"] == "Main chat" and main["device"] == "pc-self"
    texts = sorted((m["role"], m["text"]) for m in relay.msgs.values())
    assert texts == [("assistant", "Hello from the desk"), ("user", "hi there")]
    # the events carry their mid and are marked, so the next push sends nothing
    evs = [e for e in _events(client, MAIN_THREAD) if e["type"] in ("user", "assistant")]
    assert all(e.get("synced") and e.get("mid") in relay.msgs for e in evs)
    assert service.sync.cid_of(MAIN_THREAD) == main["cid"]
    before = len(relay.pushes)
    client.portal.call(service.sync.push)  # type: ignore[union-attr]
    assert len(relay.pushes) == before
    # sync.json remembers the cid; the cursor catches up on the pull that follows a push
    state = service.sync.state
    assert state["cids"][MAIN_THREAD] == main["cid"]
    wait_for(lambda: state["cursor"] == relay.seq)
    # a rename and a new side chat go up on their own; deleting one tombstones it on the relay
    side = client.post("/api/threads", json={"title": "Trip"}).json()
    wait_for(lambda: any(c["title"] == "Trip" for c in relay.convs.values()))
    client.patch(f"/api/threads/{side['id']}", json={"title": "Trip to Kyoto"})
    wait_for(lambda: any(c["title"] == "Trip to Kyoto" for c in relay.convs.values()))
    cid = service.sync.cid_of(side["id"])
    client.delete(f"/api/threads/{side['id']}")
    wait_for(lambda: relay.convs[cid]["deleted"])
    assert service.sync.cid_of(side["id"]) is None


def test_the_second_main_adopts_the_accounts_id(synced) -> None:
    client, service, llm, relay = synced
    # another device pushed the account's main chat already, with a message in it
    theirs = str(uuid.uuid4())
    relay.add_conversation(theirs, "main", "Main chat")
    relay.add_message(theirs, "user", "from the phone")
    # our main chat has a turn the relay has not seen; we push before pulling (the race)
    llm.script.append(LLMResponse(content="desk answer", finish_reason="stop"))
    client.post(f"/api/threads/{MAIN_THREAD}/send", json={"text": "desk question"})
    wait_for(lambda: any(m["text"] == "desk answer" for m in relay.msgs.values()))
    # refused with main_exists, re-posted under theirs: one main on the relay, everything in it
    assert sum(1 for c in relay.convs.values() if c["kind"] == "main") == 1
    assert service.sync.cid_of(MAIN_THREAD) == theirs
    assert {m["cid"] for m in relay.msgs.values()} == {theirs}
    assert len(relay.pushes) >= 2
    # and the phone's message is in our main chat after a pull
    client.post("/api/sync/pull")
    texts = [e["text"] for e in _events(client, MAIN_THREAD) if e["type"] == "user"]
    assert "from the phone" in texts and "desk question" in texts


# ----------------------------------------------------------------------------- pull
def test_pull_makes_threads_and_history_and_tombstones_remove(synced) -> None:
    client, service, llm, relay = synced
    # the start-up chain (pull, the push 50 ms later, the pull that follows a push) is through
    # before the rows go on the relay; on a slow runner one of those pulls took them and the
    # pull below applied 0 (the macOS runner, once the fixture waited for the first pull alone)
    wait_for(lambda: settled(service))
    cid = str(uuid.uuid4())
    relay.add_conversation(cid, "side", "Dinner plans", device="phone-1")
    m1 = relay.add_message(cid, "user", "book a table", created_at=1738000050)
    relay.add_message(cid, "assistant", "Booked for 7", created_at=1738000060)
    r = client.post("/api/sync/pull")
    assert r.status_code == 200 and r.json()["applied"] == 3
    threads = client.get("/api/threads").json()
    t = next(x for x in threads if x["title"] == "Dinner plans")
    assert t["origin_device"] == "phone-1" and t["origin_device_name"] == "Pixel 8"
    evs = _events(client, t["id"])
    assert [(e["type"], e["text"]) for e in evs] == [
        ("user", "book a table"),
        ("assistant", "Booked for 7"),
    ]
    assert all(e["synced"] and e["via_device_name"] == "Pixel 8" for e in evs)
    assert evs[1]["final"] is True
    # the agent reads the synced transcript as history on its next turn here
    thread = service.threads[t["id"]]
    assert [(m.role.value, m.content) for m in thread.agent.messages] == [
        ("user", "book a table"),
        ("assistant", "Booked for 7"),
    ]
    llm.script.append(LLMResponse(content="Changed to 8", finish_reason="stop"))
    client.post(f"/api/threads/{t['id']}/send", json={"text": "make it 8"})
    wait_for(lambda: any(m["text"] == "Changed to 8" for m in relay.msgs.values()))
    seen = [m.content for m in llm.calls[-1]["messages"] if m.role.value == "user"]
    assert "book a table" in seen and "make it 8" in seen
    # the new turn synced back into the same conversation
    assert {m["cid"] for m in relay.msgs.values()} == {cid}
    # an edit elsewhere: the old message tombstoned → gone here; the chat deleted → thread gone
    relay.tombstone_message(m1)
    client.post("/api/sync/pull")
    assert "book a table" not in [e["text"] for e in _events(client, t["id"])]
    relay.tombstone_conversation(cid)
    client.post("/api/sync/pull")
    assert t["id"] not in {x["id"] for x in client.get("/api/threads").json()}
    # the tombstone came from the relay: no DELETE went back
    assert "delete_conversation" not in relay.calls
    # a renamed chat elsewhere is renamed here
    cid2 = str(uuid.uuid4())
    relay.add_conversation(cid2, "side", "Old name")
    client.post("/api/sync/pull")
    relay.convs[cid2].update(title="New name", seq=relay._next())
    client.post("/api/sync/pull")
    assert "New name" in [x["title"] for x in client.get("/api/threads").json()]
    # a chat renamed after its messages (the usual auto-title): the conversation's seq is
    # above the messages', and the messages still land in it on a single pull
    cid3 = str(uuid.uuid4())
    relay.add_conversation(cid3, "side", "New chat")
    relay.add_message(cid3, "user", "late title", created_at=1738000070)
    relay.convs[cid3].update(title="Titled later", seq=relay._next())
    client.post("/api/sync/pull")
    t3 = next(x for x in client.get("/api/threads").json() if x["title"] == "Titled later")
    assert [e["text"] for e in _events(client, t3["id"])] == ["late title"]


def test_the_hub_frame_triggers_a_pull_and_our_own_echo_does_not(synced) -> None:
    client, service, llm, relay = synced
    # launch: a pull, the main chat's title pushed, the pull that follows a push
    wait_for(lambda: relay.calls.count("changes") >= 2)
    time.sleep(0.1)
    relay.calls.clear()
    cid = str(uuid.uuid4())
    relay.add_conversation(cid, "side", "From the phone")
    client.portal.call(
        service.sync.on_frame,
        {"type": "sync", "what": "conversations", "cursor": relay.seq, "from": "pc-self"},
    )  # type: ignore[union-attr]
    time.sleep(0.2)
    assert "changes" not in relay.calls
    client.portal.call(
        service.sync.on_frame,
        {"type": "sync", "what": "conversations", "cursor": relay.seq, "from": "phone-1"},
    )  # type: ignore[union-attr]
    wait_for(lambda: "From the phone" in [x["title"] for x in client.get("/api/threads").json()])


# ----------------------------------------------------------------------------- the switch, the failures
def test_the_switch_and_the_relays_refusals(synced) -> None:
    client, service, llm, relay = synced
    st = client.get("/api/sync/state").json()
    assert st["enabled"] is True and st["available"] is True and st["relay"]["enabled"] is True
    cid = str(uuid.uuid4())
    relay.add_conversation(cid, "side", "Elsewhere")
    relay.add_message(cid, "user", "x")
    client.post("/api/sync/pull")
    # off: the relay deletes, nothing more goes out
    st = client.put("/api/sync/state", json={"enabled": False}).json()
    assert (
        st["enabled"] is False and relay.enabled is False and relay.convs == {} and relay.msgs == {}
    )
    assert service.sync.active is False
    calls = len(relay.calls)
    client.post("/api/threads", json={"title": "Quiet"})
    time.sleep(0.2)
    assert len(relay.calls) == calls
    # on again: this device's conversations go up in full
    st = client.put("/api/sync/state", json={"enabled": True}).json()
    assert st["enabled"] is True
    wait_for(
        lambda: (
            any(c["title"] == "Quiet" for c in relay.convs.values())
            and any(c["title"] == "Elsewhere" for c in relay.convs.values())
        )
    )
    # "Delete synced conversations" empties the relay and keeps the switch
    st = client.post("/api/sync/delete").json()
    assert relay.convs == {} and st["enabled"] is True and relay.enabled is True
    # sync_off from the relay (turned off on another device) flips the switch here
    relay.enabled = False
    client.post("/api/sync/pull")
    assert client.get("/api/sync/state").json()["enabled"] is False
    relay.enabled = True
    client.put("/api/sync/state", json={"enabled": True})
    # a refused key pauses until the next sign-in
    relay.fail = CloudError(401, "bad_key", "no")
    client.post("/api/sync/pull")
    assert service.sync.active is False and client.get("/api/sync/state").json()["paused"] is True
    client.portal.call(service.sync.account_changed, "acct-1")  # type: ignore[union-attr]
    assert service.sync.active is True
    # the main chat joins the first account on its push (C10: owner = account.id); the push
    # must have landed before the relay's store is swapped under it
    wait_for(lambda: settled(service) and service.sync.owner_of(MAIN_THREAD) == "acct-1")
    old = service.sync.cid_of(MAIN_THREAD)
    assert old is not None and relay_main(relay) == old
    # a different account starts from zero: a fresh main chat, pushed anew under a new id
    # (the first account's was empty, so there is nothing to keep aside)
    pushes = len(relay.pushes)
    relay.switch_account("acct-2")
    client.portal.call(service.sync.account_changed, "acct-2")  # type: ignore[union-attr]
    assert service.sync.state["account_id"] == "acct-2"
    wait_for(lambda: relay.pulls and relay.pulls[-1]["since"] == 0)  # the cursor started over
    wait_for(lambda: len(relay.pushes) > pushes)
    wait_for(lambda: settled(service) and service.sync.cid_of(MAIN_THREAD) not in (None, old))
    assert relay_main(relay) == service.sync.cid_of(MAIN_THREAD)
    assert service.sync.state["mains"] == {} and service.sync.owner_of(MAIN_THREAD) == "acct-2"


def test_signed_out_runtimes_do_not_sync(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings.server.token = "t"
    settings.hub.enabled = False
    settings.cloud.base_url = "http://127.0.0.1:9"
    monkeypatch.setattr(engine_mod, "PUSH_DELAY_S", 0.05)
    service = MuseService(settings, llm=MockLLM([]))
    relay = FakeSyncRelay()
    service.sync.client = relay  # type: ignore[assignment]
    with TestClient(create_app(settings, service)) as client:
        client.headers["Authorization"] = "Bearer t"
        st = client.get("/api/sync/state").json()
        assert st["available"] is False and st["relay"] is None
        client.post("/api/threads", json={"title": "Local only"})
        time.sleep(0.2)
        assert relay.calls == []
        assert client.post("/api/sync/pull").json()["applied"] == 0


# ----------------------------------------------------------------------------- @device in the composer
def test_a_mention_hands_the_turn_to_the_device(synced, monkeypatch: pytest.MonkeyPatch) -> None:
    client, service, llm, relay = synced
    monkeypatch.setattr(service.hub, "others", lambda: [d for d in DEVICES if d["id"] != "pc-self"])
    llm.script.append(LLMResponse(content="Asked the phone.", finish_reason="stop"))
    r = client.post(
        f"/api/threads/{MAIN_THREAD}/send", json={"text": "@Pixel 8 what is on the screen?"}
    )
    assert r.status_code == 200
    ev = r.json()["event"]
    assert (
        ev["text"] == "what is on the screen?"
        and ev["to_device"] == "phone-1"
        and ev["to_device_name"] == "Pixel 8"
    )
    wait_for(lambda: llm.calls)
    user = [m.content for m in llm.calls[0]["messages"] if m.role.value == "user"][-1]
    assert user.startswith("[" + system_note("Pixel 8", "phone-1")) and user.endswith(
        "what is on the screen?"
    )
    # no match: the text stays as typed, nothing is addressed
    r = client.post(f"/api/threads/{MAIN_THREAD}/send", json={"text": "@everyone hello"})
    assert r.json()["event"]["text"] == "@everyone hello" and "to_device" not in r.json()["event"]
    # the synced copy carries the text without the mention
    wait_for(lambda: any(m["text"] == "what is on the screen?" for m in relay.msgs.values()))


# ----------------------------------------------------------------------------- C8: one thread
def _signed_in(
    settings: Settings, monkeypatch: pytest.MonkeyPatch, side_chats: bool = True
) -> MuseService:
    settings.server.token = "secret-token"
    settings.hub.enabled = False
    settings.hub.device_id = "pc-self"
    settings.hub.name = "Desk"
    settings.sync.side_chats = side_chats
    settings.cloud.base_url = "http://127.0.0.1:9"

    async def fake_models(self: CloudClient) -> list[dict[str, Any]]:
        return []

    monkeypatch.setattr(CloudClient, "models", fake_models)
    monkeypatch.setattr(engine_mod, "PUSH_DELAY_S", 0.05)
    service = MuseService(settings, llm=MockLLM([]))
    service.app.vault.set("NANOMUSE_CLOUD_KEY", "test-key")
    return service


def test_sign_in_backfills_the_whole_history_oldest_first(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A runtime with a long past signs in: everything eligible goes up — the first
    conversation included — oldest first, 200 messages a POST, across several rounds."""
    service = _signed_in(settings, monkeypatch)
    relay = FakeSyncRelay()
    service.sync.client = relay  # type: ignore[assignment]
    main = service.threads[MAIN_THREAD]
    base = 1738000000
    for i in range(130):  # 260 messages in the main chat alone: more than one page
        main.timeline.add(
            {"type": "user", "text": f"q{i}", "ts": _iso_at(base + 10 * i)},
        )
        main.timeline.add(
            {"type": "assistant", "text": f"a{i}", "final": True, "ts": _iso_at(base + 10 * i + 5)}
        )
    side = service.create_thread("An old side chat")
    side.timeline.add({"type": "user", "text": "side q", "ts": _iso_at(base + 5000)})
    # not eligible: a step of the agent's, a chat for another device
    main.timeline.add({"type": "assistant", "text": "thinking…", "ts": _iso_at(base + 9000)})
    other = service.create_thread("On the phone")
    other.device = "phone-1"
    other.timeline.add({"type": "user", "text": "runs on the phone", "ts": _iso_at(base + 9500)})
    with TestClient(create_app(settings, service)) as client:
        client.headers["Authorization"] = "Bearer secret-token"
        wait_for(lambda: len(relay.msgs) == 261)
        texts = {m["text"] for m in relay.msgs.values()}
        assert "thinking…" not in texts and "runs on the phone" not in texts
        assert {c["title"] for c in relay.convs.values()} == {"Main chat", "An old side chat"}
        # pages of 200, the main chat oldest first, then the rest
        batches = [p["messages"] for p in relay.pushes if p["messages"]]
        assert len(batches[0]) == 200 and [m["text"] for m in batches[0][:4]] == [
            "q0",
            "a0",
            "q1",
            "a1",
        ]
        stamps = [m["created_at"] for p in batches for m in p if m["cid"] == relay_main(relay)]
        assert stamps == sorted(stamps)
        # the pulled echo adds nothing: still one bubble per line
        client.post("/api/sync/pull")
        evs = client.get(f"/api/threads/{MAIN_THREAD}/events?limit=1000").json()["events"]
        evs = [e for e in evs if e["type"] in ("user", "assistant")]
        assert len(evs) == 261 and sum(1 for e in evs if e["text"] == "q0") == 1


def _iso_at(unix: int) -> str:
    return engine_mod._iso(unix)


def relay_main(relay: FakeSyncRelay) -> str:
    return next(c["cid"] for c in relay.convs.values() if c["kind"] == "main")


def test_the_persons_message_is_pushed_when_it_is_sent(synced) -> None:
    """Real time (C8): the user line goes up at once, the assistant's text when the turn ends."""
    client, service, llm, relay = synced
    gate = asyncio.Event()

    class GatedLLM(MockLLM):
        """Answers only once the test lets it: the turn stays open meanwhile."""

        async def ask(self, messages: Any, *args: Any, **kwargs: Any) -> LLMResponse:
            await gate.wait()
            return await super().ask(messages, *args, **kwargs)

    service.threads[MAIN_THREAD].agent.llm = GatedLLM(
        [LLMResponse(content="late answer", finish_reason="stop")]
    )
    client.post(f"/api/threads/{MAIN_THREAD}/send", json={"text": "right now"})
    wait_for(lambda: any(m["text"] == "right now" for m in relay.msgs.values()))
    # the turn is still running: nothing from the assistant yet
    assert [m["role"] for m in relay.msgs.values()] == ["user"]
    assert service.threads[MAIN_THREAD].busy
    client.portal.call(gate.set)  # type: ignore[union-attr]
    wait_for(lambda: any(m["text"] == "late answer" for m in relay.msgs.values()))
    assert sorted(m["role"] for m in relay.msgs.values()) == ["assistant", "user"]


def test_the_main_chat_merges_the_other_devices_turns_in_time_order(synced) -> None:
    client, service, llm, relay = synced
    # a turn here, at "now"
    llm.script.append(LLMResponse(content="desk answer", finish_reason="stop"))
    client.post(f"/api/threads/{MAIN_THREAD}/send", json={"text": "desk question"})
    wait_for(lambda: any(m["text"] == "desk answer" for m in relay.msgs.values()))
    cid = relay_main(relay)
    local_ts = next(e["ts"] for e in _events(client, MAIN_THREAD) if e["text"] == "desk question")
    local_unix = engine_mod._unix(local_ts)
    # the phone wrote into the same conversation: one turn an hour ago, one just after ours
    relay.add_message(cid, "user", "earlier on the phone", created_at=local_unix - 3600)
    relay.add_message(cid, "assistant", "phone answer", created_at=local_unix - 3590)
    relay.add_message(cid, "user", "later on the phone", created_at=local_unix + 60)
    client.post("/api/sync/pull")
    evs = [e for e in _events(client, MAIN_THREAD) if e["type"] in ("user", "assistant")]
    assert [e["text"] for e in evs] == [
        "earlier on the phone",
        "phone answer",
        "desk question",
        "desk answer",
        "later on the phone",
    ]
    # the phone's rows carry the caption, ours do not; still one main chat in the list
    assert all(e.get("via_device_name") == "Pixel 8" for e in evs if "phone" in e["text"])
    assert all("via_device" not in e for e in evs if "desk" in e["text"])
    titles = [t["title"] for t in client.get("/api/threads").json()]
    assert titles.count("Main chat") == 1 and not any(
        t.get("origin_device") for t in client.get("/api/threads").json()
    )
    # the agent knows what was said elsewhere on its next turn here
    llm.script.append(LLMResponse(content="ok", finish_reason="stop"))
    client.post(f"/api/threads/{MAIN_THREAD}/send", json={"text": "and now?"})
    wait_for(lambda: any(m["text"] == "ok" for m in relay.msgs.values()))
    seen = [m.content for m in llm.calls[-1]["messages"] if m.role.value == "user"]
    assert "later on the phone" in seen
    # the switch off and on again: our whole history goes up — the phone's rows are the phone's
    client.put("/api/sync/state", json={"enabled": False})
    client.put("/api/sync/state", json={"enabled": True})
    wait_for(lambda: any(m["text"] == "ok" for m in relay.msgs.values()))
    assert sorted(m["text"] for m in relay.msgs.values()) == [
        "and now?",
        "desk answer",
        "desk question",
        "ok",
    ]


def test_the_echo_of_our_own_push_is_never_a_second_bubble(synced) -> None:
    client, service, llm, relay = synced
    llm.script.append(LLMResponse(content="echo answer", finish_reason="stop"))
    client.post(f"/api/threads/{MAIN_THREAD}/send", json={"text": "echo question"})
    wait_for(lambda: any(m["text"] == "echo answer" for m in relay.msgs.values()))
    wait_for(lambda: service.sync.cursor == relay.seq)
    for _ in range(2):
        client.post("/api/sync/pull")
    evs = [e for e in _events(client, MAIN_THREAD) if e["type"] in ("user", "assistant")]
    assert [e["text"] for e in evs] == ["echo question", "echo answer"]
    # the mapping lost (a reset, a trimmed timeline): a row from this device is still not
    # added again — the relay says who wrote it
    service.sync.state["cursor"] = 0
    for e in service.threads[MAIN_THREAD].timeline.events:
        e.pop("mid", None)
    client.post("/api/sync/pull")
    evs = [e for e in _events(client, MAIN_THREAD) if e["type"] in ("user", "assistant")]
    assert [e["text"] for e in evs] == ["echo question", "echo answer"]


def test_sync_state_survives_a_restart(settings: Settings, tmp_path: Path) -> None:
    settings.hub.enabled = False
    service = MuseService(settings, llm=MockLLM([]))
    service.sync.state["cids"][MAIN_THREAD] = "abc"
    service.sync.state["cursor"] = 7
    service.sync._save()
    again = MuseService(settings, llm=MockLLM([]))
    assert again.sync.cid_of(MAIN_THREAD) == "abc" and again.sync.cursor == 7
    assert again.sync.thread_of("abc") is again.threads[MAIN_THREAD]


# ----------------------------------------------------------------------------- C9: main first
@pytest.fixture()
def main_only(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> Iterator[tuple[TestClient, MuseService, MockLLM, FakeSyncRelay]]:
    """The default: side chats off — the main conversation alone moves."""
    service = _signed_in(settings, monkeypatch, side_chats=False)
    relay = FakeSyncRelay()
    service.sync.client = relay  # type: ignore[assignment]
    llm = service.threads[MAIN_THREAD].agent.llm
    assert isinstance(llm, MockLLM)
    with TestClient(create_app(settings, service)) as client:
        client.headers["Authorization"] = "Bearer secret-token"
        yield client, service, llm, relay


def test_side_chats_stay_local_by_default(main_only) -> None:
    client, service, llm, relay = main_only
    st = client.get("/api/sync/state").json()
    assert st["enabled"] is True and st["side_chats"] is False and st["working"] == []
    # the first pull of a fresh device: the tail of the main scope
    wait_for(lambda: relay.pulls)
    assert relay.pulls[0] == {"since": 0, "limit": 500, "scope": "main", "tail": 300}
    # a turn in the main chat goes up; a side chat here does not
    llm.script.append(LLMResponse(content="main answer", finish_reason="stop"))
    client.post(f"/api/threads/{MAIN_THREAD}/send", json={"text": "main question"})
    wait_for(lambda: any(m["text"] == "main answer" for m in relay.msgs.values()))
    side = client.post("/api/threads", json={"title": "Local work"}).json()
    llm.script.append(LLMResponse(content="side answer", finish_reason="stop"))
    client.post(f"/api/threads/{side['id']}/send", json={"text": "side question"})
    wait_for(lambda: any(e["type"] == "assistant" for e in _events(client, side["id"])))
    time.sleep(0.3)
    assert {c["kind"] for c in relay.convs.values()} == {"main"}
    assert "side question" not in {m["text"] for m in relay.msgs.values()}
    assert service.sync.cid_of(side["id"]) is None
    # later pulls ask for the main scope from the cursor (the tail is for a cursor at zero)
    wait_for(lambda: service.sync.cursor == relay.seq)
    client.post("/api/sync/pull")
    assert all(p["scope"] == "main" for p in relay.pulls)
    assert relay.pulls[-1]["tail"] == 0 and relay.pulls[-1]["since"] == relay.seq > 0
    # a side row that still arrives (an older relay) is ignored; a main row is applied
    cid = str(uuid.uuid4())
    relay.add_conversation(cid, "side", "From the phone")
    relay.add_message(cid, "user", "phone side")
    relay.add_message(relay_main(relay), "user", "phone main", created_at=int(time.time()) + 1)
    client.post("/api/sync/pull")
    titles = [t["title"] for t in client.get("/api/threads").json()]
    assert "From the phone" not in titles
    assert "phone main" in [e["text"] for e in _events(client, MAIN_THREAD)]
    # deleting the local side chat sends no tombstone: nothing of it was ever on the relay
    calls = relay.calls.count("delete_conversation")
    client.delete(f"/api/threads/{side['id']}")
    time.sleep(0.2)
    assert relay.calls.count("delete_conversation") == calls


def test_turning_side_chats_on_pulls_once_from_zero_and_pushes_them(main_only) -> None:
    client, service, llm, relay = main_only
    wait_for(lambda: relay.pulls)
    # a side chat here, and one on the phone that the main-only pulls left out
    side = client.post("/api/threads", json={"title": "Here first"}).json()
    theirs = str(uuid.uuid4())
    relay.add_conversation(theirs, "side", "Phone side")
    relay.add_message(theirs, "user", "from the phone's side chat")
    client.post("/api/sync/pull")
    assert "Phone side" not in [t["title"] for t in client.get("/api/threads").json()]
    cursor_before = service.sync.cursor
    assert cursor_before == relay.seq
    n_pulls = len(relay.pulls)
    st = client.put("/api/sync/state", json={"side_chats": True}).json()
    assert st["side_chats"] is True and service.sync.state["side_chats"] is True
    # one pull from zero, everything, as a tail — the phone's side chat is here now
    wait_for(lambda: len(relay.pulls) > n_pulls)
    assert relay.pulls[n_pulls] == {"since": 0, "limit": 500, "scope": "all", "tail": 300}
    wait_for(lambda: "Phone side" in [t["title"] for t in client.get("/api/threads").json()])
    # and ours went up
    wait_for(lambda: any(c["title"] == "Here first" for c in relay.convs.values()))
    assert service.sync.cid_of(side["id"]) is not None
    # the cursor did not go backwards; the pulls that follow are `all` from the cursor
    wait_for(lambda: service.sync.cursor == relay.seq)
    assert service.sync.cursor >= cursor_before
    assert relay.pulls[-1]["scope"] == "all" and relay.pulls[-1]["tail"] == 0
    # off again: a new side chat stays here, the synced one keeps its place everywhere
    client.put("/api/sync/state", json={"side_chats": False})
    assert client.get("/api/sync/state").json()["side_chats"] is False
    client.post("/api/threads", json={"title": "After off"})
    time.sleep(0.3)
    assert "After off" not in {c["title"] for c in relay.convs.values()}
    assert any(c["title"] == "Here first" for c in relay.convs.values())
    assert "Phone side" in [t["title"] for t in client.get("/api/threads").json()]
    # the setting survives a restart
    assert client.put("/api/sync/state", json={}).status_code == 400
    again = MuseService(settings=service.settings, llm=MockLLM([]))
    assert again.sync.side_chats is False


def test_the_status_watcher_heals_after_the_bus_drops_it(
    main_only, monkeypatch: pytest.MonkeyPatch
) -> None:
    """0.31: the bus discards a subscriber whose queue filled (a burst of stream frames
    while the watcher waited its turn). The watcher notices within one poll and
    subscribes again, so presence keeps following the run instead of hanging on a queue
    nobody fills."""
    client, service, llm, relay = main_only
    monkeypatch.setattr(engine_mod, "PRESENCE_INTERVAL_S", 0.01)
    monkeypatch.setattr(engine_mod, "WATCH_POLL_S", 0.05)
    gate = asyncio.Event()

    class GatedLLM(MockLLM):
        async def ask(self, messages: Any, *args: Any, **kwargs: Any) -> LLMResponse:
            await gate.wait()
            return await super().ask(messages, *args, **kwargs)

    service.threads[MAIN_THREAD].agent.llm = GatedLLM(
        [LLMResponse(content="done", finish_reason="stop")]
    )
    client.post(f"/api/threads/{MAIN_THREAD}/send", json={"text": "go"})
    wait_for(lambda: relay.working_calls)
    dropped = service.sync._status_queue
    assert dropped is not None and service.bus.subscribed(dropped)
    # the bus drops the slow subscriber — exactly what publish does on a full queue
    client.portal.call(service.bus.unsubscribe, dropped)  # type: ignore[union-attr]

    # a later step still reaches the relay: the watcher healed itself. The presence
    # task the first status scheduled refreshes itself off ui.status and can carry the
    # new step before the watcher's poll swaps the dropped queue, so the delivery does
    # not by itself prove the heal: the fresh queue is waited for, then the delivery.
    def healed() -> bool:
        fresh = service.sync._status_queue
        return fresh is not None and fresh is not dropped and service.bus.subscribed(fresh)

    client.portal.call(lambda: service.ui.set_status("working", "after the drop", MAIN_THREAD))
    wait_for(healed)
    wait_for(lambda: any(c.get("detail") == "after the drop" for c in relay.working_calls))
    client.portal.call(gate.set)  # type: ignore[union-attr]
    wait_for(lambda: relay.working_calls[-1]["working"] is False)


def test_presence_follows_the_runs_steps(main_only, monkeypatch: pytest.MonkeyPatch) -> None:
    """0.31: the presence the other devices see says what the run is doing — the state and
    the step's own words — and follows the run as the steps change, one throttled post
    that carries the newest step, not one per change."""
    client, service, llm, relay = main_only
    monkeypatch.setattr(engine_mod, "PRESENCE_INTERVAL_S", 0.01)
    gate = asyncio.Event()

    class GatedLLM(MockLLM):
        async def ask(self, messages: Any, *args: Any, **kwargs: Any) -> LLMResponse:
            await gate.wait()
            return await super().ask(messages, *args, **kwargs)

    service.threads[MAIN_THREAD].agent.llm = GatedLLM(
        [LLMResponse(content="done", finish_reason="stop")]
    )
    client.post(f"/api/threads/{MAIN_THREAD}/send", json={"text": "go"})
    wait_for(lambda: relay.working_calls)
    assert relay.working_calls[0]["working"] is True

    # a step arrives on the bus (the run calls set_status before every tool) and presence
    # follows it — the watcher reads the frames, the post carries the newest step
    client.portal.call(lambda: service.ui.set_status("working", "打开携程网站", MAIN_THREAD))
    wait_for(lambda: any(c.get("detail") == "打开携程网站" for c in relay.working_calls))
    # two steps in quick succession: each throttled round reads the newest status, so the
    # other devices end up on the newest step — whether a round caught the middle one is
    # timing, not contract
    client.portal.call(lambda: service.ui.set_status("working", "shell: ls", MAIN_THREAD))
    client.portal.call(lambda: service.ui.set_status("working", "读文件 config.toml", MAIN_THREAD))
    wait_for(
        lambda: (
            relay.working_calls and relay.working_calls[-1].get("detail") == "读文件 config.toml"
        )
    )
    # nothing new to say: no further posts
    calls_so_far = len(relay.working_calls)
    client.portal.call(lambda: service.ui.set_status("working", "读文件 config.toml", MAIN_THREAD))
    time.sleep(0.1)
    assert len(relay.working_calls) == calls_so_far
    # waiting on the person reads as waiting
    client.portal.call(lambda: service.ui.set_status("waiting", "等你确认", MAIN_THREAD))
    wait_for(lambda: any(c.get("state") == "waiting" for c in relay.working_calls))
    # the run ends: the line goes
    client.portal.call(gate.set)  # type: ignore[union-attr]
    wait_for(lambda: relay.working_calls[-1]["working"] is False)


def test_working_goes_up_with_the_turn_and_comes_down_from_the_hub(main_only) -> None:
    client, service, llm, relay = main_only
    gate = asyncio.Event()

    class GatedLLM(MockLLM):
        async def ask(self, messages: Any, *args: Any, **kwargs: Any) -> LLMResponse:
            await gate.wait()
            return await super().ask(messages, *args, **kwargs)

    service.threads[MAIN_THREAD].agent.llm = GatedLLM(
        [LLMResponse(content="late", finish_reason="stop")]
    )
    client.post(f"/api/threads/{MAIN_THREAD}/send", json={"text": "go"})
    # working: true right after the person's message is on the relay, under the main's cid
    wait_for(lambda: relay.working_calls)
    # 0.31: a `working: true` carries the run's state beside the device
    assert relay.working_calls[0] == {
        "cid": relay_main(relay),
        "working": True,
        "device": "pc-self",
        "state": "working",
    }
    assert [m["text"] for m in relay.msgs.values()] == ["go"]
    client.portal.call(gate.set)  # type: ignore[union-attr]
    wait_for(lambda: len(relay.working_calls) == 2)
    assert relay.working_calls[1]["working"] is False
    assert any(m["text"] == "late" for m in relay.msgs.values())
    # the other way: the phone says it is working on the main chat
    main_cid = relay_main(relay)
    frame = {
        "type": "working",
        "cid": main_cid,
        "from": "phone-1",
        "device_name": "Pixel 8",
        "working": True,
        "at": int(time.time()),
    }
    client.portal.call(service.sync.on_frame, frame)  # type: ignore[union-attr]
    st = client.get("/api/sync/state").json()
    assert st["working"] == [
        {
            "thread": MAIN_THREAD,
            "cid": main_cid,
            "device": "phone-1",
            "device_name": "Pixel 8",
            "state": "working",
            "detail": "",
            "at": frame["at"],
        }
    ]
    # our own echo is ignored; another device's `false` does not clear the phone's line
    client.portal.call(service.sync.on_frame, {**frame, "from": "pc-self"})  # type: ignore[union-attr]
    client.portal.call(  # type: ignore[union-attr]
        service.sync.on_frame, {**frame, "from": "mac-1", "working": False}
    )
    assert len(client.get("/api/sync/state").json()["working"]) == 1
    # the phone's reply arrives: the line goes
    relay.add_message(main_cid, "assistant", "phone reply", created_at=int(time.time()) + 2)
    client.post("/api/sync/pull")
    assert client.get("/api/sync/state").json()["working"] == []
    # ten minutes without news and it goes on its own
    client.portal.call(service.sync.on_frame, {**frame, "at": int(time.time()) - 601})  # type: ignore[union-attr]
    assert client.get("/api/sync/state").json()["working"] == []
    # an unknown conversation is nobody's line
    client.portal.call(service.sync.on_frame, {**frame, "cid": str(uuid.uuid4())})  # type: ignore[union-attr]
    assert client.get("/api/sync/state").json()["working"] == []
    # a relay that refuses presence changes nothing here: the turn and its push go on
    relay.fail_working = CloudError(404, "no_conversation", "none")
    service.threads[MAIN_THREAD].agent.llm = MockLLM(
        [LLMResponse(content="fine", finish_reason="stop")]
    )
    client.post(f"/api/threads/{MAIN_THREAD}/send", json={"text": "again"})
    wait_for(lambda: any(m["text"] == "fine" for m in relay.msgs.values()))
    wait_for(lambda: relay.calls.count("working") >= 3)
    assert service.sync.active and client.get("/api/sync/state").json()["error"] == ""


def test_the_working_frame_reaches_the_web_app(main_only) -> None:
    client, service, llm, relay = main_only
    wait_for(lambda: relay.pulls)
    llm.script.append(LLMResponse(content="ok", finish_reason="stop"))
    client.post(f"/api/threads/{MAIN_THREAD}/send", json={"text": "hi"})
    wait_for(lambda: any(m["text"] == "ok" for m in relay.msgs.values()))
    main_cid = relay_main(relay)
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"kind": "auth", "token": "secret-token"})
        hello = ws.receive_json()
        assert hello["kind"] == "hello" and hello["state"]["working"] == []
        frame = {
            "type": "working",
            "cid": main_cid,
            "from": "phone-1",
            "device_name": "Pixel 8",
            "working": True,
            "at": int(time.time()),
        }
        client.portal.call(service.sync.on_frame, frame)  # type: ignore[union-attr]
        msg = ws.receive_json()
        while msg["kind"] != "working":
            msg = ws.receive_json()
        assert msg == {
            "kind": "working",
            "thread": MAIN_THREAD,
            "cid": main_cid,
            "device": "phone-1",
            "device_name": "Pixel 8",
            "state": "working",
            "detail": "",
            "working": True,
            "at": frame["at"],
        }
    # a fresh page sees it in the snapshot
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"kind": "auth", "token": "secret-token"})
        assert ws.receive_json()["state"]["working"][0]["device"] == "phone-1"


# ----------------------------------------------------------------------------- C10: whose conversations
def _titles(client: TestClient) -> set[str]:
    return {t["title"] for t in client.get("/api/threads").json()}


def test_a_device_shows_and_pushes_the_current_accounts_conversations_only(synced) -> None:
    """Account A signs in and works; B signs in on the same device: B sees a fresh main chat
    and nothing of A's, pushes nothing of A's; A back: everything of A's again, nothing of
    B's. Signed out, every local conversation is shown."""
    client, service, llm, relay = synced
    client.portal.call(service.sync.account_changed, "acct-A")  # type: ignore[union-attr]
    llm.script.append(LLMResponse(content="A's answer", finish_reason="stop"))
    client.post(f"/api/threads/{MAIN_THREAD}/send", json={"text": "A's question"})
    wait_for(lambda: any(m["text"] == "A's answer" for m in relay.msgs.values()))
    a_side = client.post("/api/threads", json={"title": "A side"}).json()
    wait_for(lambda: settled(service) and service.sync.owner_of(a_side["id"]) == "acct-A")
    assert service.sync.owner_of(MAIN_THREAD) == "acct-A"
    a_main_cid = relay_main(relay)
    # a chat that never synced belongs to nobody (side chats of another device, say)
    local = service.create_thread("Nobody's")
    local.device = "phone-1"
    service._save_index()
    assert _titles(client) == {"Main chat", "A side", "Nobody's"}

    # B signs in: cursor 0, presence gone, A's hidden, a fresh main chat
    service.sync.working["x"] = {"thread": MAIN_THREAD, "cid": "x", "device": "d", "at": 1}
    service.sync.state["cursor"] = 99
    pushes = len(relay.pushes)
    pulls = len(relay.pulls)
    relay.switch_account("acct-B")
    client.portal.call(service.sync.account_changed, "acct-B")  # type: ignore[union-attr]
    assert service.sync.working == {}
    assert _titles(client) == {"Main chat", "Nobody's"}
    main_b = client.get(f"/api/threads/{MAIN_THREAD}/events").json()["events"]
    assert main_b == []
    archived_id = service.sync.state["mains"]["acct-A"]
    archived = service.threads[archived_id]
    assert archived.main_of == "acct-A" and service.sync.cid_of(archived_id) == a_main_cid
    assert [e["text"] for e in archived.timeline.events if e["type"] == "user"] == ["A's question"]
    assert all(e["thread"] == archived_id for e in archived.timeline.events)
    # what B does goes up as B's; nothing of A's is pushed again
    wait_for(lambda: len(relay.pulls) > pulls)
    assert relay.pulls[pulls]["since"] == 0  # the cursor started over
    llm.script.append(LLMResponse(content="B's answer", finish_reason="stop"))
    client.post(f"/api/threads/{MAIN_THREAD}/send", json={"text": "B's question"})
    wait_for(lambda: any(m["text"] == "B's answer" for m in relay.msgs.values()))
    b_side = client.post("/api/threads", json={"title": "B side"}).json()
    wait_for(lambda: settled(service) and service.sync.owner_of(b_side["id"]) == "acct-B")
    sent = {m["cid"] for p in relay.pushes[pushes:] for m in p["messages"]} | {
        c["cid"] for p in relay.pushes[pushes:] for c in p["conversations"]
    }
    assert a_main_cid not in sent and service.sync.cid_of(a_side["id"]) not in sent
    assert service.sync.owner_of(MAIN_THREAD) == "acct-B"
    assert _titles(client) == {"Main chat", "Nobody's", "B side"}
    # the ownerless chat joins B on its first push
    local.device = None
    client.patch(f"/api/threads/{local.id}", json={"title": "Now B's"})
    wait_for(lambda: settled(service) and service.sync.owner_of(local.id) == "acct-B")

    # A comes back: A's main chat and side chat, B's put aside
    relay.switch_account("acct-A")
    client.portal.call(service.sync.account_changed, "acct-A")  # type: ignore[union-attr]
    assert _titles(client) == {"Main chat", "A side"}
    texts = [e["text"] for e in _events(client, MAIN_THREAD) if e["type"] == "user"]
    assert texts == ["A's question"]
    assert service.sync.cid_of(MAIN_THREAD) == a_main_cid
    assert service.sync.owner_of(MAIN_THREAD) == "acct-A"
    assert archived_id not in service.threads and "acct-A" not in service.sync.state["mains"]
    b_kept = service.threads[service.sync.state["mains"]["acct-B"]]
    assert [e["text"] for e in b_kept.timeline.events if e["type"] == "user"] == ["B's question"]
    # the snapshot the web app gets says the same
    assert {t["title"] for t in service.state()["threads"]} == {"Main chat", "A side"}

    # signed out: the device is the person's, everything local is shown
    client.portal.call(service.hub._forget_key)  # type: ignore[union-attr]
    assert not service.hub.signed_in
    assert _titles(client) == {"Main chat", "A side", "B side", "Now B's"}
    kept_meta = next(t for t in client.get("/api/threads").json() if t.get("main_of"))
    assert kept_meta["main_of"] == "acct-B" and kept_meta["title"] == "Main chat"

    # and all of it survives a restart
    again = MuseService(settings=service.settings, llm=MockLLM([]))
    assert again.sync.owner_of(MAIN_THREAD) == "acct-A"
    assert again.sync.state["mains"]["acct-B"] == b_kept.id
    assert again.threads[b_kept.id].main_of == "acct-B"


def test_the_first_sign_in_keeps_the_main_chat_and_a_new_account_relogs_the_hub(
    synced, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, service, llm, relay = synced
    # text from before any sign-in is nobody's: the first account takes it (as before)
    main = service.threads[MAIN_THREAD]
    main.timeline.add({"type": "user", "text": "before sign-in"})
    client.portal.call(service.sync.account_changed, "acct-A")  # type: ignore[union-attr]
    assert "before sign-in" in [e["text"] for e in _events(client, MAIN_THREAD)]
    wait_for(lambda: settled(service) and service.sync.owner_of(MAIN_THREAD) == "acct-A")

    # sign-in through the hub service with another account: the socket and the account's
    # model lists start over (the device list with them), the engine hears the new id
    stopped: list[bool] = []

    class FakeClient:
        running = True
        state = "online"
        state_detail = ""
        devices = [{"id": "x", "name": "Old phone"}]

        async def stop(self) -> None:
            stopped.append(True)

    service.hub.client = FakeClient()  # type: ignore[assignment]
    service.hub.chat_models = ["m"]
    relay.switch_account("acct-B")
    client.portal.call(  # type: ignore[union-attr]
        service.hub._signed_in,
        {"api_key": "key-b", "account": {"id": "acct-B", "hint": "", "channel": "email"}},
    )
    assert stopped == [True] and service.hub.client is None
    assert service.hub.view()["devices"] == [] and service.hub.chat_models == []
    assert service.sync.account_id == "acct-B"
    assert "before sign-in" not in [e["text"] for e in _events(client, MAIN_THREAD)]

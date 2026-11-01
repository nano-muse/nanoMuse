"""The channel manager end to end, with a fake channel plugged into a real server and a
scripted model: pairing, allowlist, group policy, replies, approvals by word, delivery."""

from __future__ import annotations

import json
import time
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from nanomuse.channels.base import Channel, ChannelStatus, Field, InboundFile, InboundMessage
from nanomuse.channels.manager import ChannelManager, thread_id_for
from nanomuse.config import Settings
from nanomuse.llm import MockLLM
from nanomuse.schema import Function, LLMResponse, ToolCall
from nanomuse.server import create_app
from nanomuse.server.service import MuseService


def tc(name: str, **args: Any) -> ToolCall:
    return ToolCall(function=Function(name=name, arguments=json.dumps(args)))


def wait_for(pred, timeout: float = 8.0, interval: float = 0.03):  # noqa: ANN001
    deadline = time.time() + timeout
    while time.time() < deadline:
        value = pred()
        if value:
            return value
        time.sleep(interval)
    raise AssertionError("condition not met in time")


class FakeChannel(Channel):
    name = "fake"
    label = "Fake"
    supports_edit = True
    console_url = "https://example.invalid/console"
    fields = (Field("token", "Token", "secret", required=True),)
    instances: list[FakeChannel] = []

    def __init__(self, settings: dict[str, Any]):
        super().__init__(settings)
        self.sent: list[tuple[str, str, list[str]]] = []
        self.streams: list[tuple[str, str, str, bool]] = []
        self.asks: list[tuple[str, str, str]] = []
        self.typing_calls: list[tuple[str, bool]] = []
        self.stopped = False
        FakeChannel.instances.append(self)

    async def start(self, bus) -> None:  # noqa: ANN001
        await super().start(bus)
        bus.set_status(self.name, "connected", "fake bot")

    async def stop(self) -> None:
        self.stopped = True

    async def send(self, chat_id: str, text: str, *, files: list[str] | None = None) -> str:
        self.sent.append((chat_id, text, list(files or [])))
        return "m1"

    async def stream(self, chat_id: str, stream_id: str, text: str, *, done: bool) -> None:
        self.streams.append((chat_id, stream_id, text, done))

    async def ask(self, chat_id: str, approval_id: str, text: str) -> None:
        self.asks.append((chat_id, approval_id, text))

    async def typing(self, chat_id: str, on: bool) -> None:
        self.typing_calls.append((chat_id, on))

    async def verify(self) -> str:
        return "Bot: fake"

    # ---- what the test says
    def texts(self, chat_id: str = "chat1") -> list[str]:
        """Everything the chat saw: plain sends and completed streams, in order."""
        out = [t for c, t, _ in self.sent if c == chat_id]
        out += [t for c, _, t, done in self.streams if c == chat_id and done]
        return out


def emit(manager: ChannelManager, message: dict[str, Any]) -> None:
    """Publish on the service bus from the test thread (asyncio queues are not thread-safe)."""
    assert manager._loop is not None
    manager._loop.call_soon_threadsafe(manager.svc.bus.publish, message)


def dm(text: str, sender: str = "u1", chat: str = "chat1", **kw: Any) -> InboundMessage:
    return InboundMessage(
        channel="fake", chat_id=chat, sender_id=sender, sender_name="Ann", text=text, **kw
    )


@pytest.fixture()
def chan(
    settings: Settings,
) -> Iterator[tuple[TestClient, MuseService, MockLLM, ChannelManager, FakeChannel]]:
    settings.server.token = "secret-token"
    settings.sentinel.always_allow_tools = ["python_execute"]
    settings.agent.language = "en"
    llm = MockLLM([])
    service = MuseService(settings, llm=llm)
    app = create_app(settings, service)
    manager: ChannelManager = service.channels  # type: ignore[attr-defined]
    manager.types["fake"] = FakeChannel
    manager.status["fake"] = ChannelStatus()
    manager.store.update(FakeChannel, enabled=True, values={"token": "t0k"})
    FakeChannel.instances.clear()
    with TestClient(app) as client:
        client.headers["Authorization"] = "Bearer secret-token"
        wait_for(lambda: manager.status["fake"].state == "connected")
        yield client, service, llm, manager, FakeChannel.instances[0]


def pair(client: TestClient, fake: FakeChannel, sender: str = "u1", chat: str = "chat1") -> str:
    fake.bus.inbound(dm("hello", sender=sender, chat=chat))
    pending = wait_for(lambda: client.get("/api/channels").json()["pending"])
    code = next(p["code"] for p in pending if p["sender_id"] == sender)
    n = len(fake.sent)
    assert client.post(f"/api/channels/pairing/{code}/approve").status_code == 200
    wait_for(lambda: len(fake.sent) > n)
    return code


def test_thread_ids_are_file_safe():
    assert thread_id_for("feishu", "oc_abc:123") == "channel-feishu-oc_abc_123"
    assert thread_id_for("dingtalk", "group:cid+x/y") == "channel-dingtalk-group_cid_x_y"
    assert thread_id_for("telegram", "-100123") == "channel-telegram--100123"
    assert thread_id_for("wecom", "") == "channel-wecom-chat"


def test_thread_ids_fold_case_only_where_ids_are_case_insensitive():
    # Windows resolves two names that differ only by case to one file, and a WeCom user's
    # id is documented case-insensitive, so one person arrives in two spellings: fold.
    assert thread_id_for("wecom", "ZhangSan") == thread_id_for("wecom", "zhangsan")
    assert thread_id_for("wecom", "ZhangSan") == "channel-wecom-zhangsan"
    # ids whose case distinguishes chats keep the case they arrive in
    assert thread_id_for("feishu", "Ou_CaseSensitive") == "channel-feishu-Ou_CaseSensitive"
    assert thread_id_for("dingtalk", "AbC123") == "channel-dingtalk-AbC123"


def test_a_folded_wecom_id_adopts_the_history_an_earlier_spelling_wrote(chan):
    client, service, llm, manager, fake = chan
    folded = thread_id_for("wecom", "zhangsan")
    # the spelling the pre-fold runtime would have registered for the same chat
    old = "channel-wecom-ZhangSan"
    assert folded == "channel-wecom-zhangsan" != old
    service.timeline(old).add({"kind": "user", "text": "earlier spelling"})
    service.rename_thread(old, "WeCom · ZhangSan")

    service.adopt_thread_id(folded)

    assert folded in service.threads and old not in service.threads
    moved = service.threads[folded]
    assert moved.title == "WeCom · ZhangSan"
    assert [e["text"] for e in moved.timeline.events] == ["earlier spelling"]
    assert moved.timeline.path.name == folded + ".json"
    assert moved.timeline.path.exists()
    # the folder holds the folded spelling only (an exists() probe would say yes to
    # both spellings on a case-insensitive filesystem)
    names = [p.name for p in service.threads_dir.glob("channel-wecom-*")]
    assert folded + ".json" in names
    assert old + ".json" not in names
    # nothing to adopt: an id already registered, or one with no earlier spelling
    service.adopt_thread_id(folded)
    service.adopt_thread_id("channel-wecom-nobody")
    assert folded in service.threads
    assert "channel-wecom-nobody" not in service.threads


def test_first_message_gets_a_pairing_code_and_approval_pairs(chan):
    client, service, llm, manager, fake = chan
    view = client.get("/api/channels").json()
    me = next(c for c in view["channels"] if c["name"] == "fake")
    assert me["status"] == {"state": "connected", "detail": "fake bot"} and me["enabled"]
    assert me["fields"][0]["has_value"] is True and "value" not in me["fields"][0]

    fake.bus.inbound(dm("hello there"))
    wait_for(lambda: fake.sent)
    chat, text, _ = fake.sent[0]
    pending = client.get("/api/channels").json()["pending"]
    assert len(pending) == 1 and pending[0]["sender_name"] == "Ann"
    code = pending[0]["code"]
    assert chat == "chat1" and code in text and "nanomuse channels approve" in text
    # nothing reached the agent
    assert "channel-fake-chat1" not in service.threads and llm.calls == []
    # the same code again while it is good; a bad code is a 404
    fake.bus.inbound(dm("still me"))
    wait_for(lambda: len(fake.sent) >= 2)
    assert code in fake.sent[1][1]
    assert client.post("/api/channels/pairing/ZZZZZZ/approve").status_code == 404

    r = client.post(f"/api/channels/pairing/{code}/approve")
    assert r.status_code == 200 and r.json()["paired"]["sender_id"] == "u1"
    wait_for(lambda: len(fake.sent) >= 3)
    assert "Paired" in fake.sent[2][1]
    me = next(c for c in r.json()["channels"] if c["name"] == "fake")
    assert (
        me["paired"][0]["sender_id"] == "u1" and me["paired"][0]["thread"] == "channel-fake-chat1"
    )
    assert client.get("/api/channels").json()["pending"] == []

    # now the message goes to the agent and the reply comes back
    llm.script.append(LLMResponse(content="Hi Ann, glad you are here."))
    fake.bus.inbound(dm("hello again"))
    wait_for(lambda: any("Hi Ann" in t for t in fake.texts()))
    thread = service.threads["channel-fake-chat1"]
    assert thread.title == "Fake · Ann"
    assert llm.calls and "hello again" in str(llm.calls[-1]["messages"][-1])


def test_deny_and_allowlist(chan):
    client, service, llm, manager, fake = chan
    fake.bus.inbound(dm("hi", sender="u9"))
    code = wait_for(lambda: client.get("/api/channels").json()["pending"])[0]["code"]
    assert client.post(f"/api/channels/pairing/{code}/deny").status_code == 200
    assert client.get("/api/channels").json()["pending"] == []
    assert client.post(f"/api/channels/pairing/{code}/deny").status_code == 404
    # someone on the allowlist needs no code
    r = client.put("/api/channels/fake", json={"allow_from": ["boss"]})
    assert r.status_code == 200
    llm.script.append(LLMResponse(content="Yes boss."))
    fake.bus.inbound(dm("status?", sender="boss", chat="dm-boss"))
    wait_for(lambda: any("Yes boss" in t for t in fake.texts("dm-boss")))
    assert client.get("/api/channels").json()["pending"] == []


def test_group_policy_mention_or_open(chan):
    client, service, llm, manager, fake = chan
    pair(client, fake)
    # a group message without an @ is ignored under "mention"
    fake.bus.inbound(dm("chatter", chat="g1", is_group=True, mentioned=False, chat_name="Team"))
    time.sleep(0.3)
    assert "channel-fake-g1" not in service.threads
    llm.script.append(LLMResponse(content="Here is the summary."))
    fake.bus.inbound(
        dm("@bot summarize", chat="g1", is_group=True, mentioned=True, chat_name="Team")
    )
    wait_for(lambda: any("summary" in t for t in fake.texts("g1")))
    assert service.threads["channel-fake-g1"].title == "Fake · Team"
    # the sender's name travels with a group message
    assert "Ann:" in str(llm.calls[-1]["messages"][-1])
    # under "open" every group message counts
    assert client.put("/api/channels/fake", json={"group_policy": "open"}).status_code == 200
    llm.script.append(LLMResponse(content="Noted."))
    fake.bus.inbound(dm("fyi", chat="g1", is_group=True, mentioned=False))
    wait_for(lambda: any("Noted" in t for t in fake.texts("g1")))
    # unknown people in a group are ignored quietly, no code
    n = len(fake.sent)
    fake.bus.inbound(dm("hey", sender="stranger", chat="g1", is_group=True))
    time.sleep(0.3)
    assert len(fake.sent) == n and client.get("/api/channels").json()["pending"] == []


def test_approval_is_asked_in_the_chat_and_answered_with_a_word(chan):
    client, service, llm, manager, fake = chan
    pair(client, fake)
    llm.script.extend(
        [
            LLMResponse(content="Running it.", tool_calls=[tc("shell", command="echo from-chat")]),
            LLMResponse(content="Done, it printed from-chat."),
        ]
    )
    fake.bus.inbound(dm("run echo"))
    chat, approval_id, text = wait_for(lambda: fake.asks)[0]
    assert chat == "chat1" and "needs your OK" in text and "allow" in text
    # a tool running shows as "working" in the chat
    wait_for(lambda: ("chat1", True) in fake.typing_calls)
    fake.bus.inbound(dm("allow"))
    wait_for(lambda: any("Allowed." in t for t in fake.texts()))
    wait_for(lambda: any("from-chat" in t for t in fake.texts()))
    wait_for(lambda: ("chat1", False) in fake.typing_calls)
    # the card can only be answered once
    fake.bus.inbound(dm("deny"))
    time.sleep(0.3)
    assert not any("no longer waiting" in t for t in fake.texts())  # a plain word is a message now


def test_button_press_decides_too(chan):
    client, service, llm, manager, fake = chan
    pair(client, fake)
    llm.script.extend(
        [
            LLMResponse(tool_calls=[tc("shell", command="echo nope")]),
            LLMResponse(content="Understood."),
        ]
    )
    fake.bus.inbound(dm("run something"))
    _, approval_id, _ = wait_for(lambda: fake.asks)[0]
    # a stranger's press is ignored
    fake.bus.action("fake", "chat1", "stranger", {"approval": approval_id, "decision": "deny"})
    time.sleep(0.2)
    fake.bus.action("fake", "chat1", "u1", {"approval": approval_id, "decision": "deny"})
    wait_for(lambda: any("Denied." in t for t in fake.texts()))
    wait_for(lambda: any("Understood" in t for t in fake.texts()))


def test_deliver_here_gets_background_events(chan):
    client, service, llm, manager, fake = chan
    pair(client, fake)
    assert client.post("/api/channels/deliver", json={"text": "ping"}).json() == {"sent": 0}
    r = client.put("/api/channels/fake/chats/u1", json={"deliver": True})
    assert r.status_code == 200
    me = next(c for c in r.json()["channels"] if c["name"] == "fake")
    assert me["paired"][0]["deliver"] is True
    assert client.post("/api/channels/deliver", json={"text": "ping"}).json() == {"sent": 1}
    wait_for(lambda: ("chat1", "ping", []) in fake.sent)
    # a background run's final words reach the chat; quiet ones and non-final ones do not
    emit(
        manager,
        {
            "kind": "event",
            "event": {
                "type": "assistant",
                "thread": "side-task",
                "text": "The report is ready.",
                "final": True,
                "source": "background",
                "about": "Weekly report",
            },
        },
    )
    wait_for(lambda: any("Weekly report" in t and "report is ready" in t for t in fake.texts()))
    emit(
        manager,
        {
            "kind": "event",
            "event": {
                "type": "assistant",
                "thread": "side-task",
                "text": "shh",
                "final": True,
                "quiet": True,
            },
        },
    )
    # a pending approval elsewhere is asked here, and a word here decides it
    emit(
        manager,
        {
            "kind": "event",
            "event": {
                "type": "approval",
                "thread": "side-task",
                "id": "ap-1",
                "status": "pending",
                "summary": "send an e-mail",
                "purpose": "weekly report",
            },
        },
    )
    wait_for(lambda: any(a[1] == "ap-1" for a in fake.asks))
    fake.bus.inbound(dm("拒绝"))
    wait_for(lambda: any("no longer waiting" in t for t in fake.texts()))
    assert not any("shh" in t for t in fake.texts())
    # a question from elsewhere is asked here and the next line answers it
    emit(
        manager,
        {
            "kind": "event",
            "event": {
                "type": "question",
                "thread": "side-task",
                "text": "Which week?",
                "status": "pending",
            },
        },
    )
    wait_for(lambda: any("Which week?" in t for t in fake.texts()))
    # switch delivery off again
    assert client.put("/api/channels/fake/chats/u1", json={"deliver": False}).status_code == 200
    assert client.post("/api/channels/deliver", json={"text": "ping2"}).json() == {"sent": 0}
    assert client.put("/api/channels/fake/chats/nobody", json={"deliver": True}).status_code == 404


def test_files_in_and_out(chan, settings: Settings):
    client, service, llm, manager, fake = chan
    pair(client, fake)
    llm.script.append(LLMResponse(content="Got your picture."))
    fake.bus.inbound(
        InboundMessage(
            channel="fake",
            chat_id="chat1",
            sender_id="u1",
            text="",
            files=[InboundFile(name="shot.png", data=b"\x89PNG fake", kind="image")],
        )
    )
    wait_for(lambda: any("Got your picture" in t for t in fake.texts()))
    saved = list((settings.agent.workspace / "attachments").rglob("*.png"))
    assert saved and saved[0].read_bytes() == b"\x89PNG fake"
    # an artifact the run produced goes out with the reply
    (settings.agent.workspace / "out.txt").write_text("hello", "utf-8")
    emit(
        manager,
        {
            "kind": "event",
            "event": {"type": "artifact", "thread": "channel-fake-chat1", "path": "out.txt"},
        },
    )
    emit(manager, {"kind": "status", "status": {"thread": "channel-fake-chat1", "state": "idle"}})
    wait_for(lambda: any(files for _, _, files in fake.sent))
    files = next(files for _, _, files in fake.sent if files)
    assert files[0].endswith("out.txt")


def test_switching_off_and_on_and_removing_a_chat(chan):
    client, service, llm, manager, fake = chan
    pair(client, fake)
    r = client.put("/api/channels/fake", json={"enabled": False})
    assert r.status_code == 200
    me = next(c for c in r.json()["channels"] if c["name"] == "fake")
    assert me["status"]["state"] == "off" and fake.stopped
    assert client.post("/api/channels/fake/test").status_code == 409
    r = client.put("/api/channels/fake", json={"enabled": True})
    me = next(c for c in r.json()["channels"] if c["name"] == "fake")
    assert me["status"]["state"] == "connected" and len(FakeChannel.instances) == 2
    fresh = FakeChannel.instances[-1]
    # a test message goes to the first paired chat; without one the credentials are checked
    r = client.post("/api/channels/fake/test")
    assert r.status_code == 200 and r.json()["detail"] == "Sent to chat1."
    assert fresh.sent and "Test message" in fresh.sent[-1][1]
    assert client.delete("/api/channels/fake/chats/u1").status_code == 200
    assert client.delete("/api/channels/fake/chats/u1").status_code == 404
    assert client.post("/api/channels/fake/test").json()["detail"] == "Bot: fake"
    # unpaired again: a message is met with a code
    fresh.bus.inbound(dm("hello?"))
    wait_for(lambda: any("Pairing code" in t for t in fresh.texts()))


def test_reload_picks_up_cli_edits(chan):
    client, service, llm, manager, fake = chan
    # as `nanomuse channels approve` does when the server runs elsewhere: edit the file
    fake.bus.inbound(dm("hi", sender="u5", chat="c5"))
    code = wait_for(lambda: client.get("/api/channels").json()["pending"])[0]["code"]
    assert manager.pairing.approve(code)
    assert client.post("/api/channels/reload").status_code == 200
    me = next(c for c in client.get("/api/channels").json()["channels"] if c["name"] == "fake")
    assert [p["sender_id"] for p in me["paired"]] == ["u5"]

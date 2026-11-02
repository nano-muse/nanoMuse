"""DingTalk against a fake ``dingtalk_stream`` and a fake robot API: credentials are
checked first, messages come off the stream thread, markdown goes out once."""

from __future__ import annotations

import asyncio
import json
import sys
import types
from importlib.machinery import ModuleSpec
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from nanomuse.channels.base import InboundMessage
from nanomuse.channels.dingtalk import DingTalkChannel
from nanomuse.logger import logger


class Bus:
    def __init__(self) -> None:
        self.inbound_msgs: list[InboundMessage] = []
        self.statuses: list[tuple[str, str, str]] = []

    def inbound(self, msg: InboundMessage) -> None:
        self.inbound_msgs.append(msg)

    def set_status(self, channel: str, state: str, detail: str = "") -> None:
        self.statuses.append((channel, state, detail))

    def action(self, channel: str, chat_id: str, sender_id: str, value: dict[str, Any]) -> None:
        pass


class FakeStreamClient:
    instances: list[FakeStreamClient] = []

    def __init__(self, credential: Any) -> None:
        self.credential = credential
        self.handlers: dict[str, Any] = {}
        self.websocket = SimpleNamespace(closed=False)
        self.started = asyncio.Event()
        FakeStreamClient.instances.append(self)

    def register_callback_handler(self, topic: str, handler: Any) -> None:
        self.handlers[topic] = handler

    async def start(self) -> None:
        self.started.set()
        while True:
            await asyncio.sleep(3600)


@pytest.fixture()
def sdk(monkeypatch: pytest.MonkeyPatch) -> types.ModuleType:
    FakeStreamClient.instances.clear()

    class CallbackHandler:
        pass

    mod = types.ModuleType("dingtalk_stream")
    mod.__spec__ = ModuleSpec("dingtalk_stream", None)
    mod.__path__ = []  # type: ignore[attr-defined]
    mod.CallbackHandler = CallbackHandler  # type: ignore[attr-defined]
    mod.AckMessage = SimpleNamespace(STATUS_OK=200)  # type: ignore[attr-defined]
    mod.Credential = lambda cid, sec: (cid, sec)  # type: ignore[attr-defined]
    mod.DingTalkStreamClient = FakeStreamClient  # type: ignore[attr-defined]
    chatbot = types.ModuleType("dingtalk_stream.chatbot")
    chatbot.__spec__ = ModuleSpec("dingtalk_stream.chatbot", None)
    chatbot.ChatbotMessage = SimpleNamespace(TOPIC="/v1.0/im/bot/messages/get")  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "dingtalk_stream", mod)
    monkeypatch.setitem(sys.modules, "dingtalk_stream.chatbot", chatbot)
    return mod


class FakeRobotApi:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any], dict[str, str]]] = []
        self.bad_secret = False

    async def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        headers = {k: v for k, v in request.headers.items() if k.startswith("x-acs")}
        body: dict[str, Any] = {}
        if request.headers.get("content-type", "").startswith("application/json"):
            body = json.loads(request.content or b"{}")
        elif request.url.host == "oapi.dingtalk.com":
            body = {"_multipart": True, "type": request.url.params.get("type")}
        self.calls.append((path, body, headers))
        if path == "/v1.0/oauth2/accessToken":
            if self.bad_secret:
                return httpx.Response(
                    400,
                    json={
                        "code": "Forbidden.AccessDenied.AccessTokenPermissionDenied",
                        "message": "不合法的appSecret",
                    },
                )
            return httpx.Response(200, json={"accessToken": "tok-1", "expireIn": 7200})
        if path == "/v1.0/robot/messageFiles/download":
            return httpx.Response(200, json={"downloadUrl": "https://files.test/x.jpg"})
        if request.url.host == "files.test":
            return httpx.Response(200, content=b"jpeg-bytes")
        if path == "/media/upload":
            return httpx.Response(200, json={"errcode": 0, "media_id": "@media1"})
        return httpx.Response(200, json={"processQueryKey": "q"})

    def of(self, path: str) -> list[dict[str, Any]]:
        return [b for p, b, _ in self.calls if p == path]


async def until(pred, timeout: float = 3.0):  # noqa: ANN001
    for _ in range(int(timeout / 0.02)):
        if pred():
            return
        await asyncio.sleep(0.02)
    raise AssertionError("condition not met in time")


def channel(api: FakeRobotApi) -> DingTalkChannel:
    return DingTalkChannel(
        {"client_id": "ding-app", "client_secret": "s3"}, transport=httpx.MockTransport(api.handler)
    )


async def test_bad_secret_is_reported_before_the_stream_starts(sdk: types.ModuleType):
    api = FakeRobotApi()
    api.bad_secret = True
    with pytest.raises(RuntimeError, match="appSecret"):
        await channel(api).start(Bus())
    assert FakeStreamClient.instances == []


async def test_messages_in_and_markdown_out(sdk: types.ModuleType, tmp_path):  # noqa: ANN001
    api = FakeRobotApi()
    bus = Bus()
    ch = channel(api)
    await ch.start(bus)
    try:
        assert ("dingtalk", "connected", "") in bus.statuses
        await until(lambda: ch._client is not None)  # the stream thread has set up
        client = FakeStreamClient.instances[0]
        assert client.credential == ("ding-app", "s3")
        handler = client.handlers["/v1.0/im/bot/messages/get"]
        assert isinstance(handler, sdk.CallbackHandler)  # type: ignore[attr-defined]

        # a direct text message, as the SDK hands it over (on the stream's own loop)
        async def deliver(data: dict[str, Any]) -> tuple[Any, str]:
            return await handler.process(SimpleNamespace(data=data))

        ack = await deliver(
            {
                "msgId": "m1",
                "msgtype": "text",
                "text": {"content": " hello "},
                "senderStaffId": "staff1",
                "senderNick": "Ann",
                "conversationType": "1",
                "conversationId": "cid1",
            }
        )
        assert ack == (200, "OK")
        await until(lambda: bus.inbound_msgs)
        msg = bus.inbound_msgs[0]
        assert msg.chat_id == "staff1" and msg.sender_id == "staff1" and msg.sender_name == "Ann"
        assert msg.text == "hello" and not msg.is_group and msg.chat_name == "Ann"
        # the same id twice is one message; a group picture is downloaded
        await deliver(
            {
                "msgId": "m1",
                "msgtype": "text",
                "text": {"content": "dup"},
                "senderStaffId": "staff1",
            }
        )
        await deliver(
            {
                "msgId": "m2",
                "msgtype": "picture",
                "content": {"downloadCode": "dl-1"},
                "senderStaffId": "staff2",
                "senderNick": "Bob",
                "conversationType": "2",
                "conversationId": "cidG",
                "conversationTitle": "Team",
            }
        )
        await until(lambda: len(bus.inbound_msgs) >= 2)
        await asyncio.sleep(0.05)
        assert len(bus.inbound_msgs) == 2
        pic = bus.inbound_msgs[1]
        assert pic.chat_id == "group:cidG" and pic.is_group and pic.chat_name == "Team"
        assert [f.kind for f in pic.files] == ["image"] and pic.files[0].data == b"jpeg-bytes"
        assert api.of("/v1.0/robot/messageFiles/download")[0] == {
            "downloadCode": "dl-1",
            "robotCode": "ding-app",
        }

        # a direct reply is a batchSend to the person; a group reply goes to the conversation
        await ch.send("staff1", "**done**\nmore")
        sent = api.of("/v1.0/robot/oToMessages/batchSend")[-1]
        assert sent["userIds"] == ["staff1"] and sent["msgKey"] == "sampleMarkdown"
        assert json.loads(sent["msgParam"]) == {"title": "**done**", "text": "**done**\nmore"}
        assert api.calls[-1][2]["x-acs-dingtalk-access-token"] == "tok-1"
        await ch.send("group:cidG", "hi group")
        group = api.of("/v1.0/robot/groupMessages/send")[-1]
        assert group["openConversationId"] == "cidG" and group["robotCode"] == "ding-app"
        # no edits: the stream default sends once, when done
        await ch.stream("staff1", "s1", "partial", done=False)
        assert len(api.of("/v1.0/robot/oToMessages/batchSend")) == 1
        await ch.stream("staff1", "s1", "final", done=True)
        assert (
            json.loads(api.of("/v1.0/robot/oToMessages/batchSend")[-1]["msgParam"])["text"]
            == "final"
        )
        # files: uploaded to the media API, then sent as image or file
        (tmp_path / "a.png").write_bytes(b"png")
        (tmp_path / "r.pdf").write_bytes(b"pdf")
        await ch.send("staff1", "", files=[str(tmp_path / "a.png"), str(tmp_path / "r.pdf")])
        keys = [b["msgKey"] for b in api.of("/v1.0/robot/oToMessages/batchSend")[-2:]]
        assert keys == ["sampleImageMsg", "sampleFile"]
        assert [b["type"] for b in api.of("/media/upload")] == ["image", "file"]
        # the token is reused while it is good
        assert len(api.of("/v1.0/oauth2/accessToken")) == 1
        assert await ch.verify() == "The AppKey and AppSecret work."
    finally:
        await ch.stop()
    assert ch._thread is None and ch._stream_loop is None


async def test_a_stream_that_gives_up_is_reported_not_left_hanging(
    sdk: types.ModuleType, monkeypatch: pytest.MonkeyPatch
):
    """The SDK's ``start()`` coming back on its own (bad credentials, the SDK giving up)
    used to leave its thread running forever and the status at "connected"."""

    class Failing(FakeStreamClient):
        async def start(self) -> None:
            self.started.set()
            await asyncio.sleep(0)
            raise RuntimeError("stream refused: 401\nmore")

    monkeypatch.setattr(sdk, "DingTalkStreamClient", Failing)
    api = FakeRobotApi()
    bus = Bus()
    ch = channel(api)
    await ch.start(bus)
    try:
        await until(lambda: ("dingtalk", "error", "stream refused: 401") in bus.statuses)
        thread = ch._thread
        assert thread is not None
        await asyncio.to_thread(thread.join, 3)
        assert not thread.is_alive()  # the loop stopped with the stream
    finally:
        await ch.stop()


async def test_a_failed_handover_is_logged_not_swallowed(sdk: types.ModuleType, tmp_path):  # noqa: ANN001
    """The stream thread hands a message to the loop with ``run_coroutine_threadsafe`` and
    acks right away; when the handed-over handling then fails, the exception sat in a future
    nobody read — the message was gone with no line in the log."""
    api = FakeRobotApi()
    bus = Bus()
    ch = channel(api)
    await ch.start(bus)
    try:
        await until(lambda: ch._client is not None)
        handler = FakeStreamClient.instances[0].handlers["/v1.0/im/bot/messages/get"]

        async def boom(data: dict[str, Any]) -> None:
            raise RuntimeError("hand-over exploded")

        ch._handle = boom  # type: ignore[method-assign]
        warnings: list[str] = []
        sink = logger.add(lambda m: warnings.append(m.record["message"]), level="WARNING")
        try:
            ack = await handler.process(
                SimpleNamespace(
                    data={
                        "msgId": "m9",
                        "msgtype": "text",
                        "text": {"content": " hi "},
                        "senderStaffId": "staff1",
                    }
                )
            )
            assert ack == (sdk.AckMessage.STATUS_OK, "OK")
            await until(lambda: any("hand-over exploded" in w for w in warnings))
        finally:
            logger.remove(sink)
    finally:
        await ch.stop()

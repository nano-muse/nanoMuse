"""WeCom against a fake ``wecom_aibot_sdk``: the socket's events, frames in, streamed
replies against the frame, proactive markdown for delivery."""

from __future__ import annotations

import asyncio
import os
import sys
import types
from importlib.machinery import ModuleSpec
from types import SimpleNamespace
from typing import Any

import pytest

from nanomuse.channels.base import InboundMessage
from nanomuse.channels.wecom import WS_HOST, WeComChannel


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


class FakeWSClient:
    instances: list[FakeWSClient] = []

    def __init__(self, options: dict[str, Any]) -> None:
        self.options = options
        self.handlers: dict[str, Any] = {}
        self.calls: list[tuple[str, Any]] = []
        self.disconnected = False
        self.fail_stream = False
        FakeWSClient.instances.append(self)

    def on(self, event: str, handler: Any) -> None:
        self.handlers[event] = handler

    async def connect_async(self) -> None:
        if self.options["secret"] == "bad":
            await self.handlers["error"](SimpleNamespace(body={"errmsg": "invalid secret"}))
            return
        await self.handlers["authenticated"](SimpleNamespace(body=None))

    async def disconnect(self) -> None:
        self.disconnected = True
        await self.handlers["disconnected"](SimpleNamespace(body="manual_disconnect"))

    async def reply_stream(
        self, frame: Any, stream_id: str, content: str, finish: bool = False
    ) -> None:
        if self.fail_stream:
            raise RuntimeError("frame expired")
        self.calls.append(("reply_stream", (frame.headers["req_id"], stream_id, content, finish)))

    async def send_message(self, chatid: str, body: dict[str, Any]) -> None:
        self.calls.append(("send_message", (chatid, body)))

    async def send_media_message(self, chatid: str, path: str) -> None:
        self.calls.append(("send_media_message", (chatid, os.path.basename(path))))

    async def download_file(self, url: str, aes_key: str | None) -> tuple[bytes, str | None]:
        self.calls.append(("download_file", (url, aes_key)))
        return b"media-bytes", "photo.jpg"

    def of(self, name: str) -> list[Any]:
        return [a for n, a in self.calls if n == name]


@pytest.fixture()
def sdk(monkeypatch: pytest.MonkeyPatch) -> types.ModuleType:
    FakeWSClient.instances.clear()
    mod = types.ModuleType("wecom_aibot_sdk")
    mod.__spec__ = ModuleSpec("wecom_aibot_sdk", None)
    mod.WSClient = FakeWSClient  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "wecom_aibot_sdk", mod)
    monkeypatch.delenv("NO_PROXY", raising=False)
    monkeypatch.setenv("no_proxy", "localhost")
    return mod


def frame(body: dict[str, Any], req_id: str = "req-1") -> SimpleNamespace:
    return SimpleNamespace(headers={"req_id": req_id}, body=body)


async def test_connect_messages_and_streamed_replies(sdk: types.ModuleType, tmp_path):  # noqa: ANN001
    bus = Bus()
    ch = WeComChannel({"bot_id": "bot-1", "secret": "s3"})
    await ch.start(bus)
    client = FakeWSClient.instances[0]
    assert client.options["bot_id"] == "bot-1" and client.options["max_reconnect_attempts"] == -1
    assert ("wecom", "connected", "") in bus.statuses
    assert WS_HOST in os.environ["NO_PROXY"] and os.environ["no_proxy"] == f"localhost,{WS_HOST}"
    assert await ch.verify() == "Connected to WeCom."

    await client.handlers["message.text"](
        frame(
            {
                "msgid": "m1",
                "from": {"userid": "ann"},
                "chattype": "single",
                "text": {"content": " hi "},
            }
        )
    )
    await client.handlers["message.text"](
        frame(
            {
                "msgid": "m1",
                "from": {"userid": "ann"},
                "chattype": "single",
                "text": {"content": "dup"},
            }
        )
    )
    await client.handlers["message.image"](
        frame(
            {
                "msgid": "m2",
                "from": {"userid": "bob"},
                "chattype": "group",
                "chatid": "wr-group",
                "image": {"url": "https://wecom.test/i", "aeskey": "k"},
            },
            req_id="req-2",
        )
    )
    await client.handlers["message.mixed"](
        frame(
            {
                "msgid": "m3",
                "from": {"userid": "ann"},
                "chattype": "single",
                "mixed": {
                    "msg_item": [
                        {"msgtype": "text", "text": {"content": "see"}},
                        {
                            "msgtype": "file",
                            "file": {"url": "https://wecom.test/f", "name": "r.pdf"},
                        },
                    ]
                },
            },
            req_id="req-3",
        )
    )
    assert len(bus.inbound_msgs) == 3
    text, image, mixed = bus.inbound_msgs
    assert (
        text.chat_id == "ann"
        and text.sender_id == "ann"
        and text.text == "hi"
        and not text.is_group
    )
    assert image.chat_id == "wr-group" and image.is_group and image.mentioned
    assert [f.kind for f in image.files] == ["image"] and image.files[0].name == "photo.jpg"
    assert mixed.text == "see" and [f.name for f in mixed.files] == ["r.pdf"]
    assert client.of("download_file")[0] == ("https://wecom.test/i", "k")

    # a reply streams against the chat's last frame and finishes
    await ch.stream("ann", "s1", "Work", done=False)
    await ch.stream("ann", "s1", "Worked.", done=True)
    assert client.of("reply_stream") == [
        ("req-3", "s1", "Work", False),
        ("req-3", "s1", "Worked.", True),
    ]
    # a chat we never heard from gets one proactive message at the end
    await ch.stream("nobody", "s2", "partial", done=False)
    await ch.stream("nobody", "s2", "final", done=True)
    assert client.of("send_message") == [
        ("nobody", {"msgtype": "markdown", "markdown": {"content": "final"}})
    ]
    # when the frame is stale the reply still gets out, plainly
    client.fail_stream = True
    await ch.stream("ann", "s3", "late", done=True)
    assert client.of("send_message")[-1][0] == "ann"
    client.fail_stream = False
    # delivery and files
    (tmp_path / "a.png").write_bytes(b"png")
    await ch.send("wr-group", "news", files=[str(tmp_path / "a.png"), str(tmp_path / "none.bin")])
    assert client.of("send_message")[-1] == (
        "wr-group",
        {"msgtype": "markdown", "markdown": {"content": "news"}},
    )
    assert client.of("send_media_message") == [("wr-group", "a.png")]
    # someone opening the chat is an empty inbound (the manager shows the pairing code)
    await client.handlers["event.enter_chat"](
        frame({"msgid": "e1", "from": {"userid": "carl"}, "chattype": "single"}, req_id="req-9")
    )
    assert bus.inbound_msgs[-1].sender_id == "carl" and bus.inbound_msgs[-1].text == ""
    # an unplanned disconnect shows as connecting; the manual one on stop does not
    await client.handlers["disconnected"](SimpleNamespace(body="connection lost"))
    assert bus.statuses[-1] == ("wecom", "connecting", "connection lost")
    n = len(bus.statuses)
    await ch.stop()
    assert client.disconnected and len(bus.statuses) == n
    with pytest.raises(RuntimeError, match="Not connected"):
        await ch.send("ann", "x")


async def test_the_last_frame_per_chat_is_capped(sdk: types.ModuleType):  # noqa: ANN001
    bus = Bus()
    ch = WeComChannel({"bot_id": "bot-1", "secret": "s3"})
    await ch.start(bus)
    client = FakeWSClient.instances[0]
    for i in range(1002):
        await client.handlers["message.text"](
            frame(
                {
                    "msgid": f"m{i}",
                    "from": {"userid": f"u{i}"},
                    "chattype": "single",
                    "text": {"content": "x"},
                },
                req_id=f"req-{i}",
            )
        )
    # a company-wide robot hears from thousands of chats: only a chat's newest frame is
    # ever asked for, and the map gives the oldest away
    assert len(ch._frames) == 1000
    # the oldest chat's frame fell off the cap, so its reply goes out plainly
    await ch.stream("u0", "s-old", "late", done=True)
    assert client.of("send_message")[-1] == (
        "u0",
        {"msgtype": "markdown", "markdown": {"content": "late"}},
    )
    # the newest chat's frame is still there to stream against
    await ch.stream("u1001", "s-new", "now", done=True)
    assert ("req-1001", "s-new", "now", True) in client.of("reply_stream")
    await ch.stop()


async def test_bad_secret_fails_to_start(sdk: types.ModuleType):
    ch = WeComChannel({"bot_id": "bot-1", "secret": "bad"})
    with pytest.raises(RuntimeError, match="invalid secret"):
        await asyncio.wait_for(ch.start(Bus()), 5)

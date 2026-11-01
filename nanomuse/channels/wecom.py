"""WeCom (企业微信) intelligent robots, over the AI-bot WebSocket (``wecom-aibot-sdk-python``).

WeCom's "intelligent robot" in API mode keeps a long connection to WeCom and gets messages
on it; replies stream back on the same socket, so the robot can type a reply out piece by
piece. A "deliver here" chat gets proactive markdown messages over the same connection.

Setup (console names, 2026): WeCom admin console (企业微信管理后台) → *Security & management*
→ *Intelligent robot* (智能机器人) → *Create robot* → *API mode* (API 模式), connection
*long connection* (长连接) → copy the Bot ID and Secret → add the robot to the chats or
let people find it in the address book.

The socket host is ``openws.work.weixin.qq.com``; a corporate proxy in ``HTTPS_PROXY``
usually cannot carry it, so the host is added to ``NO_PROXY`` for the process.
"""

from __future__ import annotations

import asyncio
import os
from collections import OrderedDict
from pathlib import Path
from typing import Any

from nanomuse.channels.base import Channel, ChannelBus, Field, InboundFile, InboundMessage
from nanomuse.logger import logger

WS_HOST = "openws.work.weixin.qq.com"


def _bypass_proxy(host: str) -> None:
    for key in ("NO_PROXY", "no_proxy"):
        current = os.environ.get(key, "")
        parts = [p.strip() for p in current.split(",") if p.strip()]
        if host not in parts:
            parts.append(host)
            os.environ[key] = ",".join(parts)


class WeComChannel(Channel):
    name = "wecom"
    label = "WeCom"
    sdk_module = "wecom_aibot_sdk"
    extra = "wecom"
    supports_edit = True
    console_url = "https://work.weixin.qq.com/wework_admin/frame#/aibot"
    fields = (
        Field("bot_id", "Bot ID", required=True, help="智能机器人 → API 模式 → Bot ID"),
        Field("secret", "Secret", "secret", required=True, help="Same page → Secret"),
    )

    def __init__(self, settings: dict[str, Any]):
        super().__init__(settings)
        self._client: Any = None
        self._seen: OrderedDict[str, None] = OrderedDict()
        # the last inbound frame per chat; replies stream against it. Capped like _seen:
        # a company-wide robot hears from thousands of chats over weeks of uptime, and
        # only a chat's newest frame is ever asked for
        self._frames: OrderedDict[str, Any] = OrderedDict()
        # stream id -> (frame, chat_id) while a reply is being typed out
        self._streams: dict[str, tuple[Any, str]] = {}
        self._connected = asyncio.Event()
        self._settled = asyncio.Event()  # authenticated or refused: start() can answer
        self._error = ""

    # ------------------------------------------------------------------ lifecycle
    async def start(self, bus: ChannelBus) -> None:
        await super().start(bus)
        _bypass_proxy(WS_HOST)
        sdk = await asyncio.to_thread(self._import)
        client = sdk.WSClient(
            {
                "bot_id": str(self.settings.get("bot_id") or ""),
                "secret": str(self.settings.get("secret") or ""),
                "reconnect_interval": 1000,
                "max_reconnect_attempts": -1,
                "heartbeat_interval": 30000,
            }
        )
        self._connected = asyncio.Event()
        self._error = ""
        client.on("authenticated", self._on_authenticated)
        client.on("disconnected", self._on_disconnected)
        client.on("error", self._on_error)
        for kind in ("text", "image", "voice", "file", "mixed"):
            client.on(f"message.{kind}", self._on_message)
        client.on("event.enter_chat", self._on_enter_chat)
        self._client = client
        self._settled = asyncio.Event()
        await client.connect_async()
        try:
            await asyncio.wait_for(self._settled.wait(), 20)
        except TimeoutError:
            raise RuntimeError("WeCom did not accept the Bot ID and Secret in time.") from None
        if not self._connected.is_set():
            raise RuntimeError(self._error or "WeCom refused the connection.")

    @staticmethod
    def _import() -> Any:
        import wecom_aibot_sdk

        return wecom_aibot_sdk

    async def stop(self) -> None:
        client, self._client = self._client, None
        if client is not None:
            try:
                await asyncio.wait_for(client.disconnect(), 5)
            except Exception as exc:  # noqa: BLE001
                logger.debug("wecom: disconnect: {}", exc)
        self._streams.clear()

    async def verify(self) -> str:
        if self._client is None or not self._connected.is_set():
            raise RuntimeError("Not connected.")
        return "Connected to WeCom."

    async def _on_authenticated(self, frame: Any) -> None:
        self._error = ""
        self._connected.set()
        self._settled.set()
        if self.bus is not None:
            self.bus.set_status(self.name, "connected")

    async def _on_disconnected(self, frame: Any) -> None:
        reason = str(getattr(frame, "body", "") or "")
        if reason == "manual_disconnect":
            return
        if self.bus is not None:
            self.bus.set_status(self.name, "connecting", reason[:200])

    async def _on_error(self, frame: Any) -> None:
        body = getattr(frame, "body", None)
        text = ""
        if isinstance(body, dict):
            text = str(body.get("errmsg") or body.get("message") or body.get("error") or "")
        elif body is not None:
            text = str(body)
        self._error = (text or getattr(frame, "errmsg", None) or "WeCom reported an error")[:300]
        self._settled.set()
        if self.bus is not None and self._connected.is_set():
            self.bus.set_status(self.name, "error", self._error)

    # ------------------------------------------------------------------ inbound
    def _remember_frame(self, chat_id: str, frame: Any) -> None:
        self._frames[chat_id] = frame
        while len(self._frames) > 1000:
            self._frames.popitem(last=False)

    async def _on_enter_chat(self, frame: Any) -> None:
        """Someone opened the robot's chat for the first time: a hello, which also
        shows the pairing code when needed."""
        body = getattr(frame, "body", None)
        if not isinstance(body, dict) or self.bus is None:
            return
        sender = str(((body.get("from") or {}).get("userid")) or "")
        chat_id = str(body.get("chatid") or sender)
        if not sender:
            return
        self._remember_frame(chat_id, frame)
        self.bus.inbound(
            InboundMessage(
                channel=self.name,
                chat_id=chat_id,
                sender_id=sender,
                sender_name="",
                text="",
                is_group=str(body.get("chattype") or "single") == "group",
                mentioned=True,
                message_id=str(body.get("msgid") or ""),
            )
        )

    async def _on_message(self, frame: Any) -> None:
        body = getattr(frame, "body", None)
        if not isinstance(body, dict) or self.bus is None:
            return
        message_id = str(body.get("msgid") or "")
        if message_id and message_id in self._seen:
            return
        if message_id:
            self._seen[message_id] = None
            while len(self._seen) > 1000:
                self._seen.popitem(last=False)
        sender = str(((body.get("from") or {}).get("userid")) or "")
        is_group = str(body.get("chattype") or "single") == "group"
        chat_id = str(body.get("chatid") or sender)
        if not sender or not chat_id:
            return
        text, files = await self._content(body)
        self._remember_frame(chat_id, frame)
        self.bus.inbound(
            InboundMessage(
                channel=self.name,
                chat_id=chat_id,
                sender_id=sender,
                sender_name="",
                text=text,
                files=files,
                is_group=is_group,
                # a WeCom robot in a group only hears messages that @ it
                mentioned=True,
                message_id=message_id,
            )
        )

    async def _content(self, body: dict[str, Any]) -> tuple[str, list[InboundFile]]:
        msg_type = str(
            body.get("msgtype")
            or next((k for k in ("text", "image", "file", "voice", "mixed") if k in body), "text")
        )
        files: list[InboundFile] = []
        if msg_type == "text":
            return str((body.get("text") or {}).get("content") or "").strip(), files
        if msg_type == "voice":
            return str((body.get("voice") or {}).get("content") or "[voice]").strip(), files
        if msg_type in ("image", "file"):
            item = await self._download(body.get(msg_type) or {}, msg_type)
            if item:
                files.append(item)
            return ("" if item else f"[{msg_type}]"), files
        if msg_type == "mixed":
            parts: list[str] = []
            for node in (body.get("mixed") or {}).get("msg_item") or []:
                if not isinstance(node, dict):
                    continue
                kind = str(node.get("msgtype") or "")
                if kind == "text":
                    parts.append(str((node.get("text") or {}).get("content") or ""))
                elif kind in ("image", "file"):
                    item = await self._download(node.get(kind) or {}, kind)
                    if item:
                        files.append(item)
            return " ".join(p for p in parts if p).strip(), files
        return f"[{msg_type}]", files

    async def _download(self, node: dict[str, Any], kind: str) -> InboundFile | None:
        url = str(node.get("url") or "")
        if not url or self._client is None:
            return None
        try:
            data, filename = await self._client.download_file(url, node.get("aeskey"))
        except Exception as exc:  # noqa: BLE001
            logger.warning("wecom: download failed: {}", exc)
            return None
        name = str(node.get("name") or filename or ("image.jpg" if kind == "image" else "file"))
        return InboundFile(name=name, data=bytes(data), kind="image" if kind == "image" else "file")

    # ------------------------------------------------------------------ outbound
    async def send(self, chat_id: str, text: str, *, files: list[str] | None = None) -> str:
        if self._client is None:
            raise RuntimeError("Not connected.")
        if text.strip():
            await self._client.send_message(
                chat_id, {"msgtype": "markdown", "markdown": {"content": text}}
            )
        for item in files or []:
            path = Path(item)
            if path.is_file():
                await self._client.send_media_message(chat_id, str(path))
        return ""

    async def stream(self, chat_id: str, stream_id: str, text: str, *, done: bool) -> None:
        if self._client is None:
            raise RuntimeError("Not connected.")
        entry = self._streams.get(stream_id)
        if entry is None:
            frame = self._frames.get(chat_id)
            if frame is None:
                # nothing to reply against (a delivery): one message at the end
                if done and text.strip():
                    await self.send(chat_id, text)
                return
            entry = (frame, chat_id)
            self._streams[stream_id] = entry
        frame = entry[0]
        try:
            await self._client.reply_stream(frame, stream_id, text or "…", finish=done)
        except Exception as exc:  # noqa: BLE001
            logger.debug("wecom: stream reply failed, sending plainly: {}", exc)
            if done and text.strip():
                await self.send(chat_id, text)
        if done:
            self._streams.pop(stream_id, None)


__all__ = ["WeComChannel"]

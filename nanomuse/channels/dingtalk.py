"""DingTalk (钉钉), in Stream mode (``dingtalk-stream``).

Stream mode is DingTalk's long connection: the SDK opens a socket to DingTalk and bot
messages arrive on it, no public URL. Replies go out through the robot HTTP API with an
access token (that is also what lets a "deliver here" chat receive something the Muse did on
its own). DingTalk messages cannot be edited, so a reply is sent once, when it is complete.

Setup (console names, 2026): https://open-dev.dingtalk.com → *Create app* (企业内部应用) →
*Add capability: Robot* (机器人) → message receive mode *Stream* (Stream 模式) → *Credentials*
(凭证与基础信息): AppKey (Client ID) and AppSecret (Client Secret) → *Permissions*: the robot
scopes for sending messages (``qyapi_robot_sendmsg``) → publish the version.

The SDK's ``start()`` swallows cancellation and reconnects forever, so it runs on a thread
with its own loop; stopping the loop stops it.
"""

from __future__ import annotations

import asyncio
import json
import mimetypes
import threading
import time
from collections import OrderedDict
from collections.abc import Coroutine
from concurrent.futures import Future
from contextlib import suppress
from pathlib import Path
from typing import Any

import httpx

from nanomuse.channels.base import (
    Channel,
    ChannelBus,
    Field,
    InboundFile,
    InboundMessage,
    json_object,
)
from nanomuse.logger import logger

API = "https://api.dingtalk.com"
OAPI = "https://oapi.dingtalk.com"
GROUP_PREFIX = "group:"
_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"}


class DingTalkChannel(Channel):
    name = "dingtalk"
    label = "DingTalk"
    sdk_module = "dingtalk_stream"
    extra = "dingtalk"
    supports_edit = False
    console_url = "https://open-dev.dingtalk.com/"
    fields = (
        Field("client_id", "AppKey (Client ID)", required=True, help="凭证与基础信息 → Client ID"),
        Field(
            "client_secret",
            "AppSecret (Client Secret)",
            "secret",
            required=True,
            help="凭证与基础信息 → Client Secret",
        ),
    )

    def __init__(self, settings: dict[str, Any], transport: httpx.AsyncBaseTransport | None = None):
        super().__init__(settings)
        self._transport = transport
        self._http: httpx.AsyncClient | None = None
        self._token = ""
        self._token_until = 0.0
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._stream_loop: asyncio.AbstractEventLoop | None = None
        self._client: Any = None
        self._seen: OrderedDict[str, None] = OrderedDict()

    @property
    def client_id(self) -> str:
        return str(self.settings.get("client_id") or "")

    # ------------------------------------------------------------------ lifecycle
    async def start(self, bus: ChannelBus) -> None:
        await super().start(bus)
        self._loop = asyncio.get_running_loop()
        self._http = httpx.AsyncClient(
            timeout=httpx.Timeout(15.0, read=60.0), transport=self._transport
        )
        # a bad AppKey/AppSecret shows here, with DingTalk's words; the stream itself
        # would only log and retry forever
        await self._access_token()
        sdk = await asyncio.to_thread(self._import)
        handler = self._make_handler(sdk)
        self._thread = threading.Thread(
            target=self._run_stream, args=(sdk, handler), name="dingtalk-stream", daemon=True
        )
        self._thread.start()
        bus.set_status(self.name, "connected")

    @staticmethod
    def _import() -> Any:
        import dingtalk_stream

        return dingtalk_stream

    def _make_handler(self, sdk: Any) -> Any:
        channel = self

        class Handler(sdk.CallbackHandler):  # type: ignore[name-defined,misc]
            async def process(self, message: Any) -> tuple[Any, str]:
                data = getattr(message, "data", None)
                if isinstance(data, dict):
                    channel.hand_over(channel._handle(dict(data)))
                return sdk.AckMessage.STATUS_OK, "OK"

        return Handler()

    def hand_over(self, coro: Coroutine[Any, Any, None]) -> None:
        """A message from the stream thread crosses to the loop; the stream has already
        acked it, so when the handed-over handling fails, the exception must not sit in a
        future nobody reads."""
        loop = self._loop
        if loop is None or loop.is_closed():
            coro.close()
            return
        try:
            done = asyncio.run_coroutine_threadsafe(coro, loop)
        except RuntimeError:
            coro.close()
            logger.warning("dingtalk: the runtime loop stopped before message handover")
            return
        done.add_done_callback(self._log_failed_handover)

    @staticmethod
    def _log_failed_handover(future: Future[Any]) -> None:
        if future.cancelled():
            return
        exc = future.exception()
        if exc is not None:
            logger.warning("dingtalk: a handed-over message failed: {}", exc)

    def _run_stream(self, sdk: Any, handler: Any) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._stream_loop = loop
        try:
            from dingtalk_stream.chatbot import ChatbotMessage

            client = sdk.DingTalkStreamClient(
                sdk.Credential(self.client_id, str(self.settings.get("client_secret") or ""))
            )
            client.register_callback_handler(ChatbotMessage.TOPIC, handler)
            self._client = client
            stream = loop.create_task(client.start())

            def _ended(task: asyncio.Task[Any]) -> None:
                # start() runs until stop(); it coming back on its own is a failure (bad
                # credentials, the SDK giving up), which would otherwise leave the loop
                # running forever with the status still "connected"
                if task.cancelled() or self._client is not client:  # stop() under way
                    return
                exc = task.exception()
                lines = str(exc).splitlines() if exc else []
                reason = lines[0] if lines else type(exc).__name__ if exc else "stream closed"
                reason = reason[:300]
                logger.warning("dingtalk: stream ended: {}", reason)
                if self.bus is not None:
                    self.bus.set_status(self.name, "error", reason)
                loop.stop()

            stream.add_done_callback(_ended)
            loop.run_forever()
        except Exception as exc:  # noqa: BLE001
            logger.warning("dingtalk: stream ended: {}", exc)
            if self.bus is not None:
                self.bus.set_status(self.name, "error", str(exc).splitlines()[0][:300])
        finally:
            # the SDK's start() swallows cancellation and goes back to sleep, so its task
            # cannot be awaited to the end; cancel, give it one turn, and let it go quietly
            pending = [t for t in asyncio.all_tasks(loop) if not t.done()]
            for task in pending:
                task.cancel()
            with suppress(Exception):
                loop.run_until_complete(asyncio.sleep(0))
            for task in pending:
                if not task.done():
                    task._log_destroy_pending = False  # type: ignore[attr-defined]
            with suppress(Exception):
                loop.run_until_complete(loop.shutdown_asyncgens())
            loop.close()

    async def stop(self) -> None:
        loop, self._stream_loop = self._stream_loop, None
        client, self._client = self._client, None
        if loop is not None and not loop.is_closed() and loop.is_running():

            def _shutdown() -> None:
                websocket = getattr(client, "websocket", None)
                close = getattr(websocket, "close", None)
                if callable(close):
                    with suppress(Exception):
                        loop.create_task(close())
                loop.call_later(0.5, loop.stop)

            loop.call_soon_threadsafe(_shutdown)
        thread, self._thread = self._thread, None
        if thread is not None:
            await asyncio.to_thread(thread.join, 5)
        if self._http is not None:
            await self._http.aclose()
            self._http = None

    async def verify(self) -> str:
        await self._access_token()
        return "The AppKey and AppSecret work."

    # ------------------------------------------------------------------ the robot API
    async def _access_token(self) -> str:
        if self._token and time.time() < self._token_until:
            return self._token
        assert self._http is not None
        response = await self._http.post(
            f"{API}/v1.0/oauth2/accessToken",
            json={
                "appKey": self.client_id,
                "appSecret": str(self.settings.get("client_secret") or ""),
            },
        )
        data = json_object(response)
        if response.status_code >= 400 or not data.get("accessToken"):
            raise RuntimeError(
                str(data.get("message") or data.get("code") or f"HTTP {response.status_code}")
            )
        self._token = str(data["accessToken"])
        self._token_until = time.time() + int(data.get("expireIn") or 7200) - 60
        return self._token

    async def _robot_send(self, chat_id: str, msg_key: str, param: dict[str, Any]) -> None:
        assert self._http is not None
        token = await self._access_token()
        headers = {"x-acs-dingtalk-access-token": token}
        if chat_id.startswith(GROUP_PREFIX):
            url = f"{API}/v1.0/robot/groupMessages/send"
            payload: dict[str, Any] = {
                "robotCode": self.client_id,
                "openConversationId": chat_id[len(GROUP_PREFIX) :],
                "msgKey": msg_key,
                "msgParam": json.dumps(param, ensure_ascii=False),
            }
        else:
            url = f"{API}/v1.0/robot/oToMessages/batchSend"
            payload = {
                "robotCode": self.client_id,
                "userIds": [chat_id],
                "msgKey": msg_key,
                "msgParam": json.dumps(param, ensure_ascii=False),
            }
        response = await self._http.post(url, json=payload, headers=headers)
        if response.status_code >= 400:
            detail = str(json_object(response).get("message") or "")
            raise RuntimeError(detail or f"HTTP {response.status_code}")

    async def _upload(self, path: Path) -> tuple[str, str]:
        """``(type, media_id)``; DingTalk wants images, voice, video and files apart."""
        assert self._http is not None
        token = await self._access_token()
        suffix = path.suffix.lower()
        media_type = "image" if suffix in _IMAGE_SUFFIXES else "file"
        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        with path.open("rb") as fh:
            response = await self._http.post(
                f"{OAPI}/media/upload",
                params={"access_token": token, "type": media_type},
                files={"media": (path.name, fh, mime)},
            )
        data = json_object(response)
        media_id = data.get("media_id") or data.get("mediaId")
        if response.status_code >= 400 or data.get("errcode") not in (0, None) or not media_id:
            raise RuntimeError(
                str(data.get("errmsg") or f"upload failed (HTTP {response.status_code})")
            )
        return media_type, str(media_id)

    async def send(self, chat_id: str, text: str, *, files: list[str] | None = None) -> str:
        if text.strip():
            title = text.strip().splitlines()[0][:40]
            await self._robot_send(chat_id, "sampleMarkdown", {"title": title, "text": text})
        for item in files or []:
            path = Path(item)
            if not path.is_file():
                continue
            media_type, media_id = await self._upload(path)
            if media_type == "image":
                await self._robot_send(chat_id, "sampleImageMsg", {"photoURL": media_id})
            else:
                await self._robot_send(
                    chat_id,
                    "sampleFile",
                    {
                        "mediaId": media_id,
                        "fileName": path.name,
                        "fileType": path.suffix.lstrip(".").lower() or "bin",
                    },
                )
        return ""

    # ------------------------------------------------------------------ inbound
    async def _handle(self, data: dict[str, Any]) -> None:
        message_id = str(data.get("msgId") or "")
        if message_id and message_id in self._seen:
            return
        if message_id:
            self._seen[message_id] = None
            while len(self._seen) > 1000:
                self._seen.popitem(last=False)
        sender_id = str(data.get("senderStaffId") or data.get("senderId") or "")
        if not sender_id:
            return
        sender_name = str(data.get("senderNick") or "")
        is_group = str(data.get("conversationType") or "1") == "2"
        conversation = str(data.get("conversationId") or data.get("openConversationId") or "")
        chat_id = f"{GROUP_PREFIX}{conversation}" if is_group and conversation else sender_id
        msg_type = str(data.get("msgtype") or "text")
        text = ""
        files: list[InboundFile] = []
        raw_content = data.get("content")
        content: dict[str, Any] = raw_content if isinstance(raw_content, dict) else {}
        if msg_type == "text":
            text = str((data.get("text") or {}).get("content") or "").strip()
        elif msg_type == "richText":
            parts: list[str] = []
            for node in content.get("richText") or []:
                if not isinstance(node, dict):
                    continue
                if node.get("text"):
                    parts.append(str(node["text"]))
                if node.get("downloadCode"):
                    item = await self._download(
                        str(node["downloadCode"]), str(node.get("fileName") or "image.png")
                    )
                    if item:
                        files.append(item)
            text = " ".join(parts).strip()
        elif msg_type in ("picture", "file", "audio", "video"):
            code = str(content.get("downloadCode") or data.get("downloadCode") or "")
            name = str(
                content.get("fileName")
                or data.get("fileName")
                or ("image.jpg" if msg_type == "picture" else "file")
            )
            item = await self._download(code, name) if code else None
            if item:
                item.kind = "image" if msg_type == "picture" else "file"
                files.append(item)
            else:
                text = f"[{msg_type}]"
            if msg_type == "audio" and content.get("recognition"):
                text = str(content["recognition"])
        else:
            text = f"[{msg_type}]"
        if self.bus is not None:
            self.bus.inbound(
                InboundMessage(
                    channel=self.name,
                    chat_id=chat_id,
                    sender_id=sender_id,
                    sender_name=sender_name,
                    text=text,
                    files=files,
                    is_group=is_group,
                    # a robot in a DingTalk group only hears messages that @ it
                    mentioned=True,
                    message_id=message_id,
                    chat_name=str(data.get("conversationTitle") or "") if is_group else sender_name,
                )
            )

    async def _download(self, code: str, name: str) -> InboundFile | None:
        assert self._http is not None
        try:
            token = await self._access_token()
            response = await self._http.post(
                f"{API}/v1.0/robot/messageFiles/download",
                json={"downloadCode": code, "robotCode": self.client_id},
                headers={"x-acs-dingtalk-access-token": token},
            )
            url = json_object(response).get("downloadUrl") if response.status_code < 400 else None
            if not url:
                return None
            got = await self._http.get(url, follow_redirects=True)
            if got.status_code >= 400:
                return None
            return InboundFile(name=name, data=got.content)
        except Exception as exc:  # noqa: BLE001
            logger.warning("dingtalk: download failed: {}", exc)
            return None


__all__ = ["DingTalkChannel"]

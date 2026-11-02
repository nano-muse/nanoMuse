"""Feishu / Lark, over the open platform's WebSocket long connection (``lark-oapi``).

The bot lives inside Feishu: the SDK keeps a socket open to Feishu's servers and events
arrive on it, so nothing needs a public URL or an ICP-filed callback. Replies are
interactive cards with one markdown block; while a reply streams, the card is patched in
place about once a second. Approvals are cards with two buttons (允许 / 拒绝); the words
work too.

Setup (the console names, as of 2026): https://open.feishu.cn/app → *Create custom app* →
*Add capability: Bot* → *Permissions*: ``im:message``, ``im:message.p2p_msg:readonly``,
``im:message.group_at_msg:readonly``, ``im:resource`` (files and images),
``im:message:update`` is included in ``im:message`` → *Events & callbacks*: subscription
mode *Long connection*, add ``im.message.receive_v1``; callback mode *Long connection*, add
``card.action.trigger`` → *Credentials*: App ID and App Secret → publish a version.
``nanomuse channels login feishu`` does the creation for you from a QR code.

The SDK's WebSocket client runs on a thread of its own with its own event loop (it keeps
the loop in a module variable, so it cannot share ours); the thread hands events to the
manager with ``call_soon_threadsafe``. That arrangement — and the private ``_connect`` /
``_disconnect`` calls it relies on — follows nanobot's ``FeishuWsRunner``
(THIRD_PARTY_NOTICES.md).
"""

from __future__ import annotations

import asyncio
import json
import re
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from concurrent.futures import Future
from contextlib import suppress
from pathlib import Path
from typing import Any

from nanomuse.channels.base import Channel, ChannelBus, Field, InboundFile, InboundMessage
from nanomuse.logger import logger

ACCOUNTS = {"feishu": "https://accounts.feishu.cn", "lark": "https://accounts.larksuite.com"}
REGISTRATION_PATH = "/oauth/v1/app/registration"
WORKING_EMOJI = "THUMBSUP"
CARD_TEXT_LIMIT = 28_000
_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}


# ----------------------------------------------------------------------------- QR login
def _registration_post(domain: str, body: dict[str, str]) -> dict[str, Any]:
    import httpx

    base = ACCOUNTS.get(domain, ACCOUNTS["feishu"])
    response = httpx.post(
        base + REGISTRATION_PATH,
        data=body,
        timeout=15,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        data = response.json()
    except ValueError:
        response.raise_for_status()
        return {}
    return data if isinstance(data, dict) else {}


def login_begin(domain: str = "feishu", name: str = "") -> dict[str, Any]:
    """Start Feishu's scan-to-create flow (the same device-code flow the official SDK's
    ``register_app`` runs): returns the URL to open or scan, the device code to poll with,
    and how long both are good for."""
    init = _registration_post(domain, {"action": "init"})
    methods = init.get("supported_auth_methods") or []
    if "client_secret" not in methods:
        raise RuntimeError("Feishu did not offer an App Secret login for this flow.")
    begun = _registration_post(
        domain,
        {
            "action": "begin",
            "archetype": "PersonalAgent",
            "auth_method": "client_secret",
            "request_user_info": "open_id",
        },
    )
    device_code = begun.get("device_code")
    url = begun.get("verification_uri_complete")
    if not isinstance(device_code, str) or not isinstance(url, str) or not device_code or not url:
        raise RuntimeError(begun.get("error_description") or "Feishu did not start the login.")
    if name:
        from urllib.parse import urlencode

        url += ("&" if "?" in url else "?") + urlencode({"name": name[:60]})
    return {
        "device_code": device_code,
        "url": url,
        "interval": int(begun.get("interval") or 5),
        "expires_in": int(begun.get("expires_in") or begun.get("expire_in") or 600),
    }


def login_poll(device_code: str, domain: str = "feishu") -> dict[str, Any]:
    """One poll of the flow: ``pending`` until the person confirmed in Feishu, then
    ``succeeded`` with the new app's id and secret, or ``failed`` when they declined or
    the code ran out."""
    data = _registration_post(
        domain, {"action": "poll", "device_code": device_code, "tp": "ob_app"}
    )
    user_info = data.get("user_info")
    user: dict[str, Any] = user_info if isinstance(user_info, dict) else {}
    if user.get("tenant_brand") == "lark":
        domain = "lark"
    if data.get("client_id") and data.get("client_secret"):
        return {
            "status": "succeeded",
            "app_id": str(data["client_id"]),
            "app_secret": str(data["client_secret"]),
            "domain": domain,
        }
    error = str(data.get("error") or "")
    if error in ("access_denied", "expired_token"):
        return {"status": "failed", "error": error, "domain": domain}
    return {"status": "pending", "domain": domain}


# ----------------------------------------------------------------------------- the socket
class _Runner:
    """The SDK's WebSocket client on its own thread and loop."""

    def __init__(
        self,
        make_client: Callable[[], Any],
        on_state: Callable[[str, str], None],
    ):
        self._make_client = make_client
        self._on_state = on_state
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._client: Any = None
        self._stop = threading.Event()
        self.first = threading.Event()  # set after the first connect attempt, either way
        self.error = ""

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="feishu-ws", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        try:
            import lark_oapi.ws.client as ws_client

            previous = getattr(ws_client, "loop", None)
            if previous is not None and previous is not loop and not previous.is_running():
                with suppress(Exception):
                    previous.close()
            ws_client.loop = loop  # the SDK schedules everything on this module variable
            delay = 5.0
            while not self._stop.is_set():
                client = self._make_client()
                self._client = client
                try:
                    loop.run_until_complete(client._connect())
                except Exception as exc:  # noqa: BLE001 — the vendor's words
                    self.error = str(exc).splitlines()[0][:300] if str(exc) else type(exc).__name__
                    self._on_state("error", self.error)
                    self.first.set()
                    with suppress(Exception):
                        loop.run_until_complete(client._disconnect())
                    if self._stop.wait(delay):
                        break
                    delay = min(delay * 2, 120.0)
                    continue
                self.error = ""
                self._on_state("connected", "")
                self.first.set()
                ping = loop.create_task(client._ping_loop())
                loop.run_forever()
                ping.cancel()
                with suppress(Exception):
                    loop.run_until_complete(client._disconnect())
                break
        finally:
            with suppress(Exception):
                loop.run_until_complete(loop.shutdown_asyncgens())
            loop.close()
            self.first.set()

    def stop(self) -> None:
        self._stop.set()
        loop, client = self._loop, self._client
        if loop is not None and not loop.is_closed() and loop.is_running():

            def _shutdown() -> None:
                if client is not None:
                    client._auto_reconnect = False
                loop.stop()

            loop.call_soon_threadsafe(_shutdown)
        if self._thread is not None:
            self._thread.join(timeout=5)


# ----------------------------------------------------------------------------- the channel
class FeishuChannel(Channel):
    name = "feishu"
    label = "Feishu"
    sdk_module = "lark_oapi"
    extra = "feishu"
    supports_edit = True
    console_url = "https://open.feishu.cn/app"
    fields = (
        Field("app_id", "App ID", required=True, help="Credentials & Basic Info → App ID (cli_…)"),
        Field(
            "app_secret",
            "App Secret",
            "secret",
            required=True,
            help="Credentials & Basic Info → App Secret",
        ),
        Field(
            "domain",
            "Edition",
            "choice",
            choices=("feishu", "lark"),
            default="feishu",
            help="feishu for 飞书 (open.feishu.cn), lark for Lark (open.larksuite.com)",
        ),
        Field(
            "encrypt_key",
            "Encrypt Key",
            "secret",
            help="Only if you set one under Events & callbacks",
        ),
        Field(
            "verification_token", "Verification Token", "secret", help="Only if you set one there"
        ),
    )

    def __init__(self, settings: dict[str, Any]):
        super().__init__(settings)
        self._lark: Any = None
        self._client: Any = None
        self._runner: _Runner | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._bot_open_id = ""
        self._seen: OrderedDict[str, None] = OrderedDict()
        # chat -> (message id of the last inbound, its reaction id)
        self._working: dict[str, tuple[str, str]] = {}
        self._last_inbound: dict[str, str] = {}
        # stream id -> card message id
        self._cards: dict[str, str] = {}

    # ------------------------------------------------------------------ lifecycle
    async def start(self, bus: ChannelBus) -> None:
        await super().start(bus)
        self._loop = asyncio.get_running_loop()
        lark = await asyncio.to_thread(self._import)
        self._lark = lark
        domain = lark.LARK_DOMAIN if self.settings.get("domain") == "lark" else lark.FEISHU_DOMAIN
        app_id = str(self.settings.get("app_id") or "")
        app_secret = str(self.settings.get("app_secret") or "")
        self._client = (
            lark.Client.builder()
            .app_id(app_id)
            .app_secret(app_secret)
            .domain(domain)
            .log_level(lark.LogLevel.WARNING)
            .build()
        )
        builder = lark.EventDispatcherHandler.builder(
            str(self.settings.get("encrypt_key") or ""),
            str(self.settings.get("verification_token") or ""),
        ).register_p2_im_message_receive_v1(self._on_message_event)
        register_card = getattr(builder, "register_p2_card_action_trigger", None)
        if callable(register_card):
            builder = register_card(self._on_card_action)
        handler = builder.build()

        def make_client() -> Any:
            return lark.ws.Client(
                app_id,
                app_secret,
                domain=domain,
                event_handler=handler,
                log_level=lark.LogLevel.WARNING,
                auto_reconnect=True,
            )

        self._runner = _Runner(make_client, self._on_state)
        self._runner.start()
        # the first connect attempt says whether the credentials are taken
        await asyncio.to_thread(self._runner.first.wait, 20)
        if self._runner.error:
            raise RuntimeError(self._runner.error)
        self._bot_open_id = await asyncio.to_thread(self._fetch_bot_open_id)

    @staticmethod
    def _import() -> Any:
        import lark_oapi as lark

        return lark

    def _on_state(self, state: str, detail: str) -> None:
        if self.bus is not None:
            self.bus.set_status(self.name, state, detail)

    async def stop(self) -> None:
        runner, self._runner = self._runner, None
        if runner is not None:
            await asyncio.to_thread(runner.stop)
        self._client = None

    async def verify(self) -> str:
        name = await asyncio.to_thread(self._bot_info, "app_name")
        return f"Bot: {name}" if name else "The credentials work."

    def _bot_info(self, key: str) -> str:
        lark = self._lark
        request = (
            lark.BaseRequest.builder()
            .http_method(lark.HttpMethod.GET)
            .uri("/open-apis/bot/v3/info")
            .token_types({lark.AccessTokenType.APP})
            .build()
        )
        response = self._client.request(request)
        if not response.success():
            raise RuntimeError(f"{response.msg} (code {response.code})")
        data = json.loads(response.raw.content or b"{}")
        bot = (data.get("data") or data).get("bot") or {}
        return str(bot.get(key) or "")

    def _fetch_bot_open_id(self) -> str:
        try:
            return self._bot_info("open_id")
        except Exception as exc:  # noqa: BLE001
            logger.debug("feishu: could not read the bot's open_id: {}", exc)
            return ""

    # ------------------------------------------------------------------ inbound
    def _on_message_event(self, data: Any) -> None:
        """Called on the socket's thread with a ``P2ImMessageReceiveV1``."""
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        # the socket reads on; when the handed-over handling fails, the exception must
        # not sit in a future nobody reads
        coro = self._handle_message(data)
        try:
            done = asyncio.run_coroutine_threadsafe(coro, loop)
        except RuntimeError:
            coro.close()
            logger.warning("feishu: the runtime loop stopped before message handover")
            return
        done.add_done_callback(self._log_failed_handover)

    @staticmethod
    def _log_failed_handover(future: Future[Any]) -> None:
        if future.cancelled():
            return
        exc = future.exception()
        if exc is not None:
            logger.warning("feishu: a handed-over message failed: {}", exc)

    def _on_card_action(self, data: Any) -> Any:
        event = getattr(data, "event", None)
        action = getattr(event, "action", None)
        value = getattr(action, "value", None)
        operator = getattr(event, "operator", None)
        context = getattr(event, "context", None)
        if isinstance(value, dict) and self.bus is not None:
            self.bus.action(
                self.name,
                str(getattr(context, "open_chat_id", "") or ""),
                str(getattr(operator, "open_id", "") or ""),
                value,
            )
        with suppress(Exception):
            from lark_oapi.event.callback.model.p2_card_action_trigger import (
                P2CardActionTriggerResponse,
            )

            return P2CardActionTriggerResponse({"toast": {"type": "info", "content": "OK"}})
        return None

    async def _handle_message(self, data: Any) -> None:
        try:
            event = data.event
            message = event.message
            sender = event.sender
        except AttributeError:
            return
        if message is None or sender is None or getattr(sender, "sender_type", "") == "bot":
            return
        message_id = str(getattr(message, "message_id", "") or "")
        if not message_id or message_id in self._seen:
            return
        self._seen[message_id] = None
        while len(self._seen) > 1000:
            self._seen.popitem(last=False)
        sender_id = str(getattr(getattr(sender, "sender_id", None), "open_id", "") or "")
        chat_id = str(getattr(message, "chat_id", "") or "")
        is_group = getattr(message, "chat_type", "p2p") == "group"
        msg_type = str(getattr(message, "message_type", "text") or "text")
        raw = getattr(message, "content", "") or "{}"
        try:
            content = json.loads(raw) if isinstance(raw, str) else {}
        except json.JSONDecodeError:
            content = {}
        mentions = list(getattr(message, "mentions", None) or [])
        mentioned = not is_group or self._mentioned(mentions, raw)
        text = ""
        files: list[InboundFile] = []
        if msg_type == "text":
            text = str(content.get("text") or "")
        elif msg_type == "post":
            text, image_keys = _post_text(content)
            for key in image_keys[:5]:
                item = await asyncio.to_thread(self._download, message_id, key, "image")
                if item:
                    files.append(item)
        elif msg_type in ("image", "file", "audio", "media"):
            key = str(content.get("image_key") or content.get("file_key") or "")
            kind = "image" if msg_type == "image" else "file"
            item = await asyncio.to_thread(self._download, message_id, key, kind) if key else None
            if item:
                if msg_type == "file" and content.get("file_name"):
                    item.name = str(content["file_name"])
                files.append(item)
            else:
                text = f"[{msg_type}]"
        else:
            text = str(content.get("text") or f"[{msg_type}]")
        text = _strip_mentions(text, mentions)
        self._last_inbound[chat_id] = message_id
        if self.bus is not None:
            self.bus.inbound(
                InboundMessage(
                    channel=self.name,
                    chat_id=chat_id,
                    sender_id=sender_id,
                    sender_name="",
                    text=text,
                    files=files,
                    is_group=is_group,
                    mentioned=mentioned,
                    message_id=message_id,
                )
            )

    def _mentioned(self, mentions: list[Any], raw: str) -> bool:
        if "@_all" in raw:
            return True
        for mention in mentions:
            ident = getattr(mention, "id", None)
            open_id = str(getattr(ident, "open_id", "") or "")
            if self._bot_open_id:
                if open_id == self._bot_open_id:
                    return True
            elif open_id.startswith("ou_") and not getattr(ident, "user_id", None):
                return True
        return False

    def _download(self, message_id: str, key: str, kind: str) -> InboundFile | None:
        from lark_oapi.api.im.v1 import GetMessageResourceRequest

        request = (
            GetMessageResourceRequest.builder()
            .message_id(message_id)
            .file_key(key)
            .type(kind)
            .build()
        )
        response = self._client.im.v1.message_resource.get(request)
        if not response.success():
            logger.warning("feishu: download failed: {} (code {})", response.msg, response.code)
            return None
        stream = getattr(response, "file", None)
        if stream is None:
            data = b""
        elif hasattr(stream, "read"):
            data = bytes(stream.read())
        else:
            data = bytes(stream)
        name = str(getattr(response, "file_name", "") or "") or (
            f"{key[:12]}.png" if kind == "image" else key[:12]
        )
        return InboundFile(name=name, data=data, kind=kind)

    # ------------------------------------------------------------------ outbound
    @staticmethod
    def _card(text: str, buttons: list[dict[str, Any]] | None = None) -> str:
        elements: list[dict[str, Any]] = [{"tag": "markdown", "content": text[:CARD_TEXT_LIMIT]}]
        if buttons:
            elements.append({"tag": "action", "actions": buttons})
        return json.dumps(
            {"config": {"wide_screen_mode": True}, "elements": elements}, ensure_ascii=False
        )

    def _create(self, chat_id: str, msg_type: str, content: str) -> str:
        from lark_oapi.api.im.v1 import CreateMessageRequest, CreateMessageRequestBody

        request = (
            CreateMessageRequest.builder()
            .receive_id_type("chat_id")
            .request_body(
                CreateMessageRequestBody.builder()
                .receive_id(chat_id)
                .msg_type(msg_type)
                .content(content)
                .build()
            )
            .build()
        )
        response = self._client.im.v1.message.create(request)
        if not response.success():
            raise RuntimeError(f"{response.msg} (code {response.code})")
        return str(getattr(response.data, "message_id", "") or "")

    def _patch(self, message_id: str, content: str) -> None:
        from lark_oapi.api.im.v1 import PatchMessageRequest, PatchMessageRequestBody

        request = (
            PatchMessageRequest.builder()
            .message_id(message_id)
            .request_body(PatchMessageRequestBody.builder().content(content).build())
            .build()
        )
        response = self._client.im.v1.message.patch(request)
        if not response.success():
            raise RuntimeError(f"{response.msg} (code {response.code})")

    def _upload(self, path: Path) -> tuple[str, str]:
        """``(msg_type, content)`` for a file: an image as an image, the rest as a file."""
        if path.suffix.lower() in _IMAGE_SUFFIXES:
            from lark_oapi.api.im.v1 import CreateImageRequest, CreateImageRequestBody

            with path.open("rb") as fh:
                request = (
                    CreateImageRequest.builder()
                    .request_body(
                        CreateImageRequestBody.builder().image_type("message").image(fh).build()
                    )
                    .build()
                )
                response = self._client.im.v1.image.create(request)
            if not response.success():
                raise RuntimeError(f"{response.msg} (code {response.code})")
            return "image", json.dumps({"image_key": response.data.image_key})
        from lark_oapi.api.im.v1 import CreateFileRequest, CreateFileRequestBody

        with path.open("rb") as fh:
            request = (
                CreateFileRequest.builder()
                .request_body(
                    CreateFileRequestBody.builder()
                    .file_type("stream")
                    .file_name(path.name)
                    .file(fh)
                    .build()
                )
                .build()
            )
            response = self._client.im.v1.file.create(request)
        if not response.success():
            raise RuntimeError(f"{response.msg} (code {response.code})")
        return "file", json.dumps({"file_key": response.data.file_key})

    async def send(self, chat_id: str, text: str, *, files: list[str] | None = None) -> str:
        message_id = ""
        if text.strip():
            message_id = await asyncio.to_thread(
                self._create, chat_id, "interactive", self._card(text)
            )
        for item in files or []:
            path = Path(item)
            if not path.is_file():
                continue
            msg_type, content = await asyncio.to_thread(self._upload, path)
            await asyncio.to_thread(self._create, chat_id, msg_type, content)
        return message_id

    async def stream(self, chat_id: str, stream_id: str, text: str, *, done: bool) -> None:
        card = self._cards.get(stream_id)
        if card is None:
            self._cards[stream_id] = await asyncio.to_thread(
                self._create, chat_id, "interactive", self._card(text or "…")
            )
        else:
            await asyncio.to_thread(self._patch, card, self._card(text))
        if done:
            self._cards.pop(stream_id, None)

    async def ask(self, chat_id: str, approval_id: str, text: str) -> None:
        buttons = [
            {
                "tag": "button",
                "text": {"tag": "plain_text", "content": "允许 · Allow"},
                "type": "primary",
                "value": {"approval": approval_id, "decision": "allow"},
            },
            {
                "tag": "button",
                "text": {"tag": "plain_text", "content": "拒绝 · Deny"},
                "type": "danger",
                "value": {"approval": approval_id, "decision": "deny"},
            },
        ]
        await asyncio.to_thread(self._create, chat_id, "interactive", self._card(text, buttons))

    async def typing(self, chat_id: str, on: bool) -> None:
        """A 👍 on the message being worked on; taken off when the reply is out."""
        if on:
            message_id = self._last_inbound.get(chat_id)
            if not message_id or chat_id in self._working:
                return
            reaction = await asyncio.to_thread(self._react, message_id)
            if reaction:
                self._working[chat_id] = (message_id, reaction)
        else:
            pair = self._working.pop(chat_id, None)
            if pair:
                await asyncio.to_thread(self._unreact, *pair)

    def _react(self, message_id: str) -> str:
        from lark_oapi.api.im.v1 import (
            CreateMessageReactionRequest,
            CreateMessageReactionRequestBody,
            Emoji,
        )

        request = (
            CreateMessageReactionRequest.builder()
            .message_id(message_id)
            .request_body(
                CreateMessageReactionRequestBody.builder()
                .reaction_type(Emoji.builder().emoji_type(WORKING_EMOJI).build())
                .build()
            )
            .build()
        )
        response = self._client.im.v1.message_reaction.create(request)
        if not response.success():
            return ""
        return str(getattr(response.data, "reaction_id", "") or "")

    def _unreact(self, message_id: str, reaction_id: str) -> None:
        from lark_oapi.api.im.v1 import DeleteMessageReactionRequest

        request = (
            DeleteMessageReactionRequest.builder()
            .message_id(message_id)
            .reaction_id(reaction_id)
            .build()
        )
        with suppress(Exception):
            self._client.im.v1.message_reaction.delete(request)


def _post_text(content: dict[str, Any]) -> tuple[str, list[str]]:
    """The text of a rich-text (``post``) message, and the keys of the images in it."""
    body = content
    if "content" not in body:
        # localized form: {"zh_cn": {"title": …, "content": […]}}
        for value in content.values():
            if isinstance(value, dict) and "content" in value:
                body = value
                break
    lines: list[str] = []
    images: list[str] = []
    title = str(body.get("title") or "")
    if title:
        lines.append(title)
    for paragraph in body.get("content") or []:
        parts: list[str] = []
        for node in paragraph if isinstance(paragraph, list) else []:
            if not isinstance(node, dict):
                continue
            tag = node.get("tag")
            if tag == "text":
                parts.append(str(node.get("text") or ""))
            elif tag == "a":
                parts.append(f"{node.get('text') or ''} ({node.get('href') or ''})")
            elif tag == "at":
                parts.append(f"@{node.get('user_name') or node.get('user_id') or ''}")
            elif tag == "img" and node.get("image_key"):
                images.append(str(node["image_key"]))
        if parts:
            lines.append("".join(parts))
    return "\n".join(lines).strip(), images


def _strip_mentions(text: str, mentions: list[Any]) -> str:
    """``@_user_1`` placeholders out of the text: the bot's own mention is dropped, other
    people's become their names."""
    for mention in mentions:
        key = str(getattr(mention, "key", "") or "")
        if not key:
            continue
        name = str(getattr(mention, "name", "") or "")
        ident = getattr(mention, "id", None)
        is_bot_like = not getattr(ident, "user_id", None)
        replacement = "" if is_bot_like else f"@{name}"
        text = re.sub(rf"{re.escape(key)}(?![A-Za-z0-9_])", replacement, text)
    return re.sub(r"[ \t]{2,}", " ", text).strip()


def wait_for_login(domain: str, name: str, on_url: Callable[[str], None]) -> dict[str, Any]:
    """The terminal's version of the QR flow: begin, show, poll until it ends."""
    begun = login_begin(domain, name)
    on_url(begun["url"])
    deadline = time.monotonic() + begun["expires_in"]
    while time.monotonic() < deadline:
        result = login_poll(begun["device_code"], domain)
        if result["status"] != "pending":
            return result
        time.sleep(begun["interval"])
    return {"status": "failed", "error": "expired"}


__all__ = ["FeishuChannel", "login_begin", "login_poll", "wait_for_login"]

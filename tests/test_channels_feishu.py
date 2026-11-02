"""Feishu against a fake ``lark_oapi``: the socket runner on its thread, events in,
cards out (and patched in place), approval buttons, reactions, the QR login flow."""

from __future__ import annotations

import asyncio
import io
import json
import sys
import types
from importlib.machinery import ModuleSpec
from types import SimpleNamespace
from typing import Any

import pytest

from nanomuse.channels import feishu
from nanomuse.channels.base import InboundMessage
from nanomuse.channels.feishu import FeishuChannel, _post_text, _strip_mentions
from nanomuse.logger import logger


class Bus:
    def __init__(self) -> None:
        self.inbound_msgs: list[InboundMessage] = []
        self.statuses: list[tuple[str, str, str]] = []
        self.actions: list[tuple[str, str, str, dict[str, Any]]] = []

    def inbound(self, msg: InboundMessage) -> None:
        self.inbound_msgs.append(msg)

    def set_status(self, channel: str, state: str, detail: str = "") -> None:
        self.statuses.append((channel, state, detail))

    def action(self, channel: str, chat_id: str, sender_id: str, value: dict[str, Any]) -> None:
        self.actions.append((channel, chat_id, sender_id, value))


# ----------------------------------------------------------------------------- a fake SDK
class Fluent:
    """The SDK's builder style: ``X.builder().a(1).b(2).build()`` → an object with ``.data``."""

    def __init__(self) -> None:
        self.data: dict[str, Any] = {}

    @classmethod
    def builder(cls) -> Fluent:
        return cls()

    def build(self) -> Fluent:
        return self

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise AttributeError(name)

        def setter(value: Any = None) -> Fluent:
            self.data[name] = value.data if isinstance(value, Fluent) else value
            return self

        return setter


def fluent(name: str) -> type[Fluent]:
    return type(name, (Fluent,), {})


class Resp:
    def __init__(self, ok: bool = True, **data: Any) -> None:
        self.ok = ok
        self.code = 0 if ok else 99991
        self.msg = "ok" if ok else "app secret invalid"
        self.data = SimpleNamespace(**data)
        self.raw = SimpleNamespace(
            content=json.dumps(
                {"data": {"bot": {"open_id": "ou_bot", "app_name": "Muse"}}}
            ).encode()
        )
        self.file = io.BytesIO(b"image-bytes")
        self.file_name = "pic.png"

    def success(self) -> bool:
        return self.ok


class FakeHttp:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.fail_next = False
        im = SimpleNamespace(
            message=SimpleNamespace(
                create=self._rec("message.create", message_id="om_1"),
                patch=self._rec("message.patch"),
            ),
            message_reaction=SimpleNamespace(
                create=self._rec("reaction.create", reaction_id="r1"),
                delete=self._rec("reaction.delete"),
            ),
            message_resource=SimpleNamespace(get=self._rec("resource.get")),
            image=SimpleNamespace(create=self._rec("image.create", image_key="img_1")),
            file=SimpleNamespace(create=self._rec("file.create", file_key="file_1")),
        )
        self.im = SimpleNamespace(v1=im)

    def _rec(self, name: str, **data: Any):  # noqa: ANN202
        def call(req: Fluent) -> Resp:
            self.calls.append((name, req.data))
            if self.fail_next:
                self.fail_next = False
                return Resp(ok=False)
            return Resp(**data)

        return call

    def request(self, req: Fluent) -> Resp:
        self.calls.append(("request", req.data))
        return Resp()

    def of(self, name: str) -> list[dict[str, Any]]:
        return [d for n, d in self.calls if n == name]


class FakeHandler:
    def __init__(self) -> None:
        self.message_cb: Any = None
        self.card_cb: Any = None


class HandlerBuilder:
    def __init__(self, handler: FakeHandler) -> None:
        self.handler = handler

    def register_p2_im_message_receive_v1(self, cb: Any) -> HandlerBuilder:
        self.handler.message_cb = cb
        return self

    def register_p2_card_action_trigger(self, cb: Any) -> HandlerBuilder:
        self.handler.card_cb = cb
        return self

    def build(self) -> FakeHandler:
        return self.handler


class FakeWs:
    instances: list[FakeWs] = []

    def __init__(self, app_id: str, app_secret: str, **kw: Any) -> None:
        self.app_id, self.app_secret, self.kw = app_id, app_secret, kw
        self.connected = False
        self.disconnected = False
        self._auto_reconnect = True
        FakeWs.instances.append(self)

    async def _connect(self) -> None:
        if self.app_secret == "bad":
            raise Exception("app secret invalid (code 10014)")
        self.connected = True

    async def _disconnect(self) -> None:
        self.disconnected = True

    async def _ping_loop(self) -> None:
        while True:
            await asyncio.sleep(3600)


@pytest.fixture()
def lark(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    http = FakeHttp()
    handler = FakeHandler()
    FakeWs.instances.clear()

    def module(name: str, **attrs: Any) -> types.ModuleType:
        mod = types.ModuleType(name)
        mod.__spec__ = ModuleSpec(name, None)
        mod.__path__ = []  # type: ignore[attr-defined]
        for key, value in attrs.items():
            setattr(mod, key, value)
        monkeypatch.setitem(sys.modules, name, mod)
        return mod

    client_builder = fluent("ClientBuilder")
    client_builder.build = lambda self: http  # type: ignore[method-assign]
    root = module(
        "lark_oapi",
        FEISHU_DOMAIN="https://open.feishu.cn",
        LARK_DOMAIN="https://open.larksuite.com",
        LogLevel=SimpleNamespace(WARNING=30),
        Client=client_builder,
        EventDispatcherHandler=SimpleNamespace(builder=lambda ek, vt: HandlerBuilder(handler)),
        BaseRequest=fluent("BaseRequest"),
        HttpMethod=SimpleNamespace(GET="GET"),
        AccessTokenType=SimpleNamespace(APP="app"),
    )
    ws = module("lark_oapi.ws", Client=FakeWs)
    root.ws = ws  # type: ignore[attr-defined]
    module("lark_oapi.ws.client", loop=None)
    module("lark_oapi.api")
    module("lark_oapi.api.im")
    module(
        "lark_oapi.api.im.v1",
        **{
            name: fluent(name)
            for name in (
                "CreateMessageRequest",
                "CreateMessageRequestBody",
                "PatchMessageRequest",
                "PatchMessageRequestBody",
                "CreateMessageReactionRequest",
                "CreateMessageReactionRequestBody",
                "Emoji",
                "DeleteMessageReactionRequest",
                "GetMessageResourceRequest",
                "CreateImageRequest",
                "CreateImageRequestBody",
                "CreateFileRequest",
                "CreateFileRequestBody",
            )
        },
    )
    module("lark_oapi.event")
    module("lark_oapi.event.callback")
    module("lark_oapi.event.callback.model")

    class P2CardActionTriggerResponse:
        def __init__(self, d: dict[str, Any]) -> None:
            self.d = d

    module(
        "lark_oapi.event.callback.model.p2_card_action_trigger",
        P2CardActionTriggerResponse=P2CardActionTriggerResponse,
    )
    return SimpleNamespace(http=http, handler=handler)


def message_event(
    text: str,
    *,
    chat_type: str = "p2p",
    message_type: str = "text",
    content: dict[str, Any] | None = None,
    mentions: list[Any] | None = None,
    message_id: str = "om_in1",
    sender_type: str = "user",
) -> SimpleNamespace:
    return SimpleNamespace(
        event=SimpleNamespace(
            sender=SimpleNamespace(
                sender_type=sender_type, sender_id=SimpleNamespace(open_id="ou_ann")
            ),
            message=SimpleNamespace(
                message_id=message_id,
                chat_id="oc_1",
                chat_type=chat_type,
                message_type=message_type,
                content=json.dumps(content if content is not None else {"text": text}),
                mentions=mentions or [],
            ),
        )
    )


def mention(key: str, open_id: str, name: str, user_id: str | None = None) -> SimpleNamespace:
    return SimpleNamespace(key=key, id=SimpleNamespace(open_id=open_id, user_id=user_id), name=name)


async def until(pred, timeout: float = 3.0):  # noqa: ANN001
    for _ in range(int(timeout / 0.02)):
        if pred():
            return
        await asyncio.sleep(0.02)
    raise AssertionError("condition not met in time")


# ----------------------------------------------------------------------------- tests
def test_rich_text_and_mentions():
    text, images = _post_text(
        {
            "zh_cn": {
                "title": "Plan",
                "content": [
                    [
                        {"tag": "text", "text": "see "},
                        {"tag": "a", "text": "this", "href": "https://x.test"},
                    ],
                    [{"tag": "img", "image_key": "img_k"}],
                    [{"tag": "at", "user_name": "Bob"}, {"tag": "text", "text": " knows"}],
                ],
            }
        }
    )
    assert text == "Plan\nsee this (https://x.test)\n@Bob knows" and images == ["img_k"]
    mentions = [mention("@_user_1", "ou_bot", "Muse"), mention("@_user_2", "ou_bob", "Bob", "u2")]
    assert _strip_mentions("@_user_1 hello @_user_2", mentions) == "hello @Bob"
    assert _strip_mentions("@_user_10 stays", mentions) == "@_user_10 stays"


def test_sdk_missing_is_a_hint(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setitem(sys.modules, "lark_oapi", None)
    assert FeishuChannel.sdk_available() is False
    assert FeishuChannel.install_hint() == "pip install 'nanomuse[feishu]'"
    assert FeishuChannel.missing({"app_id": "x"}) == ["app_secret"]


async def test_events_in_and_cards_out(lark: SimpleNamespace):
    assert FeishuChannel.sdk_available() is True
    bus = Bus()
    ch = FeishuChannel({"app_id": "cli_x", "app_secret": "s3", "domain": "feishu"})
    await ch.start(bus)
    try:
        assert ("feishu", "connected", "") in bus.statuses
        assert FakeWs.instances[0].kw["domain"] == "https://open.feishu.cn"
        assert ch._bot_open_id == "ou_bot"
        assert await ch.verify() == "Bot: Muse"

        # a group message that @s the bot; the placeholder is stripped
        lark.handler.message_cb(
            message_event(
                "@_user_1 hello",
                chat_type="group",
                mentions=[mention("@_user_1", "ou_bot", "Muse")],
            )
        )
        await until(lambda: bus.inbound_msgs)
        msg = bus.inbound_msgs[0]
        assert (
            msg.chat_id == "oc_1" and msg.sender_id == "ou_ann" and msg.is_group and msg.mentioned
        )
        assert msg.text == "hello" and msg.message_id == "om_in1"
        # the same event twice is one message; a bot's message is nothing
        lark.handler.message_cb(message_event("again"))
        lark.handler.message_cb(message_event("bot", message_id="om_b", sender_type="bot"))
        # a group message to someone else is not for us
        lark.handler.message_cb(
            message_event(
                "@_user_1 bob?",
                chat_type="group",
                message_id="om_in2",
                mentions=[mention("@_user_1", "ou_bob", "Bob", "u2")],
            )
        )
        # an image in a direct chat is downloaded
        lark.handler.message_cb(
            message_event(
                "", message_type="image", content={"image_key": "img_9"}, message_id="om_in3"
            )
        )
        await until(lambda: len(bus.inbound_msgs) >= 3)
        await asyncio.sleep(0.05)
        assert len(bus.inbound_msgs) == 3
        other, image = bus.inbound_msgs[1:]
        assert other.is_group and not other.mentioned
        assert image.text == "" and [f.name for f in image.files] == ["pic.png"]
        assert image.files[0].data == b"image-bytes" and image.files[0].kind == "image"
        assert lark.http.of("resource.get")[0]["file_key"] == "img_9"

        # replies are interactive cards with one markdown block
        assert await ch.send("oc_1", "**hi**") == "om_1"
        created = lark.http.of("message.create")[-1]
        assert created["receive_id_type"] == "chat_id"
        body = created["request_body"]
        assert body["receive_id"] == "oc_1" and body["msg_type"] == "interactive"
        assert json.loads(body["content"])["elements"][0] == {
            "tag": "markdown",
            "content": "**hi**",
        }
        # a growing reply patches the same card
        await ch.stream("oc_1", "s1", "Work", done=False)
        await ch.stream("oc_1", "s1", "Working…", done=False)
        await ch.stream("oc_1", "s1", "Worked.", done=True)
        patches = lark.http.of("message.patch")
        assert len(patches) == 2 and patches[-1]["message_id"] == "om_1"
        assert (
            json.loads(patches[-1]["request_body"]["content"])["elements"][0]["content"]
            == "Worked."
        )
        # an approval card has two buttons carrying the decision
        await ch.ask("oc_1", "ap-1", "May I?")
        card = json.loads(lark.http.of("message.create")[-1]["request_body"]["content"])
        actions = card["elements"][1]["actions"]
        assert [a["value"]["decision"] for a in actions] == ["allow", "deny"]
        assert actions[0]["value"]["approval"] == "ap-1"
        # a press comes back as an action with a toast
        response = lark.handler.card_cb(
            SimpleNamespace(
                event=SimpleNamespace(
                    action=SimpleNamespace(value={"approval": "ap-1", "decision": "allow"}),
                    operator=SimpleNamespace(open_id="ou_ann"),
                    context=SimpleNamespace(open_chat_id="oc_1"),
                )
            )
        )
        assert response.d["toast"]["type"] == "info"
        assert bus.actions == [
            ("feishu", "oc_1", "ou_ann", {"approval": "ap-1", "decision": "allow"})
        ]
        # "working" is a reaction on the message being answered, taken off after
        await ch.typing("oc_1", True)
        assert lark.http.of("reaction.create")[-1]["message_id"] == "om_in3"
        await ch.typing("oc_1", False)
        assert lark.http.of("reaction.delete")[-1]["reaction_id"] == "r1"
        # files: an image as an image, the rest as a file
        lark.http.fail_next = True
        with pytest.raises(RuntimeError, match="app secret invalid"):
            await ch.send("oc_1", "fails")
    finally:
        await ch.stop()
    assert FakeWs.instances[0].disconnected


async def test_files_out(lark: SimpleNamespace, tmp_path):  # noqa: ANN001
    ch = FeishuChannel({"app_id": "cli_x", "app_secret": "s3"})
    await ch.start(Bus())
    try:
        (tmp_path / "a.png").write_bytes(b"png")
        (tmp_path / "b.pdf").write_bytes(b"pdf")
        await ch.send("oc_1", "", files=[str(tmp_path / "a.png"), str(tmp_path / "b.pdf")])
        kinds = [d["request_body"]["msg_type"] for d in lark.http.of("message.create")]
        assert kinds == ["image", "file"]
        assert (
            lark.http.of("image.create")
            and lark.http.of("file.create")[0]["request_body"]["file_name"] == "b.pdf"
        )
    finally:
        await ch.stop()


async def test_bad_credentials_fail_to_start(lark: SimpleNamespace):
    ch = FeishuChannel({"app_id": "cli_x", "app_secret": "bad"})
    with pytest.raises(RuntimeError, match="app secret invalid"):
        await ch.start(Bus())
    await ch.stop()


def test_qr_login_flow(monkeypatch: pytest.MonkeyPatch):
    posted: list[tuple[str, dict[str, str]]] = []
    answers = iter(
        [
            {"supported_auth_methods": ["client_secret"]},
            {
                "device_code": "dev-1",
                "verification_uri_complete": "https://accounts.feishu.cn/page/launcher?ticket=t1",
                "interval": 2,
                "expires_in": 300,
            },
            {"error": "authorization_pending"},
            {"user_info": {"tenant_brand": "lark"}, "error": "authorization_pending"},
            {
                "client_id": "cli_new",
                "client_secret": "sec_new",
                "user_info": {"tenant_brand": "lark"},
            },
            {"error": "expired_token"},
        ]
    )

    def fake_post(domain: str, body: dict[str, str]) -> dict[str, Any]:
        posted.append((domain, body))
        return next(answers)

    monkeypatch.setattr(feishu, "_registration_post", fake_post)
    begun = feishu.login_begin("feishu", "My Muse")
    assert begun["device_code"] == "dev-1" and begun["interval"] == 2 and begun["expires_in"] == 300
    assert begun["url"].startswith("https://accounts.feishu.cn/page/launcher?ticket=t1&name=My")
    assert posted[1][1]["archetype"] == "PersonalAgent"
    assert feishu.login_poll("dev-1") == {"status": "pending", "domain": "feishu"}
    assert feishu.login_poll("dev-1") == {"status": "pending", "domain": "lark"}
    assert feishu.login_poll("dev-1", "lark") == {
        "status": "succeeded",
        "app_id": "cli_new",
        "app_secret": "sec_new",
        "domain": "lark",
    }
    assert posted[-1][0] == "lark" and posted[-1][1]["tp"] == "ob_app"
    assert feishu.login_poll("dev-1")["status"] == "failed"


async def test_a_failed_handover_is_logged_not_swallowed(lark: SimpleNamespace):
    """The socket thread hands an event to the loop with ``run_coroutine_threadsafe`` and
    reads on; when the handed-over handling then fails, the exception sat in a future
    nobody read — the event was gone with no line in the log."""
    bus = Bus()
    ch = FeishuChannel({"app_id": "cli_x", "app_secret": "s3", "domain": "feishu"})
    await ch.start(bus)
    try:

        async def boom(data: Any) -> None:
            raise RuntimeError("hand-over exploded")

        ch._handle_message = boom  # type: ignore[method-assign]
        warnings: list[str] = []
        sink = logger.add(lambda m: warnings.append(m.record["message"]), level="WARNING")
        try:
            lark.handler.message_cb(message_event("boom"))
            await until(lambda: any("hand-over exploded" in w for w in warnings))
        finally:
            logger.remove(sink)
    finally:
        await ch.stop()

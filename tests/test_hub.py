"""The hub end of the runtime: local actions, the async client against a fake relay, and
the service that turns another device's `task` into a visible side chat (and a side chat
addressed to a device into a `task` on it) — docs/hub.md, docs/every-device.md."""

from __future__ import annotations

import asyncio
import base64
import functools
import hashlib
import json
import queue
import ssl
import sys
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from websockets.asyncio.server import ServerConnection, serve

from nanomuse.cloud import CloudClient, hub_url, model_url
from nanomuse.config import Settings
from nanomuse.hub import actions
from nanomuse.hub.client import HubClient, HubError
from nanomuse.llm import MockLLM
from nanomuse.schema import Function, LLMResponse, ToolCall
from nanomuse.server import create_app
from nanomuse.server.service import MuseService

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="posix shell in the tests")

PHONE = {
    "id": "phone-1",
    "name": "Pixel",
    "kind": "phone",
    "os": "Android 15",
    "online": True,
    "actions": ["info", "shell", "files", "screen", "task", "stop", "approve"],
}


def tc(name: str, **args: Any) -> ToolCall:
    return ToolCall(function=Function(name=name, arguments=json.dumps(args)))


def wait_for(pred: Callable[[], Any], timeout: float = 8.0, interval: float = 0.03) -> Any:
    deadline = time.time() + timeout
    while time.time() < deadline:
        value = pred()
        if value:
            return value
        time.sleep(interval)
    raise AssertionError("condition not met in time")


# ----------------------------------------------------------------------------- local actions
def test_info_and_shell(tmp_path: Path) -> None:
    info = actions.info(("task",))
    assert info["kind"] == "computer" and "task" in info["actions"] and info["runtime"]
    r = actions.run("shell", {"command": "echo hi; echo err 1>&2; exit 3", "cwd": str(tmp_path)})
    assert r["stdout"].strip() == "hi" and r["stderr"].strip() == "err" and r["exit_code"] == 3
    slow = actions.run("shell", {"command": "sleep 5", "timeout": 1})
    assert slow["exit_code"] == 124 and slow["timed_out"] is True
    with pytest.raises(actions.ActionError):
        actions.run("shell", {"command": ""})


def test_files_get_put(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("hello")
    (tmp_path / "sub").mkdir()
    listing = actions.run("files", {"path": str(tmp_path)})
    names = {e["name"]: e for e in listing["entries"]}
    assert names["a.txt"]["size"] == 5 and names["sub"]["type"] == "dir"
    got = actions.run("file.get", {"path": str(tmp_path / "a.txt")})
    assert base64.b64decode(got["data"]) == b"hello" and got["mime"].startswith("text/")
    put = actions.run(
        "file.put",
        {"path": str(tmp_path / "b.txt"), "data": base64.b64encode(b"copy").decode()},
    )
    assert put["bytes"] == 4 and (tmp_path / "b.txt").read_bytes() == b"copy"
    with pytest.raises(actions.ActionError) as exc:
        actions.run("file.put", {"path": str(tmp_path / "b.txt"), "data": "eA=="})
    assert exc.value.code == "exists"
    actions.run("file.put", {"path": str(tmp_path / "b.txt"), "data": "eA==", "force": True})
    assert (tmp_path / "b.txt").read_bytes() == b"x"
    with pytest.raises(actions.ActionError) as exc:
        actions.run("file.get", {"path": str(tmp_path / "missing")})
    assert exc.value.code == "not_found"
    with pytest.raises(actions.ActionError):
        actions.run("dance", {})


def test_cloud_urls() -> None:
    assert hub_url("https://cloud.nanomuse.cn/") == "wss://cloud.nanomuse.cn/v1/hub"
    assert hub_url("http://127.0.0.1:8080") == "ws://127.0.0.1:8080/v1/hub"
    assert model_url("https://cloud.nanomuse.cn") == "https://cloud.nanomuse.cn/v1"
    # contract C4: the chat default when offered, else the first chat model; the hands
    # default is a separate pick (the relay's `for` field, else what the id says it sees)
    assert (
        CloudClient.recommended_model([{"id": "x"}, {"id": "deepseek-v4.1-flash"}])
        == "deepseek-v4.1-flash"
    )
    assert CloudClient.recommended_model([{"id": "only"}]) == "only"
    assert (
        CloudClient.recommended_model([{"id": "x"}, {"id": "qwen3.8-27b"}], "gui") == "qwen3.8-27b"
    )
    assert CloudClient.recommended_model([{"id": "x"}], "gui") == "qwen3.8-27b"
    labelled = [
        {"id": "deepseek-v4.1-flash", "for": ["chat"]},
        {"id": "qwen3.8-27b", "for": ["gui"]},
        {"id": "qwen3.8-plus", "for": ["chat", "gui"]},
    ]
    assert [m["id"] for m in CloudClient.models_for(labelled, "chat")] == [
        "deepseek-v4.1-flash",
        "qwen3.8-plus",
    ]
    assert [m["id"] for m in CloudClient.models_for(labelled, "gui")] == [
        "qwen3.8-27b",
        "qwen3.8-plus",
    ]
    assert CloudClient.recommended_model(labelled, "gui") == "qwen3.8-27b"
    assert (
        CloudClient.recommended_model(
            [
                {
                    "id": "a",
                    "for": ["gui"],
                    "nanomuse": {"recommended": True, "recommended_for": ["gui"]},
                },
                {"id": "qwen3.8-27b", "for": ["gui"]},
            ],
            "gui",
        )
        == "a"
    )
    # the relay 0.17 shape: the lanes live under `nanomuse`, next to its other flags
    menu = [
        {
            "id": "deepseek-v4.1-flash",
            "nanomuse": {"for": ["chat"], "recommended": True, "recommended_for": ["chat"]},
        },
        {
            "id": "qwen3.8-27b",
            "nanomuse": {"for": ["gui", "chat"], "recommended": True, "recommended_for": ["gui"]},
        },
        {"id": "qwen3.8-flash", "nanomuse": {"for": ["chat"], "recommended": False}},
        {"id": "qwen-image-3.0", "nanomuse": {"for": [], "kind": "image"}},
    ]
    assert [m["id"] for m in CloudClient.models_for(menu, "chat")] == [
        "deepseek-v4.1-flash",
        "qwen3.8-27b",
        "qwen3.8-flash",
    ]
    assert [m["id"] for m in CloudClient.models_for(menu, "gui")] == ["qwen3.8-27b"]
    assert CloudClient.recommended_model(menu, "chat") == "deepseek-v4.1-flash"
    assert CloudClient.recommended_model(menu, "gui") == "qwen3.8-27b"
    assert CloudClient.recommended_model(list(reversed(menu)), "chat") == "deepseek-v4.1-flash"


# ----------------------------------------------------------------------------- a fake relay
class _TrackedConnection(ServerConnection):
    """A server connection the relay keeps a list of, from the TCP accept to the TCP close.

    websockets itself only lists the connections whose handshake succeeded; the HTTP requests
    the runtime's cloud client also sends to this port (it is the relay's URL) never get
    that far, so stopping needs its own list to end them from this side."""

    def __init__(self, *args: Any, registry: set[_TrackedConnection], **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._registry = registry

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        super().connection_made(transport)
        self._registry.add(self)

    def connection_lost(self, exc: Exception | None) -> None:
        self._registry.discard(self)
        super().connection_lost(exc)


class FakeRelay:
    """A relay in its own thread: one runtime connects; a fake phone answers its calls.

    ``phone_handler(frame) -> list[frame]`` decides what the phone sends back for a call
    addressed to it; frames the relay itself wants to send go through ``send``."""

    def __init__(self, key: str = "test-key"):
        self.key = key
        self.loop = asyncio.new_event_loop()
        self.port = 0
        self.ready = threading.Event()
        self.frames: queue.Queue[dict[str, Any]] = queue.Queue()  # from the runtime, in order
        self.skipped: list[dict[str, Any]] = []  # frames next_frame() passed over
        self.invites: list[str] = []  # invite codes seen by the (faked) verify call
        self.hello: dict[str, Any] | None = None
        self.ws: Any = None
        self.phone_handler: Callable[[dict[str, Any]], list[dict[str, Any]]] | None = None
        self.connections = 0
        self._server: Any = None
        self._conns: set[_TrackedConnection] = set()  # every TCP connection still open
        self._thread = threading.Thread(target=self._run, daemon=True)

    # -- lifecycle
    def start(self) -> FakeRelay:
        self._thread.start()
        assert self.ready.wait(5), "relay did not start"
        return self

    def stop(self) -> None:
        """Stop listening, drop every connection still open, wait for the handlers.

        Waiting for the server waits for every accepted TCP connection to close and for
        every handler to return. Those depend on the peer: an open socket is closed with a
        close handshake the peer must answer, a socket whose HTTP request never came is kept
        until it does — each for up to 10 s (websockets' close and open timeouts). The peer
        here is the runtime under test, whose event loop is gone by the time this runs, so a
        connection it left open would hold the stop past the 5 s below. Ending those from
        this side keeps the stop independent of the peer."""

        async def _close() -> None:
            if self._server is None:
                return
            self._server.close()
            for conn in list(self._conns):
                conn.transport.abort()
            await self._server.wait_closed()

        asyncio.run_coroutine_threadsafe(_close(), self.loop).result(5)
        self.loop.call_soon_threadsafe(self.loop.stop)
        self._thread.join(5)
        if not self._thread.is_alive():
            self.loop.close()

    def _run(self) -> None:
        asyncio.set_event_loop(self.loop)
        self.loop.run_until_complete(self._serve())
        self.loop.run_forever()

    async def _serve(self) -> None:
        self._server = await serve(
            self._handler,
            "127.0.0.1",
            0,
            create_connection=functools.partial(_TrackedConnection, registry=self._conns),
        )
        self.port = self._server.sockets[0].getsockname()[1]
        self.ready.set()

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    # -- the runtime's socket
    async def _handler(self, ws: Any) -> None:
        auth = ws.request.headers.get("Authorization", "")
        if auth != f"Bearer {self.key}":
            await ws.close(4001, "bad key")
            return
        raw = await ws.recv()
        hello = json.loads(raw)
        if hello.get("type") != "hello":
            await ws.close(4000, "hello expected")
            return
        self.hello = hello
        self.ws = ws
        self.connections += 1
        me = {**hello["device"], "online": True}
        await ws.send(
            json.dumps(
                {
                    "type": "welcome",
                    "device_id": me["id"],
                    "devices": [me, PHONE],
                    "server": {"name": "fake relay", "version": "0"},
                }
            )
        )
        async for raw in ws:
            frame = json.loads(raw)
            if frame.get("type") == "ping":
                await ws.send('{"type":"pong"}')
                continue
            self.frames.put(frame)
            if frame.get("type") == "call" and frame.get("to") == PHONE["id"]:
                for reply in (self.phone_handler or _phone_default)(frame):
                    await ws.send(json.dumps(reply))
            elif frame.get("type") == "devices":
                await ws.send(json.dumps({"type": "devices", "devices": [me, PHONE]}))

    # -- talking to the runtime
    def send(self, frame: dict[str, Any]) -> None:
        ws = wait_for(lambda: self.ws)
        asyncio.run_coroutine_threadsafe(ws.send(json.dumps(frame)), self.loop).result(5)

    def next_frame(self, type_: str | None = None, timeout: float = 8.0) -> dict[str, Any]:
        deadline = time.time() + timeout
        while True:
            left = deadline - time.time()
            if left <= 0:
                raise AssertionError(f"no {type_ or 'frame'} from the runtime in time")
            frame = self.frames.get(timeout=left)
            if type_ is None or frame.get("type") == type_:
                return frame
            self.skipped.append(frame)  # kept, for checks on what came in between

    def drain(self, type_: str | None = None) -> list[dict[str, Any]]:
        """Whatever the runtime has sent so far (of one type), without waiting."""
        out: list[dict[str, Any]] = []
        while True:
            try:
                frame = self.frames.get_nowait()
            except queue.Empty:
                return out
            if type_ is None or frame.get("type") == type_:
                out.append(frame)

    def call_runtime(self, action: str, args: dict[str, Any], call_id: str = "c1") -> None:
        self.send({"type": "call", "id": call_id, "from": PHONE, "action": action, "args": args})


def _phone_default(frame: dict[str, Any]) -> list[dict[str, Any]]:
    """The fake phone: echoes shell commands, answers tasks after one tool step."""
    action, cid, args = frame.get("action"), frame["id"], frame.get("args") or {}
    if action == "shell":
        return [
            {
                "type": "result",
                "id": cid,
                "ok": True,
                "body": {
                    "stdout": f"phone ran: {args.get('command')}\n",
                    "stderr": "",
                    "exit_code": 0,
                },
            }
        ]
    if action == "task":
        return [
            {
                "type": "event",
                "id": cid,
                "body": {"stage": "tool", "name": "calendar", "summary": "reading tomorrow"},
            },
            {
                "type": "event",
                "id": cid,
                "body": {
                    "stage": "tool_result",
                    "name": "calendar",
                    "ok": True,
                    "summary": "1 event",
                },
            },
            {
                "type": "result",
                "id": cid,
                "ok": True,
                "body": {"text": f"Pixel says: {args.get('text')}", "device": "Pixel"},
            },
        ]
    if action == "approve":
        return [{"type": "result", "id": cid, "ok": True, "body": {"ok": True}}]
    if action == "stop":
        return [{"type": "result", "id": cid, "ok": True, "body": {"stopped": True}}]
    return [
        {"type": "result", "id": cid, "ok": False, "error": "unknown_action", "message": action}
    ]


@pytest.fixture()
def relay() -> Iterator[FakeRelay]:
    r = FakeRelay().start()
    yield r
    r.stop()


# ----------------------------------------------------------------------------- the client
def test_client_connects_calls_and_answers(relay: FakeRelay) -> None:
    async def scenario() -> None:
        seen: list[str] = []

        async def on_call(call: Any) -> None:
            seen.append(call.action)
            await call.event({"stage": "tool", "name": "shell"})
            await call.result({"stdout": "ok\n", "exit_code": 0})

        client = HubClient(
            hub_url(relay.base_url),
            "test-key",
            "pc-1",
            "Desk",
            actions=["info", "shell"],
            on_call=on_call,
        )
        client.start()
        await asyncio.wait_for(client.connected.wait(), 5)
        assert client.state == "connected"
        assert [d["name"] for d in client.others()] == ["Pixel"]
        assert client.find("phone")["id"] == "phone-1"
        assert client.find("pixel")["id"] == "phone-1"
        assert client.find("Desk") is None  # never itself
        # a call out, to the fake phone
        body = await client.call("phone-1", "shell", {"command": "ls"})
        assert body["stdout"].startswith("phone ran: ls")
        # a call in, from the fake phone
        await asyncio.to_thread(relay.call_runtime, "shell", {"command": "echo hi"})
        ev = await asyncio.to_thread(relay.next_frame, "event")
        assert ev["id"] == "c1" and ev["body"]["stage"] == "tool"
        res = await asyncio.to_thread(relay.next_frame, "result")
        assert res["ok"] is True and res["body"]["stdout"] == "ok\n" and seen == ["shell"]
        # a call the phone refuses
        with pytest.raises(HubError) as exc:
            await client.call("phone-1", "dance", {})
        assert exc.value.code == "unknown_action"
        await client.stop()
        assert client.state == "stopped"

    asyncio.run(scenario())


def test_client_refuses_to_hammer_on_bad_key(relay: FakeRelay) -> None:
    async def scenario() -> None:
        client = HubClient(hub_url(relay.base_url), "wrong", "pc-1", "Desk", actions=["info"])
        client.start()
        await asyncio.sleep(0)
        for _ in range(100):
            if client.state == "refused":
                break
            await asyncio.sleep(0.05)
        assert client.state == "refused"
        await client.stop()

    asyncio.run(scenario())


def test_a_paused_hub_is_waited_out_not_hammered(monkeypatch: pytest.MonkeyPatch) -> None:
    """4003 with the reason `hub_paused` (docs/hub.md): the client waits a minute before the
    next try instead of reconnecting on the 1 s backoff; a plain 4003 keeps the backoff."""
    from websockets.exceptions import ConnectionClosed
    from websockets.frames import Close

    async def scenario(reason: str) -> tuple[str, str, float]:
        client = HubClient("wss://relay.test/v1/hub", "k", "pc-1", "Desk", actions=["info"])
        seen: list[tuple[str, str, float]] = []

        async def paused() -> None:
            raise ConnectionClosed(Close(4003, reason), None)

        async def spy(aw, timeout):  # noqa: ANN001
            # the back-off wait: note how long it would be and end the loop instead
            seen.append((client.state, client.state_detail, timeout))
            client._stop.set()
            aw.close()

        monkeypatch.setattr(client, "_session", paused)
        monkeypatch.setattr("nanomuse.hub.client.asyncio.wait_for", spy)
        client.start()
        for _ in range(100):
            if seen:
                break
            await asyncio.sleep(0.02)
        await client.stop()
        return seen[0]

    state, detail, wait = asyncio.run(scenario("hub_paused"))
    assert state == "disconnected" and "paused" in detail and wait == 60.0
    state, _, wait = asyncio.run(scenario("replaced"))
    assert state == "disconnected" and wait == 1.0


def test_a_certificate_failure_is_a_disconnect_not_a_refusal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SSLCertVerificationError is a ValueError too; it used to land in the refused branch
    and read as the hub refusing the device (a Mac whose bundled Python had no CA store)."""

    async def scenario() -> None:
        client = HubClient("wss://relay.test/v1/hub", "k", "pc-1", "Desk", actions=["info"])

        async def bad_cert() -> None:
            exc = ssl.SSLCertVerificationError("certificate verify failed")
            exc.verify_message = "unable to get local issuer certificate"
            raise exc

        monkeypatch.setattr(client, "_session", bad_cert)
        client.start()
        for _ in range(100):
            if client.state == "disconnected":
                break
            await asyncio.sleep(0.02)
        assert client.state == "disconnected"
        assert "certificate could not be verified" in client.state_detail
        assert "unable to get local issuer certificate" in client.state_detail
        assert client.running  # it keeps trying (slowly), rather than giving up
        await client.stop()

    asyncio.run(scenario())


# ----------------------------------------------------------------------------- the service
@pytest.fixture()
def hub_server(
    settings: Settings, relay: FakeRelay, monkeypatch: pytest.MonkeyPatch
) -> Iterator[tuple[TestClient, MuseService, MockLLM, FakeRelay]]:
    settings.server.token = "secret-token"
    settings.cloud.base_url = relay.base_url
    settings.hub.name = "Desk"
    llm = MockLLM([])

    async def fake_request_code(self: CloudClient, identifier: str) -> dict[str, Any]:
        assert identifier
        return {"ok": True, "channel": "email"}

    async def fake_verify(
        self: CloudClient, identifier: str, code: str, device: str = "", invite: str = ""
    ) -> dict[str, Any]:
        relay.invites.append(invite)  # what the web/app sent along (a friend's code, or "")
        if code != "123456":
            from nanomuse.cloud import CloudError

            raise CloudError(400, "bad_code", "wrong code")
        self.api_key = "test-key"
        return {"api_key": "test-key", "account": {"hint": "s***@example.com", "channel": "email"}}

    async def fake_models(self: CloudClient) -> list[dict[str, Any]]:
        return [{"id": "qwen3.8-27b"}, {"id": "other"}]

    monkeypatch.setattr(CloudClient, "request_code", fake_request_code)
    monkeypatch.setattr(CloudClient, "verify", fake_verify)
    monkeypatch.setattr(CloudClient, "models", fake_models)
    service = MuseService(settings, llm=llm)
    app = create_app(settings, service)
    with TestClient(app) as client:
        client.headers["Authorization"] = "Bearer secret-token"
        yield client, service, llm, relay


def sign_in(client: TestClient) -> dict[str, Any]:
    assert (
        client.post("/api/cloud/code", json={"identifier": "someone@example.com"}).status_code
        == 200
    )
    r = client.post(
        "/api/cloud/verify", json={"identifier": "someone@example.com", "code": "123456"}
    )
    assert r.status_code == 200, r.text
    return r.json()


def test_sign_in_joins_hub_and_lists_devices(hub_server) -> None:
    client, service, _llm, relay = hub_server
    before = client.get("/api/hub").json()
    assert before["state"] == "signed_out" and before["account"]["signed_in"] is False
    assert "devices" not in service.app.tools
    bad = client.post(
        "/api/cloud/verify",
        json={"identifier": "x@example.com", "code": "000000", "invite": "abcd-2345"},
    )
    assert bad.status_code == 400
    account = sign_in(client)
    assert account["signed_in"] is True and account["hint"] == "s***@example.com"
    # the invite code travels to the relay as typed (it normalises), and is absent when not given
    assert relay.invites == ["abcd-2345", ""]
    hub = wait_for(lambda: (h := client.get("/api/hub").json())["state"] == "connected" and h)
    assert relay.hello["device"]["name"] == "Desk"
    assert relay.hello["device"]["kind"] == "computer"
    assert (
        "task" in relay.hello["device"]["actions"] and "shell" in relay.hello["device"]["actions"]
    )
    names = {d["name"]: d for d in hub["devices"]}
    assert names["Pixel"]["online"] is True and names["Desk"]["this"] is True
    assert "devices" in service.app.tools and "delegate" in service.app.tools
    # the state view carries the hub too, for the GUI's first paint
    assert client.get("/api/state").json()["hub"]["state"] == "connected"
    # rename travels to the relay
    client.put("/api/hub", json={"name": "Study"})
    assert relay.next_frame("rename")["name"] == "Study"
    # the relay as the model provider: the key stays a vault reference
    llm = client.post("/api/cloud/use-as-model", json={}).json()
    assert llm["model"] == "qwen3.8-27b" and llm["base_url"] == model_url(relay.base_url)
    assert service.settings.llm.api_key == "{{vault:NANOMUSE_CLOUD_KEY}}"
    assert service.app.vault.get("NANOMUSE_CLOUD_KEY") == "test-key"
    assert client.get("/api/cloud").json()["is_model"] is True
    # leaving takes the tools away; signing out clears the account
    client.post("/api/hub/leave")
    wait_for(lambda: "devices" not in service.app.tools)
    assert client.get("/api/hub").json()["state"] == "off"
    client.post("/api/cloud/sign-out")
    assert client.get("/api/cloud").json()["signed_in"] is False


def test_hosted_runtime_starts_signed_in_from_the_environment(
    settings: Settings, relay: FakeRelay, monkeypatch: pytest.MonkeyPatch
) -> None:
    """nanoMuse Web: the gateway hands the container the account key; the runtime comes up
    signed in, on the hub under the given name, with the relay as its model and no first run."""
    settings.server.token = "secret-token"
    settings.cloud.base_url = relay.base_url
    settings.hub.name = "Web"
    settings.llm.api_key = ""
    monkeypatch.setenv("NANOMUSE_CLOUD_KEY", "test-key")
    monkeypatch.setenv("NANOMUSE_CLOUD_HINT", "a***@example.com")
    monkeypatch.setenv("NANOMUSE_CLOUD_CHANNEL", "email")
    monkeypatch.setenv("NANOMUSE_ONBOARDED", "1")

    async def fake_models(self: CloudClient) -> list[dict[str, Any]]:
        return [{"id": "qwen3.8-27b"}]

    monkeypatch.setattr(CloudClient, "models", fake_models)
    service = MuseService(settings, llm=MockLLM([]))
    app = create_app(settings, service)
    with TestClient(app) as client:
        client.headers["Authorization"] = "Bearer secret-token"
        account = client.get("/api/cloud").json()
        assert account["signed_in"] is True and account["hint"] == "a***@example.com"
        assert account["is_model"] is True
        assert service.app.vault.get("NANOMUSE_CLOUD_KEY") == "test-key"
        assert client.get("/api/state").json()["settings"]["onboarded"] is True
        wait_for(lambda: client.get("/api/hub").json()["state"] == "connected")
        assert relay.hello["device"]["name"] == "Web"


def test_a_signed_in_runtime_with_no_model_key_makes_the_relay_its_model(
    settings: Settings, relay: FakeRelay, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A desktop that signed in before the model followed the account (or had its model
    reset) still has the bare default with no key; at start the relay becomes the model,
    the same as at the moment of signing in — instead of the provider's 401 on the first
    message. A local server without a key is left alone."""
    settings.server.token = "secret-token"
    settings.cloud.base_url = relay.base_url
    settings.llm.api_key = ""
    settings.llm.base_url = "https://api.deepseek.com"

    async def fake_models(self: CloudClient) -> list[dict[str, Any]]:
        return [{"id": "qwen3.8-27b"}]

    monkeypatch.setattr(CloudClient, "models", fake_models)
    service = MuseService(settings, llm=MockLLM([]))
    service.app.vault.set("NANOMUSE_CLOUD_KEY", "old-key")
    app = create_app(settings, service)
    with TestClient(app) as client:
        client.headers["Authorization"] = "Bearer secret-token"
        account = client.get("/api/cloud").json()
        assert account["signed_in"] is True and account["is_model"] is True
        assert settings.llm.base_url.startswith(relay.base_url)
        assert settings.llm.api_key == "{{vault:NANOMUSE_CLOUD_KEY}}"

    settings2 = settings.model_copy(deep=True)
    settings2.llm.api_key = ""
    settings2.llm.base_url = "http://localhost:11434/v1"
    service2 = MuseService(settings2, llm=MockLLM([]))
    service2.app.vault.set("NANOMUSE_CLOUD_KEY", "old-key")
    service2.hub.data.pop("llm", None)
    with TestClient(create_app(settings2, service2)) as client:
        client.headers["Authorization"] = "Bearer secret-token"
        assert client.get("/api/cloud").json()["is_model"] is False
        assert settings2.llm.base_url == "http://localhost:11434/v1"


def test_the_model_picker_groups_the_menu_and_the_models_under_the_key(
    settings: Settings, relay: FakeRelay, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Relay 0.10 lists, for a member, the usable models under the operator's key after the
    menu (`nanomuse.catalog`); /api/llm/models for the Cloud preset hands the pickers the
    whole list in groups — menu, the rest, the picture / clip models likewise — plus which
    chat models read pictures. Nothing to type: the member picks."""
    settings.server.token = "secret-token"
    settings.cloud.base_url = relay.base_url

    def entry(
        mid: str, kind: str = "chat", listed: bool = True, vision: bool = False, rec: bool = False
    ) -> dict[str, Any]:
        inputs = ["text", "image"] if vision or kind != "chat" else ["text"]
        out = ["text"] if kind == "chat" else [kind]
        nm: dict[str, Any] = {"kind": kind, "listed": listed, "recommended": rec}
        if not listed:
            nm.update(catalog=True, vision=vision)
        return {
            "id": mid,
            "architecture": {"input_modalities": inputs, "output_modalities": out},
            "nanomuse": nm,
        }

    async def fake_models(self: CloudClient) -> list[dict[str, Any]]:
        return [
            entry("qwen3.8-flash"),
            entry("qwen3.8-27b", vision=True, rec=True),
            entry("qwen-image-3.0", "image"),
            entry("wan2.2-t2v-plus", "video"),
            entry("deepseek-v4.1-flash", listed=False),
            entry("qwen3-vl-plus", listed=False, vision=True),
            entry("wan2.7-image", "image", listed=False),
        ]

    monkeypatch.setattr(CloudClient, "models", fake_models)
    service = MuseService(settings, llm=MockLLM([]))
    service.app.vault.set("NANOMUSE_CLOUD_KEY", "member-key")
    with TestClient(create_app(settings, service)) as client:
        client.headers["Authorization"] = "Bearer secret-token"
        got = client.post("/api/llm/models", json={"preset": "nanomuse_cloud"}).json()
    assert got["source"] == "live"
    assert got["models"] == ["qwen3.8-27b", "qwen3.8-flash", "deepseek-v4.1-flash", "qwen3-vl-plus"]
    assert got["menu"] == ["qwen3.8-27b", "qwen3.8-flash"]
    assert got["catalog"] == ["deepseek-v4.1-flash", "qwen3-vl-plus"]
    assert got["image_models"] == ["qwen-image-3.0", "wan2.7-image"] and got["image_catalog"] == [
        "wan2.7-image"
    ]
    assert got["video_models"] == ["wan2.2-t2v-plus"] and got["video_catalog"] == []
    assert got["vision"] == ["qwen3.8-27b", "qwen3-vl-plus"]


def test_task_from_a_device_runs_in_a_visible_side_chat(hub_server) -> None:
    client, service, llm, relay = hub_server
    sign_in(client)
    wait_for(lambda: client.get("/api/hub").json()["state"] == "connected")
    llm.script.append(LLMResponse(tool_calls=[tc("shell", command="echo from-pixel")]))
    llm.script.append(LLMResponse(content="Done: from-pixel"))
    service.settings.sentinel.mode = "auto"
    relay.call_runtime("task", {"text": "run echo from-pixel", "conversation": "conv-1"}, "t1")
    # the approval-free run: the tool starting, the tool finishing, then the result
    ev = relay.next_frame("event")
    assert ev["id"] == "t1" and ev["body"]["stage"] == "tool" and ev["body"]["name"] == "shell"
    done = relay.next_frame("event")
    assert done["body"]["stage"] == "tool_result" and done["body"]["ok"] is True
    assert done["body"]["id"] == ev["body"]["id"] and "from-pixel" in done["body"]["summary"]
    res = relay.next_frame("result")
    assert res["id"] == "t1" and res["ok"] is True
    assert res["body"]["text"] == "Done: from-pixel" and res["body"]["device"] == "Desk"
    # and it happened in a side chat named after the phone, visible here
    threads = {t["title"]: t for t in client.get("/api/threads").json()}
    side = threads["From Pixel"]
    assert (
        side["remote_from"]["name"] == "Pixel" and side["remote_from"]["conversation"] == "conv-1"
    )
    events = client.get(f"/api/threads/{side['id']}/events").json()["events"]
    user = [e for e in events if e["type"] == "user"][0]
    assert user["text"] == "run echo from-pixel" and user["via"] == "Pixel"
    assert [e["text"] for e in events if e["type"] == "assistant"] == ["Done: from-pixel"]
    # a second task from the same conversation reuses the chat
    llm.script.append(LLMResponse(content="Again"))
    relay.call_runtime("task", {"text": "again", "conversation": "conv-1"}, "t2")
    assert relay.next_frame("result")["body"]["text"] == "Again"
    assert len([t for t in client.get("/api/threads").json() if t["title"] == "From Pixel"]) == 1


def test_a_stopped_task_fails_with_cancelled_and_only_for_its_asker(hub_server) -> None:
    """docs/hub.md: the asking device ends its task with `stop {call}` or
    `stop {conversation}`; the target answers `{stopped: true}` and the `task` call fails
    with `cancelled`, never with an older reply as its answer. Another device gets
    `{stopped: false}` and the run goes on."""
    client, service, llm, relay = hub_server
    sign_in(client)
    wait_for(lambda: client.get("/api/hub").json()["state"] == "connected")
    service.settings.sentinel.mode = "auto"
    # an earlier task answered, so the thread has a last reply a stop must not hand back
    llm.script.append(LLMResponse(content="Earlier answer"))
    relay.call_runtime("task", {"text": "first", "conversation": "conv-s"}, "t1")
    assert relay.next_frame("result")["body"]["text"] == "Earlier answer"

    llm.script.append(LLMResponse(tool_calls=[tc("shell", command="sleep 20")]))
    relay.call_runtime("task", {"text": "take a while", "conversation": "conv-s"}, "t2")
    assert relay.next_frame("event")["body"]["stage"] == "tool"
    # another device of the account cannot stop it, by call id or by conversation
    other = {**PHONE, "id": "phone-2", "name": "Tablet"}
    relay.send(
        {"type": "call", "id": "x1", "from": other, "action": "stop", "args": {"call": "t2"}}
    )
    assert relay.next_frame("result")["body"] == {"stopped": False}
    relay.send(
        {
            "type": "call",
            "id": "x2",
            "from": other,
            "action": "stop",
            "args": {"conversation": "conv-s"},
        }
    )
    assert relay.next_frame("result")["body"] == {"stopped": False}
    assert client.get("/api/state").json()["status"]["state"] != "idle"
    # the asker can
    relay.call_runtime("stop", {"call": "t2"}, "s1")
    results = {f["id"]: f for f in (relay.next_frame("result"), relay.next_frame("result"))}
    assert results["s1"]["body"] == {"stopped": True}
    assert results["t2"]["ok"] is False and results["t2"]["error"] == "cancelled"
    wait_for(lambda: client.get("/api/state").json()["status"]["state"] == "idle")
    # the stop button here does the same for a task under way
    llm.script.append(LLMResponse(tool_calls=[tc("shell", command="sleep 20")]))
    relay.call_runtime("task", {"text": "once more", "conversation": "conv-s"}, "t3")
    assert relay.next_frame("event")["body"]["stage"] == "tool"
    side = [t for t in client.get("/api/threads").json() if t["title"] == "From Pixel"][0]
    assert client.post(f"/api/threads/{side['id']}/stop").json() == {"ok": True}
    res = relay.next_frame("result")
    assert res["id"] == "t3" and res["ok"] is False and res["error"] == "cancelled"


def test_task_approval_is_relayed_and_answered_by_the_device(hub_server) -> None:
    client, service, llm, relay = hub_server
    sign_in(client)
    wait_for(lambda: client.get("/api/hub").json()["state"] == "connected")
    llm.script.append(LLMResponse(tool_calls=[tc("shell", command="echo careful")]))
    llm.script.append(LLMResponse(content="Ran it"))
    relay.call_runtime("task", {"text": "run something", "conversation": "conv-2"}, "t3")
    approval = relay.next_frame("event")
    while approval["body"].get("stage") != "approval":
        approval = relay.next_frame("event")
    body = approval["body"]
    assert body["device"] == "Desk" and "echo careful" in body["preview"] and body["approval_id"]
    # the card is pending here too; the phone answers it over the hub
    pending = client.get("/api/state").json()["pending_approvals"]
    assert [p["id"] for p in pending] == [body["approval_id"]]
    relay.call_runtime("approve", {"approval_id": body["approval_id"], "allow": True}, "a1")
    results = [relay.next_frame("result"), relay.next_frame("result")]
    by_id = {r["id"]: r for r in results}
    assert by_id["a1"]["body"]["ok"] is True
    assert by_id["t3"]["ok"] is True and by_id["t3"]["body"]["text"] == "Ran it"
    # the caller was told the card was answered, so its copy closes as well
    seen = relay.skipped + relay.drain("event")
    stages = [f["body"]["stage"] for f in seen if f.get("type") == "event" and f["id"] == "t3"]
    assert "approval_result" in stages and "tool_result" in stages


def test_remote_control_off_refuses_everything_but_info(hub_server) -> None:
    client, _service, _llm, relay = hub_server
    sign_in(client)
    wait_for(lambda: client.get("/api/hub").json()["state"] == "connected")
    client.put("/api/hub", json={"remote_control": False})
    relay.call_runtime("shell", {"command": "echo hi"}, "s1")
    res = relay.next_frame("result")
    assert res["ok"] is False and res["error"] == "not_allowed"
    relay.call_runtime("info", {}, "i1")
    res = relay.next_frame("result")
    assert res["ok"] is True and res["body"]["kind"] == "computer"
    client.put("/api/hub", json={"remote_control": True})
    relay.call_runtime("shell", {"command": "echo hi"}, "s2")
    # with remote control on, the person at this computer still agrees first: a card here,
    # addressed to the phone, offering once / always for that device
    pending = wait_for(lambda: client.get("/api/state").json()["pending_approvals"])
    card = pending[0]
    assert card["tool"] == "remote_control" and card["target"] == "phone-1"
    assert card["grant_options"] == ["once", "always"] and "echo hi" in card["summary"]
    assert card["args"]["device"] == "Pixel" and card["args"]["action"] == "shell"
    # the phone cannot answer that card itself — it is not one of its own run's cards
    relay.call_runtime("approve", {"approval_id": card["id"], "allow": True}, "a0")
    assert relay.next_frame("result")["body"]["ok"] is False
    client.post(f"/api/approvals/{card['id']}", json={"approved": True, "scope": "always"})
    res = relay.next_frame("result")
    assert res["id"] == "s2" and res["ok"] is True and res["body"]["stdout"].strip() == "hi"
    # the standing answer is an ordinary grant: no card next time, revocable like the others
    relay.call_runtime("shell", {"command": "echo again"}, "s3")
    res = relay.next_frame("result")
    assert res["ok"] is True and res["body"]["stdout"].strip() == "again"
    grants = client.get("/api/activity").json()["grants"]
    assert any(g["tool"] == "remote_control" and g["target"] == "phone-1" for g in grants)
    client.delete("/api/approvals/grants/remote_control:phone-1")
    relay.call_runtime("files", {"path": "."}, "f1")
    card = wait_for(lambda: client.get("/api/state").json()["pending_approvals"])[0]
    client.post(f"/api/approvals/{card['id']}", json={"approved": False})
    res = relay.next_frame("result")
    assert res["id"] == "f1" and res["ok"] is False and res["error"] == "not_allowed"
    # a notice and a look at this computer never ask
    relay.call_runtime("notify", {"title": "hi", "text": "there"}, "n1")
    assert relay.next_frame("result")["ok"] is True


def test_ask_a_device_runs_the_text_there_and_shows_its_steps(hub_server) -> None:
    client, service, _llm, relay = hub_server
    sign_in(client)
    wait_for(lambda: client.get("/api/hub").json()["state"] == "connected")
    r = client.post(
        "/api/hub/ask", json={"device": "Pixel", "text": "what is tomorrow's first meeting?"}
    )
    assert r.status_code == 200, r.text
    thread = r.json()["thread"]
    assert thread["device"] == "phone-1" and thread["device_name"] == "Pixel"
    call = relay.next_frame("call")
    assert call["to"] == "phone-1" and call["action"] == "task"
    assert call["args"]["text"].startswith("what is") and call["args"]["from"] == "Desk"
    wait_for(lambda: not service.threads[thread["id"]].busy)
    events = client.get(f"/api/threads/{thread['id']}/events").json()["events"]
    types = [e["type"] for e in events]
    assert types == ["user", "tool", "assistant"]
    assert (
        events[1]["tool"] == "calendar"
        and events[1]["status"] == "ok"
        and events[1]["device"] == "Pixel"
    )
    assert events[2]["text"].startswith("Pixel says:") and events[2]["device"] == "Pixel"
    # the same device gets the same chat
    again = client.post("/api/hub/ask", json={"device": "phone-1"}).json()
    assert again["thread"]["id"] == thread["id"]
    assert client.post("/api/hub/ask", json={"device": "toaster"}).status_code == 404


def test_device_chat_relays_its_approval_card_back(hub_server) -> None:
    client, service, _llm, relay = hub_server
    sign_in(client)
    wait_for(lambda: client.get("/api/hub").json()["state"] == "connected")
    approved: list[dict[str, Any]] = []

    def phone(frame: dict[str, Any]) -> list[dict[str, Any]]:
        cid, action = frame["id"], frame.get("action")
        if action == "task":
            return [
                {
                    "type": "event",
                    "id": cid,
                    "body": {
                        "stage": "approval",
                        "approval_id": "ap-phone-1",
                        "preview": "delete the draft",
                        "risk": "sensitive",
                        "reason": "removes a file",
                        "device": "Pixel",
                    },
                }
            ]
        if action == "approve":
            approved.append(frame["args"])
            # the phone finishes its task once it has the answer
            return [
                {"type": "result", "id": cid, "ok": True, "body": {"ok": True}},
                {
                    "type": "result",
                    "id": approved_task[0],
                    "ok": True,
                    "body": {"text": "Deleted."},
                },
            ]
        return _phone_default(frame)

    approved_task: list[str] = []
    relay.phone_handler = phone
    r = client.post("/api/hub/ask", json={"device": "Pixel", "text": "delete the draft"})
    thread = r.json()["thread"]
    approved_task.append(relay.next_frame("call")["id"])
    card = wait_for(
        lambda: [
            e
            for e in client.get(f"/api/threads/{thread['id']}/events").json()["events"]
            if e["type"] == "approval"
        ]
    )[0]
    assert card["status"] == "pending" and card["remote"]["device"] == "phone-1"
    assert card["summary"] == "delete the draft" and card["grant_options"] == ["once"]
    assert card["id"] in service.hub.remote_approvals
    r = client.post(f"/api/approvals/{card['id']}", json={"approved": True, "scope": "once"})
    assert r.status_code == 200, r.text
    assert approved == [{"approval_id": "ap-phone-1", "allow": True}]
    wait_for(lambda: not service.threads[thread["id"]].busy)
    events = client.get(f"/api/threads/{thread['id']}/events").json()["events"]
    card_after = [e for e in events if e["type"] == "approval"][0]
    assert card_after["status"] == "approved"
    assert [e["text"] for e in events if e["type"] == "assistant"] == ["Deleted."]


def test_device_chat_approval_over_the_websocket_travels_the_hub(hub_server) -> None:
    client, service, _llm, relay = hub_server
    sign_in(client)
    wait_for(lambda: client.get("/api/hub").json()["state"] == "connected")
    approved: list[dict[str, Any]] = []
    task_ids: list[str] = []

    def phone(frame: dict[str, Any]) -> list[dict[str, Any]]:
        cid, action = frame["id"], frame.get("action")
        if action == "task":
            task_ids.append(cid)
            return [
                {
                    "type": "event",
                    "id": cid,
                    "body": {"stage": "approval", "approval_id": "ap-ws", "preview": "send it"},
                }
            ]
        if action == "approve":
            approved.append(frame["args"])
            return [
                {"type": "result", "id": cid, "ok": True, "body": {"ok": True}},
                {"type": "result", "id": task_ids[0], "ok": True, "body": {"text": "Sent."}},
            ]
        return _phone_default(frame)

    relay.phone_handler = phone
    thread = client.post("/api/hub/ask", json={"device": "Pixel", "text": "send it"}).json()[
        "thread"
    ]
    card = wait_for(
        lambda: [
            e
            for e in client.get(f"/api/threads/{thread['id']}/events").json()["events"]
            if e["type"] == "approval"
        ]
    )[0]
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"kind": "auth", "token": "secret-token"})
        ws.receive_json()  # hello
        ws.send_json({"kind": "approval", "id": card["id"], "approved": True, "scope": "once"})
        wait_for(lambda: approved == [{"approval_id": "ap-ws", "allow": True}])
    wait_for(lambda: not service.threads[thread["id"]].busy)
    events = client.get(f"/api/threads/{thread['id']}/events").json()["events"]
    assert [e["status"] for e in events if e["type"] == "approval"] == ["approved"]
    assert [e["text"] for e in events if e["type"] == "assistant"] == ["Sent."]


def test_delegate_tool_asks_the_device_and_passes_the_answer_on(hub_server) -> None:
    client, service, llm, relay = hub_server
    sign_in(client)
    wait_for(lambda: client.get("/api/hub").json()["state"] == "connected")
    service.settings.sentinel.mode = "auto"
    llm.script.append(LLMResponse(tool_calls=[tc("devices")]))
    llm.script.append(
        LLMResponse(tool_calls=[tc("delegate", device="phone", task="read tomorrow's calendar")])
    )
    llm.script.append(LLMResponse(tool_calls=[tc("device_shell", device="Pixel", command="uname")]))
    llm.script.append(LLMResponse(content="Your phone says it is fine."))
    client.post("/api/threads/main/send", json={"text": "ask my phone about tomorrow"})
    wait_for(lambda: not service.threads["main"].busy and service.threads["main"].inbox.empty())
    events = client.get("/api/threads/main/events").json()["events"]
    tools = [e for e in events if e["type"] == "tool"]
    assert [t["tool"] for t in tools] == ["devices", "delegate", "device_shell"]
    assert all(t["status"] == "ok" for t in tools), [t.get("output") for t in tools]
    assert "Pixel" in tools[0]["output"]
    assert "Pixel says: read tomorrow's calendar" in tools[1]["output"]
    assert "phone ran: uname" in tools[2]["output"]
    calls = []
    while True:
        try:
            calls.append(relay.frames.get(timeout=0.2))
        except queue.Empty:
            break
    actions_sent = [c["action"] for c in calls if c.get("type") == "call"]
    assert actions_sent == ["task", "shell"]
    task_call = [c for c in calls if c.get("action") == "task"][0]
    assert task_call["args"]["from"] == "Desk"


def test_coding_actions_are_served_to_other_devices(
    hub_server, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The phone asks this computer about its coding agents (docs/coding-agents.md)."""
    from nanomuse.coding import agents as coding_agents

    home = tmp_path / "home"
    ws = tmp_path / "ws"
    ws.mkdir()
    slug = str(ws).strip("/").replace("/", "-")
    path = home / ".cursor" / "projects" / slug / "agent-transcripts" / "s1" / "s1.jsonl"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps({"role": "user", "message": {"content": [{"type": "text", "text": "hello"}]}})
        + "\n"
        + json.dumps(
            {"role": "assistant", "message": {"content": [{"type": "text", "text": "hi"}]}}
        )
        + "\n"
    )
    monkeypatch.setenv("NANOMUSE_CODING_HOME", str(home))
    monkeypatch.setattr(coding_agents, "which", lambda agent: None)
    client, service, _llm, relay = hub_server
    sign_in(client)
    wait_for(lambda: client.get("/api/hub").json()["state"] == "connected")
    assert "coding.sessions" in relay.hello["device"]["actions"]
    assert "coding.send" in relay.hello["device"]["actions"]

    relay.call_runtime("coding.sessions", {"agent": "cursor"}, "c1")
    res = relay.next_frame("result")
    assert res["id"] == "c1" and res["ok"] is True
    assert [s["id"] for s in res["body"]["sessions"]] == ["s1"]
    assert res["body"]["sessions"][0]["title"] == "hello"

    relay.call_runtime("coding.session", {"agent": "cursor", "session_id": "s1"}, "c2")
    res = relay.next_frame("result")
    assert res["ok"] is True and [m["text"] for m in res["body"]["transcript"]] == ["hello", "hi"]

    relay.call_runtime("coding.session", {"agent": "cursor", "session_id": "zz"}, "c3")
    res = relay.next_frame("result")
    assert res["ok"] is False and res["error"] == "no_session"

    # steering an agent is something another device does *to* this computer: the person
    # here agrees first (the lists above are reads and did not ask)
    relay.call_runtime("coding.send", {"agent": "cursor", "text": "go", "session_id": "s1"}, "c4")
    card = wait_for(lambda: client.get("/api/state").json()["pending_approvals"])[0]
    assert card["tool"] == "remote_control" and card["args"]["action"] == "coding.send"
    client.post(f"/api/approvals/{card['id']}", json={"approved": True, "scope": "once"})
    # sending needs the CLI; without it the caller hears why
    res = relay.next_frame("result")
    assert res["ok"] is False and res["error"] == "not_installed"


def test_password_sign_in_and_account_management(
    hub_server, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Passwords, other sign-ins, signing out everywhere — the runtime's side of the account
    (the relay's own rules are covered in cloud/tests)."""
    client, service, _llm, relay = hub_server
    calls: list[tuple[str, Any]] = []

    async def fake_login(
        self: CloudClient, identifier: str, password: str, device: str = ""
    ) -> dict[str, Any]:
        from nanomuse.cloud import CloudError

        calls.append(("login", (identifier, password, device)))
        if password != "correct horse":
            raise CloudError(401, "bad_credentials", "wrong")
        self.api_key = "test-key"
        return {
            "api_key": "test-key",
            "account": {
                "id": "acc_1",
                "hint": "s***@example.com",
                "channel": "email",
                "has_password": True,
            },
            "usage": {"today": {"by_kind": {"chat": {"charged": 12}}}},
        }

    async def fake_set_password(
        self: CloudClient, password: str, current: str | None = None
    ) -> None:
        calls.append(("set_password", (password, current)))

    async def fake_sessions(self: CloudClient) -> list[dict[str, Any]]:
        return [
            {"prefix": "nmk_aaaa", "device": "Desk", "via": "password", "current": True},
            {"prefix": "nmk_bbbb", "device": "Pixel", "via": "code", "current": False},
        ]

    async def fake_revoke(self: CloudClient, prefix: str) -> None:
        calls.append(("revoke", prefix))

    async def fake_sign_out_all(self: CloudClient, everything: bool = False) -> int:
        calls.append(("sign_out_all", everything))
        return 2 if everything else 1

    monkeypatch.setattr(CloudClient, "login", fake_login)
    monkeypatch.setattr(CloudClient, "set_password", fake_set_password)
    monkeypatch.setattr(CloudClient, "sessions", fake_sessions)
    monkeypatch.setattr(CloudClient, "revoke_session", fake_revoke)
    monkeypatch.setattr(CloudClient, "sign_out_all", fake_sign_out_all)

    before = client.get("/api/cloud").json()
    assert (
        before["signed_in"] is False
        and before["required"] is True
        and before["has_password"] is False
    )
    bad = client.post(
        "/api/cloud/login", json={"identifier": "someone@example.com", "password": "nope"}
    )
    assert bad.status_code == 401 and "do not match" in str(bad.json()["detail"])
    assert (
        client.post(
            "/api/cloud/login", json={"identifier": "someone@example.com", "password": ""}
        ).status_code
        == 422
    )
    ok = client.post(
        "/api/cloud/login", json={"identifier": "someone@example.com", "password": "correct horse"}
    )
    assert ok.status_code == 200, ok.text
    account = ok.json()
    assert (
        account["signed_in"] is True
        and account["has_password"] is True
        and account["account_id"] == "acc_1"
    )
    assert calls[-1][1][2] == "Desk"  # the device name travels with the sign-in
    assert service.app.vault.get("NANOMUSE_CLOUD_KEY") == "test-key"
    wait_for(lambda: client.get("/api/hub").json()["state"] == "connected")

    # change the password (the relay checks the current one)
    r = client.post(
        "/api/cloud/password", json={"password": "new longer one", "current": "correct horse"}
    )
    assert r.status_code == 200 and r.json()["has_password"] is True
    assert calls[-1] == ("set_password", ("new longer one", "correct horse"))
    # remove it
    r = client.post("/api/cloud/password", json={"password": "", "current": "new longer one"})
    assert r.status_code == 200 and r.json()["has_password"] is False

    sessions = client.get("/api/cloud/sessions").json()["sessions"]
    assert [s["device"] for s in sessions] == ["Desk", "Pixel"] and sessions[0]["current"] is True
    assert client.delete("/api/cloud/sessions/nmk_bbbb").status_code == 200
    assert calls[-1] == ("revoke", "nmk_bbbb")

    # sign out the other devices: still signed in here
    r = client.post("/api/cloud/sign-out-all", json={"all": False})
    assert r.json()["signed_out"] == 1 and client.get("/api/cloud").json()["signed_in"] is True
    # everywhere: this one too
    r = client.post("/api/cloud/sign-out-all", json={"all": True})
    assert r.json()["signed_out"] == 2
    assert client.get("/api/cloud").json()["signed_in"] is False
    assert service.app.vault.get("NANOMUSE_CLOUD_KEY") is None
    assert client.get("/api/cloud/sessions").status_code == 401


# ----------------------------------------------------------------------------- the shared look
WEBP_IDLE = b"RIFF\x00\x00\x00\x00WEBPVP8 " + b"\x01" * 40
WEBP_HAPPY = b"RIFF\x00\x00\x00\x00WEBPVP8 " + b"\x02" * 40


def _fake_profile_relay(
    monkeypatch: pytest.MonkeyPatch, store: dict[str, Any]
) -> list[dict[str, Any]]:
    """``/v1/me/profile`` on the relay, faked: ``store`` is the row, ``puts`` what came in."""
    puts: list[dict[str, Any]] = []

    async def fake_profile(self: CloudClient, with_face: bool = True) -> dict[str, Any]:
        if with_face:
            return dict(store)
        return {k: v for k, v in store.items() if k != "face"}

    async def fake_put(self: CloudClient, body: dict[str, Any]) -> dict[str, Any]:
        puts.append(body)
        store["rev"] = int(store.get("rev") or 0) + 1
        store["device"] = str(body.get("device") or "")
        for k in ("name", "avatar", "emoji", "color", "style", "description"):
            store[k] = body.get(k, "")
        if "face" in body:
            store["face"] = body["face"]
        store["has_face"] = bool(store.get("face"))
        store.pop("face_id", None)
        if "connectors" in body:
            # merged by device, as the relay does it: the writer's replaced, the others' kept
            kept = [
                c for c in store.get("connectors") or [] if c.get("device_id") != store["device"]
            ]
            store["connectors"] = kept + list(body["connectors"])
        return {"rev": store["rev"], "device": store["device"]}

    monkeypatch.setattr(CloudClient, "profile", fake_profile)
    monkeypatch.setattr(CloudClient, "put_profile", fake_put)
    monkeypatch.setattr("nanomuse.hub.profile.PUSH_DELAY_S", 0.05)
    return puts


def test_the_name_and_face_follow_the_account(hub_server, monkeypatch: pytest.MonkeyPatch) -> None:
    client, service, _llm, relay = hub_server
    store: dict[str, Any] = {
        "rev": 2,
        "updated_at": 1,
        "device": "phone-1",
        "name": "小火",
        "avatar": "face",
        "emoji": "",
        "color": "",
        "style": "pixel",
        "description": "a robot owl",
        "has_face": True,
        "face": {
            "idle": base64.b64encode(WEBP_IDLE).decode(),
            "happy": base64.b64encode(WEBP_HAPPY).decode(),
        },
    }
    puts = _fake_profile_relay(monkeypatch, store)
    sign_in(client)
    # the relay's look is worn: the name, and the stills in the workspace behind the files API
    wait_for(lambda: service.profile.name == "小火")
    face = service.profile.avatar
    assert face.startswith("sync-")
    folder = service.workspace() / "avatar" / face
    assert (folder / "idle.webp").read_bytes() == WEBP_IDLE
    assert (folder / "happy.webp").read_bytes() == WEBP_HAPPY
    assert (folder / "working.webp").read_bytes() == WEBP_IDLE  # a missing mood wears idle
    assert client.get(f"/api/files/avatar/{face}/idle.webp").status_code == 200
    assert service.hub.profile.rev == 2 and puts == []  # a pulled look is not pushed back
    # a change here goes to the relay a moment later; a rename keeps the pictures there
    client.put("/api/settings", json={"profile": {"name": "小火龙"}})
    wait_for(lambda: puts)
    assert puts[0]["name"] == "小火龙" and puts[0]["avatar"] == "face"
    assert "face" not in puts[0] and puts[0]["device"] == service.hub.device_id
    wait_for(lambda: service.hub.profile.rev == 3)
    # the relay's word that another device changed it: pulled and worn
    store.update(
        rev=4, device="phone-1", avatar="emoji", emoji="🦉", color="#059669", has_face=False
    )
    store["face"] = None
    relay.send({"type": "profile", "rev": 4, "device": "phone-1"})
    wait_for(lambda: service.profile.emoji == "🦉")
    assert service.profile.avatar == "" and service.profile.color == "#059669"
    assert service.hub.profile.rev == 4 and len(puts) == 1
    # the dragon chosen here is shared too; signing out forgets the rev, not the look
    client.put("/api/settings", json={"profile": {"avatar": "dragon"}})
    wait_for(lambda: len(puts) == 2)
    assert puts[1]["avatar"] == "dragon" and store["rev"] == 5
    client.post("/api/cloud/sign-out")
    assert service.hub.profile.rev == 0 and service.profile.avatar == "dragon"


def test_a_device_keeps_the_face_it_drew_when_another_renames(
    hub_server, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The studio's folder — the clips and ``face.json`` — stays when the account's pictures
    are the ones this device already wears; its description and style travel to the rest."""
    client, service, _llm, relay = hub_server
    store: dict[str, Any] = {"rev": 0, "name": "", "avatar": "", "has_face": False, "face": None}
    puts = _fake_profile_relay(monkeypatch, store)
    folder = service.workspace() / "avatar" / "face-abc123"
    folder.mkdir(parents=True)
    for mood in ("idle", "working", "waiting", "happy", "error"):
        (folder / f"{mood}.webp").write_bytes(WEBP_IDLE if mood != "happy" else WEBP_HAPPY)
    (folder / "idle.mp4").write_bytes(b"clip")
    (folder / "face.json").write_text(
        json.dumps({"description": "a robot owl", "style": "pixel", "model": "draw-1"})
    )
    service.update_profile({"name": "Owl", "avatar": "face-abc123"})
    sign_in(client)
    wait_for(lambda: puts)
    assert puts[0]["avatar"] == "face" and puts[0]["description"] == "a robot owl"
    assert puts[0]["style"] == "pixel" and set(puts[0]["face"]) == {
        "idle",
        "working",
        "waiting",
        "happy",
        "error",
    }
    wait_for(lambda: service.hub.profile.rev == 1)
    # the phone renames; the relay carries the same pictures — and says so with face_id
    store.update(rev=2, device="phone-1", name="Owlet")
    store["face_id"] = hashlib.sha1(WEBP_IDLE).hexdigest()[:12]
    relay.send({"type": "profile", "rev": 2, "device": "phone-1"})
    wait_for(lambda: service.profile.name == "Owlet")
    assert service.profile.avatar == "face-abc123" and (folder / "idle.mp4").is_file()
    assert not [p for p in (service.workspace() / "avatar").iterdir() if p.name.startswith("sync-")]
    # an older relay without face_id: the downloaded still is compared instead
    store.update(rev=3, name="Owlet II")
    store.pop("face_id")
    relay.send({"type": "profile", "rev": 3, "device": "phone-1"})
    wait_for(lambda: service.profile.name == "Owlet II")
    assert service.profile.avatar == "face-abc123"
    # different pictures from the phone: pulled into a sync folder with what they are
    store.update(rev=4, description="a corgi", style="muse", face_id="other")
    store["face"] = {"idle": base64.b64encode(WEBP_HAPPY).decode()}
    relay.send({"type": "profile", "rev": 4, "device": "phone-1"})
    wait_for(lambda: service.profile.avatar.startswith("sync-"))
    info = json.loads(
        (service.workspace() / "avatar" / service.profile.avatar / "face.json").read_text()
    )
    assert info["description"] == "a corgi" and info["style"] == "muse"
    assert client.get("/api/avatar").json()["face"]["description"] == "a corgi"
    assert len(puts) == 1  # nothing pulled was pushed back


def test_the_first_device_seeds_the_accounts_look(
    hub_server, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, service, _llm, _relay = hub_server
    store: dict[str, Any] = {"rev": 0, "name": "", "avatar": "", "has_face": False, "face": None}
    puts = _fake_profile_relay(monkeypatch, store)
    service.update_profile({"name": "Nova", "avatar": "", "emoji": "🪐", "color": "#7c3aed"})
    assert puts == []  # not signed in: nothing to tell
    sign_in(client)
    wait_for(lambda: puts)
    assert puts[0] == {
        "device": service.hub.device_id,
        "name": "Nova",
        "avatar": "emoji",
        "emoji": "🪐",
        "color": "#7c3aed",
        "connectors": [],
    }
    wait_for(lambda: service.hub.profile.rev == 1)


def test_connections_travel_by_name_only(hub_server, monkeypatch: pytest.MonkeyPatch) -> None:
    """Contract C3: the remote MCP servers this device connected go to the account as a
    name, an address and a kind — never the key — and the other devices' come back and show
    under Connections as held elsewhere."""
    from nanomuse.config import MCPServerSettings

    client, service, _llm, relay = hub_server
    phone_entry = {
        "id": "github",
        "label": "GitHub",
        "url": "https://api.githubcopilot.com/mcp/",
        "auth": "oauth",
        "device": "Li's phone",
        "device_id": "phone-1",
        "enabled": True,
        "at": "2026-10-01T08:00:00Z",
    }
    store: dict[str, Any] = {
        "rev": 2,
        "device": "phone-1",
        "name": "Nova",
        "avatar": "dragon",
        "has_face": False,
        "face": None,
        "connectors": [phone_entry],
    }
    puts = _fake_profile_relay(monkeypatch, store)
    service.settings.mcp.servers = [
        MCPServerSettings(name="notes", url="https://mcp.example.net/sse?key=SECRET-123"),
        MCPServerSettings(name="local-files", command="python", args=["-m", "files"]),
    ]
    assert client.get("/api/connections").json()["shared"] == []  # not signed in
    sign_in(client)
    wait_for(lambda: service.hub.profile.rev == 2)
    shared = client.get("/api/connections").json()["shared"]
    assert shared == [{**phone_entry, "here": False}]
    # what this device holds goes up when the look changes: the URL without its query, the
    # kind of sign-in, never the key; the stdio server stays private
    client.put("/api/settings", json={"profile": {"name": "Nova II"}})
    wait_for(lambda: puts)
    mine = puts[0]["connectors"]
    assert [c["id"] for c in mine] == ["notes"]
    assert mine[0]["url"] == "https://mcp.example.net/sse" and mine[0]["auth"] == "key"
    assert mine[0]["device_id"] == service.hub.device_id and mine[0]["device"]
    assert "SECRET" not in json.dumps(puts[0])
    # the relay's word that another device connected something: pulled, and the one this
    # device also has is marked as here
    store["connectors"] = store["connectors"] + [
        {**phone_entry, "id": "notes", "label": "Notes", "url": "https://mcp.example.net/sse"},
        {**phone_entry, "id": "stale", "device_id": service.hub.device_id},  # our own echo
    ]
    store["rev"] = 4
    relay.send({"type": "profile", "rev": 4, "device": "phone-1"})
    wait_for(lambda: len(service.hub.profile.shared_connectors) == 2)
    shared = client.get("/api/connections").json()["shared"]
    assert {(c["id"], c["here"]) for c in shared} == {("github", False), ("notes", True)}
    assert service.profile.name == "Nova II"  # a connectors-only rev does not undo the rename
    # dropping a remote server tells the account; signing out forgets the others' list
    service.connections.data["mcp"] = {
        "servers": [{"name": "notes", "url": "https://mcp.example.net/sse?key=SECRET-123"}]
    }
    assert client.delete("/api/connections/mcp/notes").status_code == 200
    wait_for(lambda: len(puts) == 2)
    assert puts[1]["connectors"] == []
    client.post("/api/cloud/sign-out")
    assert service.hub.profile.shared_connectors == []
    assert client.get("/api/connections").json()["shared"] == []

"""The hub through the ASGI app: two devices of one account find each other and
pass calls; a second account sees nothing of it."""

from __future__ import annotations

import asyncio
import hashlib
import json
import time

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from nanomuse_cloud.api import create_app
from nanomuse_cloud.config import Settings
from nanomuse_cloud.db import Database
from nanomuse_cloud.hub import SEND_QUEUE_FRAMES, Connection
from nanomuse_cloud.senders import LogSender
from nanomuse_cloud.service import Cloud


@pytest.fixture
def client():
    settings = Settings(database=":memory:", secret="test-secret", public_base="http://cloud.test", hub_frame_limit=4096)
    sender = LogSender()
    cloud = Cloud(settings, Database(":memory:"), sender)
    app = create_app(settings, cloud)
    with TestClient(app) as c:
        c.sender = sender
        yield c


def sign_up(
    client: TestClient,
    identifier: str,
    *,
    device_id: str = "",
    device_kind: str = "",
) -> str:
    assert client.post("/v1/auth/code", json={"identifier": identifier}).status_code == 204
    _, code = client.sender.sent[-1]
    body = {"identifier": identifier, "code": code, "device": "test"}
    if device_id or device_kind:
        body.update({"device_id": device_id, "device_kind": device_kind})
    r = client.post("/v1/auth/verify", json=body)
    assert r.status_code == 200, r.text
    return r.json()["api_key"]


def hello(kind: str, device_id: str, name: str, key: str | None = None, actions=("info", "shell")) -> dict:
    frame = {
        "type": "hello",
        "device": {"id": device_id, "name": name, "kind": kind, "os": "TestOS", "version": "0.1", "actions": list(actions)},
    }
    if key:
        frame["key"] = key
    return frame


def connect(client: TestClient, key: str | None, **kw):
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    return client.websocket_connect("/v1/hub", headers=headers, **kw)


def test_two_devices_route_calls_and_results(client):
    key = sign_up(client, "13800138000")
    pc_key = sign_up(client, "13800138000")
    with connect(client, key) as phone, connect(client, pc_key) as pc:
        phone.send_json(hello("phone", "phone-1", "Pixel"))
        w1 = phone.receive_json()
        assert w1["type"] == "welcome" and w1["device_id"] == "phone-1"
        assert [d["id"] for d in w1["devices"]] == ["phone-1"]
        phone.receive_json()  # the devices broadcast triggered by its own arrival

        pc.send_json(hello("computer", "pc-1", "desk", actions=("info", "shell", "screen")))
        w2 = pc.receive_json()
        assert w2["type"] == "welcome"
        assert {d["id"]: d["online"] for d in w2["devices"]} == {"phone-1": True, "pc-1": True}
        pc.receive_json()  # broadcast
        upd = phone.receive_json()
        assert upd["type"] == "devices" and {d["id"] for d in upd["devices"]} == {"phone-1", "pc-1"}
        pc_row = next(d for d in upd["devices"] if d["id"] == "pc-1")
        assert pc_row["actions"] == ["info", "shell", "screen"] and pc_row["controllable"] is True

        # phone → pc: a call, progress, then the result; each lands on the right side.
        phone.send_json({"type": "call", "id": "c1", "to": "pc-1", "action": "shell", "args": {"command": "uname"}})
        call = pc.receive_json()
        assert call == {
            "type": "call",
            "id": "c1",
            "from": {"id": "phone-1", "name": "Pixel", "kind": "phone"},
            "action": "shell",
            "args": {"command": "uname"},
        }
        pc.send_json({"type": "event", "id": "c1", "body": {"stage": "running"}})
        ev = phone.receive_json()
        assert ev["type"] == "event" and ev["body"] == {"stage": "running"} and ev["from"]["id"] == "pc-1"
        pc.send_json({"type": "result", "id": "c1", "ok": True, "body": {"stdout": "Linux\n", "exit_code": 0}})
        res = phone.receive_json()
        assert res["type"] == "result" and res["ok"] is True and res["body"]["stdout"] == "Linux\n"

        # A result for a call that is not pending is refused, once, to its sender.
        pc.send_json({"type": "result", "id": "c1", "ok": True, "body": {}})
        assert pc.receive_json()["code"] == "unknown_call"

        # pc → phone works the same way.
        pc.send_json({"type": "call", "id": "c2", "to": "phone-1", "action": "notify", "args": {"text": "hi"}})
        assert phone.receive_json()["action"] == "notify"
        phone.send_json({"type": "result", "id": "c2", "ok": False, "error": "denied", "message": "no"})
        r2 = pc.receive_json()
        assert r2["ok"] is False and r2["error"] == "denied"

        # Calling yourself, or a device that is not there.
        pc.send_json({"type": "call", "id": "c3", "to": "pc-1", "action": "info", "args": {}})
        assert pc.receive_json()["code"] == "self_call"
        pc.send_json({"type": "call", "id": "c4", "to": "nope", "action": "info", "args": {}})
        assert pc.receive_json()["code"] == "device_offline"

        pc.send_json({"type": "ping"})
        assert pc.receive_json()["type"] == "pong"

    # Both gone: remembered, offline, listable over HTTP.
    r = client.get("/v1/devices", headers={"Authorization": f"Bearer {key}"})
    assert r.status_code == 200
    rows = {d["id"]: d for d in r.json()["devices"]}
    assert set(rows) == {"phone-1", "pc-1"} and not rows["pc-1"]["online"]
    assert client.delete("/v1/devices/pc-1", headers={"Authorization": f"Bearer {key}"}).status_code == 204
    assert [d["id"] for d in client.get("/v1/devices", headers={"Authorization": f"Bearer {key}"}).json()["devices"]] == ["phone-1"]


def test_target_leaving_fails_the_pending_call(client):
    key = sign_up(client, "someone@example.com")
    pc_key = sign_up(client, "someone@example.com")
    with connect(client, key) as phone, connect(client, pc_key) as pc:
        phone.send_json(hello("phone", "phone-1", "Pixel"))
        phone.receive_json()
        phone.receive_json()
        pc.send_json(hello("computer", "pc-1", "desk"))
        pc.receive_json()
        pc.receive_json()
        phone.receive_json()  # devices: pc joined
        phone.send_json({"type": "call", "id": "c1", "to": "pc-1", "action": "shell", "args": {"command": "sleep 100"}})
        assert pc.receive_json()["action"] == "shell"
        # pc drops without answering (an explicit close: the test session's own
        # exit cancels the server task before it can tell anyone).
        pc.close(1000)
        seen = [phone.receive_json(), phone.receive_json()]
        kinds = {f["type"]: f for f in seen}
        assert kinds["error"]["code"] == "device_offline" and kinds["error"]["id"] == "c1"
        assert {d["id"]: d["online"] for d in kinds["devices"]["devices"]} == {"phone-1": True, "pc-1": False}


def test_a_lone_pending_call_times_out_on_the_callers_ping(client):
    """The sweep ran only when another `call` arrived, so a caller with one call outstanding
    and nothing more to ask never heard `timeout`; every client pings, so it sweeps too."""
    from nanomuse_cloud import hub as hub_mod

    key = sign_up(client, "someone@example.com")
    pc_key = sign_up(client, "someone@example.com")
    with connect(client, key) as phone, connect(client, pc_key) as pc:
        phone.send_json(hello("phone", "phone-1", "Pixel"))
        phone.receive_json()
        phone.receive_json()
        pc.send_json(hello("computer", "pc-1", "desk"))
        pc.receive_json()
        pc.receive_json()
        phone.receive_json()  # devices: pc joined
        phone.send_json({"type": "call", "id": "c1", "to": "pc-1", "action": "shell", "args": {"command": "sleep"}})
        assert pc.receive_json()["action"] == "shell"
        hub = client.app.state.hub
        assert ("hub", "c1") not in hub.pending and len(hub.pending) == 1
        # a ping while the call is young: a pong and nothing else
        phone.send_json({"type": "ping"})
        assert phone.receive_json()["type"] == "pong"
        # the call ages past the limit; the next ping delivers the timeout
        for p in hub.pending.values():
            p.started -= hub_mod.CALL_TTL_S + 1
        phone.send_json({"type": "ping"})
        assert phone.receive_json()["type"] == "pong"
        err = phone.receive_json()
        assert err == {"type": "error", "id": "c1", "code": "timeout", "message": "the device did not answer in time"}
        assert not hub.pending
        # a late result from the target is an unknown call now
        pc.send_json({"type": "result", "id": "c1", "ok": True, "body": {}})
        assert pc.receive_json()["code"] == "unknown_call"


def test_web_tab_authenticates_in_hello_and_cannot_be_called(client):
    key = sign_up(client, "13800138000")
    pc_key = sign_up(client, "13800138000")
    with connect(client, None) as web, connect(client, pc_key) as pc:
        web.send_json(hello("web", "", "Chrome", key=key))
        w = web.receive_json()
        assert w["type"] == "welcome" and w["device_id"].startswith("web-")
        web.receive_json()
        pc.send_json(hello("computer", "pc-1", "desk"))
        pc.receive_json()
        pc.receive_json()
        upd = web.receive_json()
        tab = next(d for d in upd["devices"] if d["kind"] == "web")
        assert tab["controllable"] is False

        pc.send_json({"type": "call", "id": "x", "to": w["device_id"], "action": "info", "args": {}})
        assert pc.receive_json()["code"] == "not_controllable"

        web.send_json({"type": "call", "id": "t1", "to": "pc-1", "action": "task", "args": {"text": "open the calendar"}})
        assert pc.receive_json()["args"] == {"text": "open the calendar"}
        pc.send_json({"type": "result", "id": "t1", "ok": True, "body": {"text": "done"}})
        assert web.receive_json()["body"] == {"text": "done"}

    # Browser tabs are not remembered.
    assert [d["kind"] for d in client.get("/v1/devices", headers={"Authorization": f"Bearer {key}"}).json()["devices"]] == ["computer"]


def test_bad_key_and_bad_hello(client):
    with connect(client, None) as ws:
        ws.send_json(hello("phone", "p", "x", key="nm_nothing"))
        assert ws.receive_json()["code"] == "bad_key"
    key = sign_up(client, "13800138000")
    with connect(client, key) as ws:
        ws.send_json(hello("toaster", "t-1", "x"))
        assert ws.receive_json()["code"] == "bad_device"
    with connect(client, key) as ws:
        ws.send_json({"type": "call"})
        with pytest.raises(WebSocketDisconnect):
            ws.receive_json()  # closed: hello expected


def test_a_bad_bearer_header_is_refused_with_4001_after_the_handshake(client):
    """The apps send the key in the header. A refusal must reach them as a close with
    4001 and the code (docs/hub.md), not as a failed handshake: a failed handshake looks
    like the network and the phone would retry it forever."""
    with connect(client, "nm_nothing") as ws:
        err = ws.receive_json()
        assert err["type"] == "error" and err["code"] == "bad_key"
        with pytest.raises(WebSocketDisconnect) as closed:
            ws.receive_json()
        assert closed.value.code == 4001 and closed.value.reason == "bad_key"


def test_binary_and_unknown_frames_are_answered_not_fatal(client):
    key = sign_up(client, "13800138000")
    # before hello a binary frame is as wrong as any other non-hello: closed, 4000
    with connect(client, key) as ws:
        ws.send_bytes(b"\x00\x01")
        with pytest.raises(WebSocketDisconnect) as closed:
            ws.receive_json()
        assert closed.value.code == 4000
    # after hello the socket stays open and says what was wrong
    with connect(client, key) as ws:
        ws.send_json(hello("phone", "phone-1", "Pixel"))
        assert ws.receive_json()["type"] == "welcome"
        ws.receive_json()  # devices broadcast
        ws.send_bytes(b"\x00\x01")
        err = ws.receive_json()
        assert err["code"] == "bad_frame" and "binary" in err["message"]
        ws.send_json({"type": "teleport"})
        err = ws.receive_json()
        assert err["code"] == "bad_frame" and "teleport" in err["message"]
        ws.send_text("[1, 2]")
        assert ws.receive_json()["code"] == "bad_frame"
        ws.send_json({"type": "ping"})
        assert ws.receive_json()["type"] == "pong"  # still alive


class _StalledSocket:
    """A peer that reads only when told to: send_text waits on the gate."""

    def __init__(self):
        self.sent: list[str] = []
        self.closed: tuple[int, str] | None = None
        self.gate = asyncio.Event()

    async def send_text(self, text: str) -> None:
        await self.gate.wait()
        self.sent.append(text)

    async def close(self, code: int, reason: str = "") -> None:
        self.closed = (code, reason)


def _conn(ws) -> Connection:
    return Connection(ws=ws, account_id="a", key_hash="k", device_id="pc-1", name="desk", kind="computer")


async def test_a_send_never_waits_on_the_peer_and_order_is_kept():
    """A slow phone used to hold the computer calling it: send awaited the phone's socket
    inside the caller's receive loop. Now a send queues and returns; the writer drains in
    order once the peer reads."""
    ws = _StalledSocket()
    conn = _conn(ws)
    conn.start()
    try:
        t0 = time.monotonic()
        for i in range(5):
            await conn.send({"type": "event", "i": i})
        assert time.monotonic() - t0 < 0.5 and ws.sent == [] and not conn.closed
        ws.gate.set()
        for _ in range(100):
            if len(ws.sent) == 5:
                break
            await asyncio.sleep(0.01)
        assert [json.loads(t)["i"] for t in ws.sent] == [0, 1, 2, 3, 4]
        assert conn.queued_bytes == 0 and not conn.queue
    finally:
        conn.stop()


async def test_a_peer_that_stops_reading_is_closed_with_4009():
    ws = _StalledSocket()
    conn = _conn(ws)
    conn.start()
    # the writer takes the first frame and blocks in send_text; the queue fills behind it
    for i in range(SEND_QUEUE_FRAMES + 2):
        await conn.send({"type": "event", "i": i})
    assert conn.closed and conn.overflowed
    for _ in range(100):
        if ws.closed:
            break
        await asyncio.sleep(0.01)
    assert ws.closed == (4009, "slow_consumer")
    assert conn.writer is not None and (conn.writer.cancelled() or conn.writer.done())
    # bytes count too: two frames of 12 MiB fit, the third does not
    ws2 = _StalledSocket()
    conn2 = _conn(ws2)
    conn2.start()
    big = "x" * (12 * 1024 * 1024)
    for _ in range(3):
        await conn2.send({"type": "event", "body": big})
    assert conn2.overflowed and len(conn2.queue) <= 2
    conn2.stop()


def test_accounts_are_separate_and_frames_are_capped(client):
    a = sign_up(client, "13800138000")
    b = sign_up(client, "13900139000")
    with connect(client, a) as pa, connect(client, b) as pb:
        pa.send_json(hello("phone", "phone-1", "A's"))
        pa.receive_json()
        pa.receive_json()
        pb.send_json(hello("computer", "pc-1", "B's"))
        w = pb.receive_json()
        assert [d["id"] for d in w["devices"]] == ["pc-1"]
        pb.receive_json()
        pa.send_json({"type": "call", "id": "c1", "to": "pc-1", "action": "info", "args": {}})
        assert pa.receive_json()["code"] == "device_offline"
        pa.send_text(json.dumps({"type": "ping", "pad": "x" * 5000}))
        assert pa.receive_json()["code"] == "too_large"
        # the cap is in bytes on the wire: 1500 Chinese characters are 4500 bytes of UTF-8
        pa.send_text(json.dumps({"type": "ping", "pad": "文" * 1500}, ensure_ascii=False))
        assert pa.receive_json()["code"] == "too_large"
        pa.send_text(json.dumps({"type": "ping", "pad": "文" * 1000}, ensure_ascii=False))
        assert pa.receive_json()["type"] == "pong"


def test_a_call_id_still_waiting_is_not_taken_twice(client):
    key = sign_up(client, "13800138000")
    pc_key = sign_up(client, "13800138000")
    with connect(client, key) as phone, connect(client, pc_key) as pc:
        phone.send_json(hello("phone", "phone-1", "Pixel"))
        phone.receive_json()
        phone.receive_json()
        pc.send_json(hello("computer", "pc-1", "desk"))
        pc.receive_json()
        pc.receive_json()
        phone.receive_json()
        phone.send_json({"type": "call", "id": "c1", "to": "pc-1", "action": "info", "args": {}})
        assert pc.receive_json()["id"] == "c1"
        phone.send_json({"type": "call", "id": "c1", "to": "pc-1", "action": "shell", "args": {"command": "rm"}})
        dup = phone.receive_json()
        assert dup["type"] == "error" and dup["code"] == "duplicate_call" and dup["id"] == "c1"
        # the first call is still the one waiting: its answer reaches the phone
        pc.send_json({"type": "result", "id": "c1", "ok": True, "body": {"os": "linux"}})
        res = phone.receive_json()
        assert res["type"] == "result" and res["body"] == {"os": "linux"}
        # and once it is answered the id is free again
        phone.send_json({"type": "call", "id": "c1", "to": "pc-1", "action": "info", "args": {}})
        assert pc.receive_json()["action"] == "info"


def test_device_credentials_are_bound_and_older_keys_cannot_claim_them(client):
    """A new client binds at sign-in. Its key cannot announce another installation or
    kind, and an unbound key from an earlier sign-in (a leaked old key, say) cannot take
    an identity a later key owns."""
    legacy = sign_up(client, "bound@example.com")
    a = sign_up(client, "bound@example.com", device_id="phone-a", device_kind="phone")
    b = sign_up(client, "bound@example.com", device_id="pc-b", device_kind="computer")

    for frame in (
        hello("phone", "pc-b", "not B"),
        hello("computer", "phone-a", "not a phone"),
    ):
        with connect(client, a) as ws:
            ws.send_json(frame)
            err = ws.receive_json()
            assert err["type"] == "error" and err["code"] == "bad_device"

    with connect(client, legacy) as ws:
        ws.send_json(hello("computer", "pc-b", "old client"))
        assert ws.receive_json()["code"] == "bad_device"

    with connect(client, a) as phone, connect(client, b) as pc:
        phone.send_json(hello("phone", "phone-a", "Pixel"))
        assert phone.receive_json()["device_id"] == "phone-a"
        phone.receive_json()
        pc.send_json(hello("computer", "pc-b", "Desk"))
        assert pc.receive_json()["device_id"] == "pc-b"


def test_old_client_binds_on_first_hello_and_reconnects(client):
    """The one-release migration path keeps an existing unbound credential working.
    Its first accepted hello registers the id and later reconnects retain it."""
    key = sign_up(client, "legacy@example.com")
    for _ in range(2):
        with connect(client, key) as ws:
            ws.send_json(hello("computer", "legacy-pc", "Desk"))
            assert ws.receive_json()["device_id"] == "legacy-pc"


def test_a_later_sign_in_on_the_same_installation_takes_the_identity_over(client):
    """A phone that signs in again without signing out (or whose sign-out never reached
    the relay) keeps its device id: the newer code sign-in proved the account, so its key
    takes the id from the older one, which stays a valid account key but no longer
    speaks for the device. The older key cannot take it back."""
    old = sign_up(client, "again@example.com")
    with connect(client, old) as ws:
        ws.send_json(hello("phone", "phone-same", "Pixel"))
        assert ws.receive_json()["device_id"] == "phone-same"
    new = sign_up(client, "again@example.com")
    with connect(client, new) as ws:
        ws.send_json(hello("phone", "phone-same", "Pixel"))
        assert ws.receive_json()["device_id"] == "phone-same"
    with connect(client, old) as ws:
        ws.send_json(hello("phone", "phone-same", "Pixel"))
        assert ws.receive_json()["code"] == "bad_device"
    with connect(client, old) as ws:
        ws.send_json(hello("phone", "phone-other", "Pixel"))
        assert ws.receive_json()["device_id"] == "phone-other"
    auth = {"Authorization": f"Bearer {old}"}
    assert client.get("/v1/me", headers=auth).status_code == 200, "the older key still opens the account"


def test_a_revoked_owner_releases_its_device_id(client):
    """Sign out, sign in again on the same installation: the revoked key no longer holds
    the id, and the fresh key registers it at its first hello."""
    first = sign_up(client, "signout@example.com")
    with connect(client, first) as ws:
        ws.send_json(hello("computer", "pc-same", "Desk"))
        assert ws.receive_json()["device_id"] == "pc-same"
    assert client.post("/v1/auth/sign-out", headers={"Authorization": f"Bearer {first}"}).status_code == 204
    second = sign_up(client, "signout@example.com")
    with connect(client, second) as ws:
        ws.send_json(hello("computer", "pc-same", "Desk"))
        assert ws.receive_json()["device_id"] == "pc-same"


def test_a_session_key_registers_a_free_identity_but_never_takes_one(client):
    """nanoMuse Web's container runs the runtime, a `computer` of the account with an id of
    its own: a session key binds that at its first hello like any credential. What it
    cannot do is take over an id a standing key holds, however new the session key is."""
    standing = sign_up(client, "web-session@example.com", device_id="pc-mine", device_kind="computer")
    r = client.post(
        "/v1/auth/session-key",
        headers={"Authorization": f"Bearer {standing}"},
        json={"device": "Web", "ttl_s": 3600},
    )
    assert r.status_code == 200
    session = r.json()
    assert set(session) == {"api_key", "expires_at"}
    with connect(client, session["api_key"]) as ws:
        ws.send_json(hello("computer", "pc-mine", "fake"))
        assert ws.receive_json()["code"] == "bad_device"
    with connect(client, session["api_key"]) as ws:
        ws.send_json(hello("computer", "pc-container", "Web"))
        assert ws.receive_json()["device_id"] == "pc-container"
    with connect(client, session["api_key"]) as ws:
        ws.send_json(hello("phone", "pc-container", "Web"))
        assert ws.receive_json()["code"] == "bad_device"


def test_forged_hello_cannot_settle_invite_but_spend_threshold_settles_once(client):
    """A remembered Hub row is not proof of real use. Only cumulative successful
    provider cost reaches the threshold, and concurrent/repeated checks pay once."""
    inviter_key = sign_up(client, "inviter@example.com")
    invitee_key = sign_up(client, "invitee@example.com")
    cloud = client.app.state.cloud
    inviter = cloud.authenticate(inviter_key).account_id
    invitee = cloud.authenticate(invitee_key).account_id
    cloud.db.link_invite(inviter, invitee)
    before_inviter = int(cloud.db.account(inviter)["grant_uy"])
    before_invitee = int(cloud.db.account(invitee)["grant_uy"])

    cloud.db.charge(invitee, "chat", "test", 0, 0, 0, "tiny", cost_uy=199)
    assert cloud.settle_invite(invitee) is False
    with connect(client, invitee_key) as forged:
        forged.send_json(hello("phone", "forged-phone", "forged"))
        assert forged.receive_json()["type"] == "welcome"
    assert cloud.settle_invite(invitee) is False

    cloud.db.charge(invitee, "chat", "test", 0, 0, 0, "enough", cost_uy=1)
    assert cloud.settle_invite(invitee) is True
    assert cloud.settle_invite(invitee) is False
    bonus = cloud.s.cny_to_uy(cloud.s.invite_bonus_cny)
    assert int(cloud.db.account(inviter)["grant_uy"]) == before_inviter + bonus
    assert int(cloud.db.account(invitee)["grant_uy"]) == before_invitee + bonus
    credits = cloud.db._conn.execute(
        "SELECT COUNT(*) FROM ledger WHERE kind='credit' AND json_extract(extra, '$.from') IN ('invite', 'invited')"
    ).fetchone()[0]
    assert credits == 2


def test_reconnect_replaces_the_older_socket(client):
    key = sign_up(client, "13800138000")
    with connect(client, key) as first:
        first.send_json(hello("computer", "pc-1", "desk"))
        first.receive_json()
        first.receive_json()
        with connect(client, key) as second:
            second.send_json(hello("computer", "pc-1", "desk"))
            w = second.receive_json()
            assert [d["id"] for d in w["devices"]] == ["pc-1"]
            second.send_json({"type": "devices"})
            frames = [second.receive_json(), second.receive_json()]
            assert all(f["type"] == "devices" for f in frames)
            assert all(len(f["devices"]) == 1 for f in frames)


def test_a_sign_out_closes_the_hub_socket_of_the_key_it_revoked(client):
    """Sign out everywhere is what to do after losing a phone. The lost phone's key stops
    opening at once; its hub socket, open before the sign-out, must go too (4001 bad_key,
    docs/hub.md), or the phone keeps a live line to the other devices until it next
    reconnects. The device that asked keeps its socket; a session revoked by prefix from
    the account page and a device's own sign-out close the same way."""
    phone_key = sign_up(client, "13800138000")
    pc_key = sign_up(client, "13800138000")
    with connect(client, phone_key) as phone, connect(client, pc_key) as pc:
        phone.send_json(hello("phone", "phone-1", "Pixel"))
        phone.receive_json()
        phone.receive_json()
        pc.send_json(hello("computer", "pc-1", "desk"))
        pc.receive_json()
        pc.receive_json()
        phone.receive_json()  # the pc arrived
        # every other device: the phone's key is revoked, its socket closed; the pc stays
        r = client.post("/v1/auth/sign-out-all", headers={"Authorization": f"Bearer {pc_key}"}, json={})
        assert r.status_code == 200 and r.json()["signed_out"] == 1
        with pytest.raises(WebSocketDisconnect) as closed:
            phone.receive_json()
        assert closed.value.code == 4001 and closed.value.reason == "bad_key"
        pc.send_json({"type": "devices"})
        assert pc.receive_json()["type"] == "devices"  # the pc's line is still open
        r = client.get("/v1/devices", headers={"Authorization": f"Bearer {pc_key}"})
        assert {d["id"]: d["online"] for d in r.json()["devices"]} == {"phone-1": False, "pc-1": True}
    # a session revoked by prefix from the account page
    key_a = sign_up(client, "dev-a@example.com")
    key_b = sign_up(client, "dev-a@example.com")
    with connect(client, key_b) as other:
        other.send_json(hello("computer", "pc-2", "laptop"))
        other.receive_json()
        other.receive_json()
        sessions = client.get("/v1/me/sessions", headers={"Authorization": f"Bearer {key_a}"}).json()["sessions"]
        prefix = next(s["prefix"] for s in sessions if not s["current"])
        assert client.delete(f"/v1/me/sessions/{prefix}", headers={"Authorization": f"Bearer {key_a}"}).status_code == 204
        with pytest.raises(WebSocketDisconnect) as closed:
            other.receive_json()
        assert closed.value.code == 4001
    # a device's own sign-out
    with connect(client, key_a) as own:
        own.send_json(hello("computer", "pc-3", "desk"))
        own.receive_json()
        own.receive_json()
        assert client.post("/v1/auth/sign-out", headers={"Authorization": f"Bearer {key_a}"}).status_code == 204
        with pytest.raises(WebSocketDisconnect) as closed:
            own.receive_json()
        assert closed.value.code == 4001


def test_the_profile_is_shared_and_announced(client):
    """The agent's name and look live on the relay so every device of the account wears
    the same one: a PUT from one device is a ``profile`` frame on the other's socket, and
    the pictures are fetched only when asked for."""
    import base64

    key = sign_up(client, "13800138000")
    pc_key = sign_up(client, "13800138000")
    auth = {"Authorization": f"Bearer {key}"}
    assert client.get("/v1/me/profile", headers=auth).json()["rev"] == 0

    webp = base64.b64encode(b"RIFF\x00\x00\x00\x00WEBPVP8 " + b"\x00" * 40).decode()
    with connect(client, key) as phone, connect(client, pc_key) as pc:
        phone.send_json(hello("phone", "phone-1", "Pixel"))
        phone.receive_json(), phone.receive_json()
        pc.send_json(hello("computer", "pc-1", "desk"))
        pc.receive_json(), pc.receive_json()
        phone.receive_json()  # the devices broadcast for the pc's arrival

        r = client.put(
            "/v1/me/profile",
            headers=auth,
            json={
                "device": "pc-1",
                "name": "小火",
                "avatar": "face",
                "style": "pixel",
                "description": "a robot owl",
                "face": {"idle": webp, "happy": webp},
            },
        )
        assert r.status_code == 200 and r.json()["rev"] == 1
        assert phone.receive_json() == {"type": "profile", "rev": 1, "device": "pc-1"}
        assert pc.receive_json() == {"type": "profile", "rev": 1, "device": "pc-1"}

    light = client.get("/v1/me/profile", params={"face": "false"}, headers=auth).json()
    assert light["rev"] == 1 and light["name"] == "小火" and light["has_face"] is True and "face" not in light
    full = client.get("/v1/me/profile", headers=auth).json()
    assert set(full["face"]) == {"idle", "happy"} and full["device"] == "pc-1"
    # the idle still's hash, so a device that already wears these pictures keeps its copy
    assert light["face_id"] == hashlib.sha1(base64.b64decode(webp)).hexdigest()[:12] == full["face_id"]

    # a rename keeps the pictures; switching to an emoji drops them
    r = client.put("/v1/me/profile", headers=auth, json={"device": "phone-1", "name": "小火龙", "avatar": "face"})
    assert r.status_code == 200 and r.json()["rev"] == 2
    assert client.get("/v1/me/profile", headers=auth).json()["face"]["idle"] == webp
    # 0.25: a write names only what changed. The name alone keeps the look (a phone that
    # renamed before it ever pulled the face no longer sends "dragon" and takes the face off
    # every device); a blank name keeps the stored one; a face without a name keeps the name.
    r = client.put("/v1/me/profile", headers=auth, json={"device": "phone-1", "name": "阿火"})
    after = client.get("/v1/me/profile", headers=auth).json()
    assert r.status_code == 200 and r.json()["rev"] == 3
    assert after["name"] == "阿火" and after["avatar"] == "face" and after["style"] == "pixel" and after["face"]["idle"] == webp
    r = client.put("/v1/me/profile", headers=auth, json={"device": "phone-1", "name": "", "description": "a robot owl, blue"})
    after = client.get("/v1/me/profile", headers=auth).json()
    assert r.status_code == 200 and after["name"] == "阿火" and after["description"] == "a robot owl, blue" and after["has_face"]
    r = client.put("/v1/me/profile", headers=auth, json={"device": "phone-1", "avatar": "face", "face": {"idle": webp}, "style": "ink"})
    after = client.get("/v1/me/profile", headers=auth).json()
    assert r.status_code == 200 and after["name"] == "阿火" and after["style"] == "ink" and set(after["face"]) == {"idle"}
    # back to the dragon without `face: null` (Android 1.0.3): the pictures go with the look,
    # so no device reads `has_face` as a face still worn while another shows the dragon
    r = client.put("/v1/me/profile", headers=auth, json={"device": "phone-1", "name": "阿火", "avatar": "dragon"})
    after = client.get("/v1/me/profile", headers=auth).json()
    assert r.status_code == 200 and after["avatar"] == "dragon" and after["has_face"] is False and after["face"] is None
    r = client.put(
        "/v1/me/profile",
        headers=auth,
        json={
            "device": "phone-1",
            "name": "阿火",
            "avatar": "face",
            "style": "pixel",
            "description": "a robot owl",
            "face": {"idle": webp},
        },
    )
    assert r.status_code == 200
    r = client.put(
        "/v1/me/profile", headers=auth, json={"name": "小火龙", "avatar": "emoji", "emoji": "🦉", "color": "#0064d4", "face": None}
    )
    after = client.get("/v1/me/profile", headers=auth).json()
    assert r.status_code == 200 and after["face"] is None and after["face_id"] == ""

    # what is refused: a face without pictures, a stray mood, a picture that is not a picture, a name too long
    bad = [
        {"name": "x", "avatar": "face"},
        {"name": "x", "avatar": "face", "face": {"idle": webp, "angry": webp}},
        {"name": "x", "avatar": "face", "face": {"idle": base64.b64encode(b"hello").decode()}},
        {"name": "x" * 61, "avatar": "dragon"},
        {"name": "x", "avatar": "emoji", "color": "blue"},
    ]
    for body in bad:
        assert client.put("/v1/me/profile", headers=auth, json=body).status_code == 400, body
    assert client.delete("/v1/me/profile", headers=auth).status_code == 204
    assert client.get("/v1/me/profile", headers=auth).json()["rev"] == 0
    # the first write of an account may be the name alone: the look is the dragon until a device says otherwise
    r = client.put("/v1/me/profile", headers=auth, json={"device": "phone-1", "name": "阿火"})
    after = client.get("/v1/me/profile", headers=auth).json()
    assert (
        r.status_code == 200
        and after["rev"] == 1
        and after["name"] == "阿火"
        and after["avatar"] == "dragon"
        and after["has_face"] is False
    )


def test_a_flooding_socket_is_slowed_then_closed(client, monkeypatch):
    """One socket may send so many frames and bytes a second (hub.FRAMES_PER_S, BYTES_PER_S,
    twice that in a burst); over it frames are dropped with one error a second, and a socket
    that keeps flooding is closed. The bucket itself, with a clock of our own."""
    from nanomuse_cloud import hub as hub_module
    from nanomuse_cloud.hub import FLOOD_CLOSE_AFTER, Bucket

    clock = [0.0]
    bucket = Bucket(10.0, 20.0, clock=lambda: clock[0])
    assert all(bucket.take() for _ in range(20)) and not bucket.take()  # the burst, then no more
    clock[0] = 0.5
    assert all(bucket.take() for _ in range(5)) and not bucket.take()  # half a second: five back
    clock[0] = 100
    assert sum(1 for _ in range(50) if bucket.take()) == 20  # never more than the burst

    # Only the connection buckets share this fixed instant. TestClient can take long
    # enough to send a burst that a wall-clock bucket would refill while it is queued.
    # The explicit-clock assertions above still cover refill and the burst ceiling.
    def frozen_bucket(rate, burst):
        return Bucket(rate, burst, clock=lambda: clock[0])

    monkeypatch.setattr(hub_module, "Bucket", frozen_bucket)

    a = sign_up(client, "13800138000")
    with connect(client, a) as pa:
        pa.send_json(hello("phone", "phone-1", "A's"))
        pa.receive_json()
        pa.receive_json()
        # A flood: twice the burst of pings with no bucket time passing. The burst is
        # answered, then one rate_limited error, not one per dropped frame, and the
        # hub counts the drops.
        burst = int(2 * hub_module.FRAMES_PER_S)
        for _ in range(burst + 50):
            pa.send_json({"type": "ping"})
        got = []
        while True:
            r = pa.receive_json()
            got.append(r)
            if r["type"] == "error":
                break
        pongs = sum(1 for r in got if r["type"] == "pong")
        assert pongs == burst and got[-1]["code"] == "rate_limited"
        hub = client.app.state.hub
        assert hub.dropped_total >= 1 and hub.stats()["dropped_frames"] == hub.dropped_total
        # kept up, the socket goes
        with pytest.raises(WebSocketDisconnect) as closed:
            for _ in range(FLOOD_CLOSE_AFTER + 200):
                pa.send_json({"type": "ping"})
            while True:
                pa.receive_json()
        assert closed.value.code == 4008
    assert hub.flood_closes == 1


def test_connectors_are_merged_by_device_and_never_hold_a_secret(client):
    """0.17 (contract C3): each device publishes which services it connected — a label and
    the sign-in kind, never the credential. The relay keeps one list per account, replaces
    only the writing device's entries, caps it at 64, refuses anything named like a secret,
    and tells the other devices on the hub as it does for the look."""
    key = sign_up(client, "13800138000")
    auth = {"Authorization": f"Bearer {key}"}
    assert client.get("/v1/me/profile", headers=auth).json()["connectors"] == []

    # the desk connects two services before the account has a look at all
    desk = [
        {"id": "github", "label": "GitHub", "url": "https://api.github.com", "auth": "oauth", "at": "2026-10-01T08:00:00Z"},
        {"id": "weather", "label": "Weather", "auth": "open", "enabled": False},
    ]
    with connect(client, key) as phone:
        phone.send_json(hello("phone", "phone-1", "Pixel"))
        phone.receive_json(), phone.receive_json()
        r = client.put("/v1/me/profile", headers=auth, json={"device": "desk-1", "connectors": desk})
        assert r.status_code == 200 and r.json() == {"rev": 1, "device": "desk-1"}
        assert phone.receive_json() == {"type": "profile", "rev": 1, "device": "desk-1"}
    got = client.get("/v1/me/profile", headers=auth).json()
    assert got["rev"] == 1 and got["name"] == "" and got["avatar"] == ""  # the look is still unset
    assert got["connectors"] == [
        {
            "id": "github",
            "label": "GitHub",
            "url": "https://api.github.com",
            "device": "desk-1",
            "device_id": "desk-1",
            "at": "2026-10-01T08:00:00Z",
            "auth": "oauth",
            "enabled": True,
        },
        {
            "id": "weather",
            "label": "Weather",
            "url": "",
            "device": "desk-1",
            "device_id": "desk-1",
            "at": got["connectors"][1]["at"],
            "auth": "open",
            "enabled": False,
        },
    ]
    assert got["connectors"][1]["at"].endswith("Z")  # stamped by the relay when the device did not say
    # ``?face=false`` carries them too — a device that reads the light profile sees the connectors
    light = client.get("/v1/me/profile", params={"face": "false"}, headers=auth).json()
    assert [c["id"] for c in light["connectors"]] == ["github", "weather"] and "face" not in light

    # the phone adds its own; the desk's stay. Then the desk drops one: only its own list changes.
    phone_conn = [{"id": "github", "label": "GitHub (phone)", "auth": "oauth", "device": "My Pixel"}]
    r = client.put("/v1/me/profile", headers=auth, json={"device": "phone-1", "connectors": phone_conn})
    assert r.status_code == 200 and r.json()["rev"] == 2
    ids = [(c["device_id"], c["id"]) for c in client.get("/v1/me/profile", headers=auth).json()["connectors"]]
    assert ids == [("desk-1", "github"), ("desk-1", "weather"), ("phone-1", "github")]
    r = client.put("/v1/me/profile", headers=auth, json={"device": "desk-1", "connectors": [desk[0]]})
    assert r.status_code == 200 and r.json()["rev"] == 3
    after = client.get("/v1/me/profile", headers=auth).json()["connectors"]
    assert [(c["device_id"], c["id"], c["device"]) for c in after] == [("phone-1", "github", "My Pixel"), ("desk-1", "github", "desk-1")]
    # an empty list from the phone clears the phone's; the desk's stand
    r = client.put("/v1/me/profile", headers=auth, json={"device": "phone-1", "connectors": []})
    assert r.status_code == 200
    assert [c["device_id"] for c in client.get("/v1/me/profile", headers=auth).json()["connectors"]] == ["desk-1"]

    # the look and the connectors in one write; a look-only write leaves the connectors alone
    r = client.put(
        "/v1/me/profile",
        headers=auth,
        json={"device": "desk-1", "name": "小火", "avatar": "dragon", "connectors": [desk[1]]},
    )
    assert r.status_code == 200
    got = client.get("/v1/me/profile", headers=auth).json()
    assert got["name"] == "小火" and [c["id"] for c in got["connectors"]] == ["weather"]
    r = client.put("/v1/me/profile", headers=auth, json={"device": "phone-1", "name": "小火龙", "avatar": "dragon"})
    assert r.status_code == 200
    got = client.get("/v1/me/profile", headers=auth).json()
    assert got["name"] == "小火龙" and [c["id"] for c in got["connectors"]] == ["weather"]

    # never a credential: a key named like one, at any depth, is a 400 and nothing is stored
    for leak in (
        [{"id": "x", "auth": "key", "api_key": "sk-abc"}],
        [{"id": "x", "auth": "oauth", "token": "t"}],
        [{"id": "x", "auth": "oauth", "Authorization": "Bearer t"}],
        [{"id": "x", "auth": "open", "extra": {"password": "p"}}],
        [{"id": "x", "auth": "open", "extra": [{"client_secret": "s"}]}],
        # the address itself: a query, a user info or a fragment is where a key rides
        [{"id": "x", "auth": "key", "url": "https://mcp.example.net/sse?key=sk-abc"}],
        [{"id": "x", "auth": "key", "url": "https://user:sk-abc@mcp.example.net/sse"}],
        [{"id": "x", "auth": "key", "url": "https://mcp.example.net/sse#sk-abc"}],
    ):
        r = client.put("/v1/me/profile", headers=auth, json={"device": "desk-1", "connectors": leak})
        assert r.status_code == 400 and r.json()["error"]["code"] == "no_secrets_in_profile", leak
        assert "sk-abc" not in r.text and "Bearer t" not in r.text
    assert [c["id"] for c in client.get("/v1/me/profile", headers=auth).json()["connectors"]] == ["weather"]

    # the shape is checked too
    for bad in (
        [{"label": "no id", "auth": "open"}],
        [{"id": "x", "auth": "magic"}],
        [{"id": "x" * 65, "auth": "open"}],
        [{"id": "x", "auth": "open", "url": "not a url"}],
        [{"id": "x", "auth": "open", "at": "yesterday"}],
        [{"id": "x", "auth": "open", "enabled": "yes"}],
        [{"id": "x", "auth": "open", "device_id": "someone-else"}],
        ["github"],
        "github",
    ):
        r = client.put("/v1/me/profile", headers=auth, json={"device": "desk-1", "connectors": bad})
        assert r.status_code == 400 and r.json()["error"]["code"] == "bad_request", bad
    r = client.put("/v1/me/profile", headers=auth, json={"connectors": [desk[0]]})  # no device: whose would these be?
    assert r.status_code == 400

    # at most 64 on the account, after the merge
    many = [{"id": f"svc-{i}", "auth": "open"} for i in range(63)]
    assert client.put("/v1/me/profile", headers=auth, json={"device": "phone-1", "connectors": many}).status_code == 200
    r = client.put("/v1/me/profile", headers=auth, json={"device": "desk-1", "connectors": [desk[0], desk[1]]})
    assert r.status_code == 400 and r.json()["error"]["code"] == "too_many_connectors"
    assert client.put("/v1/me/profile", headers=auth, json={"device": "desk-1", "connectors": [desk[0]]}).status_code == 200
    assert len(client.get("/v1/me/profile", headers=auth).json()["connectors"]) == 64

    # DELETE clears the connectors with the look
    assert client.delete("/v1/me/profile", headers=auth).status_code == 204
    assert client.get("/v1/me/profile", headers=auth).json() == {
        "rev": 0,
        "updated_at": None,
        "device": "",
        "name": "",
        "avatar": "",
        "emoji": "",
        "color": "",
        "style": "",
        "description": "",
        "face": None,
        "clips": None,
        "connectors": [],
    }


def test_too_many_sockets_are_refused_before_the_hello_is_read(client, monkeypatch):
    """0.30: an address opening sockets faster than HELLOS_PER_MINUTE, or an account past
    MAX_ONLINE_PER_ACCOUNT devices, is closed with 4008 `too_many_connections`; a device
    taking its own place again is not a new one."""
    from nanomuse_cloud import hub as hub_mod
    from nanomuse_cloud.service import Pace

    # three sign-ins of one account: a key is one installation's credential
    pc_key, phone_key, laptop_key = (sign_up(client, "13800138000") for _ in range(3))
    hub = client.app.state.hub
    monkeypatch.setattr(hub_mod, "MAX_ONLINE_PER_ACCOUNT", 2)
    with connect(client, pc_key) as first:
        first.send_json(hello("computer", "pc-1", "desk"))
        first.receive_json()
        with connect(client, phone_key) as second:
            second.send_json(hello("phone", "ph-1", "pocket"))
            second.receive_json()
            with connect(client, laptop_key) as third:
                third.send_json(hello("computer", "pc-2", "laptop"))
                err = third.receive_json()
                assert err["type"] == "error" and err["code"] == "too_many_connections"
                with pytest.raises(WebSocketDisconnect) as closed:
                    third.receive_json()
                assert closed.value.code == 4008
            # the first device again, under its own id: a replacement, never a third
            with connect(client, pc_key) as again:
                again.send_json(hello("computer", "pc-1", "desk"))
                assert again.receive_json()["type"] == "welcome"
    assert hub.stats()["refused_connections"] == 1
    # the pace per address: the third socket in the window is closed with no hello read
    hub._hellos = Pace(2, 60.0)
    with connect(client, pc_key) as a, connect(client, phone_key) as b:
        a.send_json(hello("computer", "pc-1", "desk"))
        b.send_json(hello("phone", "ph-1", "pocket"))
        assert a.receive_json()["type"] == "welcome" and b.receive_json()["type"] == "welcome"
        with connect(client, laptop_key) as c:
            with pytest.raises(WebSocketDisconnect) as closed:
                c.receive_json()
            assert closed.value.code == 4008
    assert hub.stats()["refused_connections"] == 2


def test_session_keys_are_paced(client):
    from nanomuse_cloud.service import Cloud

    key = sign_up(client, "13800138001")
    for _ in range(Cloud.SESSION_KEYS_PER_HOUR):
        assert client.post("/v1/auth/session-key", headers={"Authorization": f"Bearer {key}"}, json={"device": "web"}).status_code == 200
    r = client.post("/v1/auth/session-key", headers={"Authorization": f"Bearer {key}"}, json={"device": "web"})
    assert r.status_code == 429 and r.json()["error"]["code"] == "rate_limited"


def _skip_devices(ws) -> dict:
    """The next frame that is not a `devices` broadcast (each arrival sends one to everyone)."""
    while True:
        frame = ws.receive_json()
        if frame["type"] != "devices":
            return frame


def test_a_pushed_event_reaches_the_devices_that_can_answer_it(client, monkeypatch):
    """0.31: an `event` with no id is a push: only `approval` and `approval_result` pass, only
    to devices of the account announcing `approve.any`, never back to the sender; each device
    may push so many a minute, each body so big."""
    from nanomuse_cloud import hub as hub_module
    from nanomuse_cloud.service import Pace

    a = sign_up(client, "13800138000")
    b = sign_up(client, "13900139000")
    keys = [sign_up(client, "13800138000") for _ in range(2)]
    with connect(client, a) as pc, connect(client, keys[0]) as phone, connect(client, keys[1]) as old, connect(client, b) as stranger:
        pc.send_json(hello("computer", "pc-1", "desk", actions=("info", "approve")))
        welcome = pc.receive_json()
        assert welcome["server"]["features"] == ["event_push"]
        phone.send_json(hello("phone", "phone-1", "Pixel", actions=("info", "approve", "approve.any")))
        assert _skip_devices(phone)["type"] == "welcome"
        old.send_json(hello("phone", "phone-2", "Old", actions=("info", "approve")))
        assert _skip_devices(old)["type"] == "welcome"
        stranger.send_json(hello("phone", "phone-9", "B's", actions=("info", "approve.any")))
        assert _skip_devices(stranger)["type"] == "welcome"

        card = {"stage": "approval", "approval_id": "ap_1", "preview": "Send the message", "any_device": True}
        pc.send_json({"type": "event", "to": "*", "body": card})
        assert _skip_devices(phone) == {"type": "event", "from": {"id": "pc-1", "name": "desk", "kind": "computer"}, "body": card}
        # the phone without approve.any, the other account and the sender hear nothing
        for ws in (old, stranger, pc):
            ws.send_json({"type": "ping"})
            assert _skip_devices(ws)["type"] == "pong"

        # another stage is dropped; the next push still goes through
        pc.send_json({"type": "event", "to": "*", "body": {"stage": "tool", "name": "shell"}})
        done = {"stage": "approval_result", "approval_id": "ap_1", "status": "approved", "by": {"id": "phone-1", "name": "Pixel"}}
        pc.send_json({"type": "event", "to": "*", "body": done})
        assert _skip_devices(phone)["body"] == done

        # one device by id: only when it announces approve.any
        pc.send_json({"type": "event", "to": "phone-2", "body": card})
        pc.send_json({"type": "event", "to": "phone-1", "body": card})
        assert _skip_devices(phone)["body"] == card
        old.send_json({"type": "ping"})
        assert _skip_devices(old)["type"] == "pong"

        # a body over the cap is refused to its sender
        monkeypatch.setattr(hub_module, "PUSH_BODY_BYTES", 100)
        pc.send_json({"type": "event", "to": "*", "body": {**card, "preview": "x" * 200}})
        assert _skip_devices(pc)["code"] == "too_large"

        # over the rate, a push is dropped with an error to its sender
        client.app.state.hub._pushes = Pace(1, 60.0)
        pc.send_json({"type": "event", "to": "*", "body": card})
        assert _skip_devices(phone)["body"] == card
        pc.send_json({"type": "event", "to": "*", "body": card})
        assert _skip_devices(pc)["code"] == "rate_limited"

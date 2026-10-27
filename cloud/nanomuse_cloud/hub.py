"""The hub: the devices of one account find each other here and pass requests
through, whatever network each of them is on.

Every device — a phone, a computer, a browser tab — keeps one WebSocket to
`/v1/hub`, opened outbound, so nothing has to be reachable from the outside.
The relay only forwards; it never runs anything itself and never sees a
command's approval, which is decided on the device that would carry it out.

Frames are JSON text. From a device:

    {"type":"hello", "key": "nm_…"?, "device": {"id","name","kind","os","version","actions":[…], "llm"?: {"provider","model"}}}
    {"type":"call",   "id","to","action","args"}         ask another device to do something
    {"type":"result", "id","ok", "body" | "error","message"}   the answer to a call received
    {"type":"event",  "id","body"}                        progress on a call still running
    {"type":"event",  "to","body"}                        no id: pushed to a device, or "*" (0.31)
    {"type":"devices"}  {"type":"rename","name"}  {"type":"forget","device_id"}  {"type":"ping"}

From the hub:

    {"type":"welcome","device_id","devices":[…],"server":{…}}
    {"type":"devices","devices":[…]}                      whenever a device comes or goes
    {"type":"call","id","from":{id,name,kind},"action","args"}
    {"type":"result", …}  {"type":"event", …}             forwarded to the caller
    {"type":"event","from","body"}                        a push from another device of the account (0.31)
    {"type":"error","code","message","id"?}               e.g. device_offline, not_controllable
    {"type":"pong"}
    {"type":"sync","what":"conversations","cursor","from"}  another device pushed chats; pull (0.19)
    {"type":"working","cid","from","device_name","working","at"}  a turn started or ended there (0.20)

`key` in hello is for browsers, which cannot set an Authorization header. A
`web` device is a front door only: it can call, it cannot be called. Devices of
the other kinds are remembered per account so the console can show them while
they are offline. Binary payloads (files, screenshots) travel base64-encoded
inside `body`, under the frame limit.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import uuid
from collections import deque
from dataclasses import dataclass, field

from fastapi import WebSocket, WebSocketDisconnect

from . import __version__
from . import client as _client
from .db import Database
from .service import Caller, Cloud, CloudError, Pace

log = logging.getLogger("nanomuse_cloud.hub")

KINDS = ("phone", "computer", "web")
HELLO_TIMEOUT_S = 15
CALL_TTL_S = 15 * 60
#: how long a finished call's result is kept for replay (docs/hub.md): a caller that
#: lost the connection after the answer reached the relay re-sends the same call id
#: and gets the kept answer instead of a second execution on the target
ANSWER_CACHE_TTL_S = 300
ANSWER_CACHE_MAX = 256
_ID = re.compile(r"^[A-Za-z0-9._:-]{4,80}$")

# What one socket may send: frames and bytes per second, sustained, with twice that as a
# burst (a screen being streamed at a few frames a second with pictures of a megabyte or
# two fits easily). Over it, frames are dropped with one `rate_limited` error a second;
# a socket that keeps flooding after that many dropped frames in a row is closed.
FRAMES_PER_S = 60.0
BYTES_PER_S = 8 * 1024 * 1024.0
FLOOD_CLOSE_AFTER = 600

# What the relay holds for one socket that is not reading: frames queued for it, and
# their bytes. A send never waits on the peer (so a slow phone cannot stall the computer
# calling it); past either bound the socket is closed with 4009 `slow_consumer` and the
# app reconnects with backoff. Dropping frames instead would lose calls and results
# without a word. 32 MiB is four seconds of the sustained rate above, or two frames of
# the largest size.
SEND_QUEUE_FRAMES = 512
SEND_QUEUE_BYTES = 32 * 1024 * 1024

# 0.30: what comes before the first frame is bounded too. One address may open this many
# sockets a minute (every device of a household reconnecting after the router came back
# fits several times over): over it, the socket is closed before any key is checked. One
# account may have this many sockets open at once (phones, computers, browser tabs): a
# further one is closed once its hello has named the account, before its device row is
# written. Both close with 4008 `too_many_connections`.
HELLOS_PER_MINUTE = 60
MAX_ONLINE_PER_ACCOUNT = 32

# 0.31: an `event` without an id is a push, not progress on a call: a computer's own approval
# card, sent to the devices that can answer it, and the word that it was answered. Only
# these stages pass; a push goes only to devices whose hello announces `approve.any`, so an
# older app never sees one. One device may push this many a minute, each body this big at
# most: `"*"` copies a frame to every device of the account.
PUSH_STAGES = ("approval", "approval_result")
APPROVE_ANY = "approve.any"
PUSHES_PER_MINUTE = 30
PUSH_BODY_BYTES = 16 * 1024
# what this relay understands beyond the frames every version has; `welcome.server.features`
FEATURES = ["event_push", "result_replay"]


class Bucket:
    """A token bucket: `rate` tokens a second, holding at most `burst`."""

    def __init__(self, rate: float, burst: float, clock=time.monotonic):
        self.rate = rate
        self.burst = burst
        self.clock = clock
        self.tokens = burst
        self.at = clock()

    def take(self, n: float = 1.0) -> bool:
        t = self.clock()
        self.tokens = min(self.burst, self.tokens + (t - self.at) * self.rate)
        self.at = t
        if self.tokens >= n:
            self.tokens -= n
            return True
        return False


def now() -> int:
    return int(time.time())


@dataclass
class Connection:
    ws: WebSocket
    account_id: str
    key_hash: str
    device_id: str
    name: str
    kind: str
    os: str = ""
    version: str = ""
    actions: list[str] = field(default_factory=list)
    ip: str = ""  # 0.10: where the socket came from, for the operator
    llm_provider: str = ""  # 0.28: what the device said it runs its chats under (ids only)
    llm_model: str = ""
    connected_at: int = field(default_factory=now)
    closed: bool = False
    # the outbound queue: send() appends, the writer task drains in order
    queue: deque[tuple[str, int]] = field(default_factory=deque)  # (frame, its UTF-8 size)
    queued_bytes: int = 0
    wake: asyncio.Event = field(default_factory=asyncio.Event)
    writer: asyncio.Task | None = None
    overflowed: bool = False  # closed for not reading fast enough
    closer: asyncio.Task | None = None  # the close of an overflowed socket, held until it is done
    frames: Bucket = field(default_factory=lambda: Bucket(FRAMES_PER_S, 2 * FRAMES_PER_S))
    bytes: Bucket = field(default_factory=lambda: Bucket(BYTES_PER_S, 2 * BYTES_PER_S))
    dropped: int = 0  # frames dropped in a row for flooding
    warned_at: float = 0.0

    def over_rate(self, size: int) -> bool:
        """Whether this frame is one too many (or too big a stream) for the moment."""
        if self.frames.take() and self.bytes.take(size):
            # the run of drops ends when the sender has eased off, not on the one frame a
            # trickle of refilled tokens lets through mid-flood
            if self.frames.tokens >= self.frames.burst / 2:
                self.dropped = 0
            return False
        self.dropped += 1
        return True

    def brief(self) -> dict:
        return {"id": self.device_id, "name": self.name, "kind": self.kind}

    def start(self) -> None:
        """Begin draining the queue to the socket; called once the connection is attached."""
        self.writer = asyncio.create_task(self._drain(), name=f"hub-writer:{self.device_id[:12]}")

    def stop(self) -> None:
        """No more frames: the writer task ends; what is still queued is dropped (the socket
        is being closed anyway)."""
        self.closed = True
        self.wake.set()
        if self.writer is not None and not self.writer.done():
            self.writer.cancel()

    async def send(self, frame: dict) -> None:
        """Queue a frame for the socket and return at once. Over SEND_QUEUE_FRAMES frames or
        SEND_QUEUE_BYTES bytes waiting, the peer is not reading: the socket is closed with
        4009 and the frame is not kept."""
        if self.closed:
            return
        text = json.dumps(frame, ensure_ascii=False, separators=(",", ":"))
        # bytes on the wire, not characters: a Chinese or emoji frame is three to four times
        # its character count in UTF-8, and the limits are stated in bytes
        size = len(text.encode("utf-8"))
        if len(self.queue) >= SEND_QUEUE_FRAMES or self.queued_bytes + size > SEND_QUEUE_BYTES:
            log.warning(
                "hub: %s is not reading (%d frames, %d bytes waiting); closing", self.device_id[:12], len(self.queue), self.queued_bytes
            )
            self.overflowed = True
            self.stop()
            # kept on the connection: a task nothing references may be collected before it runs
            self.closer = asyncio.get_running_loop().create_task(self._close(4009, "slow_consumer"))
            return
        self.queue.append((text, size))
        self.queued_bytes += size
        self.wake.set()

    async def _drain(self) -> None:
        while not self.closed:
            if not self.queue:
                self.wake.clear()
                await self.wake.wait()
                continue
            text, size = self.queue.popleft()
            self.queued_bytes -= size
            try:
                await self.ws.send_text(text)
            except Exception as e:  # the socket went away under us; the receive loop notices too
                log.debug("send to %s failed: %s", self.device_id[:12], e)
                self.closed = True

    async def _close(self, code: int, reason: str) -> None:
        try:
            await self.ws.close(code=code, reason=reason)
        except Exception as e:  # already gone
            log.debug("close %s: %s", self.device_id[:12], e)


@dataclass
class Pending:
    call_id: str
    caller: str
    target: str
    account_id: str
    started: int = field(default_factory=now)


@dataclass
class Answered:
    """A finished call's result, kept so a re-sent call id replays instead of
    re-executing. Bounded and short-lived: the cache is an idempotency aid for a
    caller that dropped, not a record of what happened."""

    call_id: str
    caller: str
    account_id: str
    frame: dict
    stored: int = field(default_factory=now)


class Hub:
    def __init__(self, cloud: Cloud, frame_limit: int = 16 * 1024 * 1024):
        self.cloud = cloud
        self.db: Database = cloud.db
        self.frame_limit = frame_limit
        self.online: dict[str, dict[str, Connection]] = {}
        # keyed (account, call id): ids are the callers' own and only unique within an account
        self.pending: dict[tuple[str, str], Pending] = {}
        # finished calls, for replay: the same key, plus the caller device that made it
        self.answered: dict[tuple[str, str], Answered] = {}
        # calls whose caller left before the answer: (account, call id) to the
        # caller, the target and when it was dropped, so a late answer from that
        # target is still kept for replay instead of refused as unknown
        self.dropped: dict[tuple[str, str], tuple[str, str, int]] = {}
        # for the operator's self-check: frames dropped and sockets closed for flooding, ever
        self.dropped_total = 0
        self.flood_closes = 0
        # ... and sockets closed because they stopped reading (SEND_QUEUE_*)
        self.slow_closes = 0
        # ... and sockets refused before their hello: an address opening too many, an
        # account with too many open (0.30)
        self.refused_connections = 0
        self._hellos = Pace(HELLOS_PER_MINUTE, 60.0)
        self._pushes = Pace(PUSHES_PER_MINUTE, 60.0)

    # -- presence -------------------------------------------------------------------

    def online_count(self) -> int:
        """Sockets open right now, across every account (the operator's page)."""
        return sum(len(v) for v in self.online.values())

    def stats(self) -> dict:
        """Aggregates for the operator's self-check: nothing about any one account."""
        return {
            "online": self.online_count(),
            "accounts_online": sum(1 for v in self.online.values() if v),
            "pending_calls": len(self.pending),
            "answered_cache": len(self.answered),
            "dropped_frames": self.dropped_total,
            "flood_closes": self.flood_closes,
            "slow_closes": self.slow_closes,
            "refused_connections": self.refused_connections,
        }

    def devices(self, account_id: str) -> list[dict]:
        """Remembered devices with their presence, then the browser tabs, newest first."""
        live = self.online.get(account_id, {})
        out: list[dict] = []
        seen: set[str] = set()
        for row in self.db.devices_for(account_id):
            c = live.get(row["id"])
            seen.add(row["id"])
            out.append(
                {
                    "id": row["id"],
                    "name": c.name if c else row["name"],
                    "kind": row["kind"],
                    "os": c.os if c else row["os"],
                    "version": c.version if c else row["version"],
                    "actions": c.actions if c else json.loads(row["actions"] or "[]"),
                    "online": c is not None,
                    "last_seen": now() if c else int(row["last_seen"]),
                    "controllable": row["kind"] != "web",
                    "ip": (c.ip if c else "") or row["ip"],
                }
            )
        for c in live.values():
            if c.device_id in seen:
                continue
            out.append(
                {
                    "id": c.device_id,
                    "name": c.name,
                    "kind": c.kind,
                    "os": c.os,
                    "version": c.version,
                    "actions": c.actions,
                    "online": True,
                    "last_seen": now(),
                    "controllable": c.kind != "web",
                    "ip": c.ip,
                }
            )
        out.sort(key=lambda d: (not d["online"], d["kind"] == "web", -d["last_seen"]))
        return out

    async def broadcast_devices(self, account_id: str) -> None:
        conns = list(self.online.get(account_id, {}).values())
        if not conns:
            return
        frame = {"type": "devices", "devices": self.devices(account_id)}
        await asyncio.gather(*(c.send(frame) for c in conns))

    async def broadcast_profile(self, account_id: str, rev: int, device: str) -> None:
        """The account's name or look changed: every connected device of it hears the new
        rev (and who wrote it, so the writer skips its own echo) and fetches the profile."""
        conns = list(self.online.get(account_id, {}).values())
        if not conns:
            return
        frame = {"type": "profile", "rev": rev, "device": device}
        await asyncio.gather(*(c.send(frame) for c in conns))

    async def notify_sync(self, account_id: str, cursor: int, from_device: str) -> None:
        """0.19: a device pushed conversation changes; every *other* connected device of the
        account hears the new cursor and pulls what it is missing (sync.py)."""
        conns = [c for c in self.online.get(account_id, {}).values() if c.device_id != from_device]
        if not conns:
            return
        frame = {"type": "sync", "what": "conversations", "cursor": int(cursor), "from": from_device}
        await asyncio.gather(*(c.send(frame) for c in conns))

    async def notify_working(self, account_id: str, body: dict) -> None:
        """0.20: a device said it is working (or done) on a synced conversation; every *other*
        connected device of the account hears it and shows or clears the line under the
        message. `body` is what sync.Presence.set returned: cid, from, device_name, working, at."""
        conns = [c for c in self.online.get(account_id, {}).values() if c.device_id != str(body.get("from") or "")]
        if not conns:
            return
        frame = {"type": "working", **body}
        await asyncio.gather(*(c.send(frame) for c in conns))

    def forget(self, account_id: str, device_id: str) -> None:
        if device_id in self.online.get(account_id, {}):
            raise CloudError(409, "device_online", "That device is connected right now; sign it out there first")
        self.db.forget_device(account_id, device_id)

    async def drop_account(self, account_id: str) -> None:
        """When an account is deleted or disabled: every socket of it is closed
        (the receive loops then remove themselves) so no device keeps a live line."""
        for c in list(self.online.get(account_id, {}).values()):
            c.stop()
            await c._close(4001, "account_gone")

    async def drop_signed_out(self, account_id: str) -> int:
        """After a sign-out (this device, every other device, one session revoked on the
        account page): every socket of the account whose key no longer opens is closed with
        4001 bad_key, so a device signed out from elsewhere, a lost phone say, loses its live
        line now and not at its next reconnect. Returns how many were closed."""
        n = 0
        for c in list(self.online.get(account_id, {}).values()):
            if self.cloud.key_live(c.key_hash):
                continue
            await c._close(4001, "bad_key")
            # off the account's list now, not when its receive loop notices the close: the
            # other devices hear it left and a call it was carrying out fails as offline
            await self._detach(c)
            n += 1
        return n

    async def drop_all(self, reason: str = "hub_paused") -> int:
        """0.22: the operator turned the hub (or the whole service) off — every socket is
        closed with 4003 and the reason; the apps reconnect with backoff and are refused
        with the same code until it is on again. Returns how many were closed."""
        n = 0
        for conns in list(self.online.values()):
            for c in list(conns.values()):
                c.stop()
                n += 1
                await c._close(4003, reason)
        return n

    # -- one socket ------------------------------------------------------------------

    async def serve(self, ws: WebSocket, caller: Caller | None) -> None:
        """The whole life of one connection: hello, then frames until it drops."""
        await ws.accept()
        ip = _client.current().ip
        if ip and not self._hellos.allow(ip):
            self.refused_connections += 1
            log.info("hub: over %d sockets a minute from one address; refused", HELLOS_PER_MINUTE)
            await self._close(ws, 4008, "too_many_connections")
            return
        try:
            raw = await asyncio.wait_for(ws.receive_text(), HELLO_TIMEOUT_S)
        except (TimeoutError, WebSocketDisconnect, KeyError):
            # KeyError: a binary frame — Starlette's receive_text has no text to give
            await self._close(ws, 4000, "hello expected")
            return
        hello = _loads(raw)
        if not isinstance(hello, dict) or hello.get("type") != "hello":
            await self._close(ws, 4000, "hello expected")
            return
        if caller is None:
            try:
                caller = self.cloud.authenticate(str(hello.get("key") or ""))
            except CloudError as e:
                await ws.send_text(json.dumps({"type": "error", "code": e.code, "message": e.message}))
                await self._close(ws, 4001, e.code)
                return
        dev = hello.get("device") if isinstance(hello.get("device"), dict) else {}
        try:
            conn = self._connection(ws, caller, dev)
        except CloudError as e:
            await ws.send_text(json.dumps({"type": "error", "code": e.code, "message": e.message}))
            await self._close(ws, 4002, e.code)
            return
        live = self.online.get(conn.account_id, {})
        if conn.device_id not in live and len(live) >= MAX_ONLINE_PER_ACCOUNT:
            # a device taking its own place again is fine; a thirty-third is not
            self.refused_connections += 1
            log.info("hub: account %s has %d devices connected; one more refused", conn.account_id[:8], len(live))
            await ws.send_text(
                json.dumps(
                    {
                        "type": "error",
                        "code": "too_many_connections",
                        "message": f"At most {MAX_ONLINE_PER_ACCOUNT} devices of one account are connected at once",
                    }
                )
            )
            await self._close(ws, 4008, "too_many_connections")
            return

        await self._attach(conn)
        try:
            await conn.send(
                {
                    "type": "welcome",
                    "device_id": conn.device_id,
                    "devices": self.devices(conn.account_id),
                    "server": {"version": __version__, "frame_limit": self.frame_limit, "time": now(), "features": FEATURES},
                }
            )
            await self.broadcast_devices(conn.account_id)
            while True:
                try:
                    raw = await ws.receive_text()
                except (WebSocketDisconnect, RuntimeError):
                    # RuntimeError: Starlette's WebSocketDisconnected, when the socket was closed
                    # under this loop (the same device connected again and took its place)
                    break
                except KeyError:
                    # a binary frame: Starlette's receive_text has no text to give. The protocol
                    # is JSON text (docs/hub.md); below it is answered with bad_frame and the
                    # socket stays open — it still counts towards the flood limit.
                    raw = None
                size = len(raw.encode("utf-8")) if raw is not None else 0
                if raw is not None and size > self.frame_limit:
                    await conn.send({"type": "error", "code": "too_large", "message": f"Frames are capped at {self.frame_limit} bytes"})
                    continue
                if conn.over_rate(size):
                    self.dropped_total += 1
                    if conn.dropped >= FLOOD_CLOSE_AFTER:
                        self.flood_closes += 1
                        log.warning("hub: %s flooded the hub; closing", conn.device_id[:12])
                        await self._close(ws, 4008, "too many frames")
                        break
                    t = time.monotonic()
                    if t - conn.warned_at >= 1.0:
                        conn.warned_at = t
                        await conn.send(
                            {
                                "type": "error",
                                "code": "rate_limited",
                                "message": f"At most {FRAMES_PER_S:.0f} frames and {BYTES_PER_S / 1048576:.0f} MB a second; this frame was dropped",
                            }
                        )
                    continue
                if raw is None:
                    await conn.send({"type": "error", "code": "bad_frame", "message": "Frames are JSON text, not binary"})
                    continue
                frame = _loads(raw)
                if not isinstance(frame, dict):
                    await conn.send({"type": "error", "code": "bad_frame", "message": "Frames are JSON objects"})
                    continue
                await self.route(conn, frame)
        finally:
            await self._detach(conn)

    def _connection(self, ws: WebSocket, caller: Caller, dev: dict) -> Connection:
        kind = str(dev.get("kind") or "")
        if kind not in KINDS:
            raise CloudError(400, "bad_device", "kind must be phone, computer or web")
        device_id = str(dev.get("id") or "")
        if caller.hub_device_id:
            # A credential is an installation identity, not an account-wide bearer.
            # Browser clients may continue to omit their server-assigned id on reconnect.
            if kind != caller.hub_device_kind:
                raise CloudError(400, "bad_device", "This credential belongs to another device kind")
            if kind == "web" and not device_id:
                device_id = caller.hub_device_id
            if device_id != caller.hub_device_id:
                raise CloudError(400, "bad_device", "This credential belongs to another device id")
        elif kind == "web" and not device_id:
            device_id = "web-" + uuid.uuid4().hex[:12]
        if not _ID.match(device_id):
            raise CloudError(400, "bad_device", "device id: 4–80 letters, digits, . _ : -")
        if not caller.hub_device_id and not self.db.bind_key_to_hub_device(caller.key_hash, caller.account_id, device_id, kind):
            # An unbound credential (issued by an older relay, or to a client that does not
            # send its identity at sign-in yet) registers its identity at its first hello.
            # It takes an id another live key holds only when it comes from a later code or
            # password sign-in on that installation; a session key never does.
            raise CloudError(400, "bad_device", "That device id belongs to another credential")
        name = str(dev.get("name") or "").strip()[:60] or {"phone": "Phone", "computer": "Computer", "web": "Browser"}[kind]
        actions = [str(a)[:40] for a in dev.get("actions") or [] if isinstance(a, str)][:64]
        # 0.28: optionally, which provider and model the device runs its chats under (a
        # key of the person's own, or "nanomuse" for the relay) — two ids, never a key;
        # the console counts them in aggregate (docs/hub.md, docs/privacy.md)
        llm = dev.get("llm") if isinstance(dev.get("llm"), dict) else {}
        llm_provider, llm_model = _llm_ids(llm)
        return Connection(
            ws=ws,
            account_id=caller.account_id,
            key_hash=caller.key_hash,
            device_id=device_id,
            name=name,
            kind=kind,
            os=str(dev.get("os") or "")[:60],
            version=str(dev.get("version") or "")[:40],
            actions=actions,
            ip=_client.current().ip,
            llm_provider=llm_provider,
            llm_model=llm_model,
        )

    async def _attach(self, conn: Connection) -> None:
        account = self.online.setdefault(conn.account_id, {})
        old = account.get(conn.device_id)
        if old is not None:
            old.stop()
            await self._close(old.ws, 4003, "replaced by a newer connection")
        account[conn.device_id] = conn
        conn.start()
        if conn.kind != "web":
            self.db.upsert_device(
                conn.account_id,
                conn.device_id,
                conn.name,
                conn.kind,
                conn.os,
                conn.version,
                json.dumps(conn.actions),
                conn.llm_provider,
                conn.llm_model,
            )
        # the id and the account masked like every other line; the device's name is the
        # person's own words and stays out of the log
        log.info("hub: %s %s connected; account %s has %d online", conn.kind, conn.device_id[:12], conn.account_id[:8], len(account))

    async def _detach(self, conn: Connection) -> None:
        conn.stop()
        if conn.overflowed:
            self.slow_closes += 1
        account = self.online.get(conn.account_id, {})
        if account.get(conn.device_id) is conn:
            del account[conn.device_id]
            if not account:
                self.online.pop(conn.account_id, None)
            if conn.kind != "web":
                self.db.touch_device(conn.account_id, conn.device_id)
            log.info("hub: %s %s left; account %s", conn.kind, conn.device_id[:12], conn.account_id[:8])
            await self._fail_pending_for(conn)
            await self.broadcast_devices(conn.account_id)

    async def _fail_pending_for(self, gone: Connection) -> None:
        """A device left: every call it was carrying out is answered `device_offline`; calls it made are dropped."""
        for key, p in list(self.pending.items()):
            if p.account_id != gone.account_id:
                continue
            if p.target == gone.device_id:
                del self.pending[key]
                caller = self.online.get(p.account_id, {}).get(p.caller)
                if caller:
                    await caller.send(
                        {
                            "type": "error",
                            "id": p.call_id,
                            "code": "device_offline",
                            "message": f"{gone.name} disconnected before answering",
                        }
                    )
            elif p.caller == gone.device_id:
                del self.pending[key]
                # The target may still answer: remember the call briefly so its
                # late result is kept for the caller when it comes back.
                self.dropped[key] = (p.caller, p.target, now())
                while len(self.dropped) > ANSWER_CACHE_MAX:
                    oldest = min(self.dropped.items(), key=lambda kv: kv[1][2])[0]
                    del self.dropped[oldest]

    @staticmethod
    async def _close(ws: WebSocket, code: int, reason: str) -> None:
        try:
            await ws.close(code=code, reason=reason)
        except Exception:
            pass

    # -- routing -----------------------------------------------------------------------

    async def route(self, conn: Connection, frame: dict) -> None:
        kind = frame.get("type")
        if kind == "ping":
            await conn.send({"type": "pong", "time": now()})
            # every client pings; a caller with one call outstanding and nothing more to
            # ask would otherwise never hear `timeout` (the sweep ran on new calls only)
            await self._sweep()
        elif kind == "devices":
            await conn.send({"type": "devices", "devices": self.devices(conn.account_id)})
        elif kind == "call":
            await self._call(conn, frame)
        elif kind == "event" and not frame.get("id"):
            await self._push(conn, frame)
        elif kind in ("result", "event"):
            await self._answer(conn, frame)
        elif kind == "rename":
            name = str(frame.get("name") or "").strip()[:60]
            if name:
                conn.name = name
                if conn.kind != "web":
                    self.db.upsert_device(
                        conn.account_id,
                        conn.device_id,
                        name,
                        conn.kind,
                        conn.os,
                        conn.version,
                        json.dumps(conn.actions),
                        conn.llm_provider,
                        conn.llm_model,
                    )
                await self.broadcast_devices(conn.account_id)
        elif kind == "forget":
            try:
                self.forget(conn.account_id, str(frame.get("device_id") or ""))
            except CloudError as e:
                await conn.send({"type": "error", "code": e.code, "message": e.message})
                return
            await self.broadcast_devices(conn.account_id)
        else:
            await conn.send({"type": "error", "code": "bad_frame", "message": f"Unknown frame type {kind!r}"})

    async def _call(self, conn: Connection, frame: dict) -> None:
        call_id = str(frame.get("id") or "")
        to = str(frame.get("to") or "")
        action = str(frame.get("action") or "")
        if not call_id or not to or not action:
            await conn.send({"type": "error", "id": call_id, "code": "bad_frame", "message": "call needs id, to and action"})
            return
        target = self.online.get(conn.account_id, {}).get(to)
        if target is None or target.closed:
            await conn.send({"type": "error", "id": call_id, "code": "device_offline", "message": "That device is not connected"})
            return
        if target.kind == "web":
            await conn.send(
                {"type": "error", "id": call_id, "code": "not_controllable", "message": "A browser tab cannot be asked to do things"}
            )
            return
        if target is conn:
            await conn.send({"type": "error", "id": call_id, "code": "self_call", "message": "That is this device"})
            return
        await self._sweep()
        # A new call with this id supersedes the dropped one: a late answer to
        # the old call must not be kept as this call's result.
        self.dropped.pop((conn.account_id, call_id), None)
        answered = self.answered.get((conn.account_id, call_id))
        if answered is not None:
            if frame.get("retry") and answered.caller == conn.device_id and now() - answered.stored < ANSWER_CACHE_TTL_S:
                # The caller says this is a retry of the call it lost: the answer
                # already reached the relay, so replay the kept result and the
                # target never sees the call a second time.
                await conn.send(dict(answered.frame))
                return
            # A plain re-send is a new call with a recycled id (the old contract:
            # an answered id is free again), and it supersedes the kept answer.
            del self.answered[(conn.account_id, call_id)]
        if (conn.account_id, call_id) in self.pending:
            # the id of a call still waiting: a second one would take its place and the first
            # answer would land on the wrong call (or on none). Ids are the caller's to make
            # unique; this one is refused and the first call goes on.
            await conn.send({"type": "error", "id": call_id, "code": "duplicate_call", "message": "A call with that id is still waiting"})
            return
        self.pending[(conn.account_id, call_id)] = Pending(call_id=call_id, caller=conn.device_id, target=to, account_id=conn.account_id)
        args = frame.get("args") if isinstance(frame.get("args"), dict) else {}
        await target.send({"type": "call", "id": call_id, "from": conn.brief(), "action": action, "args": args})

    async def _answer(self, conn: Connection, frame: dict) -> None:
        call_id = str(frame.get("id") or "")
        p = self.pending.get((conn.account_id, call_id))
        if p is None:
            dropped = self.dropped.get((conn.account_id, call_id))
            if (
                dropped is not None
                and frame.get("type") == "result"
                and dropped[1] == conn.device_id
                and now() - dropped[2] < ANSWER_CACHE_TTL_S
            ):
                # The caller left before this answer arrived: keep it, so the
                # caller reconnecting and retrying the id gets it replayed.
                del self.dropped[(conn.account_id, call_id)]
                ghost = Pending(call_id=call_id, caller=dropped[0], target=dropped[1], account_id=conn.account_id)
                out = {k: v for k, v in frame.items() if k in ("type", "id", "ok", "body", "error", "message")}
                out["from"] = conn.brief()
                self._remember_answer(ghost, out)
                return
            # Unknown or not this device's call: nothing to deliver to. Tell the sender once.
            await conn.send(
                {"type": "error", "id": call_id, "code": "unknown_call", "message": "No call with that id is waiting on this device"}
            )
            return
        if p.target != conn.device_id:
            await conn.send(
                {"type": "error", "id": call_id, "code": "unknown_call", "message": "No call with that id is waiting on this device"}
            )
            return
        caller = self.online.get(p.account_id, {}).get(p.caller)
        if frame.get("type") == "result":
            del self.pending[(conn.account_id, call_id)]
        out = {k: v for k, v in frame.items() if k in ("type", "id", "ok", "body", "error", "message")}
        out["from"] = conn.brief()
        if frame.get("type") == "result":
            # Kept even when the caller has already left: it may come back and
            # re-send the same id, and the kept answer is what stops a second run.
            self._remember_answer(p, out)
        if caller is None:
            return
        await caller.send(out)

    def _remember_answer(self, pending: Pending, frame: dict) -> None:
        """Keep a finished result for replay, bounded in count and time. The frame is
        copied: the caller's queue must not be able to mutate the kept answer."""
        key = (pending.account_id, pending.call_id)
        self.answered[key] = Answered(
            call_id=pending.call_id,
            caller=pending.caller,
            account_id=pending.account_id,
            frame=dict(frame),
        )
        cutoff = now() - ANSWER_CACHE_TTL_S
        for old_key, old in list(self.answered.items()):
            if old.stored < cutoff:
                del self.answered[old_key]
        while len(self.answered) > ANSWER_CACHE_MAX:
            oldest = min(self.answered.items(), key=lambda kv: kv[1].stored)[0]
            del self.answered[oldest]

    async def _push(self, conn: Connection, frame: dict) -> None:
        """An event with no call behind it, to one device or to every device of the account
        (`"*"`) that announces `approve.any`; never back to the sender."""
        body = frame.get("body") if isinstance(frame.get("body"), dict) else {}
        stage = body.get("stage")
        if stage not in PUSH_STAGES:
            log.info("hub: %s pushed an event of stage %r; dropped", conn.device_id[:12], str(stage)[:40])
            return
        if len(json.dumps(body, ensure_ascii=False).encode("utf-8")) > PUSH_BODY_BYTES:
            await conn.send(
                {"type": "error", "code": "too_large", "message": f"A pushed event's body is capped at {PUSH_BODY_BYTES} bytes"}
            )
            return
        if not self._pushes.allow(f"{conn.account_id}:{conn.device_id}"):
            await conn.send(
                {
                    "type": "error",
                    "code": "rate_limited",
                    "message": f"At most {PUSHES_PER_MINUTE} pushed events a minute; this one was dropped",
                }
            )
            return
        to = str(frame.get("to") or "")
        targets = [
            c
            for c in self.online.get(conn.account_id, {}).values()
            if c is not conn and not c.closed and APPROVE_ANY in c.actions and (to == "*" or c.device_id == to)
        ]
        out = {"type": "event", "from": conn.brief(), "body": body}
        for target in targets:
            await target.send(out)

    async def _sweep(self) -> None:
        """Calls nobody answered in time are dropped, and the caller hears so instead of waiting for its own clock."""
        cutoff = now() - CALL_TTL_S
        for key, p in list(self.pending.items()):
            if p.started < cutoff:
                del self.pending[key]
                caller = self.online.get(p.account_id, {}).get(p.caller)
                if caller:
                    await caller.send({"type": "error", "id": p.call_id, "code": "timeout", "message": "the device did not answer in time"})
        answer_cutoff = now() - ANSWER_CACHE_TTL_S
        for key, answered in list(self.answered.items()):
            if answered.stored < answer_cutoff:
                del self.answered[key]
        for key, (_, _, dropped_at) in list(self.dropped.items()):
            if dropped_at < answer_cutoff:
                del self.dropped[key]


_LLM_ID = re.compile(r"^[A-Za-z0-9._:/ -]{1,80}$")


def _llm_ids(llm: dict) -> tuple[str, str]:
    """The provider and model ids a hello's ``device.llm`` names, each a plain id (letters,
    digits, ``. _ : / -``) or nothing; anything shaped like a secret, a URL or a sentence
    is dropped rather than kept."""
    out = []
    for key, limit in (("provider", 60), ("model", 80)):
        v = str(llm.get(key) or "").strip()
        out.append(v[:limit] if v and len(v) <= limit and _LLM_ID.match(v) and "://" not in v else "")
    return out[0], out[1]


def _loads(raw: str):
    try:
        return json.loads(raw)
    except ValueError:
        return None

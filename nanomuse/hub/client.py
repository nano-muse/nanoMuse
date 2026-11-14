"""The runtime's end of the hub: one WebSocket to the relay, kept up; calls in, calls out,
and the account's device list as it changes. The frames are in docs/hub.md.

An asyncio port of the standard-library binary's ``hub.py``: the same ``hello`` /
``call`` / ``event`` / ``result`` exchange, reconnecting with backoff, refusing to hammer a
relay that said the key or the device is bad (close codes 4001 / 4002).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import platform
import re
import ssl
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed, InvalidStatus, InvalidURI

from nanomuse import __version__
from nanomuse.logger import logger

PING_EVERY_S = 25.0
MAX_FRAME = 16 * 1024 * 1024
TASK_CALL_TIMEOUT_S = 15 * 60
TASK_STOP_TIMEOUT_S = 15.0
#: a provider or model id as `hello` may carry it: no URL, no key, no space
_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9.:/_-]{0,79}")


class HubError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class IncomingCall:
    """A call another device made to this one; answer it exactly once."""

    id: str
    sender: dict[str, Any]
    action: str
    args: dict[str, Any]
    _client: HubClient
    answered: bool = False

    @property
    def sender_name(self) -> str:
        return str(self.sender.get("name") or self.sender.get("id") or "a device")

    @property
    def sender_id(self) -> str:
        return str(self.sender.get("id") or "")

    async def event(self, body: dict[str, Any]) -> None:
        if not self.answered:
            await self._client._send({"type": "event", "id": self.id, "body": body})

    async def result(self, body: dict[str, Any]) -> None:
        if not self.answered:
            self.answered = True
            await self._client._send({"type": "result", "id": self.id, "ok": True, "body": body})

    async def fail(self, code: str, message: str, **extra: Any) -> None:
        if not self.answered:
            self.answered = True
            await self._client._send(
                {
                    "type": "result",
                    "id": self.id,
                    "ok": False,
                    "error": code,
                    "message": message,
                    "body": extra or {},
                }
            )


@dataclass
class _Pending:
    done: asyncio.Future[dict[str, Any]]
    on_event: Callable[[dict[str, Any]], Awaitable[None]] | None = None
    tasks: set[asyncio.Task[None]] = field(default_factory=set)


OnCall = Callable[[IncomingCall], Awaitable[None]]
OnDevices = Callable[[list[dict[str, Any]]], None]
OnState = Callable[[str, str], None]
# the account's profile (name and look) changed on the relay: the frame, with its rev
OnProfile = Callable[[dict[str, Any]], None]
# another device pushed conversations (contract C7): the frame, with the relay's cursor;
# or said it is working on one (C9): the `working` frame
OnSync = Callable[[dict[str, Any]], None]


class HubClient:
    def __init__(
        self,
        url: str,
        api_key: str,
        device_id: str,
        name: str,
        actions: list[str],
        kind: str = "computer",
        on_call: OnCall | None = None,
        on_devices: OnDevices | None = None,
        on_state: OnState | None = None,
        on_profile: OnProfile | None = None,
        on_sync: OnSync | None = None,
        llm: Callable[[], tuple[str, str]] | None = None,
    ):
        self.url = url
        self.api_key = api_key
        self.device_id = device_id
        self.name = name
        self.kind = kind
        self.actions = actions
        # the ids this device runs its chat model under, asked for at each hello (relay
        # 0.28, `device.llm`): a provider id and a model id, plain, never a key or a URL
        self._llm = llm
        self.on_call = on_call
        self.on_devices = on_devices
        self.on_state = on_state
        self.on_profile = on_profile
        self.on_sync = on_sync
        self.devices: list[dict[str, Any]] = []
        self.connected = asyncio.Event()
        self.state = "stopped"
        self.state_detail = ""
        self.last_error = ""
        self._ws: Any = None
        self._pending: dict[str, _Pending] = {}
        self._task: asyncio.Task[None] | None = None
        self._calls: set[asyncio.Task[None]] = set()
        self._stop = asyncio.Event()

    # ------------------------------------------------------------------ lifecycle
    def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._run(), name="hub")

    async def stop(self) -> None:
        self._stop.set()
        ws = self._ws
        if ws is not None:
            with contextlib.suppress(Exception):
                await ws.close(1000, "bye")
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._task
            self._task = None
        handlers = [t for t in self._calls if not t.done()]
        for t in handlers:
            t.cancel()
        if handlers:
            # a handler may be mid-action, or about to answer: it gets a moment to wind
            # down before the services it uses are closed behind it
            with contextlib.suppress(BaseException):
                await asyncio.wait_for(asyncio.gather(*handlers, return_exceptions=True), 5)
        self._calls.clear()
        self._fail_all("closed", "the hub connection was closed")
        self._set_state("stopped")

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    def llm_ids(self) -> tuple[str, str] | None:
        """What `hello` says of the model: ``(provider, model)`` when both are plain ids
        (letters, digits and ``.:/_-``, 80 characters at most), else nothing. A URL, a key
        or anything with a space or a query in it is not an id and is not sent."""
        if self._llm is None:
            return None
        try:
            provider, model = self._llm()
        except Exception:  # noqa: BLE001 - the hello goes out either way
            return None
        for value in (provider, model):
            if not _ID_RE.fullmatch(value or "") or "://" in value:
                return None
        return provider, model

    def _set_state(self, state: str, detail: str = "") -> None:
        self.state, self.state_detail = state, detail
        if self.on_state is not None:
            try:
                self.on_state(state, detail)
            except Exception:  # noqa: BLE001
                logger.exception("hub on_state")

    async def _run(self) -> None:
        delay = 1.0
        while not self._stop.is_set():
            refused = False  # a bad key, a paused hub, a certificate: a minute, not a backoff
            try:
                await self._session()
                delay = 1.0
                if not self._stop.is_set():
                    # the socket closed without an error (the relay restarting, an idle
                    # close): the state says so until the next session is up
                    self._set_state("disconnected", "the connection closed")
            except ConnectionClosed as exc:
                self.last_error = str(exc)
                code = exc.rcvd.code if exc.rcvd else None
                reason = (exc.rcvd.reason if exc.rcvd else "") or ""
                if code in (4001, 4002):  # bad key, bad device: no point retrying quickly
                    self._set_state("refused", reason or str(code))
                    refused = True
                elif code == 4003 and reason == "hub_paused":
                    # the operator switched the hub off (docs/hub.md): wait, do not hammer
                    self._set_state("disconnected", "the relay's hub is paused")
                    refused = True
                else:
                    self._set_state("disconnected", str(exc))
            except InvalidStatus as exc:
                self.last_error = str(exc)
                status = exc.response.status_code
                if status in (401, 403):
                    self._set_state("refused", f"HTTP {status}")
                    refused = True
                else:
                    self._set_state("disconnected", f"HTTP {status}")
            except ssl.SSLCertVerificationError as exc:
                # (a ValueError too — it must not read as the hub refusing the device)
                self.last_error = str(exc)
                self._set_state(
                    "disconnected",
                    f"the relay's certificate could not be verified here: {exc.verify_message or exc}",
                )
                refused = True
            except (InvalidURI, ValueError) as exc:
                self.last_error = str(exc)
                self._set_state("refused", str(exc))
                return
            except asyncio.CancelledError:
                raise
            except (TimeoutError, OSError) as exc:
                self.last_error = str(exc)
                self._set_state("disconnected", str(exc))
            except Exception as exc:  # noqa: BLE001 — keep the loop alive whatever happened
                self.last_error = str(exc)
                logger.exception("hub session")
                self._set_state("disconnected", str(exc))
            finally:
                self.connected.clear()
                self._fail_all("disconnected", "the hub connection dropped")
                # the calls this session was carrying out can answer nobody now: the relay
                # told their callers `device_offline` the moment the socket went. A side
                # chat a `task` started runs on in its thread (it is the person's own and
                # syncs); what stops is the following and answering of it.
                for t in [t for t in self._calls if not t.done()]:
                    t.cancel()
            if self._stop.is_set():
                break
            if refused:
                # a minute every time, as docs/hub.md says; the network's backoff below
                # starts over once the relay lets the device in again
                delay = 60.0
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(self._stop.wait(), delay)
            delay = 1.0 if refused else min(delay * 2, 30.0)

    async def _session(self) -> None:
        self._set_state("connecting", self.url)
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "User-Agent": f"nanoMuse/{__version__} ({platform.system()})",
        }
        async with connect(
            self.url,
            additional_headers=headers,
            max_size=MAX_FRAME,
            ping_interval=20,
            ping_timeout=20,
            open_timeout=20,
        ) as ws:
            self._ws = ws
            device: dict[str, Any] = {
                "id": self.device_id,
                "name": self.name,
                "kind": self.kind,
                "os": f"{platform.system()} {platform.release()}".strip(),
                "version": __version__,
                "actions": self.actions,
            }
            llm = self.llm_ids()
            if llm is not None:
                device["llm"] = {"provider": llm[0], "model": llm[1]}
            await ws.send(json.dumps({"type": "hello", "device": device}, ensure_ascii=False))
            pinger = asyncio.create_task(self._pinger(ws), name="hub-ping")
            try:
                async for raw in ws:
                    if self._stop.is_set():
                        break
                    try:
                        frame = json.loads(raw)
                    except ValueError:
                        continue
                    if isinstance(frame, dict):
                        self._on_frame(frame)
            finally:
                pinger.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await pinger
                self._ws = None

    async def _pinger(self, ws: Any) -> None:
        while not self._stop.is_set():
            await asyncio.sleep(PING_EVERY_S)
            try:
                await ws.send('{"type":"ping"}')
            except ConnectionClosed:
                return

    # ------------------------------------------------------------------ frames
    def _on_frame(self, frame: dict[str, Any]) -> None:
        kind = frame.get("type")
        if kind == "welcome":
            self.devices = list(frame.get("devices") or [])
            self.connected.set()
            self._set_state("connected", str(frame.get("device_id") or self.device_id))
            self._devices_changed()
        elif kind == "devices":
            self.devices = list(frame.get("devices") or [])
            self._devices_changed()
        elif kind == "profile":
            if self.on_profile is not None:
                try:
                    self.on_profile(frame)
                except Exception:  # noqa: BLE001
                    logger.exception("hub on_profile")
        elif kind in ("sync", "working"):
            # another device pushed conversations (contract C7): the engine pulls; or a turn
            # started or ended there (C9 `working`): the engine notes who is working
            if self.on_sync is not None:
                try:
                    self.on_sync(frame)
                except Exception:  # noqa: BLE001
                    logger.exception("hub on_sync")
        elif kind == "call":
            call = IncomingCall(
                id=str(frame.get("id") or ""),
                sender=_dict(frame.get("from")),
                action=str(frame.get("action") or ""),
                args=_dict(frame.get("args")),
                _client=self,
            )
            task = asyncio.create_task(self._handle(call), name=f"hub-call-{call.action}")
            self._calls.add(task)
            task.add_done_callback(self._calls.discard)
        elif kind in ("result", "event", "error"):
            call_id = str(frame.get("id") or "")
            p = self._pending.get(call_id)
            if p is None:
                if kind == "error" and not call_id:
                    logger.warning("hub error: {} {}", frame.get("code"), frame.get("message"))
                return
            if kind == "event":
                if p.on_event is not None:
                    t = asyncio.create_task(self._deliver(p, _dict(frame.get("body"))))
                    p.tasks.add(t)
                    t.add_done_callback(p.tasks.discard)
                return
            if not p.done.done():
                p.done.set_result(frame)

    async def _deliver(self, p: _Pending, body: dict[str, Any]) -> None:
        assert p.on_event is not None
        try:
            await p.on_event(body)
        except Exception:  # noqa: BLE001
            logger.exception("hub on_event")

    def _devices_changed(self) -> None:
        if self.on_devices is not None:
            try:
                self.on_devices(self.devices)
            except Exception:  # noqa: BLE001
                logger.exception("hub on_devices")

    async def _handle(self, call: IncomingCall) -> None:
        if self.on_call is None:
            await call.fail("not_controllable", "this device takes no calls")
            return
        try:
            await self.on_call(call)
        except asyncio.CancelledError:
            with contextlib.suppress(Exception):
                await call.fail("cancelled", "this device stopped")
            raise
        except Exception as exc:  # noqa: BLE001
            logger.exception("handling {} from {}", call.action, call.sender_name)
            with contextlib.suppress(Exception):
                await call.fail("failed", f"{type(exc).__name__}: {exc}")
        if not call.answered:
            with contextlib.suppress(Exception):
                await call.fail("failed", "the handler did not answer")

    async def _send(self, frame: dict[str, Any]) -> None:
        ws = self._ws
        if ws is None:
            raise HubError("disconnected", "not connected to the hub")
        try:
            await ws.send(json.dumps(frame, ensure_ascii=False, separators=(",", ":")))
        except ConnectionClosed as exc:
            raise HubError("disconnected", "the hub connection dropped") from exc

    def _fail_all(self, code: str, message: str) -> None:
        pending = list(self._pending.values())
        self._pending.clear()
        for p in pending:
            if not p.done.done():
                p.done.set_result({"type": "error", "code": code, "message": message})

    # ------------------------------------------------------------------ calls out
    async def call(
        self,
        to: str,
        action: str,
        args: dict[str, Any] | None = None,
        timeout: float = 120.0,
        on_event: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
        call_id: str | None = None,
        retries: int = 0,
    ) -> dict[str, Any]:
        """Ask device ``to`` to carry out ``action``; the result body, or :class:`HubError`.
        ``on_event`` gets every progress frame (tool steps, approvals, images) meanwhile.

        ``retries`` re-sends the call with the *same* id when the connection drops
        before an answer arrives: a relay that kept the finished answer replays it
        instead of running the action again (docs/hub.md), so a retried call does not
        become a second side effect. The total wait is still ``timeout``; a call that
        times out or is refused is never retried, since the relay may still be
        carrying it. The default (no retries) keeps the old behaviour exactly.
        """
        call_id = call_id or uuid.uuid4().hex[:16]
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        attempts = 0
        try:
            while True:
                p = _Pending(done=loop.create_future(), on_event=on_event)
                self._pending[call_id] = p
                try:
                    await self._send(
                        {
                            "type": "call",
                            "id": call_id,
                            "to": to,
                            "action": action,
                            "args": args or {},
                            # Only a re-send says so: a relay that kept the finished
                            # answer replays it, and a plain re-send stays a new call.
                            "retry": attempts > 0,
                        }
                    )
                    remaining = deadline - loop.time()
                    if remaining <= 0:
                        raise HubError(
                            "timeout", f"no answer from the device within {int(timeout)} s"
                        )
                    try:
                        frame = await asyncio.wait_for(p.done, remaining)
                    except TimeoutError:
                        raise HubError(
                            "timeout", f"no answer from the device within {int(timeout)} s"
                        ) from None
                except HubError as exc:
                    if exc.code != "disconnected" or attempts >= retries:
                        raise
                    attempts += 1
                    remaining = deadline - loop.time()
                    if remaining <= 0:
                        raise HubError(
                            "timeout", f"no answer from the device within {int(timeout)} s"
                        ) from None
                    try:
                        await asyncio.wait_for(self.connected.wait(), remaining)
                    except TimeoutError:
                        raise HubError(
                            "timeout", f"no answer from the device within {int(timeout)} s"
                        ) from None
                    continue
                finally:
                    self._pending.pop(call_id, None)
                    for t in list(p.tasks):
                        if not t.done():
                            t.cancel()
                if frame.get("type") == "error":
                    code = str(frame.get("code") or "error")
                    if code == "disconnected" and attempts < retries:
                        attempts += 1
                        remaining = deadline - loop.time()
                        if remaining <= 0:
                            raise HubError(
                                "timeout",
                                f"no answer from the device within {int(timeout)} s",
                            )
                        try:
                            await asyncio.wait_for(self.connected.wait(), remaining)
                        except TimeoutError:
                            raise HubError(
                                "timeout",
                                f"no answer from the device within {int(timeout)} s",
                            ) from None
                        continue
                    raise HubError(
                        code,
                        str(frame.get("message") or "the hub refused the call"),
                    )
                if not frame.get("ok"):
                    raise HubError(
                        str(frame.get("error") or "failed"),
                        str(frame.get("message") or "the device could not do it"),
                    )
                body = frame.get("body")
                return body if isinstance(body, dict) else {}
        except (HubError, asyncio.CancelledError) as exc:
            if action == "task" and (
                isinstance(exc, asyncio.CancelledError) or exc.code == "timeout"
            ):
                # Both the local deadline and the relay's timeout abandon the same run.
                # An exact call id prevents a delayed stop from ending its successor.
                with contextlib.suppress(HubError, TimeoutError):
                    await asyncio.wait_for(
                        self.call(to, "stop", {"call": call_id}, timeout=TASK_STOP_TIMEOUT_S),
                        timeout=TASK_STOP_TIMEOUT_S,
                    )
            raise

    async def request_devices(self) -> None:
        await self._send({"type": "devices"})

    async def rename(self, name: str) -> None:
        self.name = name
        await self._send({"type": "rename", "name": name})

    async def forget(self, device_id: str) -> None:
        await self._send({"type": "forget", "device_id": device_id})

    # ------------------------------------------------------------------ the list
    def others(self) -> list[dict[str, Any]]:
        return [d for d in self.devices if d.get("id") != self.device_id and d.get("kind") != "web"]

    def find(self, query: str) -> dict[str, Any] | None:
        """A device by name (case-insensitive), by id, or by a unique substring; never
        this one. An empty query means the only other device online, if there is one."""
        q = (query or "").strip().lower()
        others = self.others()
        if not q:
            online = [d for d in others if d.get("online")]
            return online[0] if len(online) == 1 else None
        for d in others:
            if str(d.get("name", "")).lower() == q or d.get("id") == query:
                return d
        hits = [d for d in others if q in str(d.get("name", "")).lower()]
        if len(hits) == 1:
            return hits[0]
        kinds = [
            d
            for d in others
            if d.get("online")
            and (
                (q in ("phone", "手机", "my phone") and d.get("kind") == "phone")
                or (q in ("pc", "computer", "电脑", "my computer") and d.get("kind") == "computer")
            )
        ]
        return kinds[0] if len(kinds) == 1 else None


__all__ = ["HubClient", "HubError", "IncomingCall", "MAX_FRAME"]


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}

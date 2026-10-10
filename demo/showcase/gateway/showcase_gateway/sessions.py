"""Sessions: one private nanoMuse per visitor, for a while, within a budget."""

from __future__ import annotations

import asyncio
import base64
import ipaddress
import logging
import secrets
import socket
import time
from collections import defaultdict, deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

import httpx

from .config import DEFAULT_GUI_MODEL, OPENROUTER_GUI_MODEL, Lane, Settings, text_only
from .runner import Runner, RunnerError

log = logging.getLogger("showcase.sessions")

CST = timezone(timedelta(hours=8))


class Refused(Exception):
    """A request the policy says no to. ``status`` is the HTTP status to answer with."""

    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


@dataclass(frozen=True)
class Provider:
    """A visitor's own model: their key, their bill, no budget of ours. ``host`` and
    ``addresses`` are what ``resolve_provider`` found at the start: the gateway's calls to
    the provider go to those addresses (``Lane.pin``), the name never looked up again."""

    base_url: str
    api_key: str
    model: str
    host: str = ""
    addresses: tuple[str, ...] = ()

    @property
    def gui_model(self) -> str:
        """The model that operates the phone on the visitor's own key.

        The chat model and the GUI model are two settings (contract C4): on OpenRouter the
        hands get ``qwen/qwen3.8-27b``, on 阿里云百炼 ``qwen3.8-27b`` — the same key, the
        visitor's bill, never the showcase's. On any other provider the visitor's one model
        does both lanes; when it is a text-only family (DeepSeek's own API, say) the hands
        have nothing to look with, and the README says so.
        """
        host = (self.host or urlparse(self.base_url).hostname or "").lower()
        if host == "openrouter.ai" or host.endswith(".openrouter.ai"):
            return OPENROUTER_GUI_MODEL
        if host.endswith("aliyuncs.com"):
            return DEFAULT_GUI_MODEL
        return self.model

    def lane(self, name: str) -> Lane:
        """The visitor's provider as the ``main`` or the ``gui`` lane."""
        model = self.gui_model if name == "gui" else self.model
        return Lane("openai", model, self.base_url, self.api_key, pin=self.addresses)


@dataclass
class Session:
    id: str
    token: str  # the nanoMuse access token, what the phone pastes
    llm_key: str  # what the container presents to the model proxy
    ip: str
    created_at: float
    expires_at: float
    container: str
    address: str = ""  # where the gateway reaches the container
    port: int = 8787
    byok: Provider | None = None
    account: str = ""  # the visitor's account id, when the showcase asks for a sign-in
    hint: str = ""  # the masked identifier, for the log and the admin
    time_zone: str = ""  # the visitor's IANA zone, the container's TZ; "" → UTC
    last_seen: float = field(default=0.0)
    requests: int = 0
    tokens: int = 0
    pictures: int = 0  # drawn for a new look (images.py), counted apart from the chat
    clips: int = 0  # the chosen face animated (clips.py), counted apart again
    ended: bool = False

    @property
    def http_base(self) -> str:
        return f"http://{self.address}:{self.port}"

    @property
    def ws_base(self) -> str:
        return f"ws://{self.address}:{self.port}"

    def public(self, settings: Settings, now: float) -> dict:
        return {
            "id": self.id,
            "server_url": settings.session_origin(self.id),
            "token": self.token,
            "expires_at": int(self.expires_at),
            "ttl_s": max(0, int(self.expires_at - now)),
            "byok": self.byok is not None,
            "quota": {
                "requests": None if self.byok else settings.session_requests,
                "tokens": None if self.byok else settings.session_tokens,
                "requests_used": self.requests,
                "tokens_used": self.tokens,
                "pictures": None if self.byok else settings.image_per_session,
                "pictures_used": self.pictures,
                "clips": None if self.byok else settings.clips_per_session,
                "clips_used": self.clips,
            },
        }


def _new_id() -> str:
    # 13 lowercase letters and digits: a DNS label, which is what a session id becomes
    return base64.b32encode(secrets.token_bytes(8)).decode().rstrip("=").lower()


def _day_key(now: float) -> str:
    return datetime.fromtimestamp(now, CST).strftime("%Y-%m-%d")


def _resolve(host: str, port: int) -> list[str]:
    return [info[4][0] for info in socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)]


def check_provider(base_url: str, allowed_hosts: tuple[str, ...], resolve=_resolve) -> str:
    """A visitor's provider URL, normalised, or ``Refused``. HTTPS only, to a known provider
    host, and never to an address inside our own network."""
    return resolve_provider(base_url, allowed_hosts, resolve)[0]


def resolve_provider(
    base_url: str, allowed_hosts: tuple[str, ...], resolve=_resolve
) -> tuple[str, str, tuple[str, ...]]:
    """``check_provider`` with what it found: (url, host, the host's public addresses). The
    session's model calls are pinned to those addresses, so the check holds for its whole
    life — a name that resolved to a public address here cannot be re-pointed at one of
    ours later (DNS rebinding) to make the gateway call inside its own network."""
    url = urlparse(base_url.strip())
    if url.scheme != "https" or not url.hostname:
        raise Refused(400, "bad_provider", "The model API address must start with https://")
    host = url.hostname.lower()
    if host not in allowed_hosts and not any(host.endswith("." + h) for h in allowed_hosts):
        raise Refused(400, "provider_not_allowed", f"{host} is not a supported model provider")
    try:
        addresses = resolve(host, url.port or 443)
    except OSError as exc:
        raise Refused(400, "bad_provider", f"{host} does not resolve") from exc
    if not addresses:
        raise Refused(400, "bad_provider", f"{host} does not resolve")
    pinned: list[str] = []
    for raw in addresses:
        if not ipaddress.ip_address(raw).is_global:
            raise Refused(400, "bad_provider", f"{host} points inside a private network")
        if raw not in pinned:
            pinned.append(raw)
    return f"{url.scheme}://{url.netloc}{url.path.rstrip('/')}", host, tuple(pinned)


class SessionManager:
    def __init__(
        self,
        settings: Settings,
        runner: Runner,
        http: httpx.AsyncClient | None = None,
        clock=time.time,
    ) -> None:
        self.s = settings
        self.runner = runner
        self.http = http or httpx.AsyncClient(timeout=5)
        self.clock = clock
        self.sessions: dict[str, Session] = {}
        self._starts: dict[str, deque[float]] = defaultdict(deque)  # per ip, last 24 h
        self._account_starts: dict[str, deque[float]] = defaultdict(deque)  # per account
        self._day = _day_key(clock())
        self.day_requests = 0
        self.day_tokens = 0
        self.day_pictures = 0
        self.day_clips = 0
        self.internal_url = settings.internal_url
        self.resolve = _resolve  # DNS, replaceable in tests
        self._lock = asyncio.Lock()
        # told when a session ends, with the reason — the visitors' book closes its visit row
        self.on_end: Callable[[Session, str], None] | None = None

    # ------------------------------------------------------------------ lifecycle
    async def startup(self) -> None:
        for name in await self.runner.leftovers():
            log.info("removing leftover %s", name)
            await self.runner.stop(name)
        if not self.internal_url:
            addr = await self.runner.gateway_address()
            if not addr:
                raise RuntimeError(
                    "INTERNAL_URL is not set and the sessions network has no gateway address"
                )
            self.internal_url = f"http://{addr}:{self.s.listen_port}"
        log.info("containers reach the gateway at %s", self.internal_url)

    async def shutdown(self) -> None:
        for sid in list(self.sessions):
            await self.end(sid, reason="gateway stopping")

    async def reap_forever(self, interval: float = 15) -> None:
        while True:
            await asyncio.sleep(interval)
            try:
                await self.reap_once()
            except Exception:  # noqa: BLE001
                log.exception("reaper")

    async def reap_once(self) -> None:
        now = self.clock()
        for sid, sess in list(self.sessions.items()):
            if sess.ended:
                continue
            if now >= sess.expires_at:
                await self.end(sid, reason="time is up")
            elif now - sess.last_seen >= self.s.idle_ttl_s:
                await self.end(sid, reason="idle")

    # ------------------------------------------------------------------ creating
    def _roll_day(self) -> None:
        key = _day_key(self.clock())
        if key != self._day:
            self._day = key
            self.day_requests = 0
            self.day_tokens = 0
            self.day_pictures = 0
            self.day_clips = 0

    def active(self) -> list[Session]:
        return [s for s in self.sessions.values() if not s.ended]

    def _check_policy(self, ip: str, account: str = "") -> None:
        now = self.clock()
        active = self.active()
        if len(active) >= self.s.max_sessions:
            raise Refused(
                503, "full", "Every demo Muse is taken right now. Try again in a few minutes."
            )
        mine = [s for s in active if s.ip == ip]
        if len(mine) >= self.s.per_ip_active:
            raise Refused(
                429, "already_running", "You already have a demo running. Finish that one first."
            )
        starts = self._starts[ip]
        while starts and now - starts[0] > 86400:
            starts.popleft()
        if len(starts) >= self.s.per_ip_daily:
            raise Refused(429, "daily_limit", "That is all the demo sessions for today from here.")
        if account:
            # the same account from two browsers is still one person: one Muse at a time,
            # and a day's worth of starts
            theirs = [s for s in active if s.account == account]
            if len(theirs) >= self.s.per_account_active:
                raise Refused(
                    429,
                    "already_running",
                    "You already have a demo running. Finish that one first.",
                )
            account_starts = self._account_starts[account]
            while account_starts and now - account_starts[0] > 86400:
                account_starts.popleft()
            if len(account_starts) >= self.s.per_account_daily:
                raise Refused(
                    429, "daily_limit", "That is all the demo sessions for today on this account."
                )

    def _env_for(self, sess: Session) -> dict[str, str]:
        s = self.s
        base = f"{self.internal_url.rstrip('/')}/llm/{sess.id}"
        if sess.byok:
            main, gui = sess.byok.lane("main"), sess.byok.lane("gui")
        else:
            main, gui = s.main, s.gui
        env = {
            "NANOMUSE_SERVER_TOKEN": sess.token,
            "NANOMUSE_LLM_PROVIDER": main.provider,
            "NANOMUSE_LLM_MODEL": main.model,
            "NANOMUSE_LLM_BASE_URL": f"{base}/main",
            "NANOMUSE_LLM_API_KEY": sess.llm_key,
            "NANOMUSE_GUI_ENABLED": "1",
            "NANOMUSE_GUI_PROVIDER": gui.provider,
            "NANOMUSE_GUI_MODEL": gui.model,
            "NANOMUSE_GUI_BASE_URL": f"{base}/gui",
            "NANOMUSE_GUI_API_KEY": sess.llm_key,
            "NANOMUSE_LOG_LEVEL": "warning",
            # a demo Muse has its model from us and no account to sign in to; without this the
            # web app opens on the Cloud sign-in (cloud.required is the runtime's default)
            "NANOMUSE_CLOUD_REQUIRED": "0",
        }
        if text_only(main.model):
            # The chat model takes no images (DeepSeek before v4.1), and on Model Studio's
            # compatible mode it does not say so: a message with a screenshot in it (the
            # operator's report carries the last screen) comes back as an empty reply, twice,
            # and the Muse falls silent. So the pictures stay out of its context; the operator
            # lane is the one that looks. A sighted main (deepseek-v4.1-flash, qwen) is left
            # to the runtime's own detection.
            env["NANOMUSE_LLM_VISION"] = "off"
        # a new look for the Muse: pictures drawn through the gateway (images.py) — on the
        # showcase's key only; a visitor's own provider is not asked to draw
        if s.image_model and s.image_api_key and not sess.byok:
            env["NANOMUSE_LLM_IMAGE_MODEL"] = s.image_model
            # …and the chosen face animated (clips.py): the studio finds the video API at the
            # session's own model address, where the gateway stands in for the provider
            if s.video_model and s.video_api_key and s.video_base_url:
                env["NANOMUSE_LLM_VIDEO_MODEL"] = s.video_model
                env["NANOMUSE_LLM_VIDEO_BASE_URL"] = f"{base}/main"
        # the visitor's clock: Python's local time in the container follows TZ (the image
        # has the zone files); a name it does not know leaves the container on UTC
        if sess.time_zone:
            env["TZ"] = sess.time_zone
        env.update(s.extra_env)
        return env

    async def create(
        self,
        ip: str,
        byok: Provider | None = None,
        account: str = "",
        hint: str = "",
        time_zone: str = "",
    ) -> Session:
        if byok and not self.s.byok_enabled:
            raise Refused(400, "byok_off", "Bringing your own key is turned off on this showcase.")
        if not byok and not self.s.main.configured:
            raise Refused(
                503, "no_model", "This showcase has no demo model configured; bring your own key."
            )
        async with self._lock:
            self._roll_day()
            self._check_policy(ip, account)
            now = self.clock()
            sid = _new_id()
            sess = Session(
                id=sid,
                token=secrets.token_urlsafe(24),
                llm_key=secrets.token_urlsafe(24),
                ip=ip,
                created_at=now,
                expires_at=now + self.s.session_ttl_s,
                container=f"nm-{sid}",
                port=self.s.container_port,
                byok=byok,
                account=account,
                hint=hint,
                time_zone=time_zone,
                last_seen=now,
            )
            self.sessions[sid] = sess
            self._starts[ip].append(now)
            if account:
                self._account_starts[account].append(now)
        try:
            sess.address = await self.runner.start(sess.container, self._env_for(sess))
            await self._wait_ready(sess)
        except (RunnerError, Refused):
            await self.end(sid, reason="failed to start")
            raise
        except Exception as exc:  # noqa: BLE001
            await self.end(sid, reason="failed to start")
            raise Refused(503, "start_failed", "Could not start a demo Muse. Try again.") from exc
        log.info(
            "session %s started for %s (visitor=%s byok=%s)",
            sid,
            ip,
            hint or "-",
            byok is not None,
        )
        return sess

    async def _wait_ready(self, sess: Session) -> None:
        deadline = self.clock() + self.s.start_timeout_s
        while True:
            try:
                r = await self.http.get(f"{sess.http_base}/api/health")
                if r.status_code == 200 and r.json().get("ok"):
                    return
            except (httpx.HTTPError, ValueError):
                pass
            if self.clock() >= deadline:
                raise Refused(503, "start_timeout", "The demo Muse took too long to start.")
            await asyncio.sleep(0.5)

    # ------------------------------------------------------------------ using
    def get(self, sid: str) -> Session | None:
        sess = self.sessions.get(sid)
        return None if sess is None or sess.ended else sess

    def authenticate(self, sid: str, token: str | None) -> Session:
        sess = self.get(sid)
        if (
            sess is None
            or not token
            or not secrets.compare_digest(token.encode(), sess.token.encode())
        ):
            raise Refused(404, "no_session", "No such session.")
        return sess

    def touch(self, sess: Session) -> None:
        sess.last_seen = self.clock()

    async def end(self, sid: str, reason: str = "") -> None:
        sess = self.sessions.get(sid)
        if sess is None or sess.ended:
            return
        sess.ended = True
        log.info(
            "session %s ended: %s (visitor=%s, %d requests, %d tokens)",
            sid,
            reason,
            sess.hint or "-",
            sess.requests,
            sess.tokens,
        )
        if self.on_end is not None:
            try:
                self.on_end(sess, reason)
            except Exception:  # a record for the operator; never holds the stop up
                log.exception("on_end hook failed for %s", sid)
        await self.runner.stop(sess.container)
        # keep the record a little so late requests get a clear "no such session"
        asyncio.get_running_loop().call_later(300, self.sessions.pop, sid, None)

    # ------------------------------------------------------------------ model budget
    def authenticate_key(self, sess: Session, key: str | None) -> None:
        """The per-session key a container presents to the model proxy, or ``Refused``."""
        if not key or not secrets.compare_digest(key.encode(), sess.llm_key.encode()):
            raise Refused(401, "bad_key", "invalid api key")

    def llm_lane(self, sess: Session, key: str | None, lane: str) -> Lane:
        """Which upstream a container's model call goes to — after the budget check."""
        self.authenticate_key(sess, key)
        if sess.byok:
            # the visitor's provider for both lanes, each with its own model (Provider.lane)
            return sess.byok.lane(lane if lane in ("main", "gui") else "main")
        upstream = self.s.lane(lane)
        if upstream is None or not upstream.configured:
            raise Refused(404, "no_lane", f"no model lane '{lane}'")
        self._roll_day()
        if sess.requests >= self.s.session_requests or sess.tokens >= self.s.session_tokens:
            raise Refused(
                429,
                "session_budget",
                "This demo session has used up its model budget. Start a new one, or bring your own key.",
            )
        if self.day_requests >= self.s.daily_requests or self.day_tokens >= self.s.daily_tokens:
            raise Refused(
                429,
                "daily_budget",
                "The showcase has spent today's model budget. Bring your own key, or come back tomorrow.",
            )
        return upstream

    def record(self, sess: Session, tokens: int) -> None:
        sess.requests += 1
        sess.tokens += tokens
        if not sess.byok:
            self.day_requests += 1
            self.day_tokens += tokens

    def check_pictures(self, sess: Session) -> None:
        """Whether one more picture for a new look is within the session's and the day's share."""
        self._roll_day()
        if sess.pictures >= self.s.image_per_session:
            raise Refused(
                429,
                "picture_budget",
                "This demo Muse has drawn all the pictures it may. A new session draws again.",
            )
        if self.day_pictures >= self.s.daily_images:
            raise Refused(
                429,
                "daily_pictures",
                "The showcase has drawn today's share of pictures. Come back tomorrow for a new look.",
            )

    def record_picture(self, sess: Session) -> None:
        sess.pictures += 1
        self.day_pictures += 1
        self.touch(sess)

    def check_clips(self, sess: Session) -> None:
        """Whether one more clip of the face is within the session's and the day's share."""
        self._roll_day()
        if sess.clips >= self.s.clips_per_session:
            raise Refused(
                429,
                "clip_budget",
                "This demo Muse has made all the clips it may. A new session animates again.",
            )
        if self.day_clips >= self.s.daily_clips:
            raise Refused(
                429,
                "daily_clips",
                "The showcase has made today's share of clips. Come back tomorrow for a moving face.",
            )

    def record_clip(self, sess: Session) -> None:
        sess.clips += 1
        self.day_clips += 1
        self.touch(sess)

    def stats(self) -> dict:
        self._roll_day()
        active = self.active()
        return {
            "active_sessions": len(active),
            "max_sessions": self.s.max_sessions,
            "day": self._day,
            "day_requests": self.day_requests,
            "day_tokens": self.day_tokens,
            "day_pictures": self.day_pictures,
            "day_clips": self.day_clips,
        }

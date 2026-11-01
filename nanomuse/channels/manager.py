"""The channel manager: one place where every chat app meets the agent.

It starts the channels that are switched on, decides who may talk to the bot (allowlist,
pairing), maps a chat to one conversation of the agent and carries the run back into the
chat as it happens: the reply grows in place where the vendor allows edits, tool activity
shows as a short status line, an approval the run asks for becomes a card (or a message)
answered with 允许 / 拒绝. Chats marked "deliver here" also get what the Muse does on its
own — check-ins, reminders, the results of background work — the same events the phone
turns into notifications.

The agent is not forked: a chat's message goes through :meth:`MuseService.send`, exactly
like a message typed in the app, and the events it produces are read off the service's bus.
"""

from __future__ import annotations

import asyncio
import contextlib
import re
import time
from collections.abc import Coroutine
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from nanomuse.background import keep_task
from nanomuse.channels.base import Channel, ChannelBus, ChannelStatus, InboundMessage
from nanomuse.channels.dingtalk import DingTalkChannel
from nanomuse.channels.feishu import FeishuChannel
from nanomuse.channels.store import ChannelSettingsStore, PairingStore
from nanomuse.channels.telegram import TelegramChannel
from nanomuse.channels.wecom import WeComChannel
from nanomuse.logger import logger
from nanomuse.server.events import new_id

if TYPE_CHECKING:
    from nanomuse.server.service import MuseService

CHANNEL_TYPES: tuple[type[Channel], ...] = (
    FeishuChannel,
    DingTalkChannel,
    WeComChannel,
    TelegramChannel,
)

ALLOW_WORDS = frozenset(
    {
        "允许",
        "同意",
        "可以",
        "好",
        "好的",
        "允许。",
        "allow",
        "yes",
        "y",
        "ok",
        "approve",
        "go ahead",
    }
)
DENY_WORDS = frozenset(
    {"拒绝", "不行", "不要", "不", "拒绝。", "deny", "no", "n", "reject", "stop"}
)

# how often a growing reply is pushed to the chat (edits are rate-limited everywhere)
EDIT_INTERVAL_S = 1.0
THREAD_PREFIX = "channel-"
_SAFE = re.compile(r"[^A-Za-z0-9_.-]+")

_TOOL_LABELS = {
    "web_search": ("Searching the web", "正在搜索"),
    "web_fetch": ("Reading a web page", "正在读网页"),
    "files": ("Working with files", "正在处理文件"),
    "shell": ("Running a command", "正在运行命令"),
    "python_execute": ("Running Python", "正在运行 Python"),
    "read_emails": ("Reading email", "正在读邮件"),
    "send_email": ("Sending email", "正在发邮件"),
    "browser": ("Browsing", "正在浏览网页"),
    "goals": ("Updating goals", "正在更新目标"),
    "remember": ("Saving a memory", "正在记下来"),
    "recall": ("Recalling", "正在回忆"),
}


_CASE_FOLDED_CHANNELS = frozenset({"wecom"})
"""Channels whose chat ids are case-insensitive by their own documentation, so one chat
can arrive in more than one spelling: WeCom's admin-typed user ids: "userid ... 不区分
大小写" (https://developer.work.weixin.qq.com/document/path/96255). Ids that merely tend
to be lower case (Telegram's numbers, Feishu's and DingTalk's ids) keep the case they
arrive in: folding those could merge two chats that are genuinely different."""


def thread_id_for(channel: str, chat_id: str) -> str:
    """The conversation a chat maps to. Letters, digits, ``_ . -`` only, folded to lower
    case where the channel's own ids are case-insensitive: the id names a file in the
    threads folder, a colon in a file name breaks on Windows, and two spellings of one
    WeCom id that differ by case are one file there — a user whose admin-typed id is
    ``ZhangSan`` and arrives once as ``ZhangSan`` and once as ``zhangsan``."""
    safe = _SAFE.sub("_", chat_id).strip("._") or "chat"
    if channel in _CASE_FOLDED_CHANNELS:
        safe = safe.lower()
    return f"{THREAD_PREFIX}{channel}-{safe[:80]}"


@dataclass
class _Live:
    """A reply under way in one chat: what has been shown, what is waiting to be shown."""

    channel: str
    chat_id: str
    stream_id: str = field(default_factory=lambda: new_id("s"))
    text: str = ""
    status: str = ""
    shown: str = ""
    sent_at: float = 0.0
    handle: asyncio.TimerHandle | None = None
    flushing: asyncio.Task[None] | None = None


class ChannelManager(ChannelBus):
    def __init__(self, svc: MuseService):
        self.svc = svc
        self.store = ChannelSettingsStore(svc.data_dir, svc.app.vault, svc.settings.source)
        self.pairing = PairingStore(svc.data_dir)
        self.types: dict[str, type[Channel]] = {c.name: c for c in CHANNEL_TYPES}
        self.channels: dict[str, Channel] = {}
        self.status: dict[str, ChannelStatus] = {n: ChannelStatus() for n in self.types}
        self._loop: asyncio.AbstractEventLoop | None = None
        self._queue: asyncio.Queue[dict[str, Any]] | None = None
        self._pump: asyncio.Task[None] | None = None
        # thread id -> (channel, chat_id)
        self.routes: dict[str, tuple[str, str]] = {}
        self._live: dict[str, _Live] = {}
        # "channel:chat" -> approval ids waiting for a word from that chat (latest last)
        self._asks: dict[str, list[str]] = {}
        # "channel:chat" -> the thread whose question was delivered there
        self._questions: dict[str, str] = {}
        self._artifacts: dict[str, list[str]] = {}
        self._typing: set[str] = set()
        self._tasks: set[asyncio.Task[Any]] = set()
        self.logins: dict[str, dict[str, Any]] = {}
        self.started = False

    # ------------------------------------------------------------------ lifecycle
    async def start(self) -> None:
        if self.started:
            return
        self.started = True
        self._loop = asyncio.get_running_loop()
        self._queue = self.svc.bus.subscribe()
        self._pump = asyncio.create_task(self._pump_loop(), name="channels-pump")
        for name in self.types:
            self._spawn(self.start_channel(name))

    async def stop(self) -> None:
        if not self.started:
            return
        self.started = False
        if self._pump is not None:
            self._pump.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._pump
            self._pump = None
        if self._queue is not None:
            self.svc.bus.unsubscribe(self._queue)
            self._queue = None
        for task in list(self._tasks):
            task.cancel()
        for name in list(self.channels):
            await self.stop_channel(name)

    def _spawn(self, coro: Coroutine[Any, Any, Any]) -> asyncio.Task[Any]:
        task = asyncio.ensure_future(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return keep_task(task)

    async def start_channel(self, name: str) -> ChannelStatus:
        """(Re)start one channel from its saved settings; the status says how it went."""
        cls = self.types[name]
        await self.stop_channel(name)
        cfg = self.store.config(name)
        if not cfg.enabled:
            return self._set(name, "off")
        if not cls.sdk_available():
            return self._set(name, "missing_sdk", cls.install_hint())
        missing = cls.missing(cfg.settings)
        if missing:
            labels = {f.key: f.label for f in cls.fields}
            return self._set(name, "unconfigured", ", ".join(labels.get(k, k) for k in missing))
        channel = cls(self.store.resolved(cfg))
        self.channels[name] = channel
        self._set(name, "connecting")
        try:
            await channel.start(self)
        except Exception as exc:  # noqa: BLE001 — the vendor's words go to the app
            logger.warning("channel {} failed to start: {}", name, exc)
            self.channels.pop(name, None)
            with contextlib.suppress(Exception):
                await channel.stop()
            return self._set(name, "error", _short(exc))
        return self.status[name]

    async def stop_channel(self, name: str) -> None:
        channel = self.channels.pop(name, None)
        if channel is None:
            return
        try:
            await asyncio.wait_for(channel.stop(), 10)
        except Exception as exc:  # noqa: BLE001
            logger.debug("channel {} did not stop cleanly: {}", name, exc)
        self._set(name, "off")

    def _set(self, name: str, state: str, detail: str = "") -> ChannelStatus:
        status = ChannelStatus(state, detail)
        if self.status.get(name) != status:
            self.status[name] = status
            self.publish()
        return status

    def publish(self) -> None:
        """Tell the open apps the channels changed (they refetch ``/api/channels``)."""
        with contextlib.suppress(Exception):
            self.svc.bus.publish({"kind": "channels"})

    # ------------------------------------------------------------------ ChannelBus
    def _threadsafe(self, fn: Any, *args: Any) -> None:
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is loop:
            fn(*args)
        else:
            loop.call_soon_threadsafe(fn, *args)

    def inbound(self, msg: InboundMessage) -> None:
        self._threadsafe(lambda m: self._spawn(self._handle_inbound(m)), msg)

    def set_status(self, channel: str, state: str, detail: str = "") -> None:
        self._threadsafe(self._set, channel, state, detail)

    def action(self, channel: str, chat_id: str, sender_id: str, value: dict[str, Any]) -> None:
        self._threadsafe(
            lambda: self._spawn(self._handle_action(channel, chat_id, sender_id, value))
        )

    # ------------------------------------------------------------------ language
    @property
    def lang(self) -> str:
        language = (self.svc.settings.agent.language or "auto").lower()
        if language.startswith("zh"):
            return "zh"
        if language.startswith("en"):
            return "en"
        return "both"

    def say(self, en: str, zh: str) -> str:
        lang = self.lang
        if lang == "zh":
            return zh
        if lang == "en":
            return en
        return f"{en}\n{zh}"

    @property
    def muse_name(self) -> str:
        return self.svc.profile.name or "nanoMuse"

    # ------------------------------------------------------------------ inbound
    def _allowed(self, msg: InboundMessage) -> bool:
        cfg = self.store.config(msg.channel)
        if "*" in cfg.allow_from or msg.sender_id in cfg.allow_from:
            return True
        return self.pairing.is_approved(msg.channel, msg.sender_id)

    async def _handle_inbound(self, msg: InboundMessage) -> None:
        channel = self.channels.get(msg.channel)
        if channel is None:
            return
        key = f"{msg.channel}:{msg.chat_id}"
        if not self._allowed(msg):
            if msg.is_group:
                logger.debug(
                    "channel {}: ignoring group message from unknown {}", msg.channel, msg.sender_id
                )
                return
            code = self.pairing.request(
                msg.channel, msg.sender_id, sender_name=msg.sender_name, chat_id=msg.chat_id
            )
            self.publish()
            await self._send(msg.channel, msg.chat_id, self.pairing_text(code))
            return
        cfg = self.store.config(msg.channel)
        if msg.is_group and cfg.group_policy == "mention" and not msg.mentioned:
            return
        if not msg.is_group:
            self.pairing.touch(
                msg.channel, msg.sender_id, sender_name=msg.sender_name, chat_id=msg.chat_id
            )
        text = msg.text.strip()
        word = text.lower().strip(" .!。！")
        # a word for an approval this chat was asked about
        if self._asks.get(key) and (word in ALLOW_WORDS or word in DENY_WORDS):
            approval_id = self._asks[key][-1]
            await self._decide(msg.channel, msg.chat_id, approval_id, word in ALLOW_WORDS)
            return
        # the answer to a question delivered here from another conversation
        delivered = self._questions.get(key)
        if delivered and text and self.svc.ui.has_pending_question(delivered):
            self._questions.pop(key, None)
            self.svc.ui.answer_question(delivered, text)
            await self._send(msg.channel, msg.chat_id, self.say("Passed on.", "已转达。"))
            return
        self._questions.pop(key, None)
        paths: list[str] = []
        for item in msg.files:
            try:
                paths.append(self.svc.save_upload(item.name, item.data).path)
            except ValueError as exc:
                await self._send(msg.channel, msg.chat_id, _short(exc))
        if not text and not paths:
            # someone opened the chat (WeCom's enter_chat), a sticker: nothing to pass on
            return
        if msg.is_group and msg.sender_name and text:
            text = f"{msg.sender_name}: {text}"
        thread_id = self._thread_for(msg)
        try:
            self.svc.send(thread_id, text, files=paths or None)
        except (ValueError, PermissionError) as exc:
            await self._send(msg.channel, msg.chat_id, _short(exc))

    def _thread_for(self, msg: InboundMessage) -> str:
        thread_id = thread_id_for(msg.channel, msg.chat_id)
        self.routes[thread_id] = (msg.channel, msg.chat_id)
        if thread_id not in self.svc.threads:
            if msg.channel in _CASE_FOLDED_CHANNELS:
                # this chat may have written history under an earlier spelling
                self.svc.adopt_thread_id(thread_id)
            self.svc.timeline(thread_id)
            label = self.types[msg.channel].label
            who = msg.chat_name or (
                msg.sender_name or msg.sender_id if not msg.is_group else "group"
            )
            self.svc.rename_thread(thread_id, f"{label} · {who}"[:60])
        return thread_id

    async def _handle_action(
        self, channel: str, chat_id: str, sender_id: str, value: dict[str, Any]
    ) -> None:
        approval_id = str(value.get("approval") or "")
        decision = str(value.get("decision") or "")
        if not approval_id or decision not in ("allow", "deny"):
            return
        probe = InboundMessage(channel=channel, chat_id=chat_id, sender_id=sender_id)
        if not self._allowed(probe):
            return
        await self._decide(channel, chat_id, approval_id, decision == "allow")

    async def _decide(self, channel: str, chat_id: str, approval_id: str, approved: bool) -> None:
        key = f"{channel}:{chat_id}"
        label = self.types[channel].label
        ok = self.svc.decide(approval_id, approved, "once", f"from {label}")
        asks = self._asks.get(key)
        if asks and approval_id in asks:
            asks.remove(approval_id)
            if not asks:
                self._asks.pop(key, None)
        if ok:
            text = self.say("Allowed.", "已允许。") if approved else self.say("Denied.", "已拒绝。")
        else:
            text = self.say("That request is no longer waiting.", "这个请求已经不在等待了。")
        await self._send(channel, chat_id, text)

    def pairing_text(self, code: str) -> str:
        name = self.muse_name
        return self.say(
            f"This chat is not paired with {name} yet. Pairing code: {code}\n"
            f"Approve it in the app under Settings → Chat apps, or run "
            f"`nanomuse channels approve {code}`. The code is good for 10 minutes.",
            f"这个聊天还没有和 {name} 配对。配对码：{code}\n"
            f"在应用的「设置 → 聊天入口」里通过，或运行 `nanomuse channels approve {code}`。"
            f"10 分钟内有效。",
        )

    # ------------------------------------------------------------------ outbound helpers
    async def _send(
        self, channel: str, chat_id: str, text: str, files: list[str] | None = None
    ) -> None:
        ch = self.channels.get(channel)
        if ch is None or not (text.strip() or files):
            return
        try:
            await ch.send(chat_id, text, files=files)
        except Exception as exc:  # noqa: BLE001 — a vendor refusal; the app shows it
            logger.warning("channel {}: send to {} failed: {}", channel, chat_id, exc)
            self._set(channel, "error", _short(exc))

    def _live_for(self, thread: str) -> _Live | None:
        route = self.routes.get(thread)
        if route is None:
            return None
        live = self._live.get(thread)
        if live is None:
            live = _Live(channel=route[0], chat_id=route[1])
            self._live[thread] = live
        return live

    def _schedule_flush(self, thread: str) -> None:
        live = self._live.get(thread)
        loop = self._loop
        if live is None or loop is None or live.handle is not None:
            return
        wait = max(0.0, EDIT_INTERVAL_S - (time.monotonic() - live.sent_at))
        live.handle = loop.call_later(wait, self._flush_now, thread)

    def _flush_now(self, thread: str) -> None:
        live = self._live.get(thread)
        if live is None:
            return
        live.handle = None
        if live.flushing is not None and not live.flushing.done():
            self._schedule_flush(thread)
            return
        live.flushing = self._spawn(self._flush(thread))

    async def _flush(self, thread: str) -> None:
        live = self._live.get(thread)
        channel = self.channels.get(live.channel) if live else None
        if live is None or channel is None or not channel.supports_edit:
            return
        content = live.text or (f"_{live.status}_" if live.status else "")
        if not content.strip() or content == live.shown:
            return
        live.sent_at = time.monotonic()
        try:
            await channel.stream(live.chat_id, live.stream_id, content, done=False)
            live.shown = content
        except Exception as exc:  # noqa: BLE001
            logger.debug("channel {}: live update failed: {}", live.channel, exc)

    async def _finish(self, thread: str, text: str, *, files: list[str] | None = None) -> None:
        """The reply (one assistant bubble) is complete: the live message gets its final
        text, or a message is sent where nothing was streamed yet."""
        live = self._live.pop(thread, None)
        route = self.routes.get(thread)
        if route is None:
            return
        channel = self.channels.get(route[0])
        if channel is None:
            return
        if live is not None:
            if live.handle is not None:
                live.handle.cancel()
            if live.flushing is not None and not live.flushing.done():
                with contextlib.suppress(Exception):
                    await live.flushing
        try:
            if live is not None and live.shown and channel.supports_edit:
                await channel.stream(live.chat_id, live.stream_id, text or live.shown, done=True)
                if files:
                    await channel.send(route[1], "", files=files)
            elif text.strip() or files:
                await channel.send(route[1], text, files=files)
        except Exception as exc:  # noqa: BLE001
            logger.warning("channel {}: reply to {} failed: {}", route[0], route[1], exc)
            self._set(route[0], "error", _short(exc))

    async def _set_typing(self, thread: str, on: bool) -> None:
        route = self.routes.get(thread)
        channel = self.channels.get(route[0]) if route else None
        if route is None or channel is None:
            return
        if on and thread in self._typing:
            return
        if not on and thread not in self._typing:
            return
        if on:
            self._typing.add(thread)
        else:
            self._typing.discard(thread)
        with contextlib.suppress(Exception):
            await channel.typing(route[1], on)

    # ------------------------------------------------------------------ the bus
    async def _pump_loop(self) -> None:
        assert self._queue is not None
        while True:
            msg = await self._queue.get()
            try:
                await self._route(msg)
            except Exception as exc:  # noqa: BLE001
                logger.warning("channels: could not route {}: {}", msg.get("kind"), exc)

    async def _route(self, msg: dict[str, Any]) -> None:
        kind = msg.get("kind")
        if kind == "delta":
            thread = str(msg.get("thread") or "")
            live = self._live_for(thread)
            if live is not None:
                live.text += str(msg.get("text") or "")
                self._schedule_flush(thread)
            return
        if kind == "stream_end":
            thread = str(msg.get("thread") or "")
            live = self._live.get(thread)
            if live is not None and msg.get("discard"):
                live.text = ""
            return
        if kind == "status":
            status = msg.get("status") or {}
            thread = str(status.get("thread") or "")
            if thread in self.routes and status.get("state") == "idle":
                await self._run_ended(thread)
            return
        if kind == "event":
            await self._route_event(msg.get("event") or {})
            return
        if kind == "update":
            event = msg.get("update") or msg.get("event") or {}
            if event.get("type") == "approval" and event.get("status") != "pending":
                for asks in self._asks.values():
                    if event.get("id") in asks:
                        asks.remove(event["id"])
            return

    async def _route_event(self, event: dict[str, Any]) -> None:
        kind = event.get("type")
        thread = str(event.get("thread") or "")
        ours = thread in self.routes
        if kind == "assistant":
            text = str(event.get("text") or "")
            if event.get("quiet"):
                return
            if ours:
                await self._finish(thread, text)
            elif event.get("source") == "background" and event.get("final") and text.strip():
                about = str(event.get("about") or "")
                await self.deliver(f"{about}\n\n{text}" if about else text, exclude_thread=thread)
            return
        if kind == "tool" and ours and event.get("status") == "running":
            await self._set_typing(thread, True)
            live = self._live_for(thread)
            if live is not None:
                live.status = self._tool_label(event)
                self._schedule_flush(thread)
            return
        if kind == "approval" and event.get("status") == "pending":
            text = self.approval_text(event)
            approval_id = str(event.get("id") or "")
            if ours:
                await self._ask(*self.routes[thread], approval_id, text)
            else:
                for channel, chat_id in self._targets(exclude_thread=thread):
                    await self._ask(channel, chat_id, approval_id, text)
            return
        if kind == "question" and event.get("status") == "pending":
            question = str(event.get("text") or "")
            if ours:
                await self._set_typing(thread, False)
                await self._finish(thread, question)
            else:
                for channel, chat_id in self._targets(exclude_thread=thread):
                    self._questions[f"{channel}:{chat_id}"] = thread
                    await self._send(
                        channel,
                        chat_id,
                        self.say(
                            f"{self.muse_name} asks: {question}\n(Reply here to answer.)",
                            f"{self.muse_name} 问：{question}\n（直接回复即可。）",
                        ),
                    )
            return
        if kind == "notice" and ours and event.get("level") == "warn":
            await self._finish(thread, str(event.get("text") or ""))
            return
        if kind == "artifact" and ours and event.get("path"):
            self._artifacts.setdefault(thread, []).append(str(event["path"]))

    async def _run_ended(self, thread: str) -> None:
        live = self._live.get(thread)
        files = self._artifacts.pop(thread, [])
        paths: list[str] = []
        for rel in files:
            with contextlib.suppress(Exception):
                paths.append(str(self.svc.resolve_workspace_path(rel)))
        if live is not None and (live.text.strip() or live.shown):
            await self._finish(thread, live.text or live.shown, files=paths or None)
        else:
            self._live.pop(thread, None)
            if paths:
                await self._finish(thread, "", files=paths)
        await self._set_typing(thread, False)

    def _tool_label(self, event: dict[str, Any]) -> str:
        title = str(event.get("title") or "").strip()
        if title:
            return title
        tool = str(event.get("tool") or "")
        en, zh = _TOOL_LABELS.get(tool, (f"Using {tool}", f"正在使用 {tool}"))
        lang = self.lang
        return zh if lang == "zh" else en

    def approval_text(self, event: dict[str, Any]) -> str:
        summary = str(event.get("summary") or event.get("tool") or "")
        purpose = str(event.get("purpose") or "")
        why = f"\n({purpose})" if purpose else ""
        return self.say(
            f"{self.muse_name} needs your OK: {summary}{why}\nReply allow / deny.",
            f"{self.muse_name} 需要你确认：{summary}{why}\n回复「允许」或「拒绝」。",
        )

    async def _ask(self, channel: str, chat_id: str, approval_id: str, text: str) -> None:
        ch = self.channels.get(channel)
        if ch is None or not approval_id:
            return
        self._asks.setdefault(f"{channel}:{chat_id}", []).append(approval_id)
        try:
            await ch.ask(chat_id, approval_id, text)
        except Exception as exc:  # noqa: BLE001
            logger.warning("channel {}: could not ask {}: {}", channel, chat_id, exc)
            self._set(channel, "error", _short(exc))

    def _targets(self, exclude_thread: str = "") -> list[tuple[str, str]]:
        skip = self.routes.get(exclude_thread)
        return [
            (channel, chat_id)
            for channel, chat_id in self.pairing.deliver_targets()
            if channel in self.channels and (channel, chat_id) != skip
        ]

    async def deliver(self, text: str, *, exclude_thread: str = "") -> int:
        """Send ``text`` to every chat marked "deliver here"; returns how many got it."""
        n = 0
        for channel, chat_id in self._targets(exclude_thread):
            await self._send(channel, chat_id, text)
            n += 1
        return n

    # ------------------------------------------------------------------ settings & pairing
    def view(self) -> dict[str, Any]:
        channels = []
        for name, cls in self.types.items():
            cfg = self.store.config(name)
            status = self.status.get(name) or ChannelStatus()
            if name not in self.channels:
                if not cfg.enabled:
                    status = ChannelStatus("off")
                elif not cls.sdk_available():
                    status = ChannelStatus("missing_sdk", cls.install_hint())
                elif cls.missing(cfg.settings):
                    labels = {f.key: f.label for f in cls.fields}
                    status = ChannelStatus(
                        "unconfigured",
                        ", ".join(labels.get(k, k) for k in cls.missing(cfg.settings)),
                    )
                elif status.state not in ("error", "connecting"):
                    status = ChannelStatus("off")
            fields = []
            for f in cls.fields:
                item = f.to_dict()
                if f.kind == "secret":
                    item["has_value"] = self.store.has_secret(cfg, f.key)
                else:
                    value = cfg.settings.get(f.key, f.default)
                    item["value"] = value if isinstance(value, bool) else str(value or "")
                fields.append(item)
            paired = [
                {
                    "sender_id": sender_id,
                    "sender_name": entry.get("sender_name", ""),
                    "chat_id": entry.get("chat_id", sender_id),
                    "deliver": bool(entry.get("deliver")),
                    "approved_at": entry.get("approved_at"),
                    "thread": thread_id_for(name, str(entry.get("chat_id") or sender_id)),
                }
                for sender_id, entry in self.pairing.approved(name).items()
            ]
            channels.append(
                {
                    "name": name,
                    "label": cls.label,
                    "enabled": cfg.enabled,
                    "status": status.to_dict(),
                    "sdk_available": cls.sdk_available(),
                    "install": cls.install_hint(),
                    "console_url": cls.console_url,
                    "supports_edit": cls.supports_edit,
                    "fields": fields,
                    "allow_from": cfg.allow_from,
                    "group_policy": cfg.group_policy,
                    "paired": paired,
                    "login": name in self.logins,
                }
            )
        return {"channels": channels, "pending": self.pairing.pending()}

    async def update(self, name: str, body: dict[str, Any]) -> dict[str, Any]:
        if name not in self.types:
            raise KeyError(name)
        was_enabled = self.store.config(name).enabled
        cfg = self.store.update(
            self.types[name],
            enabled=body.get("enabled"),
            values=body.get("settings"),
            allow_from=body.get("allow_from"),
            group_policy=body.get("group_policy"),
        )
        # the allowlist and the group policy are read per message; only credentials and the
        # switch itself touch the connection
        reconnect = bool(body.get("settings")) or cfg.enabled != was_enabled
        if not cfg.enabled:
            await self.stop_channel(name)
        elif reconnect or name not in self.channels:
            await self.start_channel(name)
        self.publish()
        return self.view()

    async def reload(self) -> dict[str, Any]:
        """Settings or pairings were changed on disk (the CLI): start what is on now."""
        for name in self.types:
            cfg = self.store.config(name)
            if cfg.enabled and name not in self.channels:
                await self.start_channel(name)
            elif not cfg.enabled and name in self.channels:
                await self.stop_channel(name)
        self.publish()
        return self.view()

    async def approve(self, code: str) -> dict[str, Any] | None:
        entry = self.pairing.approve(code)
        if entry is None:
            return None
        self.publish()
        await self._send(
            entry["channel"],
            str(entry.get("chat_id") or entry["sender_id"]),
            self.say(
                f"Paired. This chat is now {self.muse_name}. Say what you need.",
                f"已配对。这里现在就是 {self.muse_name}，有事直接说。",
            ),
        )
        return entry

    async def deny(self, code: str) -> dict[str, Any] | None:
        info = self.pairing.deny(code)
        if info is not None:
            self.publish()
        return info

    def set_deliver(self, name: str, sender_id: str, on: bool) -> dict[str, Any] | None:
        entry = self.pairing.set_deliver(name, sender_id, on)
        if entry is not None:
            self.publish()
        return entry

    def remove_chat(self, name: str, sender_id: str) -> bool:
        ok = self.pairing.remove(name, sender_id)
        if ok:
            self.publish()
        return ok

    async def test(self, name: str, chat_id: str = "") -> dict[str, Any]:
        """Send a test message to a paired chat (the first one when none is given), or
        check the credentials when the channel has no paired chat yet."""
        channel = self.channels.get(name)
        if channel is None:
            status = self.status.get(name) or ChannelStatus()
            raise ValueError(
                status.detail or f"{self.types[name].label} is not running; switch it on first."
            )
        if not chat_id:
            paired = self.pairing.approved(name)
            first = next(iter(paired.values()), None)
            chat_id = str(first.get("chat_id") or "") if first else ""
        if not chat_id:
            about = await channel.verify()
            return {"ok": True, "detail": about or "The credentials work."}
        await channel.send(
            chat_id,
            self.say(
                f"Test message from {self.muse_name}: this chat is connected.",
                f"来自 {self.muse_name} 的测试消息：这个聊天已经连上了。",
            ),
        )
        return {"ok": True, "detail": f"Sent to {chat_id}."}

    # ------------------------------------------------------------------ Feishu QR login
    async def login_begin(self, name: str, domain: str = "feishu") -> dict[str, Any]:
        if name != "feishu":
            raise ValueError(
                "Only Feishu has a scan-to-create login; the others take an id and a secret."
            )
        from nanomuse.channels import feishu

        session = await asyncio.to_thread(feishu.login_begin, domain, self.muse_name)
        self.logins[name] = {**session, "domain": domain, "started": time.time()}
        self.publish()
        return dict(session)

    async def login_poll(self, name: str, device_code: str) -> dict[str, Any]:
        session = self.logins.get(name)
        if session is None or session.get("device_code") != device_code:
            raise KeyError(device_code)
        from nanomuse.channels import feishu

        result = await asyncio.to_thread(feishu.login_poll, device_code, session["domain"])
        if result.get("status") == "succeeded":
            self.logins.pop(name, None)
            self.store.update(
                self.types[name],
                enabled=True,
                values={
                    "app_id": result["app_id"],
                    "app_secret": result["app_secret"],
                    "domain": result.get("domain") or session["domain"],
                },
            )
            await self.start_channel(name)
            self.publish()
            return {"status": "succeeded", "app_id": result["app_id"]}
        if result.get("status") == "failed":
            self.logins.pop(name, None)
            self.publish()
        if time.time() - session.get("started", 0) > session.get("expires_in", 600):
            self.logins.pop(name, None)
            self.publish()
            return {"status": "failed", "error": "expired"}
        return result


def _short(exc: BaseException) -> str:
    text = str(exc).strip() or type(exc).__name__
    return text.splitlines()[0][:300]


__all__ = ["CHANNEL_TYPES", "ChannelManager", "thread_id_for"]

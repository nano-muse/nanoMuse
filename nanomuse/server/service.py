"""The always-on nanoMuse: threads, background workers, goals scheduler, ideas, profile.

This is the piece that keeps working after you close the app. It owns one
:class:`~nanomuse.app.NanoMuseApp` (LLM, tools, Sentinel, vault, memory, goals)
and runs one agent per *thread* — the main chat plus any side chats — so the
user can fire off several requests without waiting for the last one to finish.
"""

from __future__ import annotations

import asyncio
import json
import mimetypes
import re
import secrets
import time
import uuid
from collections.abc import Coroutine
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from datetime import time as time_of_day
from pathlib import Path
from typing import Any

from nanomuse import __version__, prompts
from nanomuse.agent import Incoming, MuseAgent
from nanomuse.app import NanoMuseApp
from nanomuse.avatar import AvatarStudio
from nanomuse.background import spawn
from nanomuse.bridge.server import Bridge
from nanomuse.cloud import model_url
from nanomuse.coding.service import CodingService
from nanomuse.config import Settings
from nanomuse.goals import Goal
from nanomuse.hub.service import HubService
from nanomuse.llm import BaseLLM
from nanomuse.llm.factory import llm_ready
from nanomuse.logger import logger
from nanomuse.memory.consolidate import TidyReport, tidy
from nanomuse.nudges import NudgesPolicy
from nanomuse.phone import PhoneLink
from nanomuse.reminders import Reminder
from nanomuse.schema import Attachment, Message, Role
from nanomuse.sentinel.grants import normalize_scope
from nanomuse.server import firstrun
from nanomuse.server.connections import Connections
from nanomuse.server.events import MAIN_THREAD, EventBus, Timeline, new_id, now_iso
from nanomuse.server.failures import failure_notice
from nanomuse.server.providers import ChatGPTSignIn, Providers
from nanomuse.server.push import PushService
from nanomuse.server.webui import WebUI, current_thread
from nanomuse.sync import ConversationSync, parse_mention, system_note
from nanomuse.tools.browser import Browser
from nanomuse.tools.coding_tool import CodingAgents
from nanomuse.tools.reminder_tools import Reminders
from nanomuse.tools.trigger_tools import Triggers
from nanomuse.triggers import MailWatcher, Trigger, matches

IDEAS_PROMPT = """You are {name}, the user's personal agent. Based on what you know about them, propose {n} concrete, genuinely useful things you could do for them right now. Prefer tasks you can actually complete with your tools (research, comparisons, planning, drafting, tracking, reminders, organising files, advancing their goals).

What you know:
{context}

Answer with a JSON array only, no prose. Each item: {{"title": "<short title, max 8 words>", "detail": "<one sentence on what you would do and why it helps>", "prompt": "<the exact request the user could send you to start>", "area": "<one of: planning, research, goals, money, health, home, learning, people, files, fun>", "kind": "<chat for a one-off conversation; routine for something to do every day at a time; goal for something long-term to track>", "time": "<HH:MM, routines only>", "category": "<goals only — one of: health, finance, career, learning, relationships, family, home, travel, creative, other>"}}. Mostly chat; at most one routine and one goal. Write in the user's language ({language})."""

# what tapping an idea does on every client: a message in the main chat, a daily routine
# (a repeating reminder with the prompt), or a goal conversation (the phone's IdeaKind)
IDEA_KINDS = ("chat", "routine", "goal")
IDEA_GOAL_CATEGORIES = (
    "health",
    "finance",
    "career",
    "learning",
    "relationships",
    "family",
    "home",
    "travel",
    "creative",
    "other",
)

IDEA_AREAS = (
    "planning",
    "research",
    "goals",
    "money",
    "health",
    "home",
    "learning",
    "people",
    "files",
    "fun",
)

FEED_PROMPT = """You are {name}, the user's personal agent, writing their personal feed: a few short posts made just for them, to read when they open the app. Think of a thoughtful friend who knows what they care about: a nudge on a goal, something worth knowing about a topic they follow, a small plan for the day, a question worth thinking about, a summary of something you noticed. Be specific to this person; never generic filler.

The user's feed instructions (what they want to read here, how often, in what tone):
{instructions}

What you know about them:
{context}

Write {n} posts. Answer with a JSON array only, no prose. Each item: {{"title": "<max 10 words>", "body": "<60-160 words of Markdown; short paragraphs or a list; no heading>", "area": "<one of: planning, research, goals, money, health, home, learning, people, files, fun>", "prompt": "<a request the user could send you to follow up, or empty>"}}. Write in the user's language ({language})."""

FEED_DEFAULT_TIME = "08:00"  # the daily routine, local time (contract C5)
FEED_MIN_GAP_HOURS = 4  # a batch asked for by hand shortly before the hour counts as the day's
FEED_RETRY_S = 3600  # after a failed batch (the model down), the next try an hour later
FEED_KEEP = 200
_FEED_TIME = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")


def _feed_time(value: Any) -> str:
    """``"8:00"`` → ``"08:00"``; anything that is not ``HH:MM`` → ``""``."""
    m = _FEED_TIME.match(str(value or "").strip())
    return f"{int(m.group(1)):02d}:{m.group(2)}" if m else ""


STARTER_IDEAS = [
    {
        "title": "Plan my week",
        "detail": "Tell me what's on your plate and I'll turn it into a realistic plan with the important things first.",
        "prompt": "Help me plan my week. Ask me what I need to get done, then propose a schedule.",
        "area": "planning",
        "kind": "chat",
    },
    {
        "title": "A morning brief",
        "detail": "Before you leave each morning: the weather, the first thing on your plate and anything new worth knowing.",
        "prompt": "Morning brief: check today's weather, read my calendar and reminders for today, and tell me in five lines what matters.",
        "area": "planning",
        "kind": "routine",
        "time": "07:30",
    },
    {
        "title": "Research & compare options",
        "detail": "Laptops, flights, insurance, a new phone plan — I'll gather the facts and compare them for you.",
        "prompt": "I need to make a purchase decision. Ask me what I'm choosing between, then research and compare the options.",
        "area": "research",
        "kind": "chat",
    },
    {
        "title": "Set up a long-term goal",
        "detail": "Share a goal (learn a language, run a 10k, save for a trip) and I'll break it into steps and keep track.",
        "prompt": "I want to set up a long-term goal. Ask me about it, then create a plan with concrete steps and track it.",
        "area": "goals",
        "kind": "goal",
        "category": "other",
    },
    {
        "title": "Tell me about yourself",
        "detail": "The more I know about your preferences, routines and constraints, the more useful I get. I'll remember what matters.",
        "prompt": "Ask me a few questions about myself so you can help me better, and remember the answers.",
        "area": "people",
        "kind": "chat",
    },
    {
        "title": "Build a quick tracker",
        "detail": "Spending, habits, workouts, reading — I can write a small script or document to track it for you.",
        "prompt": "Build me a simple tracker. Ask me what I want to track and how, then create it in the workspace.",
        "area": "files",
        "kind": "chat",
    },
]


PROACTIVITY = ("off", "low", "default", "high")

# identity limits and vocabularies (the app's forms and the identity tool share them)
NAME_MAX = 20
TAGLINE_MAX = 60
TONES: dict[str, str] = {
    "formal": "Tone: formal — polite and precise, no slang, no exclamation marks.",
    "casual": "Tone: casual — relaxed and friendly, the way a capable friend talks.",
    "playful": "Tone: playful — light and a little witty, never at the expense of being clear.",
    "concise": "Tone: concise — say what matters, then stop; no preamble, no recap.",
}
COMMUNICATION: dict[str, str] = {
    "short": "Length: keep replies short — a few sentences, one or two paragraphs at most, unless asked for more.",
    "detailed": "Length: be thorough — give the reasoning, the alternatives and what you ruled out.",
    "bullets": "Shape: prefer bullet points and short headings over running prose; one idea per line.",
}
# how the configured interval stretches or shrinks per level
_INTERVAL_FACTOR = {"low": 2.0, "default": 1.0, "high": 0.5}
_QUIET_HOURS_RE = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)-([01]?\d|2[0-3]):([0-5]\d)$")
# A thread id arrives over the WebSocket and names a file in the threads folder, so it
# carries no separator: the same rule as channels' thread_id_for, whose longest id is
# "channel-" plus an 80-character chat id.
_THREAD_ID_RE = re.compile(r"[A-Za-z0-9_.-]{1,128}")
# how long `stop()` lets a cancelled worker take to settle before closing over its work
_SHUTDOWN_GRACE_S = 5.0


@dataclass
class Profile:
    name: str = "nanoMuse"
    # the face: "dragon" (the one the Android app wears; stills per mood), a face drawn in
    # the avatar studio (its id names files under the workspace), or "" for the emoji; the
    # red panda and the dolls of 0.1.22 are gone — a profile naming one wears the dragon
    avatar: str = "dragon"
    emoji: str = "✨"
    color: str = "#0064d4"
    # one line under the name, the way Muse shows it ("Your day, sorted.")
    tagline: str = ""
    # how it talks: a tone (formal · casual · playful · concise), a length or shape of reply
    # (short · detailed · bullets) and free text; each becomes its own paragraph of the prompt
    tone: str = ""
    communication: str = ""
    style: str = ""
    # what the user wants to be called
    user_name: str = ""
    # how eagerly background work runs and reaches out: off · low · default · high
    proactivity: str = "default"
    goal_interval_minutes: int = 60
    # "22:00-08:00" (server local time): no background passes in this window
    quiet_hours: str = ""

    @property
    def proactive(self) -> bool:
        return self.proactivity != "off"

    @property
    def interval_seconds(self) -> int:
        factor = _INTERVAL_FACTOR.get(self.proactivity, 1.0)
        return max(60, int(self.goal_interval_minutes * 60 * factor))

    def in_quiet_hours(self, now: datetime | None = None) -> bool:
        window = _parse_quiet_hours(self.quiet_hours)
        if window is None:
            return False
        start, end = window
        local = (now or datetime.now()).astimezone()
        minute = local.hour * 60 + local.minute
        if start <= end:
            return start <= minute < end
        return minute >= start or minute < end  # wraps midnight

    def quiet_hours_end(self, now: datetime | None = None) -> datetime | None:
        """When the current quiet window ends, or None if we are not in one."""
        if not self.in_quiet_hours(now):
            return None
        _, end = _parse_quiet_hours(self.quiet_hours)  # type: ignore[misc]
        now = (now or datetime.now()).astimezone()
        candidate = now.replace(hour=end // 60, minute=end % 60, second=0, microsecond=0)
        if candidate <= now:
            candidate += timedelta(days=1)
        return candidate

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "avatar": self.avatar,
            "emoji": self.emoji,
            "color": self.color,
            "tagline": self.tagline,
            "tone": self.tone,
            "communication": self.communication,
            "style": self.style,
            "user_name": self.user_name,
            "proactivity": self.proactivity,
            "proactive": self.proactive,
            "goal_interval_minutes": self.goal_interval_minutes,
            "quiet_hours": self.quiet_hours,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Profile:
        p = cls()
        for k, v in data.items():
            if k != "proactive" and hasattr(p, k) and v is not None:
                setattr(p, k, v)
        if "proactivity" not in data and "proactive" in data:
            # profiles written before the dial existed
            p.proactivity = "default" if data["proactive"] else "off"
        if p.proactivity not in PROACTIVITY:
            p.proactivity = "default"
        p.name = (str(p.name).strip() or "nanoMuse")[:NAME_MAX]
        if "avatar" not in data:
            # a profile from before the dolls: keep the emoji it has
            p.avatar = ""
        p.avatar = re.sub(r"[^a-z0-9-]", "", str(p.avatar).lower())[:32]
        p.emoji = str(p.emoji)[:8] or "✨"
        p.color = str(p.color)[:16] or "#0064d4"
        p.tagline = " ".join(str(p.tagline).split())[:TAGLINE_MAX]
        p.tone = str(p.tone).strip().lower()
        if p.tone not in TONES:
            p.tone = ""
        p.communication = str(p.communication).strip().lower()
        if p.communication not in COMMUNICATION:
            p.communication = ""
        p.style = str(p.style)[:1000]
        p.user_name = str(p.user_name).strip()[:60]
        p.goal_interval_minutes = max(5, min(int(p.goal_interval_minutes), 24 * 60))
        p.quiet_hours = str(p.quiet_hours).strip()
        if p.quiet_hours and _parse_quiet_hours(p.quiet_hours) is None:
            p.quiet_hours = ""
        return p


def _parse_quiet_hours(value: str) -> tuple[int, int] | None:
    m = _QUIET_HOURS_RE.match(value.strip()) if value else None
    if not m:
        return None
    start = int(m.group(1)) * 60 + int(m.group(2))
    end = int(m.group(3)) * 60 + int(m.group(4))
    return (start, end) if start != end else None


@dataclass
class Thread:
    id: str
    title: str
    created_at: str
    updated_at: str
    timeline: Timeline
    agent: MuseAgent
    inbox: asyncio.Queue[str | Incoming] = field(default_factory=asyncio.Queue)
    worker: asyncio.Task[None] | None = None
    stopping: bool = False
    busy: bool = False
    # background prompts (goal work, ideas) → the short label shown as the approval purpose
    purposes: dict[str, str] = field(default_factory=dict)
    # a chat addressed to another device of the account: what is typed here runs there
    device: str | None = None
    device_name: str = ""
    # a chat another device opened here with a `task` over the hub: who asked
    remote_from: dict[str, Any] | None = None
    # a chat that came in through conversation sync (contract C7): the device that started
    # it, for the "From Pixel 8" badge; "" for chats started here
    origin_device: str = ""
    origin_device_name: str = ""
    # the main chat of another account of this device (contract C10): kept while someone
    # else is signed in, hidden from them, back as `main` when that account returns
    main_of: str = ""

    def meta(self) -> dict[str, Any]:
        meta: dict[str, Any] = {
            "id": self.id,
            "title": self.title,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "busy": self.busy,
            "queued": self.inbox.qsize(),
            "events": len(self.timeline.events),
        }
        if self.device:
            meta["device"] = self.device
            meta["device_name"] = self.device_name
        if self.remote_from:
            meta["remote_from"] = self.remote_from
        if self.origin_device:
            meta["origin_device"] = self.origin_device
            meta["origin_device_name"] = self.origin_device_name
        if self.main_of:
            meta["main_of"] = self.main_of
        return meta


def _parse_when(value: str | None) -> datetime | None:
    """An ISO timestamp from a store → aware datetime (naive ones are local), or None."""
    if not value:
        return None
    try:
        when = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return when.astimezone()  # a naive stamp is local time


class MuseService:
    def __init__(self, settings: Settings, llm: BaseLLM | None = None):
        self.settings = settings
        settings.ensure_dirs()
        self.data_dir: Path = settings.data_dir
        self.threads_dir = self.data_dir / "threads"
        self.threads_dir.mkdir(parents=True, exist_ok=True)
        self.bus = EventBus()
        self.threads: dict[str, Thread] = {}
        self._base_instructions = settings.agent.instructions
        self.profile = self._load_profile()
        self._apply_profile()
        self.ui = WebUI(
            self.bus,
            self.timeline,
            approval_timeout=settings.server.approval_timeout,
            show_thinking=settings.agent.show_thinking,
            workspace=settings.agent.workspace.resolve(),
            exclude=(settings.data_dir,),
        )
        self.ui._timelines_provider = lambda: [(t.id, t.timeline) for t in self.threads.values()]
        self.push = PushService(settings.data_dir)
        self.ui.on_event = self._maybe_push
        # The phone: whichever device announces itself on the WebSocket (see nanomuse.phone).
        self.phone = PhoneLink(
            timeout_s=settings.gui.device_timeout_s,
            shots_dir=settings.agent.workspace.resolve() / "screenshots",
        )
        self.phone.on_change = self.publish_phone
        self.app = NanoMuseApp(settings, ui=self.ui, llm=llm, session_id="app", phone=self.phone)
        # a hold belongs to the chat whose run is acting (docs/browser.md, contract C1)
        self.app.holds.thread_of = current_thread.get
        # The CLI bridge: `nanomuse-device` and friends, from inside a shell command. It
        # learns where the server listens in `serve()`; until then no token is minted.
        self.bridge = Bridge(self.app.tools, self.app.sentinel, self.ui)
        for name in ("shell", "python_execute"):
            tool = self.app.tools.get(name)
            if tool is not None:
                tool.bridge = self.bridge  # type: ignore[attr-defined]
        self.watch_browser()
        self._watch_reminders()
        self._mail_polled_at: float | None = None
        self._fired_pruned_at: float | None = None
        self.mail_checked_at: str | None = None
        self.mail_watch_error = ""
        self._watch_triggers()
        self.connections = Connections(self)
        # this computer on the hub: the Cloud account, the other devices, their side chats
        self.hub = HubService(self)
        # the same conversations on every device of the account (contract C7; docs/every-device.md)
        self.sync = ConversationSync(self)
        # when the app may ask for a star on GitHub: the relay's policy, a day at a time
        # (contract C1; GET /api/nudges hands it to the web app)
        self.nudges = NudgesPolicy(self.data_dir, settings.cloud.base_url)
        # the first conversation (contract C4): bound to the main chat by Start, the model
        # hears its phase there and nowhere else (docs/web.md)
        self.firstrun = firstrun.FirstRunStore(self.data_dir)
        # a new face from a description, drawn on the chat model's host (docs/avatar.md)
        self.avatar = AvatarStudio(self)
        # the catalogue with what is configured and what that covers (contract C11), and the
        # ChatGPT sign-in run from the app (GET /api/providers, /api/chatgpt/*)
        self.providers = Providers(self)
        self.chatgpt = ChatGPTSignIn(self)
        self.coding = CodingService(self)
        self.app.tools.add(CodingAgents(coding=self.coding))
        self.token = self._load_token()
        self._scheduler: asyncio.Task[None] | None = None
        # what start() is busy with, for /api/health and the log while the app comes up
        self.starting: str = "not started"
        self._tidying = False
        self._writing_feed = False
        self._feed_failed_at: float | None = None
        self._started = False
        self.started_at = now_iso()
        self.next_goal_pass_at: datetime | None = None
        # the scheduler naps on this: `wake()` (POST /api/tick — the phone's alarm) ends the
        # nap early so what is due runs now, not at the end of the nap
        self._wake = asyncio.Event()
        self._announced_wake: str | None = None
        self._load_threads()

    def phone_view(self) -> dict[str, Any]:
        return {**self.phone.status(), "gui_enabled": self.settings.gui.enabled}

    def publish_phone(self) -> None:
        self.bus.publish({"kind": "phone", "phone": self.phone_view()})

    def hands_view(self) -> dict[str, Any]:
        return self.connections.hands_view()

    def publish_hands(self) -> None:
        self.bus.publish({"kind": "hands_state", "hands": self.hands_view()})

    def stop_hands(self) -> bool:
        """The Stop button of the Hands card: the task on this computer's screen ends at its
        next step, like the phone's Stop pill."""
        computer = self.app.computer
        return computer.stop() if computer is not None else False

    # ------------------------------------------------------------------ lifecycle
    async def start(self) -> None:
        """Bring the services up, one logged step at a time. A step that stalls (an MCP
        server that never answers, a relay that cannot be reached through a broken proxy)
        is given up after its timeout with a warning, so that the app still opens."""
        if self._started:
            return
        started = time.monotonic()
        await self._step("tools", self.app.start(), 90)
        self._started = True
        await self._step("cloud account and hub", self.hub.start(), 30)
        self.sync.start()
        self._scheduler = asyncio.create_task(self._goal_scheduler(), name="goal-scheduler")
        self.starting = ""
        logger.info(
            "MuseService started ({} threads, {:.1f}s)",
            len(self.threads),
            time.monotonic() - started,
        )

    async def _step(self, name: str, work: Coroutine[Any, Any, Any], timeout: float) -> None:
        self.starting = name
        logger.info("starting: {}", name)
        try:
            await asyncio.wait_for(work, timeout)
        except TimeoutError:
            logger.warning(
                "starting: {} did not finish in {:.0f}s; going on without it", name, timeout
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("starting: {} failed: {}: {}", name, type(exc).__name__, exc)

    async def stop(self) -> None:
        if self._scheduler:
            self._scheduler.cancel()
        loop = asyncio.get_running_loop()
        workers: list[asyncio.Task[None]] = []
        for t in self.threads.values():
            work = t.worker
            if work is None or work.done() or work.get_loop() is not loop:
                # nothing to wait for, or a task of a loop that is already closed (an app
                # built twice in one process, as a test does): cancelling it means nothing
                # and waiting on it would raise across the loops
                continue
            work.cancel()
            workers.append(work)
        if workers:
            # cancelled is not finished: a worker still runs its own settling once the
            # CancelledError lands — the stopped notice, the timeline, the store — and doing
            # that after the flushes and the closes below is the "Exception ignored ... during
            # shutdown" of the log. Wait, but only so long: a worker wedged in a provider
            # response must not hold the exit.
            try:
                await asyncio.wait_for(
                    asyncio.gather(*workers, return_exceptions=True),
                    _SHUTDOWN_GRACE_S,
                )
            except TimeoutError:
                logger.warning(
                    "shutdown: {} worker(s) were still running after {:.0f}s; closing over their work",
                    len(workers),
                    _SHUTDOWN_GRACE_S,
                )
        for t in self.threads.values():
            t.timeline.flush()
        await self.chatgpt.close()
        if self._started:
            await self.sync.stop()
            await self.coding.close()
            await self.avatar.close()
            await self.hub.stop()
            await self.connections.close()
            await self.app.close()
        self._started = False

    # ------------------------------------------------------------------ token / profile
    def _load_token(self) -> str:
        if not self.settings.server.auth:
            return ""
        if self.settings.server.token:
            return self.settings.server.token
        path = self.data_dir / "server_token"
        if path.exists():
            tok = path.read_text("utf-8").strip()
            if tok:
                return tok
        tok = secrets.token_urlsafe(18)
        path.write_text(tok, "utf-8")
        try:
            path.chmod(0o600)
        except OSError:  # pragma: no cover
            pass
        return tok

    def _load_profile(self) -> Profile:
        path = self.data_dir / "profile.json"
        if path.exists():
            try:
                return Profile.from_dict(json.loads(path.read_text("utf-8")))
            except (OSError, json.JSONDecodeError, ValueError):
                pass
        return Profile(name=self.settings.agent.name)

    def _save_profile(self) -> None:
        (self.data_dir / "profile.json").write_text(
            json.dumps(self.profile.to_dict(), ensure_ascii=False, indent=1), "utf-8"
        )

    def _apply_profile(self) -> None:
        a = self.settings.agent
        a.name = self.profile.name
        extra = ""
        if self.profile.user_name:
            extra += (
                f"\nThe user's name is {self.profile.user_name}; address them by it when natural."
            )
        if self.profile.tagline.strip():
            extra += f"\nYour tagline, the line under your name in the app: {self.profile.tagline.strip()!r}"
        # each choice is its own paragraph, so a change to one leaves the others alone
        if self.profile.tone in TONES:
            extra += "\n\n" + TONES[self.profile.tone]
        if self.profile.communication in COMMUNICATION:
            extra += "\n\n" + COMMUNICATION[self.profile.communication]
        if self.profile.style.strip():
            extra += (
                "\n\nYour personality / style, in the user's own words: "
                + self.profile.style.strip()
            )
        a.instructions = (self._base_instructions.rstrip() + extra).strip()

    def update_profile(self, data: dict[str, Any]) -> Profile:
        data = {k: v for k, v in data.items() if v is not None}
        if "proactive" in data and "proactivity" not in data:
            # the old switch: off, or back to the default level
            data["proactivity"] = (
                "off"
                if not data["proactive"]
                else (self.profile.proactivity if self.profile.proactive else "default")
            )
        data.pop("proactive", None)
        merged = {**self.profile.to_dict(), **data}
        merged.pop("proactive", None)
        before = (
            self.profile.proactivity,
            self.profile.goal_interval_minutes,
            self.profile.quiet_hours,
        )
        look_before = (
            self.profile.name,
            self.profile.avatar,
            self.profile.emoji,
            self.profile.color,
        )
        self.profile = Profile.from_dict(merged)
        if before != (
            self.profile.proactivity,
            self.profile.goal_interval_minutes,
            self.profile.quiet_hours,
        ):
            self.schedule_next_pass()
        self._save_profile()
        self._apply_profile()
        self.bus.publish({"kind": "profile", "profile": self.profile.to_dict()})
        if look_before != (
            self.profile.name,
            self.profile.avatar,
            self.profile.emoji,
            self.profile.color,
        ):
            # the account's other devices wear the same name and face
            self.hub.profile.changed()
        return self.profile

    # ------------------------------------------------------------------ first conversation (C4)
    def firstrun_lang(self, lang: str = "") -> str:
        """The language of the opening: the one asked for, else the one Start was pressed in,
        else the agent's reply language."""
        return lang.strip() or self.firstrun.state.lang or self.ui_language()

    def firstrun_view(self, lang: str = "", intro: bool = False) -> dict[str, Any]:
        """``GET /api/firstrun`` and the ``firstrun`` frame: the state and the chips; with
        ``intro``, the three lines the app speaks first, in ``lang``."""
        view = self.firstrun.view(self.firstrun_lang(lang))
        if intro:
            view["intro"] = firstrun.intro_lines(self.firstrun_lang(lang))
        return view

    def _publish_firstrun(self) -> None:
        self.bus.publish({"kind": "firstrun", "firstrun": self.firstrun_view()})

    def _firstrun_addendum_for(self, thread_id: str):  # noqa: ANN202 - a closure for the agent
        def addendum() -> str:
            state = self.firstrun.state
            if not firstrun.bound_to(state, thread_id):
                return ""
            return firstrun.prompt_addendum(state, self.firstrun_lang(), self.profile.name) or ""

        return addendum

    def start_first_conversation(self, lang: str = "") -> dict[str, Any]:
        """Start was pressed: the main chat is bound as the first conversation and the
        setup counts as finished (what ``POST /api/onboarded`` records). The app speaks
        first there, from the browser, at no cost in tokens; the model only hears from the
        person. A main chat that already holds a conversation (synced from another device
        of the account, or an older install) is not begun again: no opening, no name to
        choose — the thread simply continues."""
        self.connections.set_onboarded(True)
        state = self.firstrun.state
        main = self.threads.get(MAIN_THREAD)
        underway = main is not None and any(
            e.get("type") in ("user", "assistant") for e in main.timeline.events
        )
        if state.phase != "done":
            base = replace(state, phase="done" if underway else "none")
        else:
            base = state
        lang = lang.strip().lower()
        lang = "zh" if lang.startswith("zh") else ("en" if lang else "")
        self.firstrun.save(firstrun.start_conversation(base, MAIN_THREAD, lang))
        self._publish_firstrun()
        if underway:
            self.first_feed_day()
        return self.firstrun_view(intro=True)

    def pick_first_name(self, name: str) -> dict[str, Any]:
        """A chip was picked on the chooser: the name is on the header before the model has
        even replied; the web then sends the name as the person's message, and the ``named``
        addendum tells the model what happened. :class:`LookupError` when no pick is due."""
        nxt = firstrun.pick_name(self.firstrun.state, name)
        if nxt is None:
            raise LookupError("no name is being chosen right now")
        self.firstrun.save(nxt)
        self.update_profile({"name": name})
        self._publish_firstrun()
        return self.firstrun_view()

    def dismiss_first_chooser(self) -> dict[str, Any]:
        """The person moved on to something the app handles itself: the chooser goes."""
        state = self.firstrun.state
        nxt = firstrun.dismiss_chooser(state)
        if nxt is not state:
            self.firstrun.save(nxt)
            self._publish_firstrun()
            self.first_feed_day()
        return self.firstrun_view()

    def _firstrun_turn_ended(self, thread_id: str, final: str) -> None:
        """The model's reply in the first conversation ended: read its block, move the
        phase, keep what it said — the address on the profile and as the memory line the
        phones write, the name on the profile."""
        state = self.firstrun.state
        if not firstrun.bound_to(state, thread_id) or not firstrun.running(state):
            return
        outcome = firstrun.after_turn(state, final)
        if outcome.state is state:
            return
        self.firstrun.save(outcome.state)
        if outcome.address_given:
            self.update_profile({"user_name": outcome.address_given})
            self._remember_address(outcome.address_given)
        if outcome.named:
            self.update_profile({"name": outcome.named})
        self._publish_firstrun()
        if firstrun.conversation_over(outcome.state):
            # the feed's first day is written once the first conversation is over
            self.first_feed_day()

    def _remember_address(self, address: str) -> None:
        """ "Call them: X" under what is known about the user: one memory, replaced when it
        changes (the phones keep the line under ``## About the user``; the runtime keeps
        memories as items, so the line is one item)."""
        store = self.app.memory
        if store is None:
            return
        line = firstrun.address_line(address)
        try:
            for item in store.all():
                if item.content.lower().startswith(firstrun.ADDRESS_PREFIX.lower()):
                    store.forget(item.id)
            store.add(line, category="profile", source="agent")
        except Exception as exc:  # noqa: BLE001 - the profile already holds the name
            logger.warning("could not remember the address: {}", exc)
        self.bus.publish({"kind": "memory"})

    # ------------------------------------------------------------------ threads
    def _load_threads(self) -> None:
        index = self.threads_dir / "index.json"
        metas: list[dict[str, Any]] = []
        if index.exists():
            try:
                metas = json.loads(index.read_text("utf-8"))
            except (OSError, json.JSONDecodeError):
                metas = []
        if not any(m.get("id") == MAIN_THREAD for m in metas):
            metas.insert(0, {"id": MAIN_THREAD, "title": "Main chat", "created_at": now_iso()})
        for m in metas:
            tid = str(m.get("id") or "")
            if not _THREAD_ID_RE.fullmatch(tid):
                # an id the app would refuse now: drop the line rather than refuse to start
                logger.warning("threads index: ignoring the entry with the id {!r}", tid)
                continue
            thread = self._make_thread(
                tid, m.get("title", tid), m.get("created_at"), m.get("updated_at")
            )
            if m.get("device"):
                thread.device = str(m["device"])
                thread.device_name = str(m.get("device_name") or m["device"])
            if isinstance(m.get("remote_from"), dict):
                thread.remote_from = dict(m["remote_from"])
            if m.get("origin_device"):
                thread.origin_device = str(m["origin_device"])
                thread.origin_device_name = str(m.get("origin_device_name") or "")
            if m.get("main_of"):
                thread.main_of = str(m["main_of"])
        self._save_index()

    def _save_index(self) -> None:
        metas = []
        for t in self.threads.values():
            m: dict[str, Any] = {
                "id": t.id,
                "title": t.title,
                "created_at": t.created_at,
                "updated_at": t.updated_at,
            }
            if t.device:
                m["device"] = t.device
                m["device_name"] = t.device_name
            if t.remote_from:
                m["remote_from"] = t.remote_from
            if t.origin_device:
                m["origin_device"] = t.origin_device
                m["origin_device_name"] = t.origin_device_name
            if t.main_of:
                m["main_of"] = t.main_of
            metas.append(m)
        (self.threads_dir / "index.json").write_text(
            json.dumps(metas, ensure_ascii=False, indent=1), "utf-8"
        )

    def _thread_file(self, thread_id: str, suffix: str) -> Path:
        """The file a thread id names: checked, not escaped, because the id is something a
        client sends and it would otherwise choose where the thread's data lives."""
        if not _THREAD_ID_RE.fullmatch(str(thread_id)):
            raise ValueError(f"invalid thread id: {thread_id}")
        path = (self.threads_dir / f"{thread_id}{suffix}").resolve()
        if path.parent != self.threads_dir.resolve():
            raise ValueError(f"invalid thread id: {thread_id}")
        return path

    def _make_thread(
        self,
        thread_id: str,
        title: str,
        created_at: str | None = None,
        updated_at: str | None = None,
    ) -> Thread:
        timeline = Timeline(thread_id, self._thread_file(thread_id, ".json"))
        # Cards that were waiting for an answer when the server stopped can't be answered
        # any more: the agent run behind them is gone.
        stale = [
            ev
            for ev in timeline.events
            if ev.get("type") in ("approval", "question") and ev.get("status") == "pending"
        ]
        for ev in stale:
            timeline.update(ev["id"], status="expired")
        running = [
            ev
            for ev in timeline.events
            if ev.get("type") == "tool" and ev.get("status") == "running"
        ]
        for ev in running:
            timeline.update(ev["id"], status="error", output="interrupted by a restart")
        for ev in timeline.events:
            if ev.get("type") in ("browser", "hands") and ev.get("status") == "live":
                timeline.update(ev["id"], status="done")
            # a hold lives in memory: after a restart nothing waits on it any more
            if ev.get("type") == "hold" and ev.get("status") == "on":
                timeline.update(ev["id"], status="off", stale=True)
        session_file = self._thread_file(thread_id, ".session.json")
        agent = MuseAgent(
            settings=self.settings,
            llm=self.app.llm,
            tools=self.app.tools,
            sentinel=self.app.sentinel,
            ui=self.ui,
            audit=self.app.audit,
            memory=self.app.memory,
            goals=self.app.goals,
            calendar=self.app.calendar,
            contacts=self.app.contacts,
            skills=self.app.skills,
            session_file=session_file,
            conversation_id=thread_id,
        )
        if session_file.exists():
            try:
                agent.load_session(session_file)
            except (OSError, ValueError) as exc:
                logger.warning("could not restore session for {}: {}", thread_id, exc)
        thread = Thread(
            id=thread_id,
            title=title,
            created_at=created_at or now_iso(),
            updated_at=updated_at or created_at or now_iso(),
            timeline=timeline,
            agent=agent,
        )
        self.threads[thread_id] = thread
        return thread

    def timeline(self, thread_id: str) -> Timeline:
        thread = self.threads.get(thread_id)
        if thread is None:
            thread = self._make_thread(thread_id, thread_id)
            self._save_index()
        return thread.timeline

    def create_thread(self, title: str = "") -> Thread:
        tid = "t_" + uuid.uuid4().hex[:8]
        thread = self._make_thread(tid, title.strip() or "Side chat")
        self._save_index()
        self.bus.publish({"kind": "thread", "thread": thread.meta()})
        self.sync.thread_changed(thread)
        return thread

    def ui_language(self) -> str:
        """``zh`` when the agent is told to answer in Chinese, else ``en`` — the two languages
        the runtime's own sentences come in."""
        language = str(self.settings.agent.language or "").lower()
        return "zh" if language.startswith(("中文", "zh", "chinese", "简体", "繁體")) else "en"

    def visible_threads(self) -> list[Thread]:
        """The conversation list (contract C10): signed in, the account's conversations and
        the ones no account has; signed out, every local one. Hidden ones stay on disk."""
        return [t for t in self.threads.values() if self.sync.visible(t)]

    def rehome_main(self, owner: str, restore: str | None, keep: bool = True) -> Thread | None:
        """A different account signed in (C10): the main chat so far is put aside under a new
        id, marked as ``owner``'s (``keep``; dropped when it is empty and nobody's), and
        ``restore`` — the thread holding the new account's main chat, when it has one — takes
        the ``main`` id back; otherwise a fresh main chat begins. Returns the thread the old
        main chat became, or None when it was dropped."""
        main = self.threads.get(MAIN_THREAD)
        if main is None:
            return None
        if main.busy:
            self.stop_thread(MAIN_THREAD)
        archived = self._move_thread(main, "t_" + uuid.uuid4().hex[:8]) if keep else None
        if archived is not None:
            archived.main_of = owner
        else:
            self._drop_thread(main)
        if restore and restore in self.threads:
            kept = self.threads[restore]
            fresh = self._move_thread(kept, MAIN_THREAD)
            fresh.main_of = ""
            self.bus.publish({"kind": "thread_deleted", "thread": restore})
        else:
            fresh = self._make_thread(MAIN_THREAD, "Main chat")
        self._save_index()
        # the list changed shape: the apps reload it from the snapshot
        if archived is not None:
            self.bus.publish({"kind": "thread", "thread": archived.meta()})
        self.bus.publish({"kind": "thread_cleared", "thread": MAIN_THREAD})
        self.bus.publish({"kind": "thread", "thread": fresh.meta()})
        return archived

    def _drop_thread(self, thread: Thread) -> None:
        """Forget a thread and its files without the sync tombstone (the main chat put aside)."""
        self.threads.pop(thread.id, None)
        if thread.worker:
            thread.worker.cancel()
        for p in (thread.timeline.path, thread.agent.session_file):
            if p and Path(p).exists():
                Path(p).unlink()
        self.app.holds.clear_thread(thread.id)
        self.app.sentinel.end_conversation(thread.id)

    def _move_thread(self, thread: Thread, new_id: str) -> Thread:
        """The same conversation under another id: its timeline and the agent's transcript
        move file by file and the thread is rebuilt from them (the events say the new id)."""
        self.threads.pop(thread.id, None)
        if thread.worker:
            thread.worker.cancel()
        for ev in thread.timeline.events:
            ev["thread"] = new_id
        thread.timeline.save()
        thread.timeline.flush()
        thread.agent._save_session()
        self.app.holds.clear_thread(thread.id)
        self.app.sentinel.end_conversation(thread.id)
        pairs = (
            (thread.timeline.path, self._thread_file(new_id, ".json")),
            (thread.agent.session_file, self._thread_file(new_id, ".session.json")),
        )
        # a write still on its way to disk lands under the new id, not the old one
        thread.timeline.path = pairs[0][1]
        for src, dst in pairs:
            if src is None:
                continue
            src_path = Path(src)
            if dst.exists():
                dst.unlink()
            if src_path.exists():
                src_path.replace(dst)
        moved = self._make_thread(new_id, thread.title, thread.created_at, thread.updated_at)
        moved.device, moved.device_name = thread.device, thread.device_name
        moved.remote_from = thread.remote_from
        moved.origin_device, moved.origin_device_name = (
            thread.origin_device,
            thread.origin_device_name,
        )
        moved.main_of = thread.main_of
        self.ui.last_assistant_text.pop(thread.id, None)
        return moved

    def rename_thread(self, thread_id: str, title: str) -> Thread | None:
        thread = self.threads.get(thread_id)
        if thread is None:
            return None
        thread.title = title.strip() or thread.title
        thread.updated_at = now_iso()
        self._save_index()
        self.bus.publish({"kind": "thread", "thread": thread.meta()})
        self.sync.thread_changed(thread)
        return thread

    def delete_thread(self, thread_id: str) -> bool:
        if thread_id == MAIN_THREAD:
            return False
        thread = self.threads.pop(thread_id, None)
        if thread is None:
            return False
        if thread.worker:
            thread.worker.cancel()
        for p in (thread.timeline.path, thread.agent.session_file):
            if p and Path(p).exists():
                Path(p).unlink()
        self.app.holds.clear_thread(thread_id)
        self.app.sentinel.end_conversation(thread_id)
        self._save_index()
        self.bus.publish({"kind": "thread_deleted", "thread": thread_id})
        self.sync.thread_deleted(thread_id)
        return True

    def stop_thread(self, thread_id: str) -> bool:
        """The stop button: end the run in progress and drop what was queued behind it.
        The conversation stays; a pending approval or question closes unanswered."""
        thread = self.threads.get(thread_id)
        if thread is not None and thread.device and thread.busy:
            spawn(self.hub.stop_remote(thread), "stopping the remote run")
            return True
        if thread is None or not thread.busy or thread.worker is None or thread.worker.done():
            return False
        while not thread.inbox.empty():
            thread.inbox.get_nowait()
        for ev in list(thread.timeline.tail(50)):
            if ev.get("type") in ("approval", "question") and ev.get("status") == "pending":
                self.ui.patch(thread_id, ev["id"], status="expired")
        thread.stopping = True
        thread.worker.cancel()
        return True

    def _settle_stopped(self, thread: Thread) -> None:
        """After a cancelled run: the transcript must not end on a tool call the model never
        saw answered, and the agent goes back to idle so the next message runs cleanly."""
        agent = thread.agent
        msgs = agent.messages
        while msgs and msgs[-1].role == Role.TOOL:
            msgs.pop()
        if msgs and msgs[-1].role == Role.ASSISTANT and msgs[-1].tool_calls:
            for tc in msgs[-1].tool_calls:
                msgs.append(
                    Message.tool("Stopped by the user before this ran.", tc.id, tc.function.name)
                )
        agent.state = agent.state.__class__.IDLE
        agent._save_session()
        thread.stopping = False
        self.ui.emit({"type": "notice", "level": "info", "text": "Stopped.", "thread": thread.id})

    def clear_thread(self, thread_id: str) -> bool:
        thread = self.threads.get(thread_id)
        if thread is None or thread.busy:
            return False
        thread.timeline.clear()
        thread.agent.reset()
        thread.agent._save_session()
        self.app.holds.clear_thread(thread_id)
        self.app.sentinel.end_conversation(thread_id)
        self.bus.publish({"kind": "thread_cleared", "thread": thread_id})
        return True

    # ------------------------------------------------------------------ messaging
    def send(
        self,
        thread_id: str,
        text: str,
        source: str = "user",
        label: str = "",
        files: list[str] | None = None,
    ) -> dict[str, Any]:
        """Queue a message for a thread. Returns the timeline event that was created.

        ``files`` are workspace paths of attachments (uploaded first with ``save_upload``);
        a message may be attachments alone."""
        text = text.strip()
        attachments = [self.attachment(path) for path in files or []]
        if not text and not attachments:
            raise ValueError("empty message")
        thread = self.threads.get(thread_id) or self._make_thread(thread_id, thread_id)
        thread.updated_at = now_iso()
        if thread.device:
            # a chat addressed to another device: the text runs there, not here
            if thread.busy:
                raise ValueError(f"{thread.device_name or 'the device'} is still busy")
            event = self.ui.emit({"type": "user", "text": text, "thread": thread_id})
            self.hub.run_remote(thread, text)
            return event
        if source in ("user", "device"):
            event_data: dict[str, Any] = {"type": "user", "text": text, "thread": thread_id}
            if attachments:
                event_data["files"] = [a.model_dump() for a in attachments]
            if source == "device":
                # asked by another device over the hub; shown as a bubble with its name
                event_data["via"] = label
                thread.purposes[text] = f"asked from {label}" if label else "asked from a device"
            note = ""
            if source == "user" and text.startswith("@"):
                # "@Pixel 8 open the calendar": the work is for that device (contract C7, rule
                # 8). The bubble shows the text without the mention and whom it is for; the
                # agent gets one system note in front and hands the task over with `delegate`.
                mention = parse_mention(text, self.hub.others(), self.hub.device_id)
                if mention is not None and (mention.text or attachments):
                    text = mention.text
                    event_data["text"] = text
                    event_data["to_device"] = mention.device_id
                    event_data["to_device_name"] = mention.device_name
                    note = system_note(mention.device_name, mention.device_id)
            event = self.ui.emit(event_data)
            if note:
                text = f"[{note}]\n\n{text}" if text else f"[{note}]"
            self.bus.publish({"kind": "thread", "thread": thread.meta()})
            # the person's words reach the account's other devices now (C8), not after the turn
            self.sync.message_sent(thread)
            if not attachments and self.ui.answer_question(thread_id, text):
                return event
            # nanoMuse: a request for a new look (or the pick among four candidates) is the
            # studio's, not the agent's — the card in the chat takes it from here; a picture
            # attached to the request is the reference the candidates are drawn from
            if (
                source == "user"
                and all(a.kind == "image" for a in attachments)
                and self.avatar.intercept(thread_id, text, [a.path for a in attachments])
            ):
                # the first conversation's "what should I call you?" is not answered by this
                if firstrun.bound_to(self.firstrun.state, thread_id):
                    self.dismiss_first_chooser()
                return event
        else:
            event = self.ui.emit(
                {
                    "type": "notice",
                    "level": "info",
                    "text": label or text,
                    "source": source,
                    "thread": thread_id,
                }
            )
            if label:
                thread.purposes[text] = label
        thread.inbox.put_nowait(Incoming(text, attachments) if attachments else text)
        self._ensure_worker(thread)
        return event

    # ------------------------------------------------------------------ attachments
    def attachment(self, rel: str) -> Attachment:
        """An attachment record for a file in the workspace (the path as the app has it)."""
        target = self.resolve_workspace_path(rel)
        if not target.is_file():
            raise ValueError(f"no such file: {rel}")
        path = target.relative_to(self.workspace()).as_posix()
        return Attachment(
            path=path,
            name=target.name,
            size=target.stat().st_size,
            kind=Attachment.kind_of(target.name),
            mime=mimetypes.guess_type(target.name)[0] or "",
        )

    def save_upload(self, name: str, data: bytes) -> Attachment:
        """A file from the phone into ``attachments/<date>/`` in the workspace, under a
        safe version of its name (a second file with the same name gets a suffix)."""
        limit = self.settings.server.max_upload_mb * 1024 * 1024
        if len(data) > limit:
            raise ValueError(f"file is larger than {self.settings.server.max_upload_mb} MB")
        safe = re.sub(
            r"[^\w.\- ()\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]+", "_", Path(name).name
        ).strip(" ._")
        safe = safe[:120] or "file"
        folder = self.workspace() / "attachments" / datetime.now().strftime("%Y-%m-%d")
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / safe
        stem, suffix = target.stem, target.suffix
        n = 2
        while target.exists():
            target = folder / f"{stem} ({n}){suffix}"
            n += 1
        target.write_bytes(data)
        return self.attachment(target.relative_to(self.workspace()).as_posix())

    def _ensure_worker(self, thread: Thread) -> None:
        if thread.worker is None or thread.worker.done():
            thread.worker = asyncio.create_task(self._worker(thread), name=f"thread-{thread.id}")

    async def _worker(self, thread: Thread) -> None:
        token = current_thread.set(thread.id)
        try:
            while not thread.inbox.empty():
                item = thread.inbox.get_nowait()
                incoming = item if isinstance(item, Incoming) else Incoming(item)
                text = incoming.text
                thread.busy = True
                thread.agent.inbox = thread.inbox
                self.bus.publish({"kind": "thread", "thread": thread.meta()})
                # No sentence of its own: each client words the pause between steps
                # itself ("On it: <the request>") in its language.
                self.ui.set_status("working", "", thread.id)
                try:
                    purpose = thread.purposes.pop(text, None)
                    # the first conversation speaks to the person's turns in its own chat;
                    # a background run (a goal pass, a routine) never hears it
                    thread.agent.prompt_addendum = (
                        None if purpose else self._firstrun_addendum_for(thread.id)
                    )
                    self.ui.begin_run(thread.id, background=purpose)
                    final = await thread.agent.run(text, purpose=purpose, files=incoming.files)
                    quiet, final = (
                        prompts.split_quiet(final or "") if purpose else (False, final or "")
                    )
                    self._finish_run(thread, purpose, final.strip(), quiet)
                except asyncio.CancelledError:
                    if thread.stopping:
                        self._settle_stopped(thread)
                    raise
                except Exception as exc:  # noqa: BLE001
                    logger.exception("thread {} failed", thread.id)
                    self.ui.emit(failure_notice(exc, thread.id))
                    if thread.agent.state.value == "error":
                        thread.agent.state = thread.agent.state.__class__.IDLE
                finally:
                    self.ui.end_run(thread.id)
                    thread.agent.inbox = None
                    thread.busy = False
                    thread.updated_at = now_iso()
                    self.ui.set_status("idle", "", thread.id)
                    self.bus.publish({"kind": "thread", "thread": thread.meta()})
        finally:
            current_thread.reset(token)

    def _finish_run(self, thread: Thread, purpose: str | None, final: str, quiet: bool) -> None:
        """The run's last word: shown as the assistant bubble unless it is on screen
        already, and flagged ``final`` so clients can tell it from the step narration
        before it. Background runs push it once, here, not per step."""
        event: dict[str, Any] | None = None
        if (
            final
            and thread.id not in self.ui.reply_shown
            and final != self.ui.last_assistant_text.get(thread.id)
        ):
            event = {"type": "assistant", "text": final, "thread": thread.id, "final": True}
            if quiet:
                event["quiet"] = True
            event = self.ui.emit(event)
        else:
            eid = self.ui.last_assistant_event.get(thread.id)
            if eid and (existing := self.ui.get_timeline(thread.id).get(eid)):
                if not existing.get("final"):
                    self.ui.patch(thread.id, eid, final=True)
                event = existing
        if purpose and event and event.get("text") and not event.get("quiet"):
            self._push_background(event)
        # the turn is done: its texts go to the account's other devices in a moment
        self.sync.turn_finished(thread)
        if not purpose:
            self._firstrun_turn_ended(thread.id, final)

    # ------------------------------------------------------------------ approvals
    def decide(
        self, approval_id: str, approved: bool, scope: str = "once", reason: str = ""
    ) -> bool:
        return self.ui.resolve_approval(approval_id, approved, normalize_scope(scope), reason)

    def forget_approvals(self) -> None:
        self.app.sentinel.forget_approvals()
        self.bus.publish({"kind": "approvals_reset"})

    def revoke_grant(self, key: str) -> bool:
        ok = self.app.sentinel.revoke(key)
        if ok:
            self.bus.publish({"kind": "approvals_reset"})
        return ok

    # ------------------------------------------------------------------ browser view
    @property
    def browser(self) -> Browser | None:
        tool = self.app.tools.get("browser")
        return tool if isinstance(tool, Browser) else None

    def watch_browser(self) -> None:
        """Show the user what the browser tool sees. Called again when the tool is added."""
        tool = self.browser
        if tool is not None:
            tool.on_frame = self.ui.on_browser_frame
            tool.link = self.phone

    def browser_backend(self) -> str:
        """Where the browser renders now: "playwright", "device", or "" for nowhere."""
        tool = self.browser
        return tool.backend_kind if tool is not None else ""

    async def browser_control(self, thread: str, body: dict[str, Any]) -> dict[str, Any]:
        """The user takes over the agent's browser from the app (tap, type, open a URL).

        ``take_over`` puts a hold on (contract C1): the agent's next browser action waits
        until ``handed_back`` — the Done button — takes it off. Both work whether or not
        a page is open; the other actions need one."""
        action = str(body.get("action") or "")
        if action not in (
            "click",
            "type",
            "key",
            "scroll",
            "back",
            "navigate",
            "look",
            "take_over",
            "handed_back",
        ):
            raise ValueError(f"unknown browser action '{action}'")
        tool = self.browser
        hold: dict[str, Any] | None = None
        if action == "take_over":
            hold = self.app.holds.open(thread, "browser", by="user", reason="").to_event()
        elif action == "handed_back":
            released = self.app.holds.release(thread, "browser")
            hold = released.to_event() if released is not None else None
        if action in ("take_over", "handed_back") and (tool is None or not tool.open):
            return {"url": "", "title": "", "hold": hold}
        if tool is None:
            raise LookupError("the browser tool is not enabled")
        if action not in ("look", "navigate") and not tool.open:
            raise LookupError("the browser is not open right now — open a URL first")
        result = await tool.user_action(
            action,
            thread,
            x=body.get("x"),
            y=body.get("y"),
            text=body.get("text"),
            key=body.get("key"),
            dy=body.get("dy"),
            url=body.get("url"),
        )
        if hold is not None:
            result["hold"] = hold
        return result

    # ------------------------------------------------------------------ holds (C1)
    def holds_view(self) -> list[dict[str, Any]]:
        return self.app.holds.view()

    def open_hold(self, thread: str, tool: str, reason: str = "") -> dict[str, Any]:
        """``POST /api/holds``: the user takes the browser, the computer or the phone over
        for this chat; the agent's actions of that kind wait until :meth:`done_hold`."""
        if thread not in self.threads:
            raise LookupError(f"no thread {thread!r}")
        return self.app.holds.open(thread, tool, by="user", reason=reason).to_event()

    def done_hold(self, hold_id: str) -> dict[str, Any]:
        """``POST /api/holds/{id}/done``: the hold goes off; whatever waited on it looks
        again and goes on. A hold that is already off comes back as it is."""
        hold = self.app.holds.done(hold_id)
        if hold is None:
            raise LookupError(f"no hold {hold_id!r}")
        if hold.tool == "browser":
            # the model hears that the page was used, the way the phone's sheet reports it
            tool = self.browser
            if tool is not None and tool.open:
                spawn(self._browser_handed_back(tool, hold.thread), "browser handed back")
        return hold.to_event()

    async def _browser_handed_back(self, tool: Browser, thread: str) -> None:
        try:
            await tool.user_action("handed_back", thread)
        except Exception as exc:  # noqa: BLE001 — the hold is off either way
            logger.debug("browser handed back: {}", exc)

    # ------------------------------------------------------------------ push
    def pending_count(self) -> int:
        """Cards waiting for the user, across threads — the app badge number."""
        return len(self.ui.pending_approvals) + len(self.ui.pending_questions)

    @staticmethod
    def _push_url(thread: str) -> str:
        return "/" if thread == MAIN_THREAD else f"/?thread={thread}"

    def _maybe_push(self, event: dict[str, Any]) -> None:
        """Called with every persisted event: a card that needs you gets a push. Background
        results go through ``_push_background`` once the run is over, so the step-by-step
        narration never leaves the app; the service worker drops the notification anyway
        if the app is on screen."""
        if not self.push.enabled or not self.push.subscriptions:
            return
        kind = event.get("type")
        thread = event.get("thread") or MAIN_THREAD
        name = self.profile.name
        if kind == "approval" and event.get("status") == "pending":
            self.push.notify(
                f"{name} needs your approval",
                event.get("summary") or event.get("tool") or "",
                tag=f"approval-{event['id']}",
                url=self._push_url(thread),
                badge=self.pending_count(),
                kind="approval",
            )
        elif kind == "question" and event.get("status") == "pending":
            self.push.notify(
                f"{name} has a question",
                event.get("text") or "",
                tag=f"question-{event['id']}",
                url=self._push_url(thread),
                badge=self.pending_count(),
                kind="question",
            )

    def _push_background(self, event: dict[str, Any]) -> None:
        """The last word of a background run (a goal pass, a check-in) worth surfacing."""
        if not self.push.enabled or not self.push.subscriptions:
            return
        thread = event.get("thread") or MAIN_THREAD
        name = self.profile.name
        about = str(event.get("about") or "")
        title = about.replace("Working on your goal: ", "") or name
        if about.startswith("Check-in: "):
            title = f"{name} · check-in"
        elif about.startswith("Reminder: "):
            title = f"{name} · reminder"
        elif about.startswith("Routine: "):
            title = about[len("Routine: ") :] or name
        elif about.startswith(("New mail: ", "Coming up: ", "Webhook: ")):
            title = f"{name} · {about.split(': ', 1)[0].lower()}"
        self.push.notify(
            title,
            _first_lines(str(event["text"])),
            tag=f"background-{thread}",
            url=self._push_url(thread),
            badge=self.pending_count(),
            kind="background",
        )

    # ------------------------------------------------------------------ goals
    def advance_goal(self, goal_id: str) -> Goal:
        goal = self.app.goals.get(goal_id)
        if goal is None:
            raise KeyError(goal_id)
        if goal.status != "active":
            raise ValueError(f"goal is {goal.status}")
        surfacing = prompts.SURFACING.get(self.profile.proactivity, prompts.SURFACING["default"])
        self.send(
            MAIN_THREAD,
            prompts.ADVANCE_GOAL_PROMPT.format(goal=goal.render(), surfacing=surfacing),
            source="goal",
            label=f"Working on your goal: {goal.title}",
        )
        return goal

    async def _nap(self, seconds: float) -> None:
        """Sleep, unless :meth:`wake` is called first."""
        try:
            await asyncio.wait_for(self._wake.wait(), timeout=seconds)
        except TimeoutError:
            return
        finally:
            self._wake.clear()

    def wake(self) -> None:
        """Run the scheduler's pass now. The Android app calls this from the exact alarm it
        set for :meth:`next_wake_at`, so a reminder fires on time on a phone that was asleep."""
        self._wake.set()

    def next_wake_at(self) -> datetime | None:
        """The earliest moment something scheduled is due — a reminder, a goal check-in, the
        next background pass — or the end of the quiet hours when they hold a check-in back.
        A host that can wake the process (the Android app) sets an alarm for it; on a machine
        that never sleeps the scheduler's own naps are enough."""
        times: list[datetime] = []
        now = datetime.now().astimezone()
        quiet_until = self.profile.quiet_hours_end()
        for r in self.app.reminders.list("active"):
            when = _parse_when(r.next_at)
            if when is not None:
                times.append(when)
        for g in self.app.goals.list("active"):
            when = _parse_when(g.next_check_in)
            if when is not None:
                # a check-in waits for the quiet window to end; wake then
                times.append(max(when, quiet_until) if quiet_until else when)
        if self.profile.proactive and self.next_goal_pass_at is not None:
            times.append(self.next_goal_pass_at.astimezone())
        if not times:
            return None
        return max(min(times), now)

    def _announce_wake(self) -> None:
        """Tell the clients when the next wake is, whenever that changes."""
        when = self.next_wake_at()
        stamp = when.isoformat(timespec="seconds") if when else None
        if stamp == self._announced_wake:
            return
        self._announced_wake = stamp
        self.bus.publish({"kind": "schedule", "next_wake_at": stamp})

    def _next_pass_delay(self) -> float:
        """Seconds until the next background pass: the level's interval, pushed past the
        quiet window if it would land inside one."""
        delay = float(self.profile.interval_seconds)
        due = datetime.now().astimezone() + timedelta(seconds=delay)
        end = self.profile.quiet_hours_end(due)
        if end is not None:
            # a second past the end, so the pass does not wake up still inside the window
            delay = max(delay, (end - datetime.now().astimezone()).total_seconds() + 1)
        return delay

    def schedule_next_pass(self) -> None:
        """(Re)compute when the next background pass is due — on start, after a pass, and
        whenever the level, the interval or the quiet hours change."""
        self.next_goal_pass_at = datetime.now(UTC) + timedelta(seconds=self._next_pass_delay())

    def check_in(self, goal_id: str) -> Goal:
        """Send the reminder for a goal now: a short message from the agent, no work done."""
        goal = self.app.goals.get(goal_id)
        if goal is None:
            raise KeyError(goal_id)
        if goal.status != "active":
            raise ValueError(f"goal is {goal.status}")
        self.send(
            MAIN_THREAD,
            prompts.CHECK_IN_PROMPT.format(
                goal=goal.render(),
                today=datetime.now().astimezone().strftime("%A, %Y-%m-%d"),
                quiet=prompts.QUIET_MARKER,
            ),
            source="goal",
            label=f"Check-in: {goal.title}",
        )
        self.app.goals.mark_checked_in(goal.id)
        return goal

    def _run_due_check_ins(self) -> None:
        """Reminders the user asked for fire at any proactivity level, but not in quiet hours
        (they wait for the window to end) and not over a conversation in progress."""
        if self.profile.in_quiet_hours():
            return
        main = self.threads.get(MAIN_THREAD)
        if main is None or main.busy or not main.inbox.empty():
            return
        for goal in self.app.goals.due_check_ins():
            self.check_in(goal.id)
            break  # one at a time; the next tick picks up the rest

    def _pick_goal_for_pass(self) -> Goal | None:
        """Overdue first, then the one that has waited longest."""
        candidates = [g for g in self.app.goals.list("active") if g.next_step is not None]
        candidates.sort(key=lambda g: (not g.overdue, g.updated_at))
        return candidates[0] if candidates else None

    # ------------------------------------------------------------------ reminders
    def _watch_reminders(self) -> None:
        """New items from the tool belong to the chat they were set in, and the Upcoming
        view learns about them right away."""
        tool = self.app.tools.get("reminders")
        if isinstance(tool, Reminders):
            tool.thread_of = current_thread.get
            tool.on_change = lambda: self.bus.publish({"kind": "reminders"})

    def create_reminder(
        self, text: str, at: str = "", repeat: str = "", kind: str = "remind", thread: str = ""
    ) -> Reminder:
        item = self.app.reminders.create(
            text, at=at, repeat=repeat, kind=kind, thread=thread or MAIN_THREAD
        )
        self.bus.publish({"kind": "reminders"})
        return item

    def cancel_reminder(self, reminder_id: str) -> Reminder | None:
        item = self.app.reminders.cancel(reminder_id)
        if item is not None:
            self.bus.publish({"kind": "reminders"})
        return item

    def fire_reminder(self, reminder_id: str) -> Reminder:
        """Hand a reminder or routine to the agent now, in the chat it was set from."""
        item = self.app.reminders.get(reminder_id)
        if item is None:
            raise KeyError(reminder_id)
        if item.status != "active":
            raise ValueError(f"reminder is {item.status}")
        thread = item.thread if item.thread in self.threads else MAIN_THREAD
        now = datetime.now().astimezone().strftime("%A, %Y-%m-%d %H:%M")
        template = prompts.REMINDER_PROMPT if item.kind == "remind" else prompts.ROUTINE_PROMPT
        label = ("Reminder: " if item.kind == "remind" else "Routine: ") + _short(item.text)
        self.send(
            thread,
            template.format(now=now, text=item.text, quiet=prompts.QUIET_MARKER),
            source="reminder",
            label=label,
        )
        fired = self.app.reminders.mark_fired(item.id)
        self.bus.publish({"kind": "reminders"})
        return fired or item

    def _run_due_reminders(self) -> None:
        """A time the user named is kept whatever the proactivity level or the quiet hours;
        the message queues behind a conversation in progress rather than skipping."""
        for item in self.app.reminders.due():
            try:
                self.fire_reminder(item.id)
            except (KeyError, ValueError):  # pragma: no cover - raced with a cancel
                continue

    # ------------------------------------------------------------------ triggers
    def _watch_triggers(self) -> None:
        """Triggers set from the chat belong to that chat; the app and the inbox watcher
        learn about a new one right away."""
        tool = self.app.tools.get("triggers")
        if isinstance(tool, Triggers):
            tool.thread_of = current_thread.get
            tool.on_change = self._triggers_changed
            tool.available = self.app.trigger_kinds
            tool.base_url = self.base_url()

    def _triggers_changed(self) -> None:
        self._mail_polled_at = None  # look at the inbox on the next tick
        self.bus.publish({"kind": "triggers"})

    def base_url(self) -> str:
        """Where this server is reached — the address a webhook is given."""
        from nanomuse.server import lan_ip  # here: the package imports this module

        s = self.settings.server
        host = s.host if s.host not in ("", "0.0.0.0", "::") else (lan_ip() or "127.0.0.1")
        return f"http://{host}:{s.port}"

    def hook_url(self, trigger: Trigger) -> str:
        return f"{self.base_url()}/api/hooks/{trigger.id}?key={trigger.secret}"

    def create_trigger(
        self, kind: str, text: str, match: str = "", lead_minutes: int = 30, thread: str = ""
    ) -> Trigger:
        have = self.app.trigger_kinds()
        if not have.get(kind, True):
            raise ValueError(
                "connect a mailbox first" if kind == "mail" else "add a calendar first"
            )
        item = self.app.triggers.create(
            kind, text, match=match, lead_minutes=lead_minutes, thread=thread or MAIN_THREAD
        )
        self._triggers_changed()
        return item

    def cancel_trigger(self, trigger_id: str) -> Trigger | None:
        item = self.app.triggers.cancel(trigger_id)
        if item is not None:
            self.bus.publish({"kind": "triggers"})
        return item

    def fire_trigger(
        self, trigger_id: str, what: str, context: str = "", key: str = "", title: str = ""
    ) -> Trigger | None:
        """Hand a trigger to the agent now, with what happened as context, in the chat it
        was set from. ``key`` names the occurrence (a mail's UID, an event's start, a
        delivery id): the same key never fires twice, so this returns None the second time.
        ``title`` is the short form for the Feed (the subject, the event, the hook's name)."""
        item = self.app.triggers.get(trigger_id)
        if item is None:
            raise KeyError(trigger_id)
        if item.status != "active":
            raise ValueError(f"trigger is {item.status}")
        if not self.app.triggers.mark_fired(item.id, key or new_id()):
            return None
        thread = item.thread if item.thread in self.threads else MAIN_THREAD
        now = datetime.now().astimezone().strftime("%A, %Y-%m-%d %H:%M")
        prefix = {"mail": "New mail: ", "event": "Coming up: ", "hook": "Webhook: "}[item.kind]
        context = context.strip()[:6000]
        block = f"{_fence(context)}\n{context}\n{_fence(context)}\n\n" if context else ""
        if item.kind != "hook":
            # the mail or the event is the user's private data: from here on, sending
            # anything to a host that is not allowlisted is an approval
            self.app.sentinel.taint(thread)
        self.send(
            thread,
            prompts.TRIGGER_PROMPT.format(
                now=now, what=what, context=block, text=item.text, quiet=prompts.QUIET_MARKER
            ),
            source="trigger",
            label=prefix + _short(title or item.match or what),
        )
        self.bus.publish({"kind": "triggers"})
        return self.app.triggers.get(item.id) or item

    def deliver_hook(self, trigger_id: str, key: str, body: str, content_type: str = "") -> Trigger:
        """A request to a trigger's webhook URL. Wrong id or key → KeyError (the caller
        answers 404 for both, so the URL cannot be probed); too soon → RuntimeError."""
        item = self.app.triggers.get(trigger_id)
        if (
            item is None
            or item.kind != "hook"
            or not secrets.compare_digest(item.secret.encode(), (key or "").encode())
        ):
            raise KeyError(trigger_id)
        if item.status != "active":
            raise ValueError(f"trigger is {item.status}")
        if item.last_fired_at:
            since = datetime.now(UTC) - datetime.fromisoformat(item.last_fired_at)
            if since.total_seconds() < self.settings.triggers.hook_min_seconds:
                raise RuntimeError("too soon after the last delivery")
        body = body.strip()
        if content_type.startswith("application/json") and body:
            try:
                body = json.dumps(json.loads(body), indent=2, ensure_ascii=False)
            except ValueError:
                pass
        name = item.match or item.id
        what = f"Webhook “{name}” was called" + (" with:" if body else " (empty body).")
        fired = self.fire_trigger(
            item.id, what=what, context=body, key=f"hook:{new_id()}", title=name
        )
        return fired or item

    def _mail_mark(self) -> str:
        """The meta key of the inbox high-water mark — one per mailbox, so a changed
        account starts fresh instead of replaying by UID."""
        email = self.settings.connectors.email
        account = self.app.vault.resolve(email.address, strict=False) or email.address
        return f"mail_uid:{email.imap_host}:{account}"

    async def _poll_mail(self) -> None:
        """Look at the inbox for the mail triggers, every ``mail_poll_minutes`` while at
        least one is active. Each new mail is offered to every mail trigger; a trigger
        fires once per mail."""
        triggers = self.app.triggers.active("mail")
        if not triggers:
            return
        email = self.settings.connectors.email
        watcher = MailWatcher(email, vault=self.app.vault)
        if not watcher.configured:
            return
        now = time.monotonic()
        every = max(1, self.settings.triggers.mail_poll_minutes) * 60
        if self._mail_polled_at is not None and now - self._mail_polled_at < every:
            return
        self._mail_polled_at = now
        store = self.app.triggers
        mark = self._mail_mark()
        last = int(store.get_meta(mark, "0") or 0)
        try:
            fresh, newest = await watcher.look(last)
        except (RuntimeError, OSError) as exc:
            self.mail_watch_error = str(exc)[:200]
            logger.warning("mail triggers: {}", exc)
            return
        self.mail_watch_error = ""
        self.mail_checked_at = now_iso()
        store.set_meta(mark, str(newest))
        for mail in fresh:
            for trig in triggers:
                if matches(trig.match, mail.sender, mail.subject):
                    self.fire_trigger(
                        trig.id,
                        what=f"New mail from {mail.sender}: {mail.subject or '(no subject)'}",
                        context=mail.render(),
                        key=mail.key,
                        title=mail.subject or mail.sender,
                    )
        self.bus.publish({"kind": "triggers"})

    def _run_event_triggers(self) -> None:
        """Fire event triggers ``lead_minutes`` before a matching event; an event that has
        already begun is left alone (a late brief helps no one)."""
        triggers = self.app.triggers.active("event")
        cal = self.app.calendar
        if not triggers or not cal.configured:
            return
        now = datetime.now(cal.tz)
        h, m = (int(x) for x in self.settings.connectors.calendar.day_start.split(":"))
        for occ in cal.agenda(now.date(), 3):  # a lead can be a day
            start = occ.start.astimezone(cal.tz)
            if occ.all_day:
                # an all-day event "starts" when the working day does, not at midnight
                start = datetime.combine(occ.start.date(), time_of_day(h, m), tzinfo=cal.tz)
            if start <= now:
                continue
            for trig in triggers:
                if not matches(trig.match, occ.summary, occ.location):
                    continue
                if now < start - timedelta(minutes=trig.lead_minutes):
                    continue
                minutes = max(1, int((start - now).total_seconds() // 60))
                when = "all day" if occ.all_day else f"{start:%H:%M}"
                where = f" · {occ.location}" if occ.location else ""
                self.fire_trigger(
                    trig.id,
                    what=f"Coming up: {occ.summary} — {start:%a %Y-%m-%d} {when}{where} (in {minutes} min)",
                    context=cal.render([occ], now.date())
                    + (f"\n\n{occ.description}" if occ.description else ""),
                    key=f"{occ.uid}:{occ.start.isoformat()}",
                    title=occ.summary,
                )

    def _prune_fired(self) -> None:
        """Firing records (a mail's UID, an event's start) are only needed until the
        occurrence is long past; drop the ones older than 90 days, once a day."""
        now = time.monotonic()
        if self._fired_pruned_at is not None and now - self._fired_pruned_at < 86400:
            return
        self._fired_pruned_at = now
        cutoff = (datetime.now(UTC) - timedelta(days=90)).isoformat(timespec="seconds")
        self.app.triggers.forget_fired_before(cutoff)

    def triggers_view(self) -> dict[str, Any]:
        items = []
        for t in self.app.triggers.list(None):
            d = t.to_dict()
            if t.kind == "hook":
                d["url"] = self.hook_url(t) if t.status == "active" else ""
            items.append(d)
        available = self.app.trigger_kinds()
        mail_error = self.mail_watch_error
        if not available["mail"] and any(
            t.kind == "mail" and t.status == "active" for t in self.app.triggers.list("active")
        ):
            mail_error = "no mailbox is connected"
        return {
            "items": items,
            "available": available,
            "mail_checked_at": self.mail_checked_at,
            "mail_error": mail_error,
            "mail_poll_minutes": self.settings.triggers.mail_poll_minutes,
        }

    async def _run_feed_routine(self) -> None:
        """The feed's daily routine (contract C5): a batch at its time, whatever the
        proactivity setting — it is quiet (one notification, no chat message), the person
        turned it on in the Feed, and a model has to be there. A failed batch is tried again
        an hour later, not every tick."""
        if not self.feed_posts_due() or not self.settings_view()["llm_ready"]:
            return
        if self._feed_failed_at and time.monotonic() - self._feed_failed_at < FEED_RETRY_S:
            return
        try:
            await self.write_feed_posts()
            self._feed_failed_at = None
        except Exception as exc:  # noqa: BLE001 — the model may be down; the routine keeps its day
            self._feed_failed_at = time.monotonic()
            logger.info("feed routine: batch not written: {}", exc)

    async def _goal_scheduler(self) -> None:
        self.schedule_next_pass()
        while True:
            try:
                self._run_due_reminders()
                self._run_due_check_ins()
                await self._refresh_calendar()
                self._run_event_triggers()
                await self._poll_mail()
                self._prune_fired()
                self._announce_wake()
                await self._run_feed_routine()
                due = self.next_goal_pass_at or datetime.now(UTC)
                remaining = (due - datetime.now(UTC)).total_seconds()
                if remaining > 0:
                    # short naps so a changed setting takes effect without a restart
                    await self._nap(min(remaining, 30))
                    continue
                self.schedule_next_pass()
                if not self.profile.proactive or self.profile.in_quiet_hours():
                    continue
                main = self.threads.get(MAIN_THREAD)
                if main is None or main.busy or not main.inbox.empty():
                    continue
                if self.memory_tidy_due():
                    # housekeeping takes this tick; the goal pass is next time
                    await self.tidy_memory()
                    continue
                goal = self._pick_goal_for_pass()
                if goal is not None:
                    self.advance_goal(goal.id)  # one goal per tick keeps the chat readable
            except asyncio.CancelledError:
                return
            except Exception as exc:  # noqa: BLE001  pragma: no cover
                logger.warning("goal scheduler error: {}", exc)
                await asyncio.sleep(30)

    # ------------------------------------------------------------------ calendar
    async def _refresh_calendar(self) -> None:
        """Fetch the calendar feeds when the cache is older than ``refresh_minutes``; the
        Feed and the system prompt read the cache. Runs whatever the proactivity level:
        it is the user's own data, not a background task."""
        cal = self.app.calendar
        if not cal.configured or not cal.stale():
            return
        before = cal.fetched_at
        await cal.refresh()
        if cal.fetched_at != before:
            self.bus.publish({"kind": "calendar", "calendar": self.calendar_view()})

    # ------------------------------------------------------------------ skills
    def skills_view(self) -> dict[str, Any]:
        lib = self.app.skills
        return {**lib.status(), "skills": [s.to_dict() for s in lib.all()]}

    def skill_view(self, name: str) -> dict[str, Any] | None:
        skill = self.app.skills.get(name)
        return skill.to_dict(body=True) if skill else None

    def save_skill(self, content: str, name: str = "") -> dict[str, Any]:
        """A skill from the text of a SKILL.md, written or pasted in the app."""
        skill = self.app.skills.save_text(content, name=name)
        self._publish_skills()
        return skill.to_dict(body=True)

    async def import_skill(self, url: str) -> dict[str, Any]:
        """A skill from a link to a SKILL.md — a raw file link, or a GitHub folder or file
        page, which is turned into one."""
        from nanomuse.skills import fetch_skill_text

        skill = self.app.skills.save_text(await fetch_skill_text(url))
        self._publish_skills()
        return skill.to_dict(body=True)

    def remove_skill(self, name: str) -> bool:
        ok = self.app.skills.remove(name)
        if ok:
            self._publish_skills()
        return ok

    def set_skill_enabled(self, name: str, enabled: bool) -> dict[str, Any] | None:
        skill = self.app.skills.set_enabled(name, enabled)
        if skill is None:
            return None
        data = self.connections.data
        data["skills"] = {"disabled": list(self.settings.skills.disabled)}
        self.connections._save()
        self._publish_skills()
        return skill.to_dict()

    def _publish_skills(self) -> None:
        self.bus.publish({"kind": "skills", "skills": self.skills_view()})
        # the avatar menu shows the counts from the settings view
        self.bus.publish({"kind": "settings", "settings": self.settings_view()})

    def calendar_view(self, days: int = 2) -> dict[str, Any]:
        """Today's and tomorrow's events with the feeds' status, for the app."""
        cal = self.app.calendar
        status = cal.status()
        today = datetime.now(cal.tz).date()
        items = cal.agenda(today, days) if cal.configured else []
        return {
            **status,
            "configured": cal.configured,
            "today": today.isoformat(),
            "events": [o.to_dict() for o in items],
        }

    # ------------------------------------------------------------------ memory tidy-up
    TIDY_MIN_LINES = 12  # nothing to tidy below this
    TIDY_EVERY_NEW = 8  # lines added since the last pass…
    TIDY_EVERY = timedelta(days=7)  # …or this long, whichever comes first

    def memory_tidy_due(self) -> bool:
        """A tidy-up is due when the store grew by a handful of lines since the last one,
        or a week went by — and never while one is running."""
        store = self.app.memory
        if store is None or self._tidying:
            return False
        count = store.count()
        if count < self.TIDY_MIN_LINES:
            return False
        last_at = store.get_meta("tidied_at")
        if not last_at or store.get_meta("tidy_more") == "1":
            return True
        if count - int(store.get_meta("tidied_count", "0") or 0) >= self.TIDY_EVERY_NEW:
            return True
        try:
            return datetime.now(UTC) - datetime.fromisoformat(last_at) >= self.TIDY_EVERY
        except ValueError:
            return True

    async def tidy_memory(self, dry_run: bool = False) -> dict[str, Any]:
        """One pass of ``memory.tidy``: merge duplicates, keep the newer fact, drop what
        was never a fact about the user. What changed goes to the Feed and to the log
        behind *Memory → Recent changes*, where each change can be undone."""
        store = self.app.memory
        if store is None:
            raise ValueError("memory is disabled")
        if self._tidying:
            raise ValueError("a tidy-up is already running")
        self._tidying = True
        try:
            report = await tidy(store, self.app.llm, dry_run=dry_run)
        finally:
            self._tidying = False
        if dry_run:
            return report.to_dict()
        store.set_meta("tidied_at", datetime.now(UTC).isoformat(timespec="seconds"))
        store.set_meta("tidied_count", str(store.count()))
        store.set_meta("tidy_more", "1" if report.more else "0")  # continue next tick
        self.bus.publish({"kind": "memory"})
        if report.changed:
            label = "Tidied memory"
            self.ui.emit(
                {
                    "type": "notice",
                    "level": "info",
                    "text": label,
                    "source": "memory",
                    "thread": MAIN_THREAD,
                }
            )
            summary = _tidy_summary(report, self.settings.agent.language)
            self.ui.emit(
                {
                    "type": "assistant",
                    "text": summary,
                    "thread": MAIN_THREAD,
                    "source": "background",
                    "about": label,
                    "final": True,
                }
            )
            self.threads[MAIN_THREAD].updated_at = now_iso()
        return report.to_dict()

    # ------------------------------------------------------------------ ideas
    def _ideas_file(self) -> Path:
        return self.data_dir / "ideas.json"

    def cached_ideas(self) -> dict[str, Any]:
        path = self._ideas_file()
        if path.exists():
            try:
                return json.loads(path.read_text("utf-8"))
            except (OSError, json.JSONDecodeError):
                pass
        return {"generated_at": None, "source": "starter", "ideas": STARTER_IDEAS}

    async def refresh_ideas(self, n: int = 5) -> dict[str, Any]:
        context_lines: list[str] = []
        if self.app.memory is not None:
            for m in self.app.memory.all(limit=30):
                context_lines.append(f"- memory ({m.category}): {m.content}")
        for g in self.app.goals.list("active")[:8]:
            nxt = g.next_step
            context_lines.append(
                f"- goal: {g.title} (progress {g.progress}"
                + (f", next: {nxt.title}" if nxt else "")
                + ")"
            )
        main = self.threads.get(MAIN_THREAD)
        if main is not None:
            recent = [e for e in main.timeline.events if e.get("type") in ("user", "assistant")][
                -8:
            ]
            for e in recent:
                context_lines.append(f"- recent {e['type']}: {str(e.get('text', ''))[:200]}")
        if self.settings.agent.user_profile.strip():
            context_lines.insert(0, f"- profile: {self.settings.agent.user_profile.strip()[:500]}")
        if not context_lines:
            data = {"generated_at": now_iso(), "source": "starter", "ideas": STARTER_IDEAS}
            self._ideas_file().write_text(json.dumps(data, ensure_ascii=False), "utf-8")
            return data
        language = self.settings.agent.language
        prompt = IDEAS_PROMPT.format(
            name=self.profile.name,
            n=n,
            context="\n".join(context_lines),
            language="the same language as the context above"
            if language in ("", "auto")
            else language,
        )
        response = await self.app.llm.ask_complete([Message.user(prompt)], tools=None)
        ideas = _parse_ideas(response.content or "")
        data = {
            "generated_at": now_iso(),
            "source": "model" if ideas else "starter",
            "ideas": ideas or STARTER_IDEAS,
        }
        self._ideas_file().write_text(json.dumps(data, ensure_ascii=False), "utf-8")
        self.bus.publish({"kind": "ideas", "ideas": data})
        return data

    # ------------------------------------------------------------------ feed posts
    def _feed_file(self) -> Path:
        return self.data_dir / "feed_posts.json"

    def feed_posts(self) -> dict[str, Any]:
        """The posts written for the user so far, newest first, their feed instructions, and
        the daily routine: ``daily`` (on by default) at ``time`` (``HH:MM``, local; 08:00)."""
        path = self._feed_file()
        data: dict[str, Any] = {}
        if path.exists():
            try:
                loaded = json.loads(path.read_text("utf-8"))
                if isinstance(loaded, dict):
                    data = loaded
            except (OSError, json.JSONDecodeError):
                pass
        data.setdefault("instructions", "")
        data.setdefault("generated_at", None)
        data.setdefault("posts", [])
        data["daily"] = data.get("daily") is not False
        data["time"] = _feed_time(data.get("time")) or FEED_DEFAULT_TIME
        return data

    def _save_feed(self, data: dict[str, Any]) -> None:
        data["posts"] = data["posts"][:FEED_KEEP]
        self._feed_file().write_text(json.dumps(data, ensure_ascii=False), "utf-8")

    def set_feed_instructions(
        self, text: str | None = None, *, daily: bool | None = None, time: str | None = None
    ) -> dict[str, Any]:
        """The feed's preferences: what to write about, and the daily routine (on or off, and
        when). A ``time`` that is not ``HH:MM`` is refused with :class:`ValueError`."""
        data = self.feed_posts()
        if text is not None:
            data["instructions"] = text.strip()[:2000]
        if daily is not None:
            data["daily"] = bool(daily)
        if time is not None:
            clean = _feed_time(time)
            if not clean:
                raise ValueError("time must be HH:MM")
            data["time"] = clean
        self._save_feed(data)
        self.bus.publish({"kind": "feed_posts"})
        return data

    def feed_scheduled_at(self, now: datetime | None = None) -> datetime:
        """The most recent moment the daily routine was due (today's ``time`` once it has
        passed, yesterday's before that), in local time."""
        now = now or datetime.now().astimezone()
        hour, minute = (int(p) for p in self.feed_posts()["time"].split(":"))
        today = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        return today if today <= now else today - timedelta(days=1)

    def first_feed_day(self) -> bool:
        """Right after the first conversation (the app set up, a model there), the first feed
        day is written in the background — a person opening the Feed finds it filled rather
        than a promise. Nothing when posts exist already or no model can be reached; the
        model's answer never counts as a task (contract C1: a background run)."""
        s = self.settings_view()
        if not s["llm_ready"] or self.feed_posts()["posts"] or self._writing_feed:
            return False

        async def write() -> None:
            try:
                await self.write_feed_posts()
            except Exception as exc:  # noqa: BLE001 — the daily routine tries again
                logger.info("first feed day not written: {}", exc)

        try:
            spawn(write(), "first feed day")
        except RuntimeError:  # pragma: no cover - no loop (a direct call outside the server)
            return False
        return True

    def delete_feed_post(self, post_id: str) -> bool:
        data = self.feed_posts()
        before = len(data["posts"])
        data["posts"] = [p for p in data["posts"] if p.get("id") != post_id]
        if len(data["posts"]) == before:
            return False
        self._save_feed(data)
        self.bus.publish({"kind": "feed_posts"})
        return True

    def feed_posts_due(self) -> bool:
        """A new feed day is due when the daily routine is on, its time has passed since the
        last batch, and there is something to write from (the first conversation done,
        memory, a goal, or instructions from the user)."""
        if self._writing_feed:
            return False
        data = self.feed_posts()
        if not data["daily"]:
            return False
        known = (
            bool(data["instructions"])
            or bool(self.app.goals.list("active"))
            or bool(self.connections.data.get("onboarded"))
        )
        if not known and self.app.memory is not None:
            known = self.app.memory.count() >= 5
        if not known:
            return False
        last = data.get("generated_at")
        if not last:
            return True
        try:
            written = datetime.fromisoformat(last)
        except ValueError:
            return True
        if written.tzinfo is None:
            written = written.replace(tzinfo=UTC)
        if datetime.now(UTC) - written < timedelta(hours=FEED_MIN_GAP_HOURS):
            return False  # "Write it now" shortly before the hour is today's batch
        return written < self.feed_scheduled_at()

    def _feed_context(self) -> list[str]:
        lines: list[str] = []
        if self.settings.agent.user_profile.strip():
            lines.append(f"- profile: {self.settings.agent.user_profile.strip()[:500]}")
        if self.profile.user_name:
            lines.append(f"- the user's name: {self.profile.user_name}")
        if self.app.memory is not None:
            for m in self.app.memory.all(limit=40):
                lines.append(f"- memory ({m.category}): {m.content}")
        for g in self.app.goals.list("active")[:8]:
            nxt = g.next_step
            lines.append(
                f"- goal: {g.title} (progress {g.progress}"
                + (f", next: {nxt.title}" if nxt else "")
                + ")"
            )
        cal = self.app.calendar
        if cal.configured:
            today = datetime.now().astimezone().date()
            if agenda := cal.agenda(today)[:8]:
                lines.append("- today on the calendar:\n" + cal.render(agenda, today))
        main = self.threads.get(MAIN_THREAD)
        if main is not None:
            recent = [e for e in main.timeline.events if e.get("type") in ("user", "assistant")][
                -6:
            ]
            for e in recent:
                lines.append(f"- recent {e['type']}: {str(e.get('text', ''))[:200]}")
        lines.append(f"- today's date: {datetime.now().strftime('%A %d %B %Y')}")
        return lines

    async def write_feed_posts(self, n: int = 3) -> dict[str, Any]:
        """Write a fresh batch of posts and notify the phone once about the first."""
        if self._writing_feed:
            return self.feed_posts()
        self._writing_feed = True
        try:
            data = self.feed_posts()
            language = self.settings.agent.language
            prompt = FEED_PROMPT.format(
                name=self.profile.name,
                n=n,
                instructions=data["instructions"]
                or "(none yet — write what a good personal agent would)",
                context="\n".join(self._feed_context()),
                language="the same language as the context above"
                if language in ("", "auto")
                else language,
            )
            response = await self.app.llm.ask_complete([Message.user(prompt)], tools=None)
            posts = _parse_posts(response.content or "")
            now = now_iso()
            for p in posts:
                p["id"] = new_id("post")
                p["ts"] = now
            data["posts"] = [*posts, *data["posts"]]
            data["generated_at"] = now
            self._save_feed(data)
            self.bus.publish({"kind": "feed_posts"})
            if posts:
                self.push.notify(
                    f"{self.profile.name} · {posts[0]['title']}",
                    _first_lines(posts[0]["body"]),
                    tag="feed-posts",
                    url=self._push_url(MAIN_THREAD).split("?")[0] + "?tab=feed",
                    kind="background",
                )
            return data
        finally:
            self._writing_feed = False

    # ------------------------------------------------------------------ files / artifacts
    def workspace(self) -> Path:
        return self.settings.agent.workspace.resolve()

    def resolve_workspace_path(self, rel: str) -> Path:
        ws = self.workspace()
        target = (ws / rel).resolve()
        if target != ws and ws not in target.parents:
            raise PermissionError("path outside the workspace")
        return target

    def list_files(self, limit: int = 200) -> list[dict[str, Any]]:
        ws = self.workspace()
        out: list[dict[str, Any]] = []
        if not ws.exists():
            return out
        for p in ws.rglob("*"):
            if not p.is_file() or any(part.startswith(".") for part in p.relative_to(ws).parts):
                continue
            try:
                st = p.stat()
            except OSError:
                continue
            out.append(
                {
                    "path": p.relative_to(ws).as_posix(),
                    "name": p.name,
                    "size": st.st_size,
                    "modified": datetime.fromtimestamp(st.st_mtime, UTC).isoformat(
                        timespec="seconds"
                    ),
                }
            )
            if len(out) >= 5000:
                break
        out.sort(key=lambda f: f["modified"], reverse=True)
        return out[:limit]

    # ------------------------------------------------------------------ feed / upcoming
    def feed(self, limit: int = 60) -> list[dict[str, Any]]:
        """What happened without you asking, newest first: one entry per background pass
        (its final reply, plus any file it made) and every card still waiting for you."""
        items: list[dict[str, Any]] = []
        for t in self.threads.values():
            items.extend(self._feed_of(t))
        items.sort(key=lambda i: i["ts"], reverse=True)
        return items[:limit]

    def _feed_of(self, t: Thread) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []

        def item(ev: dict[str, Any], kind: str, title: str, text: str) -> dict[str, Any]:
            return {
                "id": ev["id"],
                "ts": ev["ts"],
                "kind": kind,
                "title": title,
                "text": text,
                "thread": t.id,
                "thread_title": t.title,
                "path": ev.get("path"),
                # a pass that found nothing worth interrupting you for
                "quiet": bool(ev.get("quiet")),
            }

        # A background pass is the notice that starts it followed by everything the agent
        # says or makes until you speak. Only its last word goes to the Feed — the
        # step-by-step narration stays in the chat.
        run: dict[str, Any] | None = None

        def flush() -> None:
            if run is None:
                return
            last = run["said"][-1] if run["said"] else None
            if last is not None:
                out.append(item(last, "background", run["label"], last.get("text", "")))
            elif t.busy and run is runs[-1]:
                out.append(item(run["start"], "background", run["label"], "Working on it…"))
            for art in run["made"]:
                out.append(item(art, "artifact", f"Made {art.get('name', 'a file')}", run["label"]))

        runs: list[dict[str, Any]] = []
        for ev in t.timeline.events:
            kind, src = ev.get("type"), ev.get("source")
            if kind == "approval":
                if ev.get("status") == "pending":
                    out.append(
                        item(ev, "approval", "Waiting for your approval", ev.get("summary", ""))
                    )
                continue
            if kind == "question":
                if ev.get("status") == "pending":
                    out.append(
                        item(
                            ev,
                            "question",
                            f"{self.profile.name} has a question",
                            ev.get("text", ""),
                        )
                    )
                continue
            if kind == "notice" and src not in (None, "background"):
                flush()
                run = {"label": ev.get("text", ""), "start": ev, "said": [], "made": []}
                runs.append(run)
            elif src == "background":
                if run is None:
                    run = {
                        "label": ev.get("about") or "While you were away",
                        "start": ev,
                        "said": [],
                        "made": [],
                    }
                    runs.append(run)
                if kind == "artifact":
                    run["made"].append(ev)
                elif kind in ("assistant", "notice"):
                    run["said"].append(ev)
            elif kind == "user":
                flush()
                run = None
        flush()
        return out

    def upcoming(self) -> dict[str, Any]:
        """What is scheduled: the next background pass and the goals it would work on."""
        active = [g for g in self.app.goals.list("active") if g.next_step is not None]
        active.sort(key=lambda g: (not g.overdue, g.updated_at))
        queue = [
            {
                "goal_id": g.id,
                "title": g.title,
                "category": g.category,
                "due": g.due or None,
                "overdue": g.overdue,
                "next_step": g.next_step.title if g.next_step else None,
                "progress": {
                    "done": sum(1 for s in g.steps if s.status in ("done", "skipped")),
                    "total": len(g.steps),
                },
            }
            for g in active
        ]
        check_ins = sorted(
            (
                {"goal_id": g.id, "title": g.title, "at": g.next_check_in, "cadence": g.check_in}
                for g in self.app.goals.list("active")
                if g.next_check_in
            ),
            key=lambda c: c["at"],
        )
        quiet_until = self.profile.quiet_hours_end()
        return {
            "check_ins": check_ins,
            "reminders": [r.to_dict() for r in self.app.reminders.list(None)],
            "triggers": self.triggers_view(),
            "proactive": self.profile.proactive,
            "proactivity": self.profile.proactivity,
            "interval_minutes": self.profile.goal_interval_minutes,
            "effective_interval_minutes": self.profile.interval_seconds // 60,
            "quiet_hours": self.profile.quiet_hours,
            "quiet_until": quiet_until.isoformat(timespec="seconds") if quiet_until else None,
            "next_pass_at": (
                self.next_goal_pass_at.isoformat(timespec="seconds")
                if self.next_goal_pass_at and self.profile.proactive
                else None
            ),
            "next_wake_at": (
                wake.isoformat(timespec="seconds") if (wake := self.next_wake_at()) else None
            ),
            "queue": queue,
            "busy": any(t.busy for t in self.threads.values()),
        }

    # ------------------------------------------------------------------ state snapshots
    def activity(self, n: int = 100) -> dict[str, Any]:
        s = self.app.sentinel
        s.grants.purge_expired()
        return {
            "audit": self.app.audit.tail(n),
            "grants": [g.to_dict() for g in s.active_grants()],
            "tainted": s.tainted_any(),
        }

    def settings_view(self) -> dict[str, Any]:
        s = self.settings
        skills = self.app.skills.status()
        return {
            "version": __version__,
            "profile": self.profile.to_dict(),
            "sentinel": {
                "mode": s.sentinel.mode,
                "always_ask_tools": s.sentinel.always_ask_tools,
                "always_allow_tools": s.sentinel.always_allow_tools,
                "deny_tools": s.sentinel.deny_tools,
                "taint_tracking": s.sentinel.taint_tracking,
                "egress_allowlist": s.sentinel.egress_allowlist,
            },
            "sandbox": {
                "mode": s.sandbox.mode,
                "active": self.app.sandbox.active,
                "status": self.app.sandbox.status,
            },
            "llm": {
                "provider": s.llm.provider,
                "model": s.llm.model,
                "stream": s.llm.stream,
                # the account's model answers (Settings offers the own-key door then)
                "cloud": bool(
                    s.llm.base_url
                    and s.llm.base_url.rstrip("/") == model_url(self.hub.cloud.base_url)
                ),
            },
            "agent": {
                "language": s.agent.language,
                "max_steps": s.agent.max_steps,
                "show_thinking": s.agent.show_thinking,
                "workspace": str(s.agent.workspace),
            },
            "connectors": {
                "email": s.connectors.email.enabled,
                "calendar": s.connectors.calendar.enabled and bool(s.connectors.calendar.feeds),
                "contacts": s.connectors.contacts.enabled and self.app.contacts.configured,
                "browser": s.browser.enabled,
                "gui": s.gui.enabled,
                "hands": s.hands.enabled,
                "mcp": [m.name for m in s.mcp.servers],
            },
            "phone": self.phone_view(),
            "browser": {"backend": self.browser_backend()},
            "tools": [
                {"name": t.name, "risk": t.risk.value, "description": t.description[:160]}
                for t in self.app.tools
            ],
            "memory_enabled": s.memory.enabled,
            "skills": {
                "enabled": s.skills.enabled,
                "count": skills["count"],
                "yours": skills["yours"],
            },
            "data_dir": str(self.data_dir),
            "started_at": self.started_at,
            "onboarded": bool(self.connections.data.get("onboarded")),
            "llm_ready": llm_ready(s.llm, self.app.vault, self.data_dir),
        }

    def update_settings(self, data: dict[str, Any]) -> dict[str, Any]:
        if "profile" in data and isinstance(data["profile"], dict):
            self.update_profile(data["profile"])
        if (mode := data.get("sentinel_mode")) in ("ask", "strict", "auto"):
            self.settings.sentinel.mode = mode
        if "show_thinking" in data:
            self.settings.agent.show_thinking = bool(data["show_thinking"])
            self.ui.show_thinking = bool(data["show_thinking"])
        if (lang := data.get("language")) is not None:
            self.settings.agent.language = str(lang)[:20] or "auto"
        self.bus.publish({"kind": "settings", "settings": self.settings_view()})
        return self.settings_view()

    def state(self) -> dict[str, Any]:
        return {
            "version": __version__,
            "profile": self.profile.to_dict(),
            "status": self.ui.overall_status(),
            # the signed-in account's conversations and the ownerless ones (C10)
            "threads": [t.meta() for t in self.visible_threads()],
            "pending_approvals": [
                ev
                for t in self.visible_threads()
                for ev in t.timeline.events
                if ev.get("type") == "approval" and ev.get("status") == "pending"
            ],
            "goals": [goal_to_dict(g) for g in self.app.goals.list()],
            "settings": self.settings_view(),
            "phone": self.phone_view(),
            # the phone this server runs on (the local runtime), or null on a computer
            "device": self.app.device.to_dict() if self.app.device is not None else None,
            # this device on the hub: the account, the other devices
            "hub": self.hub.view(),
            # this computer's own screen and hands
            "hands": self.hands_view(),
            "holds": self.holds_view(),
            # the other devices' turns under way on synced chats (C9), for the line under
            # a message written elsewhere; `working` frames keep it current
            "working": self.sync.working_view(),
            # the first conversation: where it is bound, which phase, the chips (C4)
            "firstrun": self.firstrun_view(),
        }


def _tidy_summary(report: TidyReport, language: str = "auto") -> str:
    """The tidy-up as one chat message: what was merged and dropped, and where to undo it.

    Written in 中文 when that is the reply language, or when the language is "auto" and the
    memories themselves are Chinese; English otherwise (the two languages the app ships in).
    """
    n_m, n_d = len(report.merged), len(report.dropped)
    if language in ("", "auto"):
        text = " ".join(m.content for c in report.merged + report.dropped for m in c.before)
        zh = prompts.detect_language(text) == "Chinese"
    else:
        zh = language.lower().startswith(("中文", "zh", "chinese", "简体", "繁體"))
    if zh:
        parts = ([f"合并了 {n_m} 条"] if n_m else []) + ([f"删除了 {n_d} 条"] if n_d else [])
        head = "我整理了一下记忆——" + "，".join(parts) + "："
        tail = "每一处改动都可以在「记忆 → 最近的改动」里撤销。"
    else:
        parts = ([f"merged {n_m} line{'s' if n_m != 1 else ''}"] if n_m else []) + (
            [f"dropped {n_d}"] if n_d else []
        )
        head = "I tidied your memory — " + " and ".join(parts) + ":"
        tail = "Each change can be undone under Memory → Recent changes."
    body = "\n".join(f"- {line}" for line in report.lines(zh=zh))
    return f"{head}\n{body}\n\n{tail}"


def _fence(text: str) -> str:
    """A code fence the text cannot close: one backtick more than its longest run."""
    longest = max((len(m) for m in re.findall(r"`+", text)), default=0)
    return "`" * max(3, longest + 1)


def _short(text: str, limit: int = 60) -> str:
    """One line of ``text`` for a label."""
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _first_lines(text: str, limit: int = 200) -> str:
    """The first sentence or two of a reply, without markdown, for a notification body."""
    text = re.sub(r"```.*?```", " ", text, flags=re.S)
    text = re.sub(r"[*_`#>]+", "", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def goal_to_dict(g: Goal) -> dict[str, Any]:
    done = sum(1 for s in g.steps if s.status in ("done", "skipped"))
    return {
        "id": g.id,
        "title": g.title,
        "description": g.description,
        "status": g.status,
        "notes": g.notes,
        "category": g.category,
        "due": g.due,
        "overdue": g.overdue,
        "check_in": g.check_in,
        "next_check_in": g.next_check_in or None,
        "proposal": g.proposal,
        "created_at": g.created_at,
        "updated_at": g.updated_at,
        "progress": {"done": done, "total": len(g.steps)},
        "next_step": g.next_step.title if g.next_step else None,
        "steps": [
            {
                "idx": s.idx,
                "title": s.title,
                "status": s.status,
                "note": s.note,
                "updated_at": s.updated_at,
            }
            for s in g.steps
        ],
    }


def _idea_objects(text: str) -> list[Any]:
    """The JSON objects in a model reply that should have been a JSON array.

    Usually it is one: ``[{...}, {...}]``, possibly inside a code fence. When the
    array does not parse — a real newline inside a string, a trailing comma, the
    reply cut off at max_tokens before the closing bracket — each ``{...}`` that
    parses on its own is kept, so one bad item does not cost the whole list.
    """
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S)
    text = re.sub(r"^\s*```(?:json)?\s*|\s*```\s*$", "", text.strip())
    start, end = text.find("["), text.rfind("]")
    if start >= 0 and end > start:
        try:
            data = json.loads(text[start : end + 1], strict=False)
            if isinstance(data, list):
                return data
        except json.JSONDecodeError:
            pass
    decoder = json.JSONDecoder(strict=False)
    found: list[Any] = []
    pos = text.find("{")
    while pos >= 0:
        try:
            obj, stop = decoder.raw_decode(text, pos)
        except json.JSONDecodeError:
            pos = text.find("{", pos + 1)
            continue
        found.append(obj)
        pos = text.find("{", stop)
    return found


def _parse_ideas(text: str) -> list[dict[str, str]]:
    ideas: list[dict[str, str]] = []
    for item in _idea_objects(text):
        if not isinstance(item, dict):
            continue
        title = str(item.get("title", "")).strip()
        prompt = str(item.get("prompt", "")).strip()
        if title and prompt:
            area = str(item.get("area", "")).strip().lower()
            kind = str(item.get("kind", "")).strip().lower()
            idea = {
                "title": title[:80],
                "detail": str(item.get("detail", "")).strip()[:300],
                "prompt": prompt[:1000],
                "area": area if area in IDEA_AREAS else "fun",
                "kind": kind if kind in IDEA_KINDS else "chat",
            }
            if idea["kind"] == "routine":
                when = str(item.get("time", "")).strip()
                idea["time"] = when if re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", when) else "09:00"
            elif idea["kind"] == "goal":
                category = str(item.get("category", "")).strip().lower()
                idea["category"] = category if category in IDEA_GOAL_CATEGORIES else "other"
            ideas.append(idea)
    return ideas[:8]


def _parse_posts(text: str) -> list[dict[str, str]]:
    posts: list[dict[str, str]] = []
    for item in _idea_objects(text):
        if not isinstance(item, dict):
            continue
        title = str(item.get("title", "")).strip()
        body = str(item.get("body", "")).strip()
        if title and body:
            area = str(item.get("area", "")).strip().lower()
            posts.append(
                {
                    "title": title[:120],
                    "body": body[:2000],
                    "area": area if area in IDEA_AREAS else "fun",
                    "prompt": str(item.get("prompt", "")).strip()[:1000],
                }
            )
    return posts[:6]


__all__ = ["MuseService", "Profile", "Thread", "goal_to_dict", "new_id"]

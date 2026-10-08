"""The first conversation, the way the phones and the desktop do it (contract C4), for the
web app: the runtime owns the state, the web stays thin.

The setup pages end with Start, which binds the main chat as the first conversation. There
the app speaks first — three scripted lines, zero tokens, never in the model's history — and
asks what to call the person. From then on the model does the talking and reports what
happened in a small ``nanomuse-naming`` block at the end of its reply; the phase moves on
that block and on nothing else. A reply without one means the person talked about something
else, the model helped and steered back, and the phase stays.

Phases: ``none → ask_user_name → ask_agent_name → named → done``. The same words, name
pools and prompt as ``harness/dsh-nanomuse/src/firstrun.ts`` and
``onboarding/FirstConversation.kt``; the pure machine is here, :class:`MuseService`
applies it (the addendum for the bound thread only, ``after_turn`` when its reply ends).
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Literal

from nanomuse.fences import FENCE_NAMING, MAX_NAME, parse_naming_block
from nanomuse.logger import logger

Phase = Literal["none", "ask_user_name", "ask_agent_name", "named", "done"]
PHASES: tuple[Phase, ...] = ("none", "ask_user_name", "ask_agent_name", "named", "done")
FILE_NAME = "firstrun.json"


@dataclass
class FirstRunState:
    """Everything the first conversation remembers; one JSON file under the data dir."""

    version: int = 1
    phase: Phase = "none"
    # the thread the first conversation is bound to; None until Start
    session_id: str | None = None
    # how the person asked to be addressed, when they said
    user_address: str | None = None
    # the model's name suggestions for itself, when it gave some
    suggestions: list[str] = field(default_factory=list)
    # the name the agent got in the first conversation, when it did
    chosen: str | None = None
    # the language the opening was shown in ("en" or "zh"): the prompt quotes it back
    lang: str = ""
    # seconds since the epoch; 0 until it happened
    started_at: float = 0.0
    finished_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": 1,
            "phase": self.phase,
            "session_id": self.session_id,
            "user_address": self.user_address,
            "suggestions": list(self.suggestions),
            "chosen": self.chosen,
            "lang": self.lang,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }

    @classmethod
    def from_dict(cls, raw: Any) -> FirstRunState:
        """A tolerant read of the file: what is missing takes the empty value."""
        if not isinstance(raw, dict):
            return cls()
        phase = raw.get("phase")

        def text(v: Any) -> str | None:
            return v if isinstance(v, str) and v else None

        def number(v: Any) -> float:
            return float(v) if isinstance(v, int | float) and not isinstance(v, bool) else 0.0

        suggestions = raw.get("suggestions")
        return cls(
            phase=phase if phase in PHASES else "none",
            session_id=text(raw.get("session_id")),
            user_address=text(raw.get("user_address")),
            suggestions=[s for s in suggestions if isinstance(s, str) and s.strip()][:3]
            if isinstance(suggestions, list)
            else [],
            chosen=text(raw.get("chosen")),
            lang=str(raw.get("lang") or ""),
            started_at=number(raw.get("started_at")),
            finished_at=number(raw.get("finished_at")),
        )


# ---- the opening the app speaks on its own behalf ----------------------------------------


def is_zh(lang: str) -> bool:
    return lang.lower().startswith("zh")


def intro_lines(lang: str) -> list[str]:
    """The three opening paragraphs, in the person's language; the phone's words, with the
    computer in the phone's place (the web runs against a runtime on a computer)."""
    if is_zh(lang):
        return [
            "你好，我是 nanoMuse，住在你电脑里的私人助理。让我替你分担几件事。",
            "先说说我怎么工作：\n\n"
            "- 我就在这台电脑上工作，能跑命令、打开网页、填表单。\n"
            "- 你指给我的文件和文件夹，我能读、能整理；提醒和定时任务也可以交给我。\n"
            "- 关键的一步之前，我会先问你。\n"
            "- 一切都在这台电脑上跑。对话发给你自己配置的模型；登录 nanoMuse Cloud 后，这段对话也会同步到你的其他设备，可以在「数据控制」里关掉。",
            "开始之前，我该怎么称呼你？",
        ]
    return [
        "Hi, I'm nanoMuse, the assistant that lives on your computer. "
        "Let me take a few things off your plate.",
        "A bit about how I work:\n\n"
        "- I work on this computer: I can run commands, open websites and fill in forms.\n"
        "- I can read and organise the files and folders you point me to, and take care of "
        "reminders and scheduled tasks.\n"
        "- Before any step that matters, I ask you first.\n"
        "- Everything runs on this computer. Your messages go to the model you configured; "
        "signed in to nanoMuse Cloud, this conversation also follows you to your other devices; "
        "Data controls switches that off.",
        "Before we start, what should I call you?",
    ]


# ---- name suggestions --------------------------------------------------------------------

NAME_POOL_EN = ("Pip", "Wren", "Juno", "Remy", "Tilly", "Milo", "Sol", "Fig")
NAME_POOL_ZH = ("豆丁", "小满", "团团", "叮叮", "小北", "一一", "小竹", "阿岳")


def hash_code(s: str) -> int:
    """Java's ``String.hashCode`` over UTF-16 units, so a seed shuffles the same way it does
    on the phone and the desktop."""
    h = 0
    units = s.encode("utf-16-le")
    for i in range(0, len(units), 2):
        unit = units[i] | (units[i + 1] << 8)
        h = (31 * h + unit) & 0xFFFFFFFF
    return h - 0x100000000 if h >= 0x80000000 else h


def built_in_suggestions(seed: str, lang: str) -> list[str]:
    """Two names from the pool, shuffled by the session id so the same chat always offers
    the same two (xorshift32, as on the desktop)."""
    pool = list(NAME_POOL_ZH if is_zh(lang) else NAME_POOL_EN)
    x = (hash_code(seed) & 0xFFFFFFFF) or 0x9E3779B9

    def next_unit() -> float:
        nonlocal x
        x ^= (x << 13) & 0xFFFFFFFF
        x ^= x >> 17
        x ^= (x << 5) & 0xFFFFFFFF
        return x / 0x100000000

    for i in range(len(pool) - 1, 0, -1):
        j = int(next_unit() * (i + 1))
        pool[i], pool[j] = pool[j], pool[i]
    return pool[:2]


def current_suggestions(state: FirstRunState, lang: str) -> list[str]:
    """The model's suggestions when it gave some; otherwise two from the pool."""
    if state.suggestions:
        return list(state.suggestions)
    return built_in_suggestions(state.session_id or "", lang)


# ---- the phase machine -------------------------------------------------------------------


def start_conversation(
    state: FirstRunState, session_id: str, lang: str = "", now: float | None = None
) -> FirstRunState:
    """Bind the first conversation to ``session_id`` and step into the opening when this is
    the start; a conversation that already ran its course stays over."""
    now = time.time() if now is None else now
    nxt = replace(state, session_id=session_id, lang=lang or state.lang)
    if nxt.phase == "none":
        nxt.phase = "ask_user_name"
        nxt.started_at = now
    return nxt


@dataclass
class TurnOutcome:
    state: FirstRunState
    # the chooser belongs under this reply
    show_card: bool = False
    # the person said how to address them (None: they would rather not be addressed by anything)
    address_given: str | None = None
    # the `user_address` key was there at all
    address_said: bool = False
    # the agent got its name in this turn
    named: str | None = None


def after_turn(state: FirstRunState, assistant_text: str | None) -> TurnOutcome:
    """The model's reply finished. Reads its ``nanomuse-naming`` block, if any, and moves the
    phase; a reply without one leaves the phase where it is."""
    block = parse_naming_block(assistant_text)
    if state.phase == "ask_user_name":
        if block is None or not block.address_given:
            return TurnOutcome(state)
        nxt = replace(
            state,
            phase="ask_agent_name",
            user_address=block.user_address or state.user_address,
            suggestions=list(block.suggestions) if block.suggestions else list(state.suggestions),
        )
        return TurnOutcome(nxt, show_card=True, address_given=block.user_address, address_said=True)
    if state.phase == "ask_agent_name":
        name = block.agent_name if block is not None else None
        if name:
            # the model already replied as itself in this turn, so the ritual is over
            return TurnOutcome(
                replace(state, phase="done", chosen=name, finished_at=time.time()), named=name
            )
        return TurnOutcome(state, show_card=True)
    if state.phase == "named":
        return TurnOutcome(replace(state, phase="done", finished_at=time.time()))
    return TurnOutcome(state)


def pick_name(state: FirstRunState, name: str) -> FirstRunState | None:
    """A chip was picked: the name is saved at once; the model's next reply is its first as
    itself. None when no pick is due."""
    if state.phase != "ask_agent_name":
        return None
    return replace(state, phase="named", chosen=name)


def dismiss_chooser(state: FirstRunState) -> FirstRunState:
    """The person moved on to something the app handles itself: the chooser goes, the
    ritual is over."""
    if state.phase != "ask_agent_name":
        return state
    return replace(state, phase="done", finished_at=time.time())


def bound_to(state: FirstRunState, session_id: str | None) -> bool:
    """The first conversation is bound to this thread (started there, or still there)."""
    return session_id is not None and state.session_id == session_id and state.phase != "none"


def running(state: FirstRunState) -> bool:
    """Started and not over: its turns are never tasks, and the model hears the addendum."""
    return state.phase not in ("none", "done")


def conversation_over(state: FirstRunState) -> bool:
    return state.phase == "done"


# ---- what the model is told --------------------------------------------------------------

TAKEN_NAMES = (
    "Siri, Alexa, Cortana, Jarvis, Muse, Gemini, Copilot, 小爱, 小度, 小艺, 天猫精灵, 豆包, "
    "文心, 通义, 阿福"
)

CAN_DO = (
    "running commands on this computer, opening websites and filling in forms, reading and "
    "organising the files and folders they point you to, setting reminders and scheduled "
    "tasks, searching the web"
)


def prompt_addendum(state: FirstRunState, lang: str, agent_name: str) -> str | None:
    """The system-prompt addendum for the current phase; None once it is over. ``agent_name``
    is the name on file now."""
    address_line = (
        f' The user goes by "{state.user_address}"; address them that way.'
        if state.user_address
        else ""
    )
    if state.phase == "ask_user_name":
        lines = "\n".join("  > " + line.replace("\n", "\n  > ") for line in intro_lines(lang))
        return "\n".join(
            [
                "First conversation. The app already showed the user this opening on your behalf:",
                lines,
                "They are now replying to the last line (what should I call you?). Decide from "
                "their message what they meant:",
                '(a) If it says how to address them (a name, a nickname, "just call me boss"), '
                "confirm it in one short sentence, ask in one sentence what they would like to "
                "call you, and end the reply with exactly this fenced block:",
                "```" + FENCE_NAMING,
                '{"user_address": "<how to address them>", "suggest": ["<name 1>", "<name 2>"]}',
                "```",
                "`suggest` holds two names for yourself the user could pick, in the language "
                "they write: two-character Chinese names in the spirit of 豆丁 or 小满 (warm, a "
                "little playful, easy to say) when they write Chinese; short English names like "
                "Pip or Wren otherwise. Never suggest the name of an existing assistant or "
                f"product ({TAKEN_NAMES}), nor the user's own name. The app renders the block "
                "as a chooser under your reply, so do not list the names in your text.",
                "(b) If they say they would rather not be called anything in particular, do "
                'the same with "user_address": null.',
                "(c) If the message is about something else (a question, a task, small talk), "
                "help with it first, in full, and end with one light sentence bringing the "
                "question back (what should I call you?). No block in that case; the app keeps "
                "waiting.",
                "Reply in the user's language; keep it short.",
            ]
        )
    if state.phase == "ask_agent_name":
        chips = current_suggestions(state, lang)
        quoted = ", ".join(f'"{c}"' for c in chips)
        first = chips[0] if chips else ""
        return "\n".join(
            [
                "First conversation. You asked what the user would like to call you; the app "
                f"is showing a chooser under that question with {quoted} and "
                '"something else". Decide from their message:',
                '(a) If it gives you a name (typed on its own, "call you 豆丁", "the first '
                f'one" (meaning "{first}")), that is your name from now on. Reply as yourself: '
                "one short line about the name, then three bullets with the most useful things "
                "you can do for them right now on this computer (choose from: "
                f"{CAN_DO}), one concrete line each, no emoji; end by asking what they want to "
                "try first. Then end the reply with exactly this fenced block:",
                "```" + FENCE_NAMING,
                '{"agent_name": "<the name>"}',
                "```",
                "The app saves the name from the block; no tool call is needed for it.",
                "(b) If the message is about something else, help with it first, in full, and "
                "end with one light sentence bringing the naming back; no block, the chooser "
                "stays.",
                "Reply in the user's language." + address_line,
            ]
        )
    if state.phase == "named":
        return (
            f'First conversation. The user just named you "{agent_name}"; the app already '
            "saved it, so it is your name now; no tool call is needed for it. "
            "Reply in the user's language: one short line about the name, then three bullets "
            "with the most useful things you can do for them right now on this computer "
            f"(choose from: {CAN_DO}). One concrete line each, no emoji. End by asking what "
            "they want to try first." + address_line
        )
    return None


# ---- the memory line ---------------------------------------------------------------------

ADDRESS_PREFIX = "Call them:"


def address_memory(current: str, address: str) -> str:
    """The memory text the phones write under ``## About the user`` when the person said how
    to be addressed: one ``- Call them: …`` line, replaced when it changes."""
    line = f"- {ADDRESS_PREFIX} {address}"
    lines = current.split("\n")
    if any(ln.strip().startswith(f"- {ADDRESS_PREFIX}") for ln in lines):
        return "\n".join(
            line if ln.strip().startswith(f"- {ADDRESS_PREFIX}") else ln for ln in lines
        )
    if not current.strip():
        return f"## About the user\n{line}\n"
    return f"{current.rstrip()}\n\n## About the user\n{line}\n"


def address_line(address: str) -> str:
    """The same fact as one memory item (the runtime keeps memories as items, not a file)."""
    return f"{ADDRESS_PREFIX} {address}"


# ---- the file ----------------------------------------------------------------------------


class FirstRunStore:
    """The state on disk under the data directory, read once and written on every change."""

    def __init__(self, data_dir: Path) -> None:
        self.path = data_dir / FILE_NAME
        self.state = FirstRunState()
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            self.state = FirstRunState.from_dict(json.loads(self.path.read_text("utf-8")))
        except (OSError, ValueError) as exc:
            logger.warning("could not read {}: {}", self.path, exc)

    def save(self, state: FirstRunState) -> None:
        self.state = state
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(state.to_dict(), ensure_ascii=False, indent=1), "utf-8")
        except OSError as exc:  # pragma: no cover - a read-only data dir
            logger.warning("could not save {}: {}", self.path, exc)

    def view(self, lang: str) -> dict[str, Any]:
        """What the API and the ``firstrun`` frame carry: the state plus the chips."""
        s = self.state
        return {
            **s.to_dict(),
            "running": running(s),
            "chips": current_suggestions(s, s.lang or lang),
        }


__all__ = [
    "CAN_DO",
    "FILE_NAME",
    "MAX_NAME",
    "NAME_POOL_EN",
    "NAME_POOL_ZH",
    "PHASES",
    "TAKEN_NAMES",
    "FirstRunState",
    "FirstRunStore",
    "Phase",
    "TurnOutcome",
    "address_line",
    "address_memory",
    "after_turn",
    "bound_to",
    "built_in_suggestions",
    "conversation_over",
    "current_suggestions",
    "dismiss_chooser",
    "hash_code",
    "intro_lines",
    "is_zh",
    "pick_name",
    "prompt_addendum",
    "running",
    "start_conversation",
]

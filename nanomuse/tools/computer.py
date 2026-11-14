"""Operating this computer's screen: ``computer_screen``, ``computer_act`` and
``computer_task`` — the phone's three tools with a mouse and a keyboard under them.

They exist only while the hands are turned on (``[hands] enabled``, the switch in the app),
and they are the last rung: a command in the shell, a file, a web page or a skill that does
the thing exactly comes first; the screen is for what has no other door — a desktop app, a
dialog, a page that will not load without a real browser session.

Risk is judged like the phone's: looking is safe but private; a click is *moderate* until
the words under the cursor say pay, transfer, send, delete, confirm — then it is *sensitive*
and asked every time. Every pointed action carries a ``label`` (the words on the button or
field, as the screenshot shows them); the window in front is the *target* of a standing
approval, so "always allow in Terminal" never covers the bank's site in a browser.

Applications are asked for one by one: the first action in an application in a conversation
asks "Let <Muse> use <App>?" (once, this conversation, always — a ``computer_app:<id>``
grant the Permissions page lists). On macOS the hands can work in one application's window
(``[hands] mode``, :mod:`nanomuse.computer.mac_window`): ``computer_target`` names it, or
``app`` on any ``computer_act`` call; the screenshot the model sees is then that window and
the person keeps the cursor.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

from pydantic import ConfigDict

from nanomuse.agent.holds import HAND_OVER_TIMEOUT_S
from nanomuse.computer.coords import box_centre, from_norm
from nanomuse.computer.hands import looks_like_an_application
from nanomuse.computer.link import ACTIONS, POINTED, ComputerLink
from nanomuse.config import GUISettings
from nanomuse.phone.link import STOP_MARKER, DeviceError, DeviceStopped
from nanomuse.phone.screen import Screen
from nanomuse.schema import RiskLevel, ToolResult
from nanomuse.tools.base import BaseTool, CallAssessment, number_arg
from nanomuse.tools.surface import (
    COMPUTER,
    hand_over,
    inside,
    num,
    screen_result,
    trusted_node_words,
    wait_hold,
)

# the actions of the tool that are not actions of the hands
_TOOL_ONLY = ("hand_over", "computer_target")

if TYPE_CHECKING:
    from nanomuse.phone.operator import PhoneOperator

# key combinations that leave the current app or change what is on disk
_HEAVY_COMBOS = {
    ("alt", "f4"): "closes the window",
    ("ctrl", "q"): "quits the application",
    ("command", "q"): "quits the application",
    ("ctrl", "w"): "closes the tab or window",
    ("command", "w"): "closes the tab or window",
    ("ctrl", "s"): "saves a file",
    ("command", "s"): "saves a file",
    ("ctrl", "shift", "delete"): "clears browsing data",
}


class ComputerScreen(BaseTool):
    """Read this computer's screen."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    name: str = "computer_screen"
    purpose: str = "Look at this computer's screen: screenshot and the window in front."
    keywords: list[str] = ["screen", "screenshot", "computer", "look"]
    description: str = (
        "Look at this computer's screen: a screenshot, which window is in front and the "
        "picture's size as W×H. Coordinates for `computer_act` are pixels of that picture, "
        "(0,0) top-left; the picture is the unit, not the display. Call it again after the "
        "screen changed. For a whole job on the screen, prefer `computer_task`."
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "app": {
                "type": "string",
                "description": "macOS: look at this application's window only (window mode)",
            }
        },
    }
    risk: RiskLevel = RiskLevel.SAFE
    reads_private_data: bool = True
    link: ComputerLink
    holds: Any = None

    async def execute(self, **kwargs: Any) -> ToolResult:
        note = await wait_hold(self.holds, COMPUTER)
        app = str(kwargs.get("app") or "").strip()
        if app:
            self.link.set_target(app)
        try:
            screen = await self.link.screen()
        except DeviceStopped as exc:
            return ToolResult.fail(f"{exc} ({STOP_MARKER})")
        except DeviceError as exc:
            return ToolResult.fail(str(exc))
        return screen_result(screen, COMPUTER, note)


class ComputerAct(BaseTool):
    """One action of the mouse or keyboard on this computer."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    name: str = "computer_act"
    purpose: str = "Do one action on this computer's screen, then look again."
    keywords: list[str] = ["click", "type", "computer", "screen", "act"]
    description: str = (
        "One action on this computer's screen, then a fresh look. `click`, `double_click`, "
        "`right_click`, `middle_click` or `move` at `x`/`y`, pixels of the last screenshot, "
        "(0,0) its top-left, W×H as `computer_screen` said; or `box` [x1,y1,x2,y2] in the same "
        "pixels, whose centre is used, with `label`, the words of what is under the cursor, "
        "as the screen shows them; `drag` from `x`/`y` to `x2`/`y2` (or `box` to `box2`); "
        "`scroll` at `x`/`y` by `dy` pixels (negative = up); `type` `text` "
        "into the focused field (`clear` first, `submit` to press Enter after); `key` presses "
        '`keys` together (e.g. ["ctrl", "s"]); `open_app` starts an application by name; '
        "`wait` `seconds`; `hand_over` with a `reason` gives the screen to the user for a "
        "password, a code or a confirmation only they can give; they press Done and you get "
        "the screen as they left it. On macOS, `computer_target` with `app` makes the hands "
        "work in that application's window only (the screenshot is then that window, and "
        "coordinates are pixels of it; the user keeps the mouse); `app` on any other action "
        "does the same first. The first action in an application asks the user once. Use "
        "`computer_task` for anything longer than a few steps."
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": [*ACTIONS, *_TOOL_ONLY]},
            "reason": {
                "type": "string",
                "description": "for hand_over: what the user should do, in their language",
            },
            "x": {"type": "number", "description": "pixels of the last screenshot, from its left"},
            "y": {"type": "number", "description": "pixels of the last screenshot, from its top"},
            "x2": {"type": "number"},
            "y2": {"type": "number"},
            "box": {
                "type": "array",
                "items": {"type": "number"},
                "description": "instead of x/y: [x1, y1, x2, y2] around the target; its centre is used",
            },
            "box2": {
                "type": "array",
                "items": {"type": "number"},
                "description": "for drag, instead of x2/y2: the box the drag ends in",
            },
            "dy": {"type": "number", "description": "scroll amount in pixels; negative = up"},
            "label": {
                "type": "string",
                "description": "the words of what is under the cursor, as shown on the screen",
            },
            "text": {"type": "string"},
            "clear": {"type": "boolean", "description": "select all before typing"},
            "submit": {"type": "boolean", "description": "press Enter after typing"},
            "keys": {"type": "array", "items": {"type": "string"}},
            "app": {
                "type": "string",
                "description": (
                    "for open_app: the application to start; for computer_target (or with any "
                    "action, macOS): the application whose window the hands work in; empty "
                    "with computer_target = the whole screen again"
                ),
            },
            "seconds": {"type": "number"},
        },
        "required": ["action"],
    }
    risk: RiskLevel = RiskLevel.MODERATE
    link: ComputerLink
    gui: GUISettings
    holds: Any = None
    hand_over_timeout: float = HAND_OVER_TIMEOUT_S
    # the per-app gate: async (app_id, label) -> bool; None = no per-app asks (tests)
    app_gate: Any = None

    # ------------------------------------------------------------------ risk
    def assess(self, args: dict[str, Any]) -> CallAssessment:
        action = str(args.get("action") or "")
        if action == "hand_over":
            return CallAssessment(
                risk=RiskLevel.SAFE,
                summary=f"computer_act: hand over: {str(args.get('reason') or '')[:80]}",
            )
        if action == "computer_target":
            wanted = str(args.get("app") or "").strip()
            return CallAssessment(
                risk=RiskLevel.SAFE,
                reads_private_data=True,
                target=wanted or None,
                summary=f"computer_act: work in {wanted}"
                if wanted
                else "computer_act: whole screen",
            )
        screen = self.link.last_screen
        app = (screen.app_name or screen.app if screen else "") or None
        where = f" in {screen.title}" if screen and screen.title != "phone" else ""
        label = str(args.get("label") or "").strip()
        shown = f' "{label[:60]}"' if label else ""
        at = (
            f" at ({num(args.get('x'))},{num(args.get('y'))})"
            if args.get("x") is not None and args.get("y") is not None
            else ""
        )
        if action in POINTED:
            summary = f"computer_act: {action}{shown}{at}{where}"
        elif action == "type":
            text = str(args.get("text") or "")
            summary = (
                f'computer_act: type "{text[:40]}"'
                + (f" into{shown}" if label else "")
                + (" and press enter" if args.get("submit") else "")
                + where
            )
        elif action == "key":
            summary = (
                f"computer_act: press {'+'.join(str(k) for k in args.get('keys') or [])}{where}"
            )
        elif action == "drag":
            summary = f"computer_act: drag{shown}{at}{where}"
        elif action == "scroll":
            summary = f"computer_act: scroll {num(args.get('dy') or 300)}px{at}{where}"
        elif action == "open_app":
            summary = f"computer_act: open {args.get('app') or '?'}"
        else:
            summary = f"computer_act: {action}{shown}{where}"

        words = list(self.gui.sensitive_words)
        risk, warnings, egress = RiskLevel.MODERATE, [], False
        hit: list[str] = []
        # The sensitive words are looked for in the model's `label` and, when the screen
        # reported elements with bounds, in the words of the element under the point: the
        # label is the model's word for what it is about to press, the element the
        # screen's. A screen without elements (the computer's screenshot, a WebView, a
        # game) is the common case and changes nothing here.
        pointed = (action in POINTED and action != "move") or action == "drag"
        trusted = (
            trusted_node_words(screen, self._assessment_point(args, screen)) if pointed else None
        )
        evidence = " / ".join(part for part in (label, trusted or "") if part)
        if pointed and evidence:
            hit = [w for w in words if w.lower() in evidence.lower()]
        if action in POINTED and action != "move" and not label:
            warnings.append("a click with no `label`: nothing says what is under the cursor")
        if action == "type" and args.get("submit"):
            risk, egress = RiskLevel.SENSITIVE, True
        if action == "key":
            combo = tuple(str(k).lower() for k in args.get("keys") or [])
            if combo == ("enter",) or combo == ("return",):
                risk, egress = RiskLevel.SENSITIVE, True
            elif combo in _HEAVY_COMBOS:
                risk = RiskLevel.SENSITIVE
                warnings.append(_HEAVY_COMBOS[combo])
        if hit:
            risk = RiskLevel.SENSITIVE
            warnings.append(f"the words under the cursor say: {', '.join(hit)}")
        wanted_app = str(args.get("app") or "").strip()
        if action == "open_app" and wanted_app and not looks_like_an_application(wanted_app):
            risk = RiskLevel.SENSITIVE
            warnings.append(f"{wanted_app!r} is a command to the machine, not an application")
        return CallAssessment(
            risk=risk,
            reads_private_data=True,
            egress=egress,
            target=app,
            summary=summary,
            warnings=warnings,
        )

    def _assessment_point(
        self, args: dict[str, Any], screen: Screen | None
    ) -> tuple[float, float] | None:
        try:
            return _point(
                args,
                "x",
                "y",
                "box",
                screen,
                self.link.settings.coords == "norm1000",
            )
        except ValueError:
            return None

    # ------------------------------------------------------------------ doing
    async def execute(self, **kwargs: Any) -> ToolResult:
        action = str(kwargs.get("action") or "")
        if action == "hand_over":
            return await hand_over(
                self.holds,
                self.link,
                str(kwargs.get("reason") or ""),
                self.hand_over_timeout,
                COMPUTER,
            )
        if action == "computer_target":
            return await self._target(str(kwargs.get("app") or ""))
        if action not in ACTIONS:
            return ToolResult.fail(
                f"unknown action '{action}'. One of: {', '.join((*ACTIONS, *_TOOL_ONLY))}"
            )
        note = await wait_hold(self.holds, COMPUTER)
        wanted = str(kwargs.get("app") or "").strip()
        if wanted and action != "open_app" and wanted != self.link.target_app:
            # `app` with an action: the window to work in, looked at before acting
            self.link.set_target(wanted)
            try:
                await self.link.screen()
            except DeviceError as exc:
                return ToolResult.fail(str(exc))
        if action != "wait":
            refused = await self._app_allowed(wanted if action == "open_app" else "")
            if refused is not None:
                return refused
        params: dict[str, Any] = {"action": action}
        label = str(kwargs.get("label") or "").strip()
        if label:
            params["label"] = label[:120]
        screen = self.link.last_screen
        norm = self.link.settings.coords == "norm1000"
        if action in (*POINTED, "drag", "scroll"):
            try:
                point = _point(kwargs, "x", "y", "box", screen, norm)
            except ValueError as exc:
                return ToolResult.fail(str(exc))
            if point is None:
                return ToolResult.fail(
                    f"`{action}` needs `x` and `y` (pixels of the last screenshot) or `box`"
                )
            if screen is not None and not inside(point, screen, COMPUTER):
                return ToolResult.fail(
                    f"({point[0]:g},{point[1]:g}) is outside the {screen.width}×{screen.height} picture"
                )
            params["x"], params["y"] = point
        if action in POINTED and action != "move" and not label:
            return ToolResult.fail(
                f"`{action}` needs `label`: the words of what is under the cursor, as the screen "
                "shows them (the Sentinel and the audit log go by it)"
            )
        if action == "drag":
            try:
                end = _point(kwargs, "x2", "y2", "box2", screen, norm)
            except ValueError as exc:
                return ToolResult.fail(str(exc))
            if end is None:
                return ToolResult.fail("`drag` needs `x2`/`y2` or `box2` (where the drag ends)")
            if screen is not None and not inside(end, screen, COMPUTER):
                return ToolResult.fail(
                    f"({end[0]:g},{end[1]:g}) is outside the {screen.width}×{screen.height} picture"
                )
            params["x2"], params["y2"] = end
        if action == "scroll":
            raw_dy = kwargs.get("dy")
            try:
                params["dy"] = float(raw_dy) if raw_dy is not None else 300.0
            except (TypeError, ValueError):
                return ToolResult.fail("`dy` must be a number of pixels")
        if action == "type":
            text = kwargs.get("text")
            if text is None:
                return ToolResult.fail("`type` needs `text`")
            params.update(
                text=str(text)[:4000],
                clear=bool(kwargs.get("clear")),
                submit=bool(kwargs.get("submit")),
            )
        if action == "key":
            keys = kwargs.get("keys")
            if isinstance(keys, str):
                keys = [k for k in keys.replace("+", " ").split() if k]
            if not isinstance(keys, list) or not keys:
                return ToolResult.fail('`key` needs `keys`, e.g. ["ctrl", "s"]')
            params["keys"] = [str(k)[:20] for k in keys][:5]
        if action == "open_app":
            app = str(kwargs.get("app") or "").strip()
            if not app:
                return ToolResult.fail("`open_app` needs `app`")
            params["app"] = app[:80]
        if action == "wait":
            params["seconds"] = number_arg(kwargs.get("seconds"), 1.0, 0.2, 10.0)
        try:
            raw = await self.link.act(
                params, timeout=self.gui.device_timeout_s + params.get("seconds", 0)
            )
        except DeviceStopped as exc:
            return ToolResult.fail(f"{exc} ({STOP_MARKER})")
        except DeviceError as exc:
            return ToolResult.fail(str(exc))
        said = str(raw.get("note") or "")
        done = (note + "\n\n" if note else "") + "Done" + (f": {said}" if said else "")
        after = self.link.last_screen
        if after is None or not raw.get("looked", True):
            return ToolResult(output=f"{done}. The screen could not be read afterwards.")
        return screen_result(after, COMPUTER, done + ". Screen now:")

    async def _target(self, app: str) -> ToolResult:
        """``computer_target``: the application the hands work in from now on, and a look
        at it. Without window mode (not macOS, no pyobjc) the hands stay on the screen and
        say so."""
        self.link.set_target(app)
        if not app.strip():
            try:
                screen = await self.link.screen()
            except DeviceError as exc:
                return ToolResult.fail(str(exc))
            return screen_result(screen, COMPUTER, "Working on the whole screen again.")
        ok, why = self.link.window_available()
        if not ok or self.link.settings.mode == "screen":
            why = why or "[hands] mode is 'screen'"
            try:
                screen = await self.link.screen()
            except DeviceError as exc:
                return ToolResult.fail(str(exc))
            return screen_result(
                screen,
                COMPUTER,
                f"Window mode is not available here ({why}); the hands work on the whole screen, "
                f"with {app.strip()} as the application they are about. Screen now:",
            )
        try:
            screen = await self.link.screen()
        except DeviceStopped as exc:
            return ToolResult.fail(f"{exc} ({STOP_MARKER})")
        except DeviceError as exc:
            return ToolResult.fail(str(exc))
        frame = self.link.window_frame
        if frame is None:
            return screen_result(
                screen,
                COMPUTER,
                f"{app.strip()} could not be worked in as a window ({self.link.status()['window']['reason']}); "
                "showing the whole screen instead.",
            )
        w = frame.window
        where = f"Working in the window of {w.owner}" + (f", {w.title}" if w.title else "")
        return screen_result(
            screen,
            COMPUTER,
            f"{where}. Coordinates are pixels of this {frame.image_width}×{frame.image_height} "
            "window picture; the user keeps the mouse. Window now:",
        )

    async def _app_allowed(self, opening: str = "") -> ToolResult | None:
        """The per-app permission: the first action in an application asks the user
        ("Let <Muse> use <App>?"). None when allowed, the refusal otherwise."""
        if self.app_gate is None:
            return None
        if opening:
            app_id, label = opening, opening
        else:
            app_id, label = self.link.app_in_front()
        if not app_id:
            return None
        if await self.app_gate(app_id, label):
            return None
        return ToolResult.fail(
            f"the user did not allow the hands in {label}. Do not retry; ask them, or do the "
            "job another way."
        )


class ComputerTask(BaseTool):
    """A whole job on this computer's screen, run step by step by the operator."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    name: str = "computer_task"
    purpose: str = "Hand a job on this computer's screen to the GUI operator."
    keywords: list[str] = ["computer", "gui", "task", "operator", "app"]
    description: str = (
        "Hand a job on this computer's screen to the operator: it opens the application, looks "
        "at the screen, clicks, types and scrolls step by step until the job is done, then "
        "reports what it found or did. Use it only for what has no other door (a desktop "
        "application, a dialog, a page that needs the user's real browser session) and not "
        "for what `shell`, `files`, `browser`, `web_fetch` or a skill does exactly and "
        "instantly. Give one concrete `goal` with the facts it needs and any `context` you "
        "already have; one goal per call, in order. It stops and asks before paying, sending or "
        "deleting; it never enters passwords or codes; it hands the screen to the user for "
        "those and carries on when they press Done. When it asks a question instead, put it to "
        "the user and call again with their answer in `context`."
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "goal": {"type": "string", "description": "what to achieve on the screen, concretely"},
            "context": {
                "type": "string",
                "description": "facts that help: what was found earlier, preferences, constraints",
            },
            "app": {"type": "string", "description": "the application to start in, if known"},
        },
        "required": ["goal"],
    }
    risk: RiskLevel = RiskLevel.MODERATE
    reads_private_data: bool = True
    link: ComputerLink
    operator: Any  # PhoneOperator with the computer dialect
    holds: Any = None

    def assess(self, args: dict[str, Any]) -> CallAssessment:
        goal = str(args.get("goal") or "")
        app = str(args.get("app") or "").strip() or None
        return CallAssessment(
            risk=self.risk,
            reads_private_data=True,
            target=app,
            summary=f"computer_task: {goal[:80]}" + (f" ({app})" if app else ""),
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        goal = str(kwargs.get("goal") or "").strip()
        if not goal:
            return ToolResult.fail("`goal` is required")
        if not self.link.connected:
            return ToolResult.fail(
                "the hands are not available on this computer: "
                + (self.link.status().get("reason") or "no backend")
            )
        operator: PhoneOperator = self.operator
        await wait_hold(self.holds, COMPUTER)
        outcome = await operator.run(
            goal, context=str(kwargs.get("context") or ""), app=str(kwargs.get("app") or "")
        )
        text = outcome.report()
        images = [outcome.last_image] if outcome.last_image else None
        return ToolResult(output=text, images=images)


def _point(
    args: dict[str, Any],
    kx: str,
    ky: str,
    kbox: str = "",
    screen: Screen | None = None,
    norm: bool = False,
) -> tuple[float, float] | None:
    """The point an action is aimed at, in pixels of the picture: ``x``/``y`` as given, or
    the centre of ``box``; on the 0–1000 grid when ``[hands] coords = "norm1000"`` (then
    the picture's size turns it into pixels). None when nothing was given; ValueError for
    a box of the wrong shape."""
    point: tuple[float, float] | None = None
    box = args.get(kbox) if kbox else None
    if args.get(kx) is not None and args.get(ky) is not None:
        try:
            point = float(args[kx]), float(args[ky])
        except (TypeError, ValueError):
            return None
    elif isinstance(box, list | tuple) and box:
        try:
            point = box_centre([float(v) for v in box])
        except (TypeError, ValueError) as exc:
            raise ValueError(f"`{kbox}` must be [x1, y1, x2, y2] in pixels of the picture") from exc
    if point is None:
        return None
    if not (math.isfinite(point[0]) and math.isfinite(point[1])):
        # NaN and infinity pass every comparison and would reach the device as they are
        raise ValueError(f"`{kx}`/`{ky}` must be finite numbers")
    if norm and screen is not None and screen.width and screen.height:
        point = from_norm(point[0], point[1], screen.width, screen.height)
    return point


__all__ = ["ComputerAct", "ComputerScreen", "ComputerTask"]

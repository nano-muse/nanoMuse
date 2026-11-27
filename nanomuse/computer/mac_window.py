"""Window mode on macOS: the hands work in *one* application's window and leave the rest
of the screen — and the person's cursor — alone.

Screen mode (:mod:`nanomuse.computer.hands`) drives the system mouse: while the operator
clicks, the person cannot. macOS lets a program do better. The window server lists the
windows on screen, one of them can be captured by id, and mouse and keyboard events can be
delivered straight to a process (``CGEventPostToPid``) — the pointer on the desk does not
move, the keyboard focus of the person's own window is not stolen. Typing goes in as unicode
keyboard events, so 中文 and emoji arrive as they are. When Accessibility is granted, a
button under the point can be pressed through the accessibility tree (``AXPress``) instead
of a synthetic click.

Everything that talks to the system is behind :class:`MacAdapter`, a thin protocol with two
real implementations, both imported lazily so this module imports on any platform:

* :class:`OperatorWindowAdapter` — under nanoMuse Desktop, the usual case. The list of
  windows and the picture of one come from the app's helper *nanoMuse Computer Use*
  (``GET /windows``, ``POST /window`` of :mod:`nanomuse.computer.operator`), which holds
  the Screen Recording grant and takes the picture with ScreenCaptureKit on macOS 14 and
  later; the runtime never captures the screen itself there. The events still go out from
  this process through pyobjc (``CGEventPostToPid`` posts to a pid; the helper's own
  ``/execute`` drives the system pointer, which window mode must not touch).
* :class:`QuartzAdapter` — the runtime on its own (no helper bundle, a run outside the
  app): ``CGWindowListCopyWindowInfo`` and ``CGWindowListCreateImage`` through pyobjc,
  announced in the log (``window mode: the runtime captures windows itself …``).

The logic above the adapter — choosing a window, mapping the model's coordinates (pixels
of the window picture) to screen points, sequencing the events of a click, a drag, a
scroll, a typed string, a key combination — is :class:`MacWindowHands`, and runs against a
fake adapter in the tests on Linux.

What the person grants once: *Screen Recording* for the capture — the helper's row,
**nanoMuse Computer Use**, under the app; *Accessibility* for the events (``CGEventPostToPid``
needs the posting process to be trusted), which macOS attributes to the *responsible*
application — the desktop app that spawned this runtime — so that row is **nanoMuse** (a
runtime started from a terminal is attributed to that terminal). Without the helper the
capture needs the app's own Screen Recording row as well. The settings page says which is
missing. Everything here fails soft: a window that cannot be found, captured or driven
raises :class:`WindowUnavailable` with the reason (:class:`WindowLayerBroken` when the
layer itself failed), and :class:`~nanomuse.computer.link.ComputerLink` falls back to the
shared screen with a notice.
"""

from __future__ import annotations

import base64
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

from nanomuse.computer.operator import OperatorClient, OperatorError
from nanomuse.logger import logger

# how many characters one unicode keyboard event carries (CGEvent takes ≤ 20 UTF-16 units)
UNICODE_CHUNK = 16
# a mouse press is this long on the way down (so apps that look at timing see a click)
PRESS_S = 0.04
# the virtual key codes of the US layout for the keys a combination names; letters and
# digits are below, the rest here. ``kVK_*`` in Carbon's Events.h.
VK = {
    "a": 0, "s": 1, "d": 2, "f": 3, "h": 4, "g": 5, "z": 6, "x": 7, "c": 8, "v": 9,
    "b": 11, "q": 12, "w": 13, "e": 14, "r": 15, "y": 16, "t": 17, "1": 18, "2": 19,
    "3": 20, "4": 21, "6": 22, "5": 23, "=": 24, "9": 25, "7": 26, "-": 27, "8": 28,
    "0": 29, "]": 30, "o": 31, "u": 32, "[": 33, "i": 34, "p": 35, "enter": 36, "l": 37,
    "j": 38, "'": 39, "k": 40, ";": 41, "\\": 42, ",": 43, "/": 44, "n": 45, "m": 46,
    ".": 47, "tab": 48, "space": 49, "`": 50, "backspace": 51, "esc": 53, "command": 55,
    "shift": 56, "capslock": 57, "alt": 58, "ctrl": 59, "f5": 96, "f6": 97, "f7": 98,
    "f3": 99, "f8": 100, "f9": 101, "f11": 103, "f13": 105, "f14": 107, "f10": 109,
    "f12": 111, "f15": 113, "help": 114, "home": 115, "pageup": 116, "delete": 117,
    "f4": 118, "end": 119, "f2": 120, "pagedown": 121, "f1": 122, "left": 123, "right": 124,
    "down": 125, "up": 126,
}  # fmt: skip
# the names a model (or pyautogui's table) uses for the same keys
KEY_ALIASES = {
    "return": "enter",
    "escape": "esc",
    "cmd": "command",
    "win": "command",
    "super": "command",
    "meta": "command",
    "option": "alt",
    "control": "ctrl",
    "del": "delete",
    "forward_delete": "delete",
    "page_up": "pageup",
    "page_down": "pagedown",
    "caps_lock": "capslock",
    "spacebar": "space",
}
MODIFIERS = ("command", "shift", "alt", "ctrl")
# CGEventFlags, as Quartz defines them (so the adapter needs no table of its own)
FLAG_BITS = {
    "shift": 1 << 17,
    "ctrl": 1 << 18,
    "alt": 1 << 19,
    "command": 1 << 20,
}


class WindowUnavailable(RuntimeError):
    """The window could not be found, captured or driven (and why)."""


class WindowLayerBroken(WindowUnavailable):
    """The Quartz layer itself failed (pyobjc, the window server) — not a window that went
    away. `auto` mode treats it as "window mode does not work here" for the current target."""


@dataclass
class WindowInfo:
    """One on-screen window, as the window server lists it."""

    id: int
    pid: int
    owner: str  # the application's name as shown in the menu bar
    title: str
    x: float  # points, top-left origin, the main display's corner is (0, 0)
    y: float
    width: float
    height: float
    layer: int = 0
    alpha: float = 1.0
    on_screen: bool = True
    bundle_id: str = ""

    @property
    def area(self) -> float:
        return max(0.0, self.width) * max(0.0, self.height)

    @property
    def app_id(self) -> str:
        """What a standing permission is bound to: the bundle id, else the name."""
        return self.bundle_id or self.owner

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "pid": self.pid,
            "app": self.owner,
            "bundle_id": self.bundle_id,
            "title": self.title,
            "bounds": [self.x, self.y, self.width, self.height],
        }


@dataclass
class WindowFrame:
    """The picture the model saw of a window and how its pixels map to the screen."""

    window: WindowInfo
    image_width: int
    image_height: int

    def to_screen(self, x: float, y: float) -> tuple[float, float]:
        """Window-picture pixels → screen points (what CGEvents take)."""
        sx = self.window.width / self.image_width if self.image_width else 1.0
        sy = self.window.height / self.image_height if self.image_height else 1.0
        px = self.window.x + min(max(x, 0.0), float(self.image_width)) * sx
        py = self.window.y + min(max(y, 0.0), float(self.image_height)) * sy
        return round(px, 2), round(py, 2)

    def contains(self, x: float, y: float) -> bool:
        return 0 <= x <= self.image_width and 0 <= y <= self.image_height


@dataclass
class MouseEvent:
    kind: str  # down | up | move | drag
    x: float
    y: float
    button: str = "left"
    clicks: int = 1


@dataclass
class KeyEvent:
    keycode: int
    down: bool
    flags: int = 0


class MacAdapter(Protocol):
    """The handful of Quartz / ApplicationServices calls the window hands need."""

    def windows(self) -> list[WindowInfo]: ...
    def capture(self, window_id: int) -> bytes | None:
        """The window as PNG (its own pixels only, no shadow), None when nothing came back."""
        ...

    def post_mouse(self, pid: int, event: MouseEvent) -> None: ...
    def post_key(self, pid: int, event: KeyEvent) -> None: ...
    def post_text(self, pid: int, text: str) -> None:
        """One keyboard event carrying ``text`` as its unicode string (≤ UNICODE_CHUNK)."""
        ...

    def post_scroll(self, pid: int, x: float, y: float, dy: float, dx: float = 0.0) -> None: ...
    def ax_press(self, pid: int, x: float, y: float) -> bool:
        """Press the accessible element under the point; False when there is none or
        Accessibility is not granted."""
        ...

    def trusted(self) -> bool:
        """Accessibility is granted to this process (events will be delivered)."""
        ...


# ---------------------------------------------------------------------- pure logic
def normalise_key(name: str) -> str:
    k = name.strip().lower()
    return KEY_ALIASES.get(k, k)


def choose_window(windows: list[WindowInfo], app: str, title: str = "") -> WindowInfo | None:
    """The window to work in for ``app`` (a name as the menu bar shows it, or a bundle id):
    the biggest ordinary window of the matching application, the one whose title matches
    when ``title`` is given. None when the application has no window on screen."""
    want = app.strip().lower()
    if not want:
        return None
    want_title = title.strip().lower()

    def matches(w: WindowInfo) -> int:
        owner, bundle = w.owner.lower(), w.bundle_id.lower()
        if want in (owner, bundle):
            return 3
        if bundle and (bundle.endswith("." + want) or want in bundle):
            return 2
        if want in owner or owner in want:
            return 1
        return 0

    candidates = [
        (matches(w), w)
        for w in windows
        if w.on_screen and w.layer == 0 and w.alpha > 0.05 and w.width >= 40 and w.height >= 40
    ]
    candidates = [(score, w) for score, w in candidates if score]
    if not candidates:
        return None
    best_score = max(score for score, _w in candidates)
    pool = [w for score, w in candidates if score == best_score]
    if want_title:
        titled = [w for w in pool if want_title in w.title.lower()]
        if titled:
            pool = titled
    # a window with a title over an untitled helper; then the biggest
    pool.sort(key=lambda w: (bool(w.title), w.area), reverse=True)
    return pool[0]


def unicode_chunks(text: str, size: int = UNICODE_CHUNK) -> list[str]:
    """``text`` in pieces one keyboard event can carry, never splitting a surrogate pair
    or a newline off its chunk."""
    out: list[str] = []
    buf = ""
    for ch in text:
        if ch in "\r\n":
            if buf:
                out.append(buf)
                buf = ""
            out.append("\n")
            continue
        buf += ch
        if len(buf.encode("utf-16-le")) // 2 >= size:
            out.append(buf)
            buf = ""
    if buf:
        out.append(buf)
    return out


def key_sequence(keys: list[str]) -> list[KeyEvent]:
    """The events of a combination: modifiers down, the key down and up with their flags,
    modifiers up in reverse. Unknown names raise ``ValueError``."""
    names = [normalise_key(k) for k in keys if k.strip()]
    if not names:
        return []
    mods = [n for n in names if n in MODIFIERS]
    plain = [n for n in names if n not in MODIFIERS]
    flags = 0
    for m in mods:
        flags |= FLAG_BITS[m]
    events: list[KeyEvent] = [KeyEvent(VK[m], True, flags) for m in mods]
    for n in plain:
        if n not in VK:
            raise ValueError(f"no key called {n!r} on this keyboard")
        events.append(KeyEvent(VK[n], True, flags))
        events.append(KeyEvent(VK[n], False, flags))
    if not plain:
        # a lone modifier (rare): press and release it
        events += [KeyEvent(VK[m], False, 0) for m in reversed(mods)]
        return events
    events += [KeyEvent(VK[m], False, 0) for m in reversed(mods)]
    return events


def mouse_sequence(
    kind: str, x: float, y: float, x2: float | None = None, y2: float | None = None
) -> list[MouseEvent]:
    """The events of one pointer action at screen points: ``click`` / ``double_click`` /
    ``right_click`` / ``middle_click`` / ``move`` / ``drag``."""
    if kind == "move":
        return [MouseEvent("move", x, y)]
    if kind == "drag":
        ex, ey = (x if x2 is None else x2), (y if y2 is None else y2)
        mx, my = (x + ex) / 2, (y + ey) / 2
        return [
            MouseEvent("move", x, y),
            MouseEvent("down", x, y),
            MouseEvent("drag", mx, my),
            MouseEvent("drag", ex, ey),
            MouseEvent("up", ex, ey),
        ]
    button = {"right_click": "right", "middle_click": "middle"}.get(kind, "left")
    clicks = 2 if kind == "double_click" else 1
    out = [MouseEvent("move", x, y)]
    for n in range(1, clicks + 1):
        out.append(MouseEvent("down", x, y, button, n))
        out.append(MouseEvent("up", x, y, button, n))
    return out


# ---------------------------------------------------------------------- the hands
@dataclass
class MacWindowHands:
    """The hands inside one window: the same verbs as :class:`~nanomuse.computer.hands.HandsBackend`,
    with coordinates in pixels of the window picture the model last saw.

    ``target`` is set by :meth:`look`; every action maps through its frame and is posted
    to the window's process. Nothing here touches the system cursor."""

    adapter: MacAdapter
    name: str = "window"
    frame: WindowFrame | None = None
    use_ax: bool = True
    sleep: Any = time.sleep
    # what was done, for the stage: the last action in screen points
    last_point: tuple[float, float] | None = None
    notes: list[str] = field(default_factory=list)

    # ------------------------------------------------------------------ the window
    def find(self, app: str, title: str = "") -> WindowInfo:
        try:
            windows = self.adapter.windows()
        except WindowUnavailable:
            raise  # the adapter's own words (the helper's grant is off)
        except Exception as exc:  # noqa: BLE001 — pyobjc raises many kinds
            raise WindowLayerBroken(f"the windows on screen could not be listed: {exc}") from exc
        window = choose_window(windows, app, title)
        if window is None:
            raise WindowUnavailable(f"{app} has no window on this screen (is it open?)")
        return window

    def look(self, app: str, title: str = "") -> tuple[bytes, WindowFrame]:
        """The window's picture (PNG) and the frame that maps its pixels back to the screen."""
        window = self.find(app, title)
        try:
            png = self.adapter.capture(window.id)
        except WindowUnavailable:
            raise  # the adapter's own words (a grant to switch on, a window that is gone)
        except Exception as exc:  # noqa: BLE001
            raise WindowLayerBroken(
                f"the window of {window.owner} could not be captured: {exc}"
            ) from exc
        if not png:
            raise WindowUnavailable(
                f"the window of {window.owner} came back empty: switch on nanoMuse Desktop "
                "(only that entry) under System Settings → Privacy & Security → Screen "
                "Recording, then quit and reopen the app"
            )
        width, height = png_size(png)
        if not width or not height:
            raise WindowUnavailable(f"the capture of {window.owner} was not a picture")
        self.frame = WindowFrame(window, width, height)
        return png, self.frame

    def _frame(self) -> WindowFrame:
        if self.frame is None:
            raise WindowUnavailable("no window has been looked at yet (call look first)")
        if not self.adapter.trusted():
            raise WindowUnavailable(
                "macOS has not granted the process controlling this window permission to send "
                "input. Check Accessibility for nanoMuse Desktop (or the terminal that started "
                "the runtime), then take a fresh look before trying again."
            )
        if self.frame.window not in self.adapter.windows():
            raise WindowUnavailable(
                "The selected window changed or closed after the last screenshot. "
                "Look at the window again before sending input."
            )
        return self.frame

    @staticmethod
    def _point(frame: WindowFrame, x: float, y: float) -> tuple[float, float]:
        if not frame.contains(x, y):
            raise WindowUnavailable(
                f"({x:g},{y:g}) is outside the {frame.image_width}×{frame.image_height} window picture"
            )
        return frame.to_screen(x, y)

    # ------------------------------------------------------------------ the verbs
    def click(self, x: float, y: float, button: str = "left", clicks: int = 1) -> None:
        frame = self._frame()
        sx, sy = self._point(frame, x, y)
        self.last_point = (sx, sy)
        if button == "left" and clicks == 1 and self.use_ax:
            try:
                if self.adapter.ax_press(frame.window.pid, sx, sy):
                    self.notes.append("pressed through accessibility")
                    return
            except Exception as exc:  # noqa: BLE001 — AX is a shortcut, never a stop
                logger.debug("AXPress at ({}, {}) failed: {}", sx, sy, exc)
        kind = {"right": "right_click", "middle": "middle_click"}.get(button, "click")
        if clicks >= 2 and kind == "click":
            kind = "double_click"
        self._post_mouse(frame.window.pid, mouse_sequence(kind, sx, sy))

    def move(self, x: float, y: float) -> None:
        frame = self._frame()
        sx, sy = self._point(frame, x, y)
        self.last_point = (sx, sy)
        self._post_mouse(frame.window.pid, mouse_sequence("move", sx, sy))

    def drag(self, x: float, y: float, x2: float, y2: float) -> None:
        frame = self._frame()
        sx, sy = self._point(frame, x, y)
        ex, ey = self._point(frame, x2, y2)
        self.last_point = (ex, ey)
        self._post_mouse(frame.window.pid, mouse_sequence("drag", sx, sy, ex, ey))

    def scroll(self, x: float, y: float, dy: float) -> None:
        frame = self._frame()
        sx, sy = self._point(frame, x, y)
        self.last_point = (sx, sy)
        # the dialect counts pixels, positive = down; a scroll wheel event counts pixels
        # too, with positive = up (the content moves down)
        self.adapter.post_scroll(frame.window.pid, sx, sy, -dy)

    def type(self, text: str) -> None:
        frame = self._frame()
        for chunk in unicode_chunks(text):
            if chunk == "\n":
                self._post_keys(frame.window.pid, key_sequence(["enter"]))
            else:
                self.adapter.post_text(frame.window.pid, chunk)
            self.sleep(0.01)

    def key(self, keys: list[str]) -> None:
        frame = self._frame()
        try:
            events = key_sequence(keys)
        except ValueError as exc:
            raise WindowUnavailable(str(exc)) from exc
        self._post_keys(frame.window.pid, events)

    def open_app(self, name: str) -> str:
        from nanomuse.computer.hands import open_application

        return open_application(name)

    # ------------------------------------------------------------------ posting
    def _post_mouse(self, pid: int, events: list[MouseEvent]) -> None:
        for ev in events:
            self.adapter.post_mouse(pid, ev)
            if ev.kind == "down":
                self.sleep(PRESS_S)
            elif ev.kind == "drag":
                self.sleep(0.05)

    def _post_keys(self, pid: int, events: list[KeyEvent]) -> None:
        for ev in events:
            self.adapter.post_key(pid, ev)
            self.sleep(0.01)


def png_size(data: bytes) -> tuple[int, int]:
    if len(data) >= 24 and data[:8] == b"\x89PNG\r\n\x1a\n":
        return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")
    return 0, 0


# ---------------------------------------------------------------------- the real adapter
def _platform() -> str:
    # a function, so mypy checks every branch on every platform
    return sys.platform


def available() -> tuple[bool, str]:
    """Whether window mode can run here: macOS with pyobjc's Quartz installed."""
    if _platform() != "darwin":
        return False, "window mode is macOS only; the hands use the shared screen here"
    try:
        import Quartz  # type: ignore[import-not-found]  # noqa: F401
    except ImportError:
        return False, "pyobjc is not installed: pip install 'nanomuse[hands]'"
    return True, ""


class QuartzAdapter:
    """The real thing, on macOS with pyobjc (``pyobjc-framework-Quartz`` and
    ``-ApplicationServices``). Every import is inside, so the module loads anywhere."""

    def __init__(self) -> None:
        ok, why = available()
        if not ok:
            raise WindowUnavailable(why)
        import Quartz  # type: ignore[import-not-found]

        self.q = Quartz
        self._bundle_ids: dict[int, str] = {}
        self._announced = False

    # -- windows
    def windows(self) -> list[WindowInfo]:
        q = self.q
        options = q.kCGWindowListOptionOnScreenOnly | q.kCGWindowListExcludeDesktopElements
        raw = q.CGWindowListCopyWindowInfo(options, q.kCGNullWindowID) or []
        out: list[WindowInfo] = []
        for info in raw:
            bounds = info.get("kCGWindowBounds") or {}
            pid = int(info.get("kCGWindowOwnerPID") or 0)
            out.append(
                WindowInfo(
                    id=int(info.get("kCGWindowNumber") or 0),
                    pid=pid,
                    owner=str(info.get("kCGWindowOwnerName") or ""),
                    title=str(info.get("kCGWindowName") or ""),
                    x=float(bounds.get("X") or 0),
                    y=float(bounds.get("Y") or 0),
                    width=float(bounds.get("Width") or 0),
                    height=float(bounds.get("Height") or 0),
                    layer=int(info.get("kCGWindowLayer") or 0),
                    alpha=float(
                        info.get("kCGWindowAlpha")
                        if info.get("kCGWindowAlpha") is not None
                        else 1.0
                    ),
                    on_screen=bool(info.get("kCGWindowIsOnscreen", True)),
                    bundle_id=self._bundle_id(pid),
                )
            )
        return out

    def _bundle_id(self, pid: int) -> str:
        if pid in self._bundle_ids:
            return self._bundle_ids[pid]
        bundle = ""
        try:
            from AppKit import NSRunningApplication  # type: ignore[import-not-found]

            app = NSRunningApplication.runningApplicationWithProcessIdentifier_(pid)
            bundle = str(app.bundleIdentifier() or "") if app is not None else ""
        except Exception:  # noqa: BLE001 — AppKit missing or the process gone
            bundle = ""
        self._bundle_ids[pid] = bundle
        return bundle

    def capture(self, window_id: int) -> bytes | None:
        q = self.q
        if not self._announced:
            # under the app the helper does this (OperatorWindowAdapter); here the runtime is
            # on its own and the capture is attributed to whatever started it
            logger.info(
                "window mode: the runtime captures windows itself with CGWindowListCreateImage "
                "(no nanoMuse Computer Use helper); Screen Recording must be on for this process"
            )
            self._announced = True
        image = q.CGWindowListCreateImage(
            q.CGRectNull,
            q.kCGWindowListOptionIncludingWindow,
            window_id,
            q.kCGWindowImageBoundsIgnoreFraming | q.kCGWindowImageBestResolution,
        )
        if image is None or not q.CGImageGetWidth(image):
            return None
        from Foundation import NSMutableData  # type: ignore[import-not-found]

        data = NSMutableData.data()
        dest = q.CGImageDestinationCreateWithData(data, "public.png", 1, None)
        if dest is None:
            return None
        q.CGImageDestinationAddImage(dest, image, None)
        if not q.CGImageDestinationFinalize(dest):
            return None
        return bytes(data)

    # -- events
    def post_mouse(self, pid: int, event: MouseEvent) -> None:
        q = self.q
        button = {"left": q.kCGMouseButtonLeft, "right": q.kCGMouseButtonRight}.get(
            event.button, q.kCGMouseButtonCenter
        )
        kinds = {
            ("down", "left"): q.kCGEventLeftMouseDown,
            ("up", "left"): q.kCGEventLeftMouseUp,
            ("drag", "left"): q.kCGEventLeftMouseDragged,
            ("down", "right"): q.kCGEventRightMouseDown,
            ("up", "right"): q.kCGEventRightMouseUp,
            ("drag", "right"): q.kCGEventRightMouseDragged,
            ("down", "middle"): q.kCGEventOtherMouseDown,
            ("up", "middle"): q.kCGEventOtherMouseUp,
            ("drag", "middle"): q.kCGEventOtherMouseDragged,
        }
        kind = q.kCGEventMouseMoved if event.kind == "move" else kinds[(event.kind, event.button)]
        ev = q.CGEventCreateMouseEvent(None, kind, (event.x, event.y), button)
        if event.kind in ("down", "up"):
            q.CGEventSetIntegerValueField(ev, q.kCGMouseEventClickState, event.clicks)
        q.CGEventPostToPid(pid, ev)

    def post_key(self, pid: int, event: KeyEvent) -> None:
        q = self.q
        ev = q.CGEventCreateKeyboardEvent(None, event.keycode, event.down)
        q.CGEventSetFlags(ev, event.flags)
        q.CGEventPostToPid(pid, ev)

    def post_text(self, pid: int, text: str) -> None:
        q = self.q
        for down in (True, False):
            ev = q.CGEventCreateKeyboardEvent(None, 0, down)
            q.CGEventKeyboardSetUnicodeString(ev, len(text.encode("utf-16-le")) // 2, text)
            q.CGEventPostToPid(pid, ev)

    def post_scroll(self, pid: int, x: float, y: float, dy: float, dx: float = 0.0) -> None:
        q = self.q
        ev = q.CGEventCreateScrollWheelEvent(None, q.kCGScrollEventUnitPixel, 2, int(dy), int(dx))
        q.CGEventSetLocation(ev, (x, y))
        q.CGEventPostToPid(pid, ev)

    def ax_press(self, pid: int, x: float, y: float) -> bool:
        try:
            import ApplicationServices as ax  # type: ignore[import-not-found]
        except ImportError:
            return False
        if not ax.AXIsProcessTrusted():
            return False
        system = ax.AXUIElementCreateSystemWide()
        err, element = ax.AXUIElementCopyElementAtPosition(system, x, y, None)
        if err != 0 or element is None:
            return False
        err, owner = ax.AXUIElementGetPid(element, None)
        if err != 0 or owner != pid:
            return False
        err, actions = ax.AXUIElementCopyActionNames(element, None)
        if err != 0 or not actions or "AXPress" not in list(actions):
            return False
        return bool(ax.AXUIElementPerformAction(element, "AXPress") == 0)

    def trusted(self) -> bool:
        try:
            import ApplicationServices as ax  # type: ignore[import-not-found]

            return bool(ax.AXIsProcessTrusted() and self.q.CGPreflightPostEventAccess())
        except Exception:  # noqa: BLE001
            return False


# ---------------------------------------------------------------------- through the helper
class OperatorWindowAdapter:
    """Window mode under nanoMuse Desktop: the windows and their pictures come from the
    app's helper through the operator (``/windows``, ``/window``), the events go out through
    ``events`` — a :class:`QuartzAdapter` by default, a fake in the tests.

    The operator's refusals come back in its words: a 403 (the helper's Screen Recording
    row is off) and a 404 (the window is gone) are :class:`WindowUnavailable`, retried on
    the next look; anything else (the helper did not start, the app's server is gone)
    is raised as is and read as the layer failing (:class:`WindowLayerBroken`)."""

    def __init__(self, client: OperatorClient, events: MacAdapter | None = None) -> None:
        self.client = client
        self.events: MacAdapter = events if events is not None else QuartzAdapter()

    # -- windows (the helper's)
    def windows(self) -> list[WindowInfo]:
        try:
            listed = self.client.windows()
        except OperatorError as exc:
            if exc.status == 403:
                raise WindowUnavailable(str(exc)) from exc
            raise
        out: list[WindowInfo] = []
        for raw in listed:
            bounds = raw.get("bounds") or [0, 0, 0, 0]
            if not isinstance(bounds, list) or len(bounds) != 4:
                bounds = [0, 0, 0, 0]
            try:
                out.append(
                    WindowInfo(
                        id=int(raw.get("id") or 0),
                        pid=int(raw.get("pid") or 0),
                        owner=str(raw.get("app") or ""),
                        title=str(raw.get("title") or ""),
                        x=float(bounds[0] or 0),
                        y=float(bounds[1] or 0),
                        width=float(bounds[2] or 0),
                        height=float(bounds[3] or 0),
                        layer=int(raw.get("layer") or 0),
                        on_screen=bool(raw.get("on_screen", True)),
                        bundle_id=str(raw.get("bundle_id") or ""),
                    )
                )
            except (TypeError, ValueError):
                continue
        return out

    def capture(self, window_id: int) -> bytes | None:
        try:
            shot = self.client.window(window_id)
        except OperatorError as exc:
            if exc.status in (403, 404):
                raise WindowUnavailable(str(exc)) from exc
            raise
        data = str(shot.get("base64") or "")
        return base64.b64decode(data) if data else None

    # -- events (this process's, through pyobjc)
    def post_mouse(self, pid: int, event: MouseEvent) -> None:
        self.events.post_mouse(pid, event)

    def post_key(self, pid: int, event: KeyEvent) -> None:
        self.events.post_key(pid, event)

    def post_text(self, pid: int, text: str) -> None:
        self.events.post_text(pid, text)

    def post_scroll(self, pid: int, x: float, y: float, dy: float, dx: float = 0.0) -> None:
        self.events.post_scroll(pid, x, y, dy, dx)

    def ax_press(self, pid: int, x: float, y: float) -> bool:
        return self.events.ax_press(pid, x, y)

    def trusted(self) -> bool:
        return self.events.trusted()


__all__ = [
    "KEY_ALIASES",
    "MODIFIERS",
    "UNICODE_CHUNK",
    "VK",
    "KeyEvent",
    "MacAdapter",
    "MacWindowHands",
    "MouseEvent",
    "OperatorWindowAdapter",
    "QuartzAdapter",
    "WindowFrame",
    "WindowInfo",
    "WindowUnavailable",
    "available",
    "choose_window",
    "key_sequence",
    "mouse_sequence",
    "normalise_key",
    "png_size",
    "unicode_chunks",
]

"""Window mode on macOS, run on Linux against a fake adapter: choosing a window, mapping the
model's coordinates to the screen, the event sequences of a click, a drag, a scroll, typed
text and key combinations, the link's fall-back to the screen, the per-app permission and
the pointer in the hands' events — and, under the desktop app, the windows and their
pictures coming through the app's helper (the operator's ``/windows`` and ``/window``)."""

from __future__ import annotations

import base64
import struct
import sys
import zlib
from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any

import pytest

from nanomuse.computer import mac_window as mw
from nanomuse.computer import operator as op
from nanomuse.computer.link import ComputerLink
from nanomuse.config import GUISettings, HandsSettings, Settings
from nanomuse.phone.link import DeviceError
from nanomuse.sentinel import AuditLog, Sentinel
from nanomuse.tools.computer import ComputerAct, ComputerScreen
from nanomuse.ui import ApprovalDecision, ApprovalRequest
from tests.test_computer import SCREEN_RAW, FakeHands
from tests.test_computer_operator import TOKEN, FakeOperator
from tests.test_phone import AutoApproveUI, png


@pytest.fixture()
def fake_screen(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """The whole-screen capture, as tests/test_computer.py fakes it: answers from this
    list (the last entry repeats)."""
    screens = [dict(SCREEN_RAW)]

    def capture(max_width: int = 1600) -> dict[str, Any]:
        return dict(screens[0] if len(screens) == 1 else screens.pop(0))

    monkeypatch.setattr("nanomuse.computer.link.capture", capture)
    monkeypatch.setattr("nanomuse.computer.link.active_window", lambda: ("firefox", "Firefox"))
    monkeypatch.setattr("nanomuse.computer.link.screen_size", lambda: (1920, 1080))
    return screens


def png_bytes(width: int, height: int) -> bytes:
    return base64.b64decode(png(width, height))


SAFARI = mw.WindowInfo(
    id=41, pid=500, owner="Safari", title="Apple", x=100, y=50, width=800, height=600,
    bundle_id="com.apple.Safari",
)  # fmt: skip
SAFARI_SMALL = mw.WindowInfo(
    id=42, pid=500, owner="Safari", title="", x=0, y=0, width=200, height=100,
    bundle_id="com.apple.Safari",
)  # fmt: skip
NOTES = mw.WindowInfo(
    id=43, pid=600, owner="Notes", title="Shopping", x=0, y=0, width=500, height=400,
    bundle_id="com.apple.Notes",
)  # fmt: skip
MENUBAR = mw.WindowInfo(id=1, pid=10, owner="Window Server", title="Menubar", x=0, y=0, width=1440, height=24, layer=24)  # fmt: skip


class FakeMac:
    """A window server that remembers every event it was asked to post."""

    def __init__(self, windows: list[mw.WindowInfo] | None = None, scale: int = 2) -> None:
        self.window_list = list(
            windows if windows is not None else [MENUBAR, SAFARI_SMALL, SAFARI, NOTES]
        )
        self.scale = scale  # Retina: the capture is twice the points
        self.events: list[tuple[Any, ...]] = []
        self.ax_hits: set[tuple[float, float]] = set()
        self.is_trusted = True
        self.capture_fails = False

    def windows(self) -> list[mw.WindowInfo]:
        return list(self.window_list)

    def capture(self, window_id: int) -> bytes | None:
        if self.capture_fails:
            return None
        w = next(w for w in self.window_list if w.id == window_id)
        return png_bytes(int(w.width) * self.scale, int(w.height) * self.scale)

    def post_mouse(self, pid: int, event: mw.MouseEvent) -> None:
        self.events.append(("mouse", pid, event.kind, event.x, event.y, event.button, event.clicks))

    def post_key(self, pid: int, event: mw.KeyEvent) -> None:
        self.events.append(("key", pid, event.keycode, event.down, event.flags))

    def post_text(self, pid: int, text: str) -> None:
        self.events.append(("text", pid, text))

    def post_scroll(self, pid: int, x: float, y: float, dy: float, dx: float = 0.0) -> None:
        self.events.append(("scroll", pid, x, y, dy, dx))

    def ax_press(self, pid: int, x: float, y: float) -> bool:
        if (x, y) in self.ax_hits:
            self.events.append(("ax", pid, x, y))
            return True
        return False

    def trusted(self) -> bool:
        return self.is_trusted


# ------------------------------------------------------------------ pure logic
def test_the_module_imports_without_pyobjc_and_says_so() -> None:
    # On Linux and Windows the reason is the platform; on a Mac without pyobjc it is the package.
    ok, why = mw.available()
    assert ok is False and ("macOS" in why or "pyobjc" in why)
    with pytest.raises(mw.WindowUnavailable):
        mw.QuartzAdapter()


def test_choosing_a_window() -> None:
    windows = [MENUBAR, SAFARI_SMALL, SAFARI, NOTES]
    # by name, by bundle id, by a part of it; the biggest titled ordinary window wins
    assert mw.choose_window(windows, "Safari") is SAFARI
    assert mw.choose_window(windows, "com.apple.safari") is SAFARI
    assert mw.choose_window(windows, "notes") is NOTES
    assert mw.choose_window(windows, "Notes", title="shopping") is NOTES
    # a menu bar layer is never a target; an unknown app has no window
    assert mw.choose_window(windows, "Window Server") is None
    assert mw.choose_window(windows, "Xcode") is None
    assert mw.choose_window(windows, "") is None


def test_coordinates_map_from_the_window_picture_to_the_screen() -> None:
    frame = mw.WindowFrame(SAFARI, image_width=1600, image_height=1200)  # a Retina capture
    assert frame.to_screen(0, 0) == (100, 50)
    assert frame.to_screen(1600, 1200) == (900, 650)
    assert frame.to_screen(800, 600) == (500, 350)
    # a scaled picture maps the same way
    small = mw.WindowFrame(SAFARI, image_width=400, image_height=300)
    assert small.to_screen(200, 150) == (500, 350)
    assert small.contains(400, 300) and not small.contains(401, 0)
    # points outside are clamped to the window, never posted elsewhere
    assert frame.to_screen(-50, 5000) == (100, 650)


def test_event_sequences() -> None:
    assert [e.kind for e in mw.mouse_sequence("click", 1, 2)] == ["move", "down", "up"]
    double = mw.mouse_sequence("double_click", 1, 2)
    assert [(e.kind, e.clicks) for e in double] == [
        ("move", 1),
        ("down", 1),
        ("up", 1),
        ("down", 2),
        ("up", 2),
    ]
    assert mw.mouse_sequence("right_click", 1, 2)[1].button == "right"
    drag = mw.mouse_sequence("drag", 0, 0, 100, 50)
    assert [(e.kind, e.x, e.y) for e in drag] == [
        ("move", 0, 0),
        ("down", 0, 0),
        ("drag", 50, 25),
        ("drag", 100, 50),
        ("up", 100, 50),
    ]
    # a key combination: modifiers down, the key with their flags, modifiers up in reverse
    seq = mw.key_sequence(["cmd", "shift", "s"])
    assert [(e.keycode, e.down) for e in seq] == [
        (55, True),
        (56, True),
        (1, True),
        (1, False),
        (56, False),
        (55, False),
    ]
    assert seq[2].flags == mw.FLAG_BITS["command"] | mw.FLAG_BITS["shift"]
    assert seq[-1].flags == 0
    assert [(e.keycode, e.down) for e in mw.key_sequence(["Return"])] == [(36, True), (36, False)]
    with pytest.raises(ValueError):
        mw.key_sequence(["hyper"])
    # unicode text goes in pieces a keyboard event can carry; newlines become Enter
    chunks = mw.unicode_chunks("你好，世界" * 5 + "\nbye")
    assert "".join(c for c in chunks if c != "\n") == "你好，世界" * 5 + "bye"
    assert all(len(c.encode("utf-16-le")) // 2 <= mw.UNICODE_CHUNK for c in chunks)
    assert "\n" in chunks
    assert mw.unicode_chunks("a😀b") == ["a😀b"]


def test_ax_press_only_uses_elements_owned_by_the_selected_process(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pressed: list[int] = []
    ax = SimpleNamespace(
        AXIsProcessTrusted=lambda: True,
        AXUIElementCreateSystemWide=lambda: None,
        AXUIElementCopyElementAtPosition=lambda *_: (0, 123),
        AXUIElementGetPid=lambda *_: (0, NOTES.pid),
        AXUIElementCopyActionNames=lambda *_: (0, ["AXPress"]),
        AXUIElementPerformAction=lambda element, _: pressed.append(element) or 0,
    )
    monkeypatch.setitem(sys.modules, "ApplicationServices", ax)
    adapter = object.__new__(mw.QuartzAdapter)
    assert not adapter.ax_press(SAFARI.pid, 15, 25)
    assert not pressed
    assert adapter.ax_press(NOTES.pid, 15, 25)
    assert pressed == [123]


async def test_window_capture_grant_does_not_authorize_posting_input(
    settings: Settings, fake_screen
) -> None:
    pytest.importorskip("PIL")
    mac = FakeMac()
    mac.is_trusted = False
    link = make_link(settings, mac)
    link.set_target("Safari")
    assert (await link.screen()).app == "com.apple.Safari"
    with pytest.raises(DeviceError, match="permission to send input"):
        await link.act({"action": "type", "text": "hello"})
    with pytest.raises(DeviceError, match="No current window"):
        await link.act({"action": "click", "x": 10, "y": 10})
    assert not mac.events
    mac.is_trusted = True
    await link.screen()
    await link.act({"action": "type", "text": "hello"})
    assert mac.events == [("text", SAFARI.pid, "hello")]


def test_the_window_hands_post_to_the_process() -> None:
    mac = FakeMac()
    hands = mw.MacWindowHands(mac, sleep=lambda _s: None)
    with pytest.raises(mw.WindowUnavailable):
        hands.click(1, 1)  # nothing looked at yet
    png_data, frame = hands.look("Safari")
    assert frame.window is SAFARI and (frame.image_width, frame.image_height) == (1600, 1200)
    assert mw.png_size(png_data) == (1600, 1200)
    # a click at the picture's centre lands at the window's centre on the screen, in the
    # window's process; the system cursor is not involved
    hands.click(800, 600, button="left")
    assert mac.events == [
        ("mouse", 500, "move", 500, 350, "left", 1),
        ("mouse", 500, "down", 500, 350, "left", 1),
        ("mouse", 500, "up", 500, 350, "left", 1),
    ]
    assert hands.last_point == (500, 350)
    mac.events.clear()
    with pytest.raises(mw.WindowUnavailable):
        hands.click(1601, 0)  # outside the picture
    # a double click, a drag, a scroll (pixels down → wheel up), text and keys
    hands.click(0, 0, clicks=2)
    assert [e[2:4] for e in mac.events] == [
        ("move", 100),
        ("down", 100),
        ("up", 100),
        ("down", 100),
        ("up", 100),
    ]
    assert mac.events[-1][6] == 2
    mac.events.clear()
    hands.drag(0, 0, 1600, 1200)
    assert mac.events[0][2:5] == ("move", 100, 50) and mac.events[-1][2:5] == ("up", 900, 650)
    mac.events.clear()
    hands.scroll(800, 600, 300)
    assert mac.events == [("scroll", 500, 500, 350, -300, 0.0)]
    mac.events.clear()
    hands.type("hi 你\nok")
    assert mac.events[0] == ("text", 500, "hi 你")
    assert ("key", 500, 36, True, 0) in mac.events and mac.events[-1] == ("text", 500, "ok")
    mac.events.clear()
    hands.key(["command", "v"])
    assert [e[2:4] for e in mac.events] == [(55, True), (9, True), (9, False), (55, False)]
    with pytest.raises(mw.WindowUnavailable):
        hands.key(["hyper"])
    # the accessibility shortcut, when the element under the point can be pressed
    mac.events.clear()
    mac.ax_hits.add((500, 350))
    hands.click(800, 600)
    assert mac.events == [("ax", 500, 500, 350)] and "accessibility" in hands.notes[-1]
    # The window closes between capture and input, while a second window from the same
    # process is still open. Input must not silently address the other window.
    mac.events.clear()
    mac.window_list.remove(SAFARI)
    with pytest.raises(mw.WindowUnavailable, match="changed or closed"):
        hands.key(["return"])
    assert not mac.events
    assert hands.look("Safari")[1].window is SAFARI_SMALL
    mac.window_list.remove(SAFARI_SMALL)
    with pytest.raises(mw.WindowUnavailable, match="no window"):
        hands.look("Safari")
    mac.capture_fails = True
    with pytest.raises(mw.WindowUnavailable, match="Screen Recording"):
        hands.look("Notes")


# ------------------------------------------------------------------ the link
def make_link(
    settings: Settings, mac: FakeMac, mode: str = "auto", events: list[dict[str, Any]] | None = None
) -> ComputerLink:
    return ComputerLink(
        HandsSettings(enabled=True, settle_s=0.0, mode=mode, max_image_width=400),  # type: ignore[arg-type]
        shots_dir=settings.agent.workspace / "screenshots",
        on_event=events.append if events is not None else None,
        backend=FakeHands(),
        window_adapter=mac,
    )


async def test_the_link_works_in_a_window_and_falls_back_to_the_screen(
    settings: Settings, fake_screen, monkeypatch: pytest.MonkeyPatch
) -> None:
    pytest.importorskip("PIL")
    mac = FakeMac()
    events: list[dict[str, Any]] = []
    link = make_link(settings, mac, events=events)
    # no target yet: the whole screen, as on any platform
    assert not link.in_window_mode()
    screen = await link.screen()
    assert screen.app == "firefox" and (screen.width, screen.height) == (1920, 1080)
    # a target: the window's picture, scaled to max_image_width, coordinates of that picture
    link.set_target("Safari")
    assert link.in_window_mode()
    screen = await link.screen()
    assert screen.app == "com.apple.Safari" and screen.app_name == "Safari"
    assert (screen.width, screen.height) == (400, 300) and "window of Safari" in screen.note
    assert link.window_frame is not None and link.window_frame.image_width == 400
    assert link.status()["window"]["active"] is True
    assert link.status()["window"]["frame"]["bundle_id"] == "com.apple.Safari"
    # an action: posted to Safari's process at the mapped point; the stage hears the point
    # in screen pixels and which window it was
    await link.act({"action": "click", "x": 200, "y": 150, "label": "Go"})
    assert ("mouse", 500, "down", 500, 350, "left", 1) in mac.events
    hands: FakeHands = link._backend  # type: ignore[assignment]
    assert hands.calls == []  # the system mouse was never touched
    act = [e for e in events if e["event"] == "act"][-1]
    assert (act["x"], act["y"]) == (500, 350) and act["mode"] == "window"
    assert act["window"]["app"] == "Safari" and act["app"] == "Safari" and act["title"] == "Apple"
    assert act["fx"] == round(500 / 1920, 4)
    # the window goes away: the next look shows the whole screen with a note, and the
    # next action cannot go to the system mouse until the target is cleared
    mac.window_list.remove(SAFARI)
    mac.window_list.remove(SAFARI_SMALL)
    screen = await link.screen()
    assert screen.app == "firefox" and "no window" in screen.note and "whole screen" in screen.note
    with pytest.raises(DeviceError, match="No current window"):
        await link.act({"action": "click", "x": 10, "y": 10, "label": "File"})
    assert not hands.calls
    link.set_target("")
    await link.screen()
    await link.act({"action": "click", "x": 10, "y": 10, "label": "File"})
    assert hands.calls[-1][:3] == ("click", 10.0, 10.0)
    assert [e for e in events if e["event"] == "act"][-1]["mode"] == "screen"
    # mode "screen" ignores the target; "" clears it
    link.settings.mode = "screen"
    assert not link.in_window_mode()
    link.settings.mode = "auto"
    link.set_target("")
    assert not link.in_window_mode()


async def test_auto_mode_keeps_the_screen_read_only_when_the_window_layer_breaks(
    settings: Settings, fake_screen
) -> None:
    pytest.importorskip("PIL")

    class BrokenMac(FakeMac):
        def __init__(self) -> None:
            super().__init__()
            self.broken = False

        def windows(self) -> list[mw.WindowInfo]:
            if self.broken:
                raise RuntimeError("objc: CGWindowListCopyWindowInfo is gone")
            return super().windows()

    mac = BrokenMac()
    link = make_link(settings, mac)
    link.set_target("Safari")
    assert (await link.screen()).app == "com.apple.Safari"
    # pyobjc itself fails (not "the window went away"): one note, then the screen for the
    # rest of this target, with input still scoped to the selected window
    mac.broken = True
    screen = await link.screen()
    assert screen.app == "firefox" and "window mode failed" in screen.note
    assert "whole screen" in screen.note
    assert not link.in_window_mode()
    assert "window mode failed" in link.status()["window"]["reason"]
    screen = await link.screen()
    assert screen.app == "firefox" and not screen.note
    with pytest.raises(DeviceError, match="No current window"):
        await link.act({"action": "click", "x": 10, "y": 10, "label": "File"})
    hands: FakeHands = link._backend  # type: ignore[assignment]
    assert not hands.calls
    # An explicit reselection retries the window, including the same application.
    mac.broken = False
    link.set_target("Safari")
    assert (await link.screen()).app == "com.apple.Safari"
    link.set_target("Notes")
    assert link.in_window_mode()
    assert (await link.screen()).app == "com.apple.Notes"
    # an explicit `window` mode is the person's choice: it keeps trying every look
    mac.broken = True
    link.settings.mode = "window"
    link.set_target("Safari")
    screen = await link.screen()
    assert screen.app == "firefox" and "window mode failed" in screen.note
    assert link.in_window_mode()


async def test_open_app_sets_the_target_and_computer_target_reports(
    settings: Settings, fake_screen
) -> None:
    pytest.importorskip("PIL")
    mac = FakeMac()
    link = make_link(settings, mac)
    act = ComputerAct(link=link, gui=GUISettings())
    # computer_target: the window, its size, who keeps the mouse
    r = await act.execute(action="computer_target", app="Notes")
    assert r.ok and "Working in the window of Notes, Shopping" in r.output
    assert "400×320" in r.output and r.images
    assert link.target_app == "Notes" and link.window_frame is not None
    assert act.assess({"action": "computer_target", "app": "Notes"}).target == "Notes"
    # `app` on an action switches the window first; an unknown app says so and shows the screen
    r = await act.execute(action="click", x=10, y=10, label="Apple", app="Safari")
    assert r.ok and ("mouse", 500, "up") == mac.events[-1][:3]  # Safari's process
    r = await act.execute(action="computer_target", app="Xcode")
    assert r.ok and "could not be worked in as a window" in r.output and "no window" in r.output
    # back to the whole screen
    r = await act.execute(action="computer_target", app="")
    assert r.ok and "whole screen" in r.output and not link.in_window_mode()
    # open_app on macOS makes the opened application the target
    await link.act({"action": "open_app", "app": "Notes"})
    assert link.target_app == "Notes"
    # computer_screen with `app` looks at that window
    look = await ComputerScreen(link=link).execute(app="Safari")
    assert look.ok and "window of Safari" in look.output
    # without window mode (Linux, no adapter) computer_target keeps the hands on the screen
    plain = ComputerLink(HandsSettings(enabled=True, settle_s=0.0), backend=FakeHands())
    r = await ComputerAct(link=plain, gui=GUISettings()).execute(
        action="computer_target", app="Notes"
    )
    assert r.ok and "Window mode is not available here" in r.output
    assert "macOS" in r.output or "pyobjc" in r.output
    assert not plain.in_window_mode()


# ------------------------------------------------------------------ through the helper
HELPER_WINDOWS: list[dict[str, Any]] = [
    {"id": 41, "pid": 500, "app": "Safari", "bundle_id": "com.apple.Safari", "title": "Apple",
     "bounds": [100, 50, 800, 600], "layer": 0, "on_screen": True},
    {"id": 43, "pid": 600, "app": "Notes", "bundle_id": "com.apple.Notes", "title": "Shopping",
     "bounds": [0, 0, 500, 400], "layer": 0, "on_screen": True},
    {"id": 1, "pid": 10, "app": "Window Server", "bundle_id": "", "title": "Menubar",
     "bounds": [0, 0, 1440, 24], "layer": 24, "on_screen": True},
]  # fmt: skip
HELPER_SCREEN_TEXT = (
    "macOS: switch on nanoMuse Computer Use under System Settings → Privacy & Security → "
    "Screen Recording. The helper restarts by itself; the app does not need to."
)


@pytest.fixture()
def mac_operator(monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeOperator]:
    """The desktop app's operator on a Mac with its helper bundle: /info says so, and the
    helper's windows are served through /windows and /window."""
    fake = FakeOperator(
        width=1440,
        height=900,
        helper={"present": True, "running": True, "pid": 4242, "capture": "ScreenCaptureKit"},
        windows=HELPER_WINDOWS,
    )
    monkeypatch.setenv(op.URL_ENV, fake.url)
    monkeypatch.setenv(op.TOKEN_ENV, TOKEN)
    monkeypatch.setattr(op, "_platform", lambda: "darwin")
    monkeypatch.setattr("nanomuse.computer.link.active_window", lambda: ("", ""))
    yield fake
    fake.close()


def test_the_operator_window_adapter_lists_and_captures_through_the_helper(
    mac_operator: FakeOperator,
) -> None:
    """Under the app the runtime never captures a window itself: the list and the picture
    are the helper's (ScreenCaptureKit on macOS 14+), the events still go out from here."""
    events = FakeMac()
    adapter = mw.OperatorWindowAdapter(op.OperatorClient(mac_operator.url, TOKEN), events)
    hands = mw.MacWindowHands(adapter, sleep=lambda _s: None)
    windows = adapter.windows()
    assert [w.id for w in windows] == [41, 43, 1]
    assert windows[0].owner == "Safari" and windows[0].bundle_id == "com.apple.Safari"
    assert (windows[0].x, windows[0].y, windows[0].width, windows[0].height) == (100, 50, 800, 600)
    assert windows[2].layer == 24  # the menu bar: listed, never chosen
    png_data, frame = hands.look("Safari")
    assert frame.window.id == 41 and (frame.image_width, frame.image_height) == (1600, 1200)
    assert mw.png_size(png_data) == (1600, 1200)
    assert mac_operator.window_shots[-1] == {"id": 41, "max_pixels": 2_000_000, "format": "png"}
    assert mac_operator.shots == []  # no whole-screen picture was taken for this
    # a click maps through the frame and is posted to Safari's process by this runtime
    hands.click(800, 600)
    assert events.events == [
        ("mouse", 500, "move", 500, 350, "left", 1),
        ("mouse", 500, "down", 500, 350, "left", 1),
        ("mouse", 500, "up", 500, 350, "left", 1),
    ]
    # the helper's Screen Recording row is off: the operator's 403, in its words, retried
    # on the next look (WindowUnavailable, not a broken layer)
    mac_operator.refuse_window = (403, f"window 41 could not be captured: {HELPER_SCREEN_TEXT}")
    with pytest.raises(mw.WindowUnavailable, match="nanoMuse Computer Use") as exc:
        hands.look("Safari")
    assert not isinstance(exc.value, mw.WindowLayerBroken)
    mac_operator.refuse_window = None
    # the window went away between the list and the capture: unavailable, not broken
    mac_operator.refuse_window = (404, "window 41 could not be captured: no window with id 41")
    with pytest.raises(mw.WindowUnavailable, match="no window with id 41") as exc:
        hands.look("Safari")
    assert not isinstance(exc.value, mw.WindowLayerBroken)
    # the helper itself is gone (503): the layer failed — `auto` mode parks on the screen
    mac_operator.refuse_window = (
        503,
        "window 41 could not be captured: nanoMuse Computer Use did not start (no port after 10 s)",
    )
    with pytest.raises(mw.WindowLayerBroken, match="did not start"):
        hands.look("Safari")


async def test_the_link_works_in_a_window_through_the_helper_under_the_app(
    settings: Settings, mac_operator: FakeOperator, monkeypatch: pytest.MonkeyPatch
) -> None:
    pytest.importorskip("PIL")
    events = FakeMac()
    # pyobjc is not here; the events adapter the link would make is the fake, and window
    # mode counts as available (a Mac with pyobjc)
    monkeypatch.setattr(mw, "QuartzAdapter", lambda: events)
    monkeypatch.setattr(mw, "available", lambda: (True, ""))
    link = ComputerLink(
        HandsSettings(enabled=True, settle_s=0.0, max_image_width=400),  # type: ignore[arg-type]
        shots_dir=settings.agent.workspace / "screenshots",
    )
    assert link.backend_available() and link._backend is not None
    assert link._backend.name == "desktop"
    # the whole screen first: the operator's picture (1440×900 points, under max_image_width)
    screen = await link.screen()
    assert (screen.width, screen.height) == (392, 252)
    assert (link.device.width, link.device.height) == (1440, 900)
    assert len(mac_operator.shots) == 1
    # then Safari's window: listed and captured through the helper, scaled for the model
    link.set_target("Safari")
    assert link.in_window_mode()
    screen = await link.screen()
    assert screen.app == "com.apple.Safari" and screen.app_name == "Safari"
    assert (screen.width, screen.height) == (400, 300) and "window of Safari" in screen.note
    assert mac_operator.window_shots[-1]["id"] == 41
    assert len(mac_operator.shots) == 1  # no second whole-screen picture
    assert isinstance(link._window.adapter, mw.OperatorWindowAdapter)  # type: ignore[union-attr]
    # the click: posted to Safari's process by the runtime, not sent to the operator's /execute
    await link.act({"action": "click", "x": 200, "y": 150, "label": "Go"})
    assert ("mouse", 500, "down", 500, 350, "left", 1) in events.events
    assert mac_operator.executed == []
    # the helper's grant goes away: the window look says so and the screen is tried instead,
    # which the operator refuses with the same words — the tool's error names the helper
    mac_operator.refuse_window = (403, f"window 41 could not be captured: {HELPER_SCREEN_TEXT}")
    mac_operator.refuse_shot = (403, f"no screenshot: {HELPER_SCREEN_TEXT}")
    with pytest.raises(DeviceError, match="nanoMuse Computer Use"):
        await link.screen()
    assert link.in_window_mode()  # not parked: a grant is retried, a broken layer is not


def test_without_the_helper_the_runtime_keeps_its_own_window_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A Mac under an app without the helper bundle (or no app at all): the Quartz adapter
    is what the link makes — the CGWindowListCreateImage path, announced in the log."""
    made: list[str] = []

    class Quartz(FakeMac):
        def __init__(self) -> None:
            super().__init__()
            made.append("quartz")

    monkeypatch.setattr(mw, "QuartzAdapter", Quartz)
    monkeypatch.setattr(op, "_platform", lambda: "darwin")
    # an app whose /info has a helper object without a bundle (`present: false`)
    fake = FakeOperator(helper={"present": False, "running": False, "reason": "no helper bundle"})
    try:
        monkeypatch.setenv(op.URL_ENV, fake.url)
        monkeypatch.setenv(op.TOKEN_ENV, TOKEN)
        link = ComputerLink(HandsSettings(enabled=True, settle_s=0.0))
        hands = link._window_hands()
        assert made == ["quartz"] and isinstance(hands.adapter, Quartz)
        # and no app at all (the CLI): the same path
        monkeypatch.delenv(op.URL_ENV)
        plain = ComputerLink(HandsSettings(enabled=True, settle_s=0.0), backend=FakeHands())
        assert isinstance(plain._window_hands().adapter, Quartz)
        assert made == ["quartz", "quartz"]
    finally:
        fake.close()


# ------------------------------------------------------------------ per-app permission
class AskingUI(AutoApproveUI):
    def __init__(self, answers: list[ApprovalDecision]) -> None:
        super().__init__()
        self.answers = answers
        self.asked: list[ApprovalRequest] = []

    async def ask_approval(self, request: ApprovalRequest) -> ApprovalDecision:
        self.asked.append(request)
        return self.answers.pop(0) if self.answers else ApprovalDecision(approved=True)


async def test_the_first_action_in_an_application_asks(settings: Settings, fake_screen) -> None:
    ui = AskingUI(
        [
            ApprovalDecision(approved=True, scope="conversation"),
            ApprovalDecision(approved=False, reason="not that one"),
            ApprovalDecision(approved=True, scope="always"),
        ]
    )
    sentinel = Sentinel(settings.sentinel, AuditLog(settings.data_dir / "audit.jsonl"), ui)
    link = ComputerLink(HandsSettings(enabled=True, settle_s=0.0), backend=FakeHands())

    async def gate(app_id: str, label: str) -> bool:
        return await sentinel.allow_app(app_id, label, "Nova")

    act = ComputerAct(link=link, gui=GUISettings(), app_gate=gate)
    token = sentinel.begin_task("click things", conversation="c1")
    try:
        await link.screen()  # Firefox is in front
        r = await act.execute(action="click", x=10, y=10, label="File")
        assert r.ok
        assert ui.asked[0].summary == "Let Nova use Firefox?"
        assert ui.asked[0].grant_key == "computer_app:firefox"
        assert ui.asked[0].grant_options == ["once", "conversation", "always"]
        # covered for the conversation: no second ask
        r = await act.execute(action="type", text="hello")
        assert r.ok and len(ui.asked) == 1
        # another application: asked again; a refusal ends the action with a plain reason
        fake_screen[0]["app"], fake_screen[0]["app_name"] = "org.gimp", "GIMP"
        await link.screen()
        r = await act.execute(action="click", x=10, y=10, label="Filters")
        assert not r.ok and "did not allow the hands in GIMP" in (r.error or "")
        assert ui.asked[1].summary == "Let Nova use GIMP?"
        # "always" lands in the grant store under computer_app:<id>, where Permissions lists it
        r = await act.execute(action="click", x=10, y=10, label="Filters")
        assert r.ok and len(ui.asked) == 3
        keys = {g.key for g in sentinel.active_grants()}
        assert "computer_app:org.gimp" in keys and "computer_app:firefox" in keys
        assert sentinel.revoke("computer_app:org.gimp")
        # open_app asks for the application being opened; wait asks nobody
        r = await act.execute(action="open_app", app="Calculator")
        assert r.ok and ui.asked[-1].summary == "Let Nova use Calculator?"
        n = len(ui.asked)
        r = await act.execute(action="wait", seconds=0.2)
        assert r.ok and len(ui.asked) == n
    finally:
        sentinel.end_task(token)
    # auto mode asks nobody
    settings.sentinel.mode = "auto"
    assert await sentinel.allow_app("com.apple.Safari", "Safari") is True
    assert len(ui.asked) == n


def _crc_png(width: int, height: int) -> bytes:  # a second PNG writer keeps the helper honest
    def chunk(kind: bytes, body: bytes) -> bytes:
        return (
            struct.pack(">I", len(body))
            + kind
            + body
            + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF)
        )

    raw = zlib.compress(b"".join(b"\x00" + b"\x80" * width for _ in range(height)))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0))
        + chunk(b"IDAT", raw)
        + chunk(b"IEND", b"")
    )


def test_png_size() -> None:
    assert mw.png_size(_crc_png(7, 3)) == (7, 3)
    assert mw.png_size(b"nope") == (0, 0)

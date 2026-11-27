"""This computer's screen and hands: the computer_use dialect, the link over a fake backend,
the tools' risk, the operator loop with the computer dialect, and the server side (the
Hands card, the switch, Stop)."""

from __future__ import annotations

import json
import platform
import time
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from nanomuse.computer import hands as hands_mod
from nanomuse.computer.link import ComputerLink
from nanomuse.config import GUISettings, HandsSettings, Settings
from nanomuse.llm import MockLLM
from nanomuse.phone.link import STOP_MARKER, DeviceError, DeviceStopped, PhoneLink
from nanomuse.phone.operator import COMPUTER, PhoneOperator, parse_step, to_computer_action
from nanomuse.phone.screen import Screen
from nanomuse.schema import Function, LLMResponse, RiskLevel, ToolCall
from nanomuse.sentinel import AuditLog, Sentinel
from nanomuse.server import create_app
from nanomuse.server.service import MuseService
from nanomuse.tools.computer import ComputerAct, ComputerScreen, ComputerTask
from nanomuse.tools.phone import PhoneAct
from tests.test_phone import PAY_SCREEN, AutoApproveUI, FakePhone, png

SCREEN_RAW = {
    "app": "firefox",
    "app_name": "Firefox",
    "width": 1920,
    "height": 1080,
    "keyboard": False,
    "screenshot": png(96, 54),
}


class FakeHands:
    """A backend that remembers what it was asked to do."""

    name = "fake"

    def __init__(self) -> None:
        self.calls: list[tuple[Any, ...]] = []

    def click(self, x: float, y: float, button: str = "left", clicks: int = 1) -> None:
        self.calls.append(("click", x, y, button, clicks))

    def move(self, x: float, y: float) -> None:
        self.calls.append(("move", x, y))

    def drag(self, x: float, y: float, x2: float, y2: float) -> None:
        self.calls.append(("drag", x, y, x2, y2))

    def scroll(self, x: float, y: float, dy: float) -> None:
        self.calls.append(("scroll", x, y, dy))

    def type(self, text: str) -> None:
        self.calls.append(("type", text))

    def key(self, keys: list[str]) -> None:
        self.calls.append(("key", tuple(keys)))

    def open_app(self, name: str) -> str:
        self.calls.append(("open", name))
        return name


@pytest.fixture()
def fake_screen(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """`capture` answers from this list (the last entry repeats)."""
    screens = [dict(SCREEN_RAW)]

    def capture(max_width: int = 1600) -> dict[str, Any]:
        return dict(screens[0] if len(screens) == 1 else screens.pop(0))

    monkeypatch.setattr("nanomuse.computer.link.mac_frontmost_pid", lambda: 501)
    monkeypatch.setattr("nanomuse.computer.link.capture", capture)
    monkeypatch.setattr("nanomuse.computer.link.active_window", lambda: ("firefox", "Firefox"))
    monkeypatch.setattr("nanomuse.computer.link.screen_size", lambda: (1920, 1080))
    return screens


def make_link(settings: Settings, events: list[dict[str, Any]] | None = None) -> ComputerLink:
    return ComputerLink(
        HandsSettings(enabled=True, settle_s=0.0),
        shots_dir=settings.agent.workspace / "screenshots",
        on_event=events.append if events is not None else None,
        backend=FakeHands(),
    )


def step(action: str, label: str = "do it", **arguments: Any) -> LLMResponse:
    call = {"name": "computer_use", "arguments": {"action": action, **arguments}}
    return LLMResponse(
        content=f"Thought: I see it.\nAction: {label}\n<tool_call>\n{json.dumps(call)}\n</tool_call>"
    )


# ----------------------------------------------------------------------------- the dialect
def test_computer_use_steps_become_hand_actions() -> None:
    screen = Screen(app="x", width=1000, height=500)
    s = parse_step(
        step("left_click", "Click Save", coordinate=[499, 250]).content, tool="computer_use"
    )
    assert s is not None and s.name == "computer_use" and s.kind == "left_click"
    assert to_computer_action(s, screen) == {
        "action": "click",
        "x": 499.5,
        "y": 125.1,
        "label": "Click Save",
    }
    s = parse_step(
        step("left_click_drag", "Drag", coordinate=[0, 0], coordinate2=[999, 999]).content,
        "computer_use",
    )
    assert to_computer_action(s, screen) == {
        "action": "drag",
        "x": 0.0,
        "y": 0.0,
        "x2": 1000.0,
        "y2": 500.0,
        "label": "Drag",
    }
    s = parse_step(
        step("scroll", "Scroll down", coordinate=[500, 500], pixels=-200).content, "computer_use"
    )
    assert to_computer_action(s, screen)["dy"] == -200.0
    s = parse_step(step("key", "Save", keys="ctrl+s").content, "computer_use")
    assert to_computer_action(s, screen) == {
        "action": "key",
        "keys": ["ctrl", "s"],
        "label": "Save",
    }
    s = parse_step(step("open", "Open Firefox", text="Firefox").content, "computer_use")
    assert to_computer_action(s, screen) == {
        "action": "open_app",
        "app": "Firefox",
        "label": "Open Firefox",
    }
    s = parse_step(step("wait", "Wait", time=3).content, "computer_use")
    assert to_computer_action(s, screen) == {"action": "wait", "seconds": 3.0}
    s = parse_step(step("terminate", "Done", status="success").content, "computer_use")
    assert to_computer_action(s, screen) is None
    # a bare arguments object is read as the dialect's function
    bare = parse_step(
        '<tool_call>{"action": "right_click", "coordinate": [10, 10]}</tool_call>', "computer_use"
    )
    assert bare is not None and bare.name == "computer_use"
    with pytest.raises(ValueError, match="needs `coordinate`"):
        to_computer_action(parse_step(step("left_click", "x").content, "computer_use"), screen)
    with pytest.raises(ValueError, match="needs `keys`"):
        to_computer_action(parse_step(step("key", "x").content, "computer_use"), screen)


def test_computer_dialect_prompt(settings: Settings, fake_screen) -> None:
    link = make_link(settings)
    ui = AutoApproveUI()
    act = ComputerAct(link=link, gui=GUISettings())
    operator = PhoneOperator(
        link,  # type: ignore[arg-type]
        GUISettings(),
        Sentinel(
            settings.sentinel, audit=AuditLog(settings.data_dir / "a.jsonl", session_id="t"), ui=ui
        ),
        act,
        ui,
        make_llm=lambda: MockLLM([]),
        dialect=COMPUTER,
    )
    prompt = operator.system_prompt()
    assert '"name": "computer_use"' in prompt and "computer_use with action=terminate" in prompt
    assert "Prefer the keyboard" in prompt and "mobile_use" not in prompt


# ----------------------------------------------------------------------------- the link
async def test_mac_keyboard_requires_stable_foreground_through_the_last_observation(
    settings: Settings, fake_screen, monkeypatch: pytest.MonkeyPatch
) -> None:
    link = make_link(settings)
    hands: FakeHands = link._backend  # type: ignore[assignment]
    monkeypatch.setattr(platform, "system", lambda: "Darwin")
    pid = 501
    monkeypatch.setattr("nanomuse.computer.link.mac_frontmost_pid", lambda: pid)
    with pytest.raises(DeviceError, match="last screen observation"):
        await link.act({"action": "key", "keys": ["return"]})
    await link.screen()
    pid = 502
    with pytest.raises(DeviceError, match="last screen observation"):
        await link.act({"action": "type", "text": "draft", "clear": True, "submit": True})
    assert not hands.calls
    changed = iter([501, 502])
    monkeypatch.setattr("nanomuse.computer.link.mac_frontmost_pid", lambda: next(changed))
    await link.screen()
    monkeypatch.setattr("nanomuse.computer.link.mac_frontmost_pid", lambda: pid)
    with pytest.raises(DeviceError, match="last screen observation"):
        await link.act({"action": "key", "keys": ["return"]})
    await link.screen()
    await link.act({"action": "type", "text": "draft"})
    assert hands.calls == [("type", "draft")]

    monkeypatch.setattr(link, "_capture_screen", lambda: None)
    with pytest.raises(DeviceError, match="no screenshot"):
        await link.screen()
    with pytest.raises(DeviceError, match="last screen observation"):
        await link.act({"action": "type", "text": "after failed capture"})
    assert hands.calls == [("type", "draft")]


async def test_link_acts_looks_again_and_reports_steps(settings: Settings, fake_screen) -> None:
    events: list[dict[str, Any]] = []
    link = make_link(settings, events)
    hands: FakeHands = link._backend  # type: ignore[assignment]
    assert link.connected and link.device.width == 1920 and link.status()["backend"] == "fake"
    screen = await link.screen()
    assert screen.title == "Firefox (firefox)" and screen.image_path
    await link.task_event("begin", "save the page")
    r = await link.act({"action": "click", "x": 100, "y": 200, "label": "File"})
    assert r["looked"] is True and hands.calls == [("click", 100.0, 200.0, "left", 1)]
    await link.act({"action": "type", "text": "hello", "clear": True, "submit": True})
    select_all = "command" if platform.system() == "Darwin" else "ctrl"
    assert hands.calls[1:] == [("key", (select_all, "a")), ("type", "hello"), ("key", ("enter",))]
    await link.act({"action": "scroll", "x": 5, "y": 5, "dy": -120})
    await link.act({"action": "drag", "x": 1, "y": 2, "x2": 3, "y2": 4})
    await link.act({"action": "open_app", "app": "Firefox"})
    assert ("open", "Firefox") in hands.calls
    await link.task_event("end")
    kinds = [e["event"] for e in events]
    assert kinds == ["begin", "act", "act", "act", "act", "act", "end"]
    first = events[1]
    assert first["action"] == "click" and first["label"] == "File"
    assert first["fx"] == round(100 / 1920, 4) and first["fy"] == round(200 / 1080, 4)
    assert first["app"] == "firefox" and first["title"] == "Firefox"
    assert link.task_active is False


async def test_stop_ends_at_the_next_step(settings: Settings, fake_screen) -> None:
    link = make_link(settings)
    await link.task_event("begin", "x")
    assert link.stop() is True
    with pytest.raises(DeviceStopped):
        await link.act({"action": "click", "x": 1, "y": 1, "label": "a"})
    # once raised, the flag is spent: the next task runs
    await link.act({"action": "move", "x": 1, "y": 1})
    assert link.stop() is True  # a last action exists, so Stop has something to end


def test_a_black_capture_is_an_error_not_a_picture(monkeypatch: pytest.MonkeyPatch) -> None:
    """macOS without Screen Recording (or granted after the process started) hands out an
    all-black frame as if it were the screen; the hands say what is wrong instead."""
    import io
    import sys
    import types

    from PIL import Image

    from nanomuse.computer import screen as screen_mod

    class Grab:
        def __init__(self, w: int, h: int, px: bytes) -> None:
            self.size = (w, h)
            self.bgra = px * (w * h)

    class Sct:
        def __init__(self, px: bytes) -> None:
            self.monitors = [{"width": 4, "height": 3}, {"width": 4, "height": 3}]
            self.px = px

        def __enter__(self) -> Sct:
            return self

        def __exit__(self, *a: object) -> None:
            return None

        def grab(self, mon: dict[str, int]) -> Grab:
            return Grab(4, 3, self.px)

    def install(px: bytes) -> None:
        fake = types.ModuleType("mss")
        fake.mss = lambda: Sct(px)  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "mss", fake)

    install(b"\x00\x00\x00\xff")  # black
    with pytest.raises(screen_mod.BlackScreen, match="Screen Recording"):
        screen_mod.take_screenshot()
    install(b"\x30\x60\x90\xff")  # a colour
    shot = screen_mod.take_screenshot()
    assert shot is not None and shot.mime == "image/jpeg" and shot.width == 4
    # the platform fallback is checked the same way
    black_png = io.BytesIO()
    Image.new("RGB", (4, 3)).save(black_png, "PNG")
    monkeypatch.setitem(sys.modules, "mss", None)
    monkeypatch.setattr(screen_mod, "_platform_screenshot", lambda: black_png.getvalue())
    with pytest.raises(screen_mod.BlackScreen):
        screen_mod.take_screenshot()


def test_hands_backend_choice(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(hands_mod.shutil, "which", lambda name: None)
    monkeypatch.setitem(hands_mod.sys.modules, "pyautogui", None)  # import fails
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    with pytest.raises(hands_mod.HandsUnavailable):
        hands_mod.pick_backend("auto")
    info = hands_mod.describe_availability("xdotool")
    assert info["available"] is False and "xdotool" in info["reason"]
    if hands_mod.sys.platform.startswith("linux"):
        monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
        monkeypatch.delenv("DISPLAY", raising=False)
        with pytest.raises(hands_mod.HandsUnavailable, match="Wayland"):
            hands_mod.pick_backend("auto")


def test_pyautogui_without_tk_does_not_take_the_runtime_down(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """mouseinfo (pyautogui's dependency) calls sys.exit at import when tkinter is missing on
    Linux; the frozen desktop runtime has no Tk. A stand-in is registered first, and should
    the import still exit, the hands are merely unavailable (0.1.25 Linux: every request died)."""
    import types

    monkeypatch.setitem(hands_mod.sys.modules, "tkinter", None)  # import tkinter fails
    monkeypatch.delitem(hands_mod.sys.modules, "mouseinfo", raising=False)
    fake = types.ModuleType("pyautogui")
    monkeypatch.setitem(hands_mod.sys.modules, "pyautogui", fake)
    assert hands_mod._import_pyautogui() is fake
    stub = hands_mod.sys.modules["mouseinfo"]
    assert stub.__name__ == "mouseinfo" and callable(stub.MouseInfoWindow)
    monkeypatch.delitem(hands_mod.sys.modules, "mouseinfo")

    def exits() -> Any:
        raise SystemExit("NOTE: You must install tkinter on Linux to use MouseInfo.")

    monkeypatch.setattr(hands_mod, "_import_pyautogui", exits)
    monkeypatch.setattr(hands_mod.shutil, "which", lambda name: None)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    with pytest.raises(hands_mod.HandsUnavailable, match="tkinter"):
        hands_mod.PyAutoGUIHands()
    info = hands_mod.describe_availability("auto")
    assert info["available"] is False and "tkinter" in info["reason"]


# ----------------------------------------------------------------------------- the tools
def test_computer_act_risk(settings: Settings, fake_screen) -> None:
    link = make_link(settings)
    link.last_screen = Screen.from_device(
        {
            **SCREEN_RAW,
            "nodes": [
                {
                    "text": "Bookmarks",
                    "box": [0, 0, 50, 50],
                    "clickable": True,
                },
                {
                    "text": "Confirm payment",
                    "box": [80, 80, 180, 140],
                    "clickable": True,
                },
            ],
        }
    )
    act = ComputerAct(link=link, gui=GUISettings())
    plain = act.assess({"action": "click", "x": 1, "y": 2, "label": "Bookmarks"})
    assert plain.risk == RiskLevel.MODERATE and plain.target == "Firefox"
    assert plain.summary == 'computer_act: click "Bookmarks" at (1,2) in Firefox (firefox)'
    unlabelled = act.assess({"action": "click", "x": 1, "y": 2})
    assert unlabelled.warnings and "no `label`" in unlabelled.warnings[0]
    claimed_pay = act.assess({"action": "click", "x": 1, "y": 2, "label": "Confirm payment"})
    assert claimed_pay.risk == RiskLevel.MODERATE and not claimed_pay.egress
    # The model says one thing, the element under the cursor another: the screen decides.
    dishonest = act.assess({"action": "click", "x": 100, "y": 100, "label": "View details"})
    assert dishonest.risk == RiskLevel.SENSITIVE and dishonest.egress
    assert any("pay" in warning for warning in dishonest.warnings)
    # No element under the point: the model's label cannot make the target safe.
    bare = act.assess({"action": "click", "x": 500, "y": 500, "label": "Bookmarks"})
    assert bare.risk == RiskLevel.SENSITIVE and bare.egress
    assert any("no element" in warning for warning in bare.warnings)
    submit = act.assess({"action": "type", "text": "hi", "submit": True})
    assert submit.risk == RiskLevel.SENSITIVE and submit.egress is True
    save = act.assess({"action": "key", "keys": ["ctrl", "s"]})
    assert save.risk == RiskLevel.SENSITIVE and save.warnings == ["saves a file"]
    assert act.assess({"action": "key", "keys": ["ctrl", "c"]}).risk == RiskLevel.MODERATE
    assert (
        act.assess({"action": "open_app", "app": "Terminal"}).summary
        == "computer_act: open Terminal"
    )


async def test_a_screen_without_elements_requires_conservative_approval(
    settings: Settings, fake_screen
) -> None:
    # A screenshot or WebView with no reported elements cannot verify a model-named target.
    phone_link = PhoneLink()
    FakePhone(phone_link, [PAY_SCREEN])
    await phone_link.screen()
    computer_link = make_link(settings)
    computer_link.last_screen = Screen.from_device(SCREEN_RAW)
    assert not computer_link.last_screen.nodes

    phone = PhoneAct(link=phone_link, gui=GUISettings()).assess(
        {"action": "tap", "x": 20, "y": 20, "label": "Harmless"}
    )
    computer = ComputerAct(link=computer_link, gui=GUISettings()).assess(
        {"action": "click", "x": 20, "y": 20, "label": "Harmless"}
    )
    for assessment in (phone, computer):
        assert assessment.risk == RiskLevel.SENSITIVE and assessment.egress
        assert assessment.reads_private_data
        assert any("no element" in warning for warning in assessment.warnings)


async def test_computer_tools_execute(settings: Settings, fake_screen) -> None:
    link = make_link(settings)
    hands: FakeHands = link._backend  # type: ignore[assignment]
    look = await ComputerScreen(link=link).execute()
    assert look.ok and look.images and "Firefox" in look.output
    act = ComputerAct(link=link, gui=GUISettings())
    r = await act.execute(action="click", x=10, y=10)
    assert not r.ok and "needs `label`" in (r.error or "")
    r = await act.execute(action="click", x=99999, y=10, label="x")
    assert not r.ok and "outside" in (r.error or "")
    r = await act.execute(action="click", x=10, y=10, label="File")
    assert r.ok and r.output.startswith("Input sent.") and r.images
    assert "screenshot is identical" in r.output
    r = await act.execute(action="key", keys="ctrl+l")
    assert r.ok and ("key", ("ctrl", "l")) in hands.calls
    r = await act.execute(action="dance")
    assert not r.ok
    link.stop()
    r = await act.execute(action="click", x=10, y=10, label="File")
    assert not r.ok and STOP_MARKER in (r.error or "")


async def test_operator_runs_on_the_computer(settings: Settings, fake_screen) -> None:
    events: list[dict[str, Any]] = []
    link = make_link(settings, events)
    hands: FakeHands = link._backend  # type: ignore[assignment]
    ui = AutoApproveUI(approve=True)
    llm = MockLLM(
        [
            step("open", "Open the text editor", text="gedit"),
            step("left_click", "Click in the document", coordinate=[499, 499]),
            step("type", "Type the note", text="hello from nanoMuse"),
            step("key", "Save with Ctrl+S", keys=["ctrl", "s"]),
            step("answer", "Report", text="Saved the note."),
        ]
    )
    gui = GUISettings(max_steps=8)
    act = ComputerAct(link=link, gui=gui)
    sentinel = Sentinel(
        settings.sentinel, audit=AuditLog(settings.data_dir / "a.jsonl", session_id="t"), ui=ui
    )
    operator = PhoneOperator(
        link,  # type: ignore[arg-type]
        gui,
        sentinel,
        act,
        ui,
        make_llm=lambda: llm,
        traces_dir=settings.data_dir / "computer-traces",
        dialect=COMPUTER,
    )
    outcome = await operator.run("write hello in a new text file and save it")
    assert outcome.status == "done" and outcome.message == "Saved the note." and outcome.steps == 5
    assert hands.calls[0] == ("open", "gedit")
    assert hands.calls[1] == ("click", 959.0, 539.5, "left", 1)  # 999-grid → 1920×1080
    assert ("type", "hello from nanoMuse") in hands.calls and ("key", ("ctrl", "s")) in hands.calls
    # The screenshot-only click has no trusted node, and saving is independently sensitive.
    assert [r.summary for r in ui.requests] == [
        'computer_act: click "Click in the document" at (959,539.5) in Firefox (firefox)',
        "computer_act: press ctrl+s in Firefox (firefox)",
    ]
    report = outcome.report()
    assert report.startswith("The computer operator finished. (5 steps)")
    assert "- open gedit" in report and "- press ctrl+s in Firefox (firefox)" in report
    assert [e["event"] for e in events][0] == "begin" and events[-1]["event"] == "end"
    assert '"name": "computer_use"' in llm.calls[0]["messages"][0].content
    tool = ComputerTask(link=link, operator=operator)
    assert tool.assess({"goal": "x", "app": "gedit"}).target == "gedit"


# ----------------------------------------------------------------------------- the server
def tc(name: str, **args: Any) -> ToolCall:
    return ToolCall(function=Function(name=name, arguments=json.dumps(args)))


@pytest.fixture()
def server(settings: Settings, fake_screen) -> Iterator[tuple[TestClient, MuseService, MockLLM]]:
    settings.server.token = "secret-token"
    llm = MockLLM([])
    service = MuseService(settings, llm=llm)
    assert service.app.computer is not None
    service.app.computer._backend = FakeHands()
    service.app.computer.settings.settle_s = 0.0
    app = create_app(settings, service)
    with TestClient(app) as client:
        client.headers["Authorization"] = "Bearer secret-token"
        yield client, service, llm


def wait_for(pred, timeout: float = 8.0):  # noqa: ANN001
    deadline = time.time() + timeout
    while time.time() < deadline:
        v = pred()
        if v:
            return v
        time.sleep(0.03)
    raise AssertionError("condition not met in time")


def test_hands_switch_adds_the_tools_and_the_card_follows_a_task(
    server, fake_screen: list[dict[str, Any]]
) -> None:
    client, service, llm = server
    view = client.get("/api/hands").json()
    assert view["enabled"] is False and view["available"] is True and view["backend"] == "fake"
    assert "computer_act" not in service.app.tools
    assert client.get("/api/state").json()["hands"]["available"] is True
    # off, on a computer: the agent is told where the switch is, not left to shrug
    section = service.app.agent.computer_section()
    assert "turned off" in section and "Devices → Hands on this computer" in section
    r = client.put("/api/connections/hands", json={"enabled": True})
    assert r.status_code == 200 and r.json()["enabled"] is True
    assert {"computer_screen", "computer_act", "computer_task"} <= {
        t.name for t in service.app.tools
    }
    assert "can drive this computer" in service.app.agent.computer_section()
    assert client.put("/api/connections/hands", json={"backend": "nope"}).status_code == 400
    # the body is typed: a switch that is not a boolean, or no object at all, is 422
    assert client.put("/api/connections/hands", json={"enabled": "maybe"}).status_code == 422
    assert client.put("/api/connections/hands", json=["enabled"]).status_code == 422
    assert service.settings.hands.enabled is True
    # the picture mode is kept with the other hands settings and read back at start
    assert client.put("/api/connections/hands", json={"mode": "nope"}).status_code == 400
    assert client.put("/api/connections/hands", json={"mode": "window"}).status_code == 200
    assert service.settings.hands.mode == "window"
    from nanomuse.config import Settings, apply_app_settings, load_app_settings

    fresh = Settings()
    apply_app_settings(fresh, load_app_settings(service.data_dir))
    assert fresh.hands.mode == "window" and fresh.hands.enabled is True
    # the computer_act tool: a hands card for the step, the screen in the tool output
    fake_screen[0]["nodes"] = [{"text": "File", "box": [0, 0, 1920, 1080], "clickable": True}]
    service.app.computer.last_screen = Screen.from_device(fake_screen[0])
    service.settings.sentinel.mode = "auto"
    llm.script.append(
        LLMResponse(tool_calls=[tc("computer_act", action="click", x=5, y=5, label="File")])
    )
    llm.script.append(LLMResponse(content="Clicked File."))
    client.post("/api/threads/main/send", json={"text": "click File"})
    wait_for(lambda: not service.threads["main"].busy and service.threads["main"].inbox.empty())
    events = client.get("/api/threads/main/events").json()["events"]
    types = [e["type"] for e in events]
    assert types == ["user", "tool", "hands", "assistant"], types
    hands_card = events[2]
    assert hands_card["status"] == "done" and hands_card["last"]["action"] == "click"
    assert hands_card["last"]["label"] == "File" and hands_card["app"] == "firefox"
    # a whole task: one live card, updated step by step, then done
    service.app.computer_operator._llm = MockLLM(  # type: ignore[union-attr]
        [step("left_click", "Click Save", coordinate=[10, 10]), step("answer", "Done", text="ok")]
    )
    llm.script.append(LLMResponse(tool_calls=[tc("computer_task", goal="save it")]))
    llm.script.append(LLMResponse(content="Saved."))
    client.post("/api/threads/main/send", json={"text": "save it"})
    wait_for(lambda: not service.threads["main"].busy and service.threads["main"].inbox.empty())
    cards = [
        e for e in client.get("/api/threads/main/events").json()["events"] if e["type"] == "hands"
    ]
    assert len(cards) == 2
    assert cards[1]["text"] == "save it" and cards[1]["status"] == "done" and cards[1]["steps"] == 1
    assert cards[1]["last"]["label"] == "Click Save"
    # the switch off takes the tools away; Stop with nothing running says so
    client.put("/api/connections/hands", json={"enabled": False})
    assert "computer_act" not in service.app.tools
    assert "turned off" in service.app.agent.computer_section()
    assert client.post("/api/hands/stop").json()["stopped"] is True  # a last action exists


def test_open_app_refuses_commands_to_the_machine(settings: Settings) -> None:
    assert hands_mod.looks_like_an_application("Notes")
    assert hands_mod.looks_like_an_application("Visual Studio Code")
    for name in ("shutdown", "reboot", "poweroff", "SHUTDOWN.EXE", "sudo", "rm", "sh"):
        assert not hands_mod.looks_like_an_application(name), name
    for name in ("/usr/bin/env", "notes; reboot", "a && b", "-r", "`id`"):
        assert not hands_mod.looks_like_an_application(name), name
    with pytest.raises(ValueError, match="not an application"):
        hands_mod.open_application("shutdown")
    # the assessment says so before the Sentinel ever asks
    link = ComputerLink(HandsSettings(enabled=True, settle_s=0.0), backend=FakeHands())
    act = ComputerAct(link=link, gui=GUISettings())
    bad = act.assess({"action": "open_app", "app": "poweroff"})
    assert bad.risk == RiskLevel.SENSITIVE and any("command" in w for w in bad.warnings)
    good = act.assess({"action": "open_app", "app": "Notes"})
    assert good.risk == RiskLevel.MODERATE and not good.warnings


def test_parse_step_with_a_broken_point_is_not_a_step() -> None:
    broken = '<tool_call>{"name": "mobile_use", "arguments": {"action": "click", "coordinate": "x"}}</tool_call>'
    assert parse_step(broken) is None
    wrong_type = (
        '<tool_call>{"name": "mobile_use", "arguments": {"action": "click", "coordinate": {"x": 1}}}'
        "</tool_call>"
    )
    assert parse_step(wrong_type) is None

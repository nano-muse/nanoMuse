"""This computer as a device the operator can look at and act on — the same face
:class:`~nanomuse.phone.link.PhoneLink` shows for the phone, so the operator loop, the
tools and the GUI's cards are shared.

``screen()`` is a screenshot plus the window in front; ``act()`` is one action of the hands
(:mod:`nanomuse.computer.hands`), followed by a short settle and a fresh look. ``stop()`` is
the Stop button: the next action raises :class:`~nanomuse.phone.link.DeviceStopped`, which
ends the task the way the phone's Stop pill does. Every action and task boundary is also
handed to ``on_event`` — the GUI shows a *Hands* card with the current step and the desktop
stage draws a cursor where the click lands (``x``/``y`` in the hands' screen pixels,
``fx``/``fy`` as fractions of the screen).

Coordinates: the picture the model sees is the unit. ``Screen.width``/``height`` are the
picture's size, and every ``x``/``y`` the tools accept is a pixel of it. The hands move in
their own screen space (``screen_w``/``screen_h``: X11 root pixels, macOS points, Windows
physical pixels), and the one place the two meet is :class:`~nanomuse.computer.coords.Mapping`
— applied in ``_do`` before an action and in ``_where`` before the overlay hears of it.
When nanoMuse Desktop started this runtime, its operator (:mod:`nanomuse.computer.operator`)
takes the screenshot and does the moving; otherwise the Python backends do.

Two modes (``[hands] mode``). *Screen*: the whole screen through ``mss`` and the system
mouse. *Window* (macOS, :mod:`nanomuse.computer.mac_window`): one application's window —
the picture the model sees is that window (taken by the desktop app's helper when the app
is around, by the runtime's own Quartz call otherwise), events go to that process, the
person keeps the cursor. ``auto`` is window mode on macOS as soon as a target application is set
(``set_target``, the ``computer_target`` action or ``app`` on ``computer_act``), screen
everywhere else. When a selected window is unavailable, observations may show the screen;
input waits for that window or for the target to be cleared.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import io
import platform
import socket
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from nanomuse.computer import hands as hands_mod
from nanomuse.computer import mac_window
from nanomuse.computer import operator as operator_mod
from nanomuse.computer.coords import Mapping
from nanomuse.computer.screen import (
    DEFAULT_MAX_WIDTH,
    active_window,
    capture,
    mac_frontmost_pid,
    screen_size,
)
from nanomuse.config import HandsSettings
from nanomuse.logger import logger
from nanomuse.phone.link import Device, DeviceError, DeviceStopped
from nanomuse.phone.screen import Screen

ACTIONS = (
    "click",
    "double_click",
    "right_click",
    "middle_click",
    "move",
    "drag",
    "scroll",
    "type",
    "key",
    "open_app",
    "wait",
)
POINTED = ("click", "double_click", "right_click", "middle_click", "move")

Listener = Callable[[dict[str, Any]], None]


class ComputerLink:
    def __init__(
        self,
        settings: HandsSettings,
        shots_dir: Path | None = None,
        on_event: Listener | None = None,
        backend: hands_mod.HandsBackend | None = None,
        window_adapter: mac_window.MacAdapter | None = None,
    ):
        self.settings = settings
        self.shots_dir = shots_dir
        self.on_event = on_event
        self._backend: hands_mod.HandsBackend | None = backend
        self._backend_error = ""
        # window mode: the application the hands work in, and the hands that drive it
        self.target_app = ""
        self.target_title = ""
        self._window: mac_window.MacWindowHands | None = (
            mac_window.MacWindowHands(window_adapter) if window_adapter is not None else None
        )
        self._window_error = ""
        # `auto` mode fail-safe: once the Quartz layer itself breaks (not "the window went
        # away" — that is retried every look), the hands stay on the screen for this target
        self._window_broken = ""
        # the frame the last window picture was taken in (None in screen mode)
        self.window_frame: mac_window.WindowFrame | None = None
        self._observed_pid: int | None = None
        self._picture_digest: bytes | None = None
        self.last_screen: Screen | None = None
        # picture pixels ↔ the hands' screen pixels for the last whole-screen picture
        self.mapping: Mapping | None = None
        self._stopped = False
        self.task_active = False
        self.task_text = ""
        self.last_action: dict[str, Any] | None = None
        w, h = self._initial_size()
        self._device = Device(
            id="this-computer",
            name=socket.gethostname() or "this computer",
            platform=platform.system().lower() or "computer",
            gui=True,
            browser=False,
            capsule=True,
            width=w,
            height=h,
        )

    def _initial_size(self) -> tuple[int, int]:
        """The hands' screen space before the first look: the desktop operator's word when
        the app is around (asking Python's capture layer on macOS would be a second
        Screen Recording prompt, for a process that never takes the picture), else the
        capture's own size."""
        found = operator_mod.operator_env()
        if self._backend is None and found is not None:
            try:
                info = operator_mod.OperatorClient(*found).info()
            except operator_mod.OperatorError as exc:
                logger.debug("desktop operator not asked for the screen size: {}", exc)
            else:
                return operator_mod.display_size(info)
            if operator_mod.operator_owns_the_screen():
                return 0, 0  # the first look through the operator sets it; never mss here
        return screen_size()

    # ------------------------------------------------------------------ the device
    @property
    def device(self) -> Device:
        return self._device

    @property
    def connected(self) -> bool:
        return self.backend_available()

    def backend_available(self) -> bool:
        try:
            self._hands()
        except hands_mod.HandsUnavailable:
            return False
        return True

    def reset_backend(self) -> None:
        """Forget the chosen backend; the next action picks one again from the settings."""
        self._backend = None
        self._backend_error = ""

    def _hands(self) -> hands_mod.HandsBackend:
        if self._backend is None:
            try:
                self._backend = hands_mod.pick_backend(self.settings.backend)
                self._backend_error = ""
            except hands_mod.HandsUnavailable as exc:
                self._backend_error = str(exc)
                raise
        return self._backend

    def status(self) -> dict[str, Any]:
        available = self.backend_available()
        window_ok, window_why = self.window_available()
        return {
            "enabled": self.settings.enabled,
            "available": available,
            "backend": self._backend.name if self._backend else None,
            "reason": self._backend_error,
            "mode": self.settings.mode,
            "coords": self.settings.coords,
            # the hands' screen space and the picture the model last saw, so a reader can
            # tell the two apart (docs/gui.md, "Coordinates")
            "screen_size": [self._device.width, self._device.height],
            "picture_size": [self.mapping.image_w, self.mapping.image_h] if self.mapping else None,
            # window mode (macOS): whether it can run here, and what it is working in
            "window": {
                "available": window_ok,
                "reason": window_why or self._window_broken or self._window_error,
                "active": self.in_window_mode(),
                "app": self.target_app,
                "title": self.target_title,
                "frame": self.window_frame.window.to_dict() if self.window_frame else None,
            },
            "device": self._device.to_dict(),
            "task_active": self.task_active,
            "task_text": self.task_text,
            "last_screen": self.last_screen.to_dict() if self.last_screen else None,
        }

    # ------------------------------------------------------------------ window mode
    def window_available(self) -> tuple[bool, str]:
        """Whether window mode can run here (macOS with pyobjc, or a fake adapter)."""
        if self._window is not None:
            return True, ""
        return mac_window.available()

    def _window_hands(self) -> mac_window.MacWindowHands:
        """The window hands, made on first use: under the desktop app with its helper
        bundle, the windows and their pictures come through the operator (the helper holds
        Screen Recording and captures with ScreenCaptureKit); otherwise the runtime's own
        Quartz path, which says so in the log."""
        if self._window is None:
            operator = self._operator()
            adapter: mac_window.MacAdapter
            if operator is not None and operator.helper_present:
                logger.info(
                    "window mode: windows are listed and captured through the desktop app's helper"
                )
                adapter = mac_window.OperatorWindowAdapter(operator.client)
            else:
                adapter = mac_window.QuartzAdapter()
            self._window = mac_window.MacWindowHands(adapter)
        return self._window

    def set_target(self, app: str, title: str = "") -> None:
        """The application the hands work in from now on ("" = the whole screen again)."""
        app, title = app.strip()[:80], title.strip()[:160]
        if (app, title) != (self.target_app, self.target_title) or self._window_broken:
            self.window_frame = None
            self._window_error = ""
            self._window_broken = ""
        self.target_app, self.target_title = app, title

    def in_window_mode(self) -> bool:
        """Whether the next look and action go to the target window rather than the screen."""
        mode = self.settings.mode
        if mode == "screen" or not self.target_app:
            return False
        if mode == "window":
            return True
        if self._window_broken:
            return False
        return mac_window.available()[0] or self._window is not None

    def _window_layer_failed(self, exc: BaseException) -> None:
        """A failure inside the Quartz layer (pyobjc, the window server) rather than a
        missing window. Auto shows the screen until a target is selected again. Window
        mode retries the window capture."""
        self._window_error = f"window mode failed: {exc}"
        self.window_frame = None
        if self.settings.mode == "auto":
            self._window_broken = self._window_error
            logger.warning("window mode: {}; the screen from here on", exc)
        else:
            logger.warning("window mode: {}", exc)

    def app_in_front(self) -> tuple[str, str]:
        """``(id, name)`` of the application an action lands in: the target window's bundle
        id and name in window mode, else the application in front as last observed. What a
        per-app permission (``computer_app:<id>``) is bound to."""
        if self.in_window_mode():
            if self.window_frame is not None:
                return self.window_frame.window.app_id, self.window_frame.window.owner
            return self.target_app, self.target_app
        screen = self.last_screen
        if screen is None:
            return "", ""
        return screen.app, screen.app_name or screen.app

    # ------------------------------------------------------------------ stop
    def stop(self) -> bool:
        """The Stop button: whatever is running ends at its next step."""
        if not self.task_active and self.last_action is None:
            return False
        self._stopped = True
        self._emit({"event": "stop"})
        return True

    def _check_stopped(self) -> None:
        if self._stopped:
            self._stopped = False
            raise DeviceStopped("the user pressed Stop")

    # ------------------------------------------------------------------ looking
    async def screen(self) -> Screen:
        self._check_stopped()
        note = ""
        if self.in_window_mode():
            raw = await asyncio.to_thread(self._capture_window)
            if raw is not None:
                self._observed_pid = None
                return self._observe(raw)
            note = self._window_error
            if self._window_broken:
                self._window_error = ""  # the fail-safe tripped: said once
        elif self._window_broken and self._window_error:
            # the fail-safe tripped during an action: say so once, then plain screen pictures
            note, self._window_error = self._window_error, ""
        on_mac = platform.system() == "Darwin"
        first_pid = await asyncio.to_thread(mac_frontmost_pid) if on_mac else None
        self._observed_pid = None
        raw = await asyncio.to_thread(self._capture_screen)
        if raw is not None and note:
            raw["note"] = (note + "; showing the whole screen instead")[:300]
        if raw is None:
            raise DeviceError(
                "no screenshot could be taken on this computer: install mss and Pillow "
                "(pip install 'nanomuse[hands]') or a screenshot tool, and make sure there is a "
                "display session"
            )
        self._place(raw)
        screen = self._observe(raw)
        if (
            screen.image_path
            and first_pid is not None
            and first_pid == await asyncio.to_thread(mac_frontmost_pid)
        ):
            self._observed_pid = first_pid
        return screen

    def _observe(self, raw: dict[str, Any]) -> Screen:
        screen = Screen.from_device(raw, device=self._device, shots_dir=self.shots_dir)
        image = raw.get("screenshot")
        self._picture_digest = (
            hashlib.sha256(image.encode()).digest()
            if screen.image_path and isinstance(image, str)
            else None
        )
        self.last_screen = screen
        return screen

    def _operator(self) -> operator_mod.OperatorHands | None:
        """The desktop app's operator, when it is the hands in use."""
        try:
            hands = self._hands()
        except hands_mod.HandsUnavailable:
            return None
        return hands if isinstance(hands, operator_mod.OperatorHands) else None

    def _capture_screen(self) -> dict[str, Any] | None:
        """The whole screen: through the desktop operator when it has the hands (then the
        Python capture layer is never touched — on macOS it would be a second Screen
        Recording prompt for a process that does not need it), else the Python capture.

        On macOS under the desktop app there is no "else": when the app set the operator
        variables, the screenshot goes through the operator or fails with the operator's
        reason (the permission text) — never ``mss`` / ``screencapture``, which would mean a
        second TCC prompt, for the runtime, and a second error text. Linux, Windows and runs
        without the app keep the Python capture."""
        max_width = self.settings.max_image_width or DEFAULT_MAX_WIDTH
        operator = self._operator()
        if operator is not None:
            try:
                raw = operator_mod.operator_capture(operator.client, max_width)
            except operator_mod.OperatorError as exc:
                raise DeviceError(f"could not take a screenshot of this computer: {exc}") from exc
            if raw is not None:
                try:
                    raw["app"], raw["app_name"] = active_window()
                except Exception:  # noqa: BLE001 — the picture matters, the name is a caption
                    raw["app"], raw["app_name"] = "", ""
                return raw
        if operator_mod.operator_owns_the_screen():
            why = self._backend_error or "the desktop app's operator returned no picture"
            raise DeviceError(f"could not take a screenshot of this computer: {why}")
        if hands_mod.wayland_session():
            # Linux under Wayland: mss would grab the XWayland root — black, or the X
            # windows alone — and the hands could not act on it anyway. Said plainly, on
            # the first attempt, with the same words as Settings → Computer use.
            raise DeviceError(
                f"the hands are off on this computer: {self._backend_error or hands_mod.WAYLAND_TEXT}"
            )
        try:
            return capture(max_width)
        except Exception as exc:  # noqa: BLE001 — platform tools fail in many ways
            raise DeviceError(f"could not take a screenshot of this computer: {exc}") from exc

    def _place(self, raw: dict[str, Any]) -> None:
        """Settle the two sizes of a whole-screen picture: ``width``/``height`` stay the
        picture's (what the model answers in); the hands' screen space is what the backend
        says it moves in, else what the capture said (``screen_w``/``screen_h``), else the
        picture itself (1:1, the case of every device that taps where it looks)."""
        try:
            image_w, image_h = int(raw.get("width") or 0), int(raw.get("height") or 0)
        except (TypeError, ValueError):
            image_w = image_h = 0
        try:
            backend: hands_mod.HandsBackend | None = self._hands()
        except hands_mod.HandsUnavailable:
            backend = None
        space = hands_mod.hands_space(backend) if backend is not None else None
        if space is None:
            try:
                sw, sh = int(raw.get("screen_w") or 0), int(raw.get("screen_h") or 0)
            except (TypeError, ValueError):
                sw = sh = 0
            space = (sw, sh) if sw > 0 and sh > 0 else None
        screen_w, screen_h = space or (image_w, image_h)
        if screen_w and screen_h:
            self._device.width, self._device.height = screen_w, screen_h
        self.mapping = Mapping(image_w, image_h, screen_w, screen_h)
        raw.pop("screen_w", None)
        raw.pop("screen_h", None)

    # ------------------------------------------------------------------ acting
    async def act(self, params: dict[str, Any], timeout: float | None = None) -> dict[str, Any]:
        """One action of the hands, a short settle, a fresh look (``last_screen``). Returns
        ``{"note": ...}``; the tool renders ``last_screen`` afterwards."""
        self._check_stopped()
        action = str(params.get("action") or "")
        if action not in ACTIONS:
            raise DeviceError(f"unknown action {action!r}")
        hands = self._hands_for(action)
        before = self._picture_digest
        self.last_action = dict(params)
        self._emit({"event": "act", **self._where(params)})
        started = time.monotonic()
        try:
            note = await asyncio.wait_for(
                asyncio.to_thread(self._do, hands, action, params), timeout or 60.0
            )
        except TimeoutError:
            raise DeviceError(f"the hands did not finish '{action}' in time") from None
        except DeviceError:
            raise
        except mac_window.WindowLayerBroken as exc:
            self._window_layer_failed(exc)
            raise DeviceError(
                f"{action} failed: {exc}. Select the window again or clear the target."
            ) from exc
        except mac_window.WindowUnavailable as exc:
            # the window went away under the hands: back to the screen for the next look
            self._window_error = str(exc)
            self.window_frame = None
            raise DeviceError(f"{action} failed: {exc}") from exc
        except Exception as exc:  # noqa: BLE001 — pyautogui's FailSafeException and friends
            name = type(exc).__name__
            if "FailSafe" in name:
                self._emit({"event": "stop"})
                raise DeviceStopped("the mouse was thrown into a corner") from exc
            if isinstance(hands, mac_window.MacWindowHands):
                self._window_layer_failed(exc)
                raise DeviceError(
                    f"{action} failed: {exc}. Select the window again or clear the target."
                ) from exc
            raise DeviceError(f"{action} failed: {exc}") from exc
        settle = max(0.0, self.settings.settle_s - (time.monotonic() - started))
        if action != "wait" and settle:
            await asyncio.sleep(settle)
        try:
            await self.screen()
        except DeviceError as exc:
            logger.debug("no screenshot after {}: {}", action, exc)
            return {"note": note, "looked": False}
        if (
            action not in {"open_app", "move", "wait"}
            and before is not None
            and before == self._picture_digest
        ):
            unchanged = "The new screenshot is identical to the previous one. Verify the effect before repeating this action."
            note = f"{note} {unchanged}".strip()
        return {"note": note, "looked": True}

    def _capture_window(self) -> dict[str, Any] | None:
        """The target window as the observation, or None (with ``_window_error`` saying why)
        so the caller shows the whole screen instead."""
        try:
            hands = self._window_hands()
            png, frame = hands.look(self.target_app, self.target_title)
        except mac_window.WindowLayerBroken as exc:
            self._window_layer_failed(exc)
            return None
        except mac_window.WindowUnavailable as exc:
            self._window_error = str(exc)
            self.window_frame = None
            logger.info("window mode: {}", exc)
            return None
        except Exception as exc:  # noqa: BLE001 — pyobjc fails in many ways
            self._window_layer_failed(exc)
            return None
        self._window_error = ""
        data, mime = png, "image/png"
        max_width = self.settings.max_image_width or DEFAULT_MAX_WIDTH
        if max_width and frame.image_width > max_width:
            # a Retina window is twice its points; the model gets a lighter picture and
            # the frame maps its pixels back to the screen
            try:
                from PIL import Image

                img = Image.open(io.BytesIO(png)).convert("RGB")
                img = img.resize((max_width, int(img.height * max_width / img.width)))
                buf = io.BytesIO()
                img.save(buf, "JPEG", quality=80)
                data, mime = buf.getvalue(), "image/jpeg"
                frame = mac_window.WindowFrame(frame.window, img.width, img.height)
                hands.frame = frame
            except Exception as exc:  # noqa: BLE001 — without Pillow the picture goes as it is
                logger.debug("window picture not scaled: {}", exc)
        self.window_frame = frame
        w = frame.window
        where = f"window of {w.owner}" + (f": {w.title}" if w.title else "")
        return {
            "app": w.app_id,
            "app_name": w.owner,
            "route": w.title[:160],
            "width": frame.image_width,
            "height": frame.image_height,
            "keyboard": False,
            "screenshot": base64.b64encode(data).decode(),
            "mime": mime,
            "mode": "window",
            "note": f"{where}; coordinates are pixels of this window picture",
        }

    def _hands_for(self, action: str) -> hands_mod.HandsBackend:
        """The hands an action goes to: the window's process in window mode (when the
        window was looked at), the system mouse otherwise."""
        if (
            self.settings.mode != "screen"
            and self.target_app
            and action not in {"open_app", "wait"}
        ):
            window_mode = self.in_window_mode()
            if window_mode and self.window_frame is not None:
                return self._window_hands()
            if window_mode or self._window_broken or platform.system() == "Darwin":
                raise DeviceError(
                    f"No current window for {self.target_app}. Look at that window again or "
                    "clear the target to use the whole screen."
                )
        try:
            return self._hands()
        except hands_mod.HandsUnavailable as exc:
            raise DeviceError(str(exc)) from exc

    def _check_keyboard_focus(self, hands: hands_mod.HandsBackend) -> None:
        if platform.system() == "Darwin" and not isinstance(hands, mac_window.MacWindowHands):
            if self._observed_pid is None or mac_frontmost_pid() != self._observed_pid:
                raise DeviceError(
                    "The foreground application no longer matches the last screen observation. "
                    "Take a new screenshot or select the intended application with computer_target."
                )

    def _to_hands(self, hands: hands_mod.HandsBackend, p: dict[str, Any]) -> dict[str, Any]:
        """The action's points in the hands' screen space. The model's numbers are pixels
        of the picture; window hands take those as they are (their frame maps them), the
        screen hands get them mapped here — the one place that happens before acting."""
        if isinstance(hands, mac_window.MacWindowHands) or self.mapping is None:
            return p
        q = dict(p)
        for kx, ky in (("x", "y"), ("x2", "y2")):
            if q.get(kx) is not None and q.get(ky) is not None:
                q[kx], q[ky] = self.mapping.to_screen(float(q[kx]), float(q[ky]))
        if q.get("dy") is not None:
            q["dy"] = round(float(q["dy"]) * self.mapping.scale[1], 2)
        return q

    def _do(self, hands: hands_mod.HandsBackend, action: str, p: dict[str, Any]) -> str:
        p = self._to_hands(hands, p)
        x, y = float(p.get("x") or 0), float(p.get("y") or 0)
        if action == "click":
            hands.click(x, y)
        elif action == "double_click":
            hands.click(x, y, clicks=2)
        elif action == "right_click":
            hands.click(x, y, button="right")
        elif action == "middle_click":
            hands.click(x, y, button="middle")
        elif action == "move":
            hands.move(x, y)
        elif action == "drag":
            hands.drag(x, y, float(p.get("x2") or x), float(p.get("y2") or y))
        elif action == "scroll":
            hands.scroll(x, y, float(p.get("dy") or 300))
        elif action == "type":
            text = str(p.get("text") or "")
            if p.get("clear"):
                self._check_keyboard_focus(hands)
                hands.key(["command" if platform.system() == "Darwin" else "ctrl", "a"])
            self._check_keyboard_focus(hands)
            hands.type(text)
            if p.get("submit"):
                self._check_keyboard_focus(hands)
                hands.key(["enter"])
        elif action == "key":
            keys = [str(k) for k in (p.get("keys") or [])]
            if not keys:
                raise DeviceError("`key` needs `keys`")
            self._check_keyboard_focus(hands)
            hands.key(keys)
        elif action == "open_app":
            try:
                started = hands.open_app(str(p.get("app") or ""))
            except (ValueError, OSError) as exc:
                raise DeviceError(str(exc)) from exc
            except Exception as exc:  # noqa: BLE001 — CalledProcessError and friends
                raise DeviceError(f"could not open {p.get('app')!r}: {exc}") from exc
            time.sleep(1.5)
            if self.settings.mode != "screen" and self.window_available()[0]:
                # macOS: the application just opened is the window the hands work in
                self.set_target(str(p.get("app") or ""))
            return f"started {started}"
        elif action == "wait":
            time.sleep(max(0.2, min(10.0, float(p.get("seconds") or 1.0))))
        return ""

    def _where(self, params: dict[str, Any]) -> dict[str, Any]:
        """The action for the GUI: what and where — the point in the hands' screen pixels
        (``x``/``y``, for a cursor sprite on the desktop stage) and as fractions of the
        screen (``fx``/``fy``, for the overlay's marker, which is sized to the display and
        so lands where the pointer does). The model's coordinates are pixels of the picture
        — the whole screen's through ``mapping``, a window's through its frame."""
        w, h = self._device.width or 1, self._device.height or 1
        frame = self.window_frame if self.in_window_mode() else None
        mapping = self.mapping if frame is None else None
        out: dict[str, Any] = {
            "action": params.get("action"),
            "label": str(params.get("label") or "")[:120],
            "mode": "window" if frame is not None else "screen",
        }
        if frame is not None:
            out["window"] = frame.window.to_dict()

        def point(kx: str, ky: str) -> tuple[float, float] | None:
            if params.get(kx) is None or params.get(ky) is None:
                return None
            px, py = float(params[kx]), float(params[ky])
            if frame is not None:
                return frame.to_screen(px, py)
            if mapping is not None:
                return mapping.to_screen(px, py)
            return px, py

        start = point("x", "y")
        if start is not None:
            out["x"], out["y"] = round(start[0], 1), round(start[1], 1)
            out["fx"] = round(min(max(start[0] / w, 0.0), 1.0), 4)
            out["fy"] = round(min(max(start[1] / h, 0.0), 1.0), 4)
        end = point("x2", "y2")
        if end is not None:
            out["x2"], out["y2"] = round(end[0], 1), round(end[1], 1)
            out["fx2"] = round(min(max(end[0] / w, 0.0), 1.0), 4)
            out["fy2"] = round(min(max(end[1] / h, 0.0), 1.0), 4)
        if params.get("action") == "type":
            out["text"] = str(params.get("text") or "")[:80]
        if params.get("action") == "key":
            out["keys"] = list(params.get("keys") or [])
        return out

    # ------------------------------------------------------------------ task boundaries
    async def task_event(self, event: str, text: str = "") -> None:
        if event == "begin":
            self.task_active = True
            self.task_text = text[:200]
            self._stopped = False
        elif event == "end":
            self.task_active = False
            self.task_text = ""
        self._emit({"event": event, "text": text[:200]})

    def _emit(self, body: dict[str, Any]) -> None:
        if self.on_event is None:
            return
        app, title = "", ""
        if body.get("event") == "act":
            frame = self.window_frame if self.in_window_mode() else None
            if frame is not None:
                app, title = frame.window.owner, frame.window.title
            else:
                try:
                    app, title = active_window()
                except Exception:  # noqa: BLE001
                    app, title = "", ""
        try:
            self.on_event({**body, "app": app, "title": title, "ts": time.time()})
        except Exception:  # noqa: BLE001
            logger.exception("hands on_event")


__all__ = ["ACTIONS", "POINTED", "ComputerLink"]

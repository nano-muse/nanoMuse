"""A picture of this computer's screen, and the name of the window in front.

``take_screenshot`` is what the hub's ``screen`` action and the ``computer_screen`` tool
share: ``mss`` + Pillow when they are installed (every platform, no external program), else
the platform's own tool (``screencapture``, PowerShell, ``grim`` / ``gnome-screenshot`` /
``spectacle`` / ``import`` / ``scrot``). The picture is scaled for the model — capped at
``max_width``, then to the size the Qwen-VL family would resize it to anyway
(:func:`nanomuse.computer.coords.picture_size`), so the model's pixels are the picture's;
the capture's own size is returned next to it so coordinates map back to the real screen.
This is the fallback: the desktop app's operator (:mod:`nanomuse.computer.operator`) takes
the screenshot when the app started the runtime.

``active_window`` names what is in front — *Firefox*, *Terminal* — so an approval card and
the audit log can say *in Firefox*, the way the phone's say *in 支付宝*.
"""

from __future__ import annotations

import base64
import io
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from nanomuse.computer.coords import picture_size
from nanomuse.logger import logger

DEFAULT_MAX_WIDTH = 1600


@dataclass
class Shot:
    data: bytes
    mime: str
    width: int  # the capture: the physical screen, in pixels
    height: int
    image_width: int  # the picture handed out (scaled)
    image_height: int

    @property
    def base64(self) -> str:
        return base64.b64encode(self.data).decode()

    def to_raw(self, app: str = "", title: str = "", note: str = "") -> dict[str, Any]:
        """The shape :meth:`nanomuse.phone.screen.Screen.from_device` takes: ``width`` and
        ``height`` are the picture's (the space the model answers in), ``screen_w`` and
        ``screen_h`` the capture's, for the link to map one onto the other."""
        return {
            "app": app,
            "app_name": title or app,
            "width": self.image_width or self.width,
            "height": self.image_height or self.height,
            "screen_w": self.width,
            "screen_h": self.height,
            "keyboard": False,
            "screenshot": self.base64,
            "mime": self.mime,
            "note": note,
        }


def _mss_grabber(mss: Any) -> Any:
    """``mss.MSS()`` on mss ≥ 10, ``mss.mss()`` before it (the old name is deprecated)."""
    factory = getattr(mss, "MSS", None) or mss.mss
    return factory()


def screen_size() -> tuple[int, int]:
    """The physical size of the main screen, (0, 0) when there is no display."""
    try:
        import mss  # type: ignore[import-not-found]

        with _mss_grabber(mss) as sct:
            mon = sct.monitors[1] if len(sct.monitors) > 1 else sct.monitors[0]
            return int(mon["width"]), int(mon["height"])
    except Exception:  # noqa: BLE001 — no display, no mss
        pass
    if shutil.which("xdotool") and os.environ.get("DISPLAY"):
        try:
            out = subprocess.run(
                ["xdotool", "getdisplaygeometry"], capture_output=True, text=True, timeout=5
            ).stdout.split()
            if len(out) == 2:
                return int(out[0]), int(out[1])
        except (OSError, ValueError, subprocess.TimeoutExpired):
            pass
    return 0, 0


class BlackScreen(RuntimeError):
    """The capture came back all black: on macOS the sign that Screen Recording is not
    granted to this process (or was granted after it started), on Linux of a compositor
    that hands out nothing. Raised instead of returning a black picture as if it were
    the screen."""


BLACK_SCREEN_HINT = (
    "the screenshot came back all black. On macOS, switch on nanoMuse Desktop (only that "
    "entry) in System Settings → Privacy & Security → Screen Recording, then quit and reopen "
    "the app: macOS applies that permission only to freshly started processes. On Linux, "
    "the hands need an X11 session (or XWayland)."
)


def _is_black(img: Any) -> bool:
    """True when nothing but black came back (every channel's maximum below 8)."""
    try:
        extrema = img.getextrema()
    except Exception:  # noqa: BLE001 — not a Pillow image we can read
        return False
    if isinstance(extrema[0], tuple):
        return all(hi < 8 for _lo, hi in extrema)
    return bool(extrema[1] < 8)


def take_screenshot(max_width: int = DEFAULT_MAX_WIDTH) -> Shot | None:
    """The main screen as JPEG (mss + Pillow) or PNG (a platform tool); None without a
    display or a way to take one. A capture that is all black raises :class:`BlackScreen`
    rather than passing for the screen."""
    try:
        import mss  # type: ignore[import-not-found]
        from PIL import Image

        with _mss_grabber(mss) as sct:
            mon = sct.monitors[1] if len(sct.monitors) > 1 else sct.monitors[0]
            grab = sct.grab(mon)
            img = Image.frombytes("RGB", grab.size, grab.bgra, "raw", "BGRX")
        if _is_black(img):
            raise BlackScreen(BLACK_SCREEN_HINT)
        width, height = img.size
        img = _fit(img, picture_size(width, height, max_width))
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=80)
        return Shot(buf.getvalue(), "image/jpeg", width, height, img.width, img.height)
    except BlackScreen:
        raise
    except Exception as exc:  # noqa: BLE001 — fall through to the platform tools
        logger.debug("mss screenshot not available: {}", exc)
    data = _platform_screenshot()
    if data is None:
        return None
    width, height = _png_size(data)
    try:
        from PIL import Image

        img = Image.open(io.BytesIO(data))
        if _is_black(img):
            raise BlackScreen(BLACK_SCREEN_HINT)
        width, height = img.size
        size = picture_size(width, height, max_width)
        if all(size) and size != (width, height):
            fitted = _fit(img.convert("RGB"), size)
            buf = io.BytesIO()
            fitted.save(buf, "JPEG", quality=80)
            return Shot(buf.getvalue(), "image/jpeg", width, height, fitted.width, fitted.height)
    except BlackScreen:
        raise
    except Exception:  # noqa: BLE001 — without Pillow the picture goes out as it is
        pass
    return Shot(data, "image/png", width, height, width, height)


def _fit(img: Any, size: tuple[int, int]) -> Any:
    """The picture at ``size`` (a smart-resize result), or itself when it already is."""
    if not all(size) or tuple(img.size) == size:
        return img
    from PIL import Image

    return img.resize(size, Image.Resampling.LANCZOS)


def _platform_screenshot() -> bytes | None:
    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / "screen.png"
        cmds: list[list[str]] = []
        if sys.platform == "darwin":
            cmds.append(["screencapture", "-x", "-t", "png", str(out)])
        elif os.name == "nt":
            ps = (
                "Add-Type -AssemblyName System.Windows.Forms,System.Drawing;"
                "$b=[System.Windows.Forms.Screen]::PrimaryScreen.Bounds;"
                "$bmp=New-Object System.Drawing.Bitmap $b.Width,$b.Height;"
                "$g=[System.Drawing.Graphics]::FromImage($bmp);"
                "$g.CopyFromScreen($b.Location,[System.Drawing.Point]::Empty,$b.Size);"
                f"$bmp.Save('{out}',[System.Drawing.Imaging.ImageFormat]::Png)"
            )
            cmds.append(["powershell", "-NoProfile", "-Command", ps])
        else:
            for tool, argv in (
                ("grim", ["grim", str(out)]),
                ("gnome-screenshot", ["gnome-screenshot", "-f", str(out)]),
                ("spectacle", ["spectacle", "-b", "-n", "-o", str(out)]),
                ("import", ["import", "-window", "root", str(out)]),
                ("scrot", ["scrot", str(out)]),
            ):
                if shutil.which(tool):
                    cmds.append(argv)
        for argv in cmds:
            try:
                subprocess.run(argv, capture_output=True, timeout=20, check=False)
            except (OSError, subprocess.TimeoutExpired):
                continue
            if out.exists() and out.stat().st_size > 0:
                return out.read_bytes()
    return None


def _png_size(data: bytes) -> tuple[int, int]:
    if len(data) >= 24 and data[:8] == b"\x89PNG\r\n\x1a\n":
        return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")
    return 0, 0


# ------------------------------------------------------------------ the window in front
_WINDOW_SUFFIX = re.compile(r"\s+[-—–]\s+([^-—–]+)$")


def mac_frontmost_pid() -> int | None:
    """The foreground process as seen by the window server, without sending Apple Events."""
    try:
        from AppKit import NSWorkspace  # type: ignore[import-not-found]

        app = NSWorkspace.sharedWorkspace().frontmostApplication()
        return int(app.processIdentifier()) if app is not None else None
    except Exception:  # noqa: BLE001 — an unidentified destination cannot receive keyboard input
        return None


def active_window() -> tuple[str, str]:
    """``(app, title)`` of the window in front: the program's name as well as it can be
    told from the platform, and the full title. Empty strings when unknown."""
    title = ""
    app = ""
    try:
        if sys.platform == "darwin":
            script = (
                'tell application "System Events" to set p to first application process '
                "whose frontmost is true\n"
                'set t to ""\n'
                "try\n"
                'tell application "System Events" to set t to name of front window of p\n'
                "end try\n"
                'return (name of p) & "\n" & t'
            )
            out = subprocess.run(
                ["osascript", "-e", script], capture_output=True, text=True, timeout=5
            ).stdout
            lines = out.split("\n")
            app = lines[0].strip() if lines else ""
            title = lines[1].strip() if len(lines) > 1 else ""
        elif os.name == "nt":
            app, title = _windows_active()
        elif shutil.which("xdotool") and os.environ.get("DISPLAY"):
            wid = subprocess.run(
                ["xdotool", "getactivewindow"], capture_output=True, text=True, timeout=5
            ).stdout.strip()
            if wid:
                title = subprocess.run(
                    ["xdotool", "getwindowname", wid], capture_output=True, text=True, timeout=5
                ).stdout.strip()
                cls = subprocess.run(
                    ["xprop", "-id", wid, "WM_CLASS"], capture_output=True, text=True, timeout=5
                ).stdout
                names = re.findall(r'"([^"]+)"', cls)
                app = names[-1] if names else ""
    except (OSError, subprocess.TimeoutExpired, ValueError):
        pass
    if not app and title:
        m = _WINDOW_SUFFIX.search(title)
        app = m.group(1).strip() if m else ""
    return app[:80], title[:160]


def _windows_active() -> tuple[str, str]:  # pragma: no cover - Windows only
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32  # type: ignore[attr-defined]
    hwnd = user32.GetForegroundWindow()
    length = user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buf, length + 1)
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    app = ""
    try:
        out = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid.value}", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout
        m = re.match(r'"([^"]+)"', out.strip())
        app = m.group(1).rsplit(".", 1)[0] if m else ""
    except (OSError, subprocess.TimeoutExpired):
        pass
    return app, buf.value


def capture(max_width: int = DEFAULT_MAX_WIDTH) -> dict[str, Any] | None:
    """One observation of this computer in the phone's ``screen`` shape (see
    :class:`~nanomuse.phone.screen.Screen`), or None when there is no picture."""
    shot = take_screenshot(max_width)
    if shot is None:
        return None
    app, title = active_window()
    return shot.to_raw(app=app, title=title)


__all__ = [
    "BLACK_SCREEN_HINT",
    "DEFAULT_MAX_WIDTH",
    "BlackScreen",
    "Shot",
    "active_window",
    "capture",
    "screen_size",
    "take_screenshot",
]

"""This computer's hands for the other devices: the actions the hub lets a phone or another
computer of the same account call here — ``info``, ``shell``, ``files``, ``file.get``,
``file.put``, ``open``, ``screen``, ``notify``. Each takes the frame's ``args`` and returns
a JSON-able dict; file bytes travel base64 in ``data``.

The contract (docs/hub.md) judges a command on the device that *asked*, before it is sent
— the phone's ShellGuard, another runtime's Sentinel — so nothing here asks again; the
switch that decides whether this computer takes calls at all is ``[hub] remote_control``
(:class:`nanomuse.hub.service.HubService`). Everything runs as the signed-in user. Ported
from the terminal edition's actions module (dropped in 0.1.39).
"""

from __future__ import annotations

import base64
import getpass
import mimetypes
import os
import platform
import shutil
import socket
import subprocess
import sys
import time
import webbrowser
from pathlib import Path
from typing import Any

from nanomuse import __version__
from nanomuse.computer.screen import BlackScreen, take_screenshot
from nanomuse.stdio import decode_output
from nanomuse.tools.base import number_arg
from nanomuse.tools.files import refuses_windows_path
from nanomuse.tools.shell import kill_tree, scrubbed_env

OUTPUT_LIMIT = 200_000
FILE_LIMIT = 8 * 1024 * 1024  # base64 inside one hub frame
SHELL_TIMEOUT_MAX = 900.0

# what this device announces in `hello`; `task`, `stop` and `approve` are the service's
ACTIONS = ("info", "shell", "files", "file.get", "file.put", "open", "screen", "notify")


class ActionError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def expand(path: str | None) -> Path:
    expanded = os.path.expandvars(os.path.expanduser(path or "~"))
    if path:
        # Check every component before resolve() can normalize the requested spelling.
        reason = refuses_windows_path(expanded)
        if reason:
            raise ActionError("bad_name", reason)
    return Path(expanded).resolve()


def shell_name() -> str:
    if os.name == "nt":
        return os.environ.get("COMSPEC", "cmd.exe")
    return os.environ.get("SHELL", "/bin/sh")


def info(extra_actions: tuple[str, ...] = (), *, operable: bool = True) -> dict[str, Any]:
    """What this computer says about itself to another device of the account. With remote
    control off (``operable=False``) it is the device's name, system and software only:
    the account name, the home directory, the working directory and the shell are what a
    caller would need to operate it, and the person here said no to that."""
    out: dict[str, Any] = {
        "name": socket.gethostname(),
        "kind": "computer",
        "os": platform.system(),
        "os_version": platform.release(),
        "arch": platform.machine(),
        "runtime": __version__,
        "actions": [*ACTIONS, *extra_actions] if operable else ["info"],
    }
    if operable:
        out.update(
            {
                "user": getpass.getuser(),
                "home": str(Path.home()),
                "cwd": os.getcwd(),
                "shell": shell_name(),
                "python": platform.python_version(),
            }
        )
    return out


def _text(b: bytes) -> str:
    # this computer's own console wrote it: 936 on a Chinese Windows, not UTF-8
    s = decode_output(b)
    if len(s) > OUTPUT_LIMIT:
        s = s[:OUTPUT_LIMIT] + f"\n… [{len(s) - OUTPUT_LIMIT} more characters not shown]"
    return s


def shell(command: str, cwd: str | None = None, timeout: Any = 120) -> dict[str, Any]:
    if not command or not command.strip():
        raise ActionError("usage", "a command is required")
    timeout = number_arg(timeout, 120, 1.0, SHELL_TIMEOUT_MAX)
    started = time.monotonic()
    timed_out = False
    try:
        proc = subprocess.Popen(
            command,
            shell=True,
            cwd=str(expand(cwd)) if cwd else None,
            env=scrubbed_env(),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=os.name != "nt",
        )
    except (OSError, ValueError) as exc:
        return {
            "exit_code": 127,
            "stdout": "",
            "stderr": str(exc),
            "timed_out": False,
            "duration_ms": 0,
        }
    try:
        out, err = proc.communicate(timeout=timeout)
        code = proc.returncode
    except subprocess.TimeoutExpired:
        timed_out = True
        kill_tree(proc)
        try:
            out, err = proc.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            out, err = b"", b""
        code = 124
    return {
        "exit_code": code,
        "stdout": _text(out),
        "stderr": _text(err),
        "timed_out": timed_out,
        "duration_ms": int((time.monotonic() - started) * 1000),
    }


def _entry(p: Path, st: os.stat_result) -> dict[str, Any]:
    kind = "link" if p.is_symlink() else "dir" if p.is_dir() else "file"
    return {"name": p.name, "type": kind, "size": st.st_size, "mtime": int(st.st_mtime)}


FILES_MAX = 2000


def files(path: str | None = None) -> dict[str, Any]:
    p = expand(path)
    if not p.exists():
        raise ActionError("not_found", f"{p} does not exist")
    if p.is_file():
        return {"path": str(p), "entries": [_entry(p, p.stat())]}
    entries: list[dict[str, Any]] = []
    try:
        children = sorted(p.iterdir(), key=lambda c: (not c.is_dir(), c.name.lower()))
    except PermissionError as exc:
        raise ActionError("forbidden", f"cannot read {p}") from exc
    for child in children:
        try:
            entry = _entry(child, child.lstat())
        except OSError:
            continue
        if len(entries) >= FILES_MAX:
            # Only an additional readable entry proves that the listing was capped.
            return {"path": str(p), "entries": entries, "truncated": True, "total": len(children)}
        entries.append(entry)
    return {"path": str(p), "entries": entries}


def file_get(path: str) -> dict[str, Any]:
    p = expand(path)
    if not p.is_file():
        raise ActionError("not_found", f"{p} is not a file")
    size = p.stat().st_size
    if size > FILE_LIMIT:
        raise ActionError(
            "too_large", f"{p.name} is {size} bytes; the limit over the hub is {FILE_LIMIT}"
        )
    return {
        "path": str(p),
        "name": p.name,
        "bytes": size,
        "mime": mimetypes.guess_type(p.name)[0] or "application/octet-stream",
        "data": base64.b64encode(p.read_bytes()).decode(),
    }


def file_put(path: str, data: str, force: bool = False) -> dict[str, Any]:
    p = expand(path)
    raw = base64.b64decode(data or "")
    if p.is_dir():
        raise ActionError("is_dir", f"{p} is a folder")
    if p.exists() and not force:
        raise ActionError("exists", f"{p} already exists; force replaces it")
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".nanomuse-part")
    tmp.write_bytes(raw)
    os.replace(tmp, p)
    return {"path": str(p), "bytes": len(raw)}


def open_target(url: str) -> dict[str, Any]:
    url = (url or "").strip()
    if not url:
        raise ActionError("usage", "a URL or a path is required")
    if "://" not in url:
        p = expand(url)
        if not p.exists():
            raise ActionError("not_found", f"{p} does not exist")
        url = p.as_uri()
    ok = False
    try:
        if sys.platform == "darwin":
            ok = subprocess.run(["open", url], capture_output=True, timeout=20).returncode == 0
        elif os.name == "nt":
            os.startfile(url)  # type: ignore[attr-defined]
            ok = True
        elif shutil.which("xdg-open"):
            ok = subprocess.run(["xdg-open", url], capture_output=True, timeout=20).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        ok = False
    if not ok:
        ok = webbrowser.open(url)
    return {"ok": bool(ok), "url": url}


def screen() -> dict[str, Any]:
    try:
        shot = take_screenshot()
    except BlackScreen as exc:
        raise ActionError("black_screen", str(exc)) from exc
    if shot is None:
        raise ActionError(
            "no_screen", "this computer cannot take a screenshot (no display, or no tool for it)"
        )
    return {
        "mime": shot.mime,
        "bytes": len(shot.data),
        "width": shot.width,
        "height": shot.height,
        "data": shot.base64,
    }


def notify(text: str, title: str = "nanoMuse") -> dict[str, Any]:
    text = (text or "").strip()
    if not text:
        raise ActionError("usage", "text is required")
    ok = False
    try:
        if sys.platform == "darwin":
            script = f'display notification "{_osa(text)}" with title "{_osa(title)}"'
            ok = (
                subprocess.run(
                    ["osascript", "-e", script], capture_output=True, timeout=20
                ).returncode
                == 0
            )
        elif os.name == "nt":
            ps = (
                "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, "
                "ContentType = WindowsRuntime] | Out-Null;"
                "$t=[Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent("
                "[Windows.UI.Notifications.ToastTemplateType]::ToastText02);"
                "$x=$t.GetElementsByTagName('text');"
                f"$x.Item(0).AppendChild($t.CreateTextNode('{_ps(title)}')) | Out-Null;"
                f"$x.Item(1).AppendChild($t.CreateTextNode('{_ps(text)}')) | Out-Null;"
                "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("
                "'nanoMuse').Show([Windows.UI.Notifications.ToastNotification]::new($t))"
            )
            ok = (
                subprocess.run(
                    ["powershell", "-NoProfile", "-Command", ps], capture_output=True, timeout=20
                ).returncode
                == 0
            )
        elif shutil.which("notify-send"):
            ok = (
                subprocess.run(
                    ["notify-send", "-a", "nanoMuse", title, text], capture_output=True, timeout=20
                ).returncode
                == 0
            )
    except (OSError, subprocess.TimeoutExpired):
        ok = False
    return {"ok": True, "shown": ok}


def _osa(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')[:400]


def _ps(s: str) -> str:
    return s.replace("'", "''")[:400]


def run(action: str, args: dict[str, Any]) -> dict[str, Any]:
    """Dispatch by the hub's action name (blocking; the service runs it in a thread)."""
    if action == "info":
        return info()
    if action == "shell":
        return shell(str(args.get("command", "")), args.get("cwd"), args.get("timeout"))
    if action == "files":
        return files(args.get("path"))
    if action == "file.get":
        return file_get(str(args.get("path", "")))
    if action == "file.put":
        return file_put(
            str(args.get("path", "")), str(args.get("data", "")), bool(args.get("force"))
        )
    if action == "open":
        return open_target(str(args.get("url", "")))
    if action == "screen":
        return screen()
    if action == "notify":
        return notify(str(args.get("text", "")), str(args.get("title") or "nanoMuse"))
    raise ActionError("unknown_action", f"this computer does not do '{action}'")


__all__ = [
    "ACTIONS",
    "FILE_LIMIT",
    "ActionError",
    "expand",
    "file_get",
    "file_put",
    "files",
    "info",
    "notify",
    "open_target",
    "run",
    "screen",
    "shell",
]

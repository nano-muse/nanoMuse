"""The user's other devices, through the hub: ``devices``, the ``device_*`` actions and
``delegate``.

These exist only while this computer is on the hub (signed in to nanoMuse Cloud, ``[hub]
enabled``). Each ``device_*`` tool is one hub action on one device (docs/hub.md): a command
in its shell, a folder listing, a file each way, a URL, its screen, a notification.
``delegate`` hands a whole task, in words, to the Muse running on that device and waits for
its answer — the job runs there, in a side chat the person can see on that device, and
whenever *that* Muse needs an approval the card shows up here, in this chat.

Risk is judged on this side, before anything is sent: a command for another device is
assessed like one for this one (``shell``'s danger patterns, the program name as the
target of a standing approval); replacing a file is destructive; opening a URL or sending
a notification is moderate; looking and listing are safe but read private data.
"""

from __future__ import annotations

import asyncio
import base64
import json
import re
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import ConfigDict

from nanomuse.hub import actions
from nanomuse.hub.client import HubError
from nanomuse.schema import RiskLevel, ToolResult
from nanomuse.tools.base import BaseTool, CallAssessment, int_arg
from nanomuse.tools.shell import _DANGEROUS, programs_of
from nanomuse.ui import ApprovalRequest

if TYPE_CHECKING:
    from nanomuse.hub.service import HubService

_DEVICE_PARAM = {
    "device": {
        "type": "string",
        "description": "the device's name as `devices` lists it (or 'phone' / 'pc')",
    }
}
_RISKS = {
    "safe": RiskLevel.SAFE,
    "low": RiskLevel.MODERATE,
    "moderate": RiskLevel.MODERATE,
    "sensitive": RiskLevel.SENSITIVE,
}


def _json(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, default=str)


class _DeviceTool(BaseTool):
    """Shared: the hub, the device lookup, the error shapes."""

    model_config = ConfigDict(arbitrary_types_allowed=True)
    hub: Any  # HubService; typed loosely to keep pydantic out of the service

    def _device(self, query: str) -> dict[str, Any]:
        hub: HubService = self.hub
        d = hub.find(str(query or ""))
        if d is None:
            names = ", ".join(
                f"{x.get('name')} ({'online' if x.get('online') else 'offline'})"
                for x in hub.others()
            )
            raise HubError(
                "no_device", f"no device matches '{query}'" + (f"; known: {names}" if names else "")
            )
        if not d.get("online"):
            raise HubError("device_offline", f"{d.get('name')} is offline right now")
        return d

    @staticmethod
    def _device_name(args: dict[str, Any]) -> str:
        return str(args.get("device") or "?")[:40]

    async def _call(
        self, device: dict[str, Any], action: str, args: dict[str, Any], timeout: float = 120
    ) -> dict[str, Any]:
        hub: HubService = self.hub
        return await hub.call(str(device["id"]), action, args, timeout=timeout)

    async def execute(self, **kwargs: Any) -> ToolResult:
        try:
            return await self._run(**kwargs)
        except HubError as exc:
            return ToolResult.fail(f"{exc.message} ({exc.code})")
        except actions.ActionError as exc:
            return ToolResult.fail(f"{exc.message} ({exc.code})")

    async def _run(self, **kwargs: Any) -> ToolResult:  # pragma: no cover - overridden
        raise NotImplementedError


class Devices(_DeviceTool):
    name: str = "devices"
    description: str = (
        "The user's other devices on the nanoMuse hub (phone, other computers) and whether "
        "each is online. Use a device's name as listed here in the device_* tools and delegate."
    )
    parameters: dict[str, Any] = {"type": "object", "properties": {}}
    risk: RiskLevel = RiskLevel.SAFE

    async def _run(self, **_: Any) -> ToolResult:
        hub: HubService = self.hub
        others = [
            {k: d.get(k) for k in ("name", "kind", "os", "online", "actions")} for d in hub.others()
        ]
        if not hub.client or not hub.client.connected.is_set():
            return ToolResult.fail(
                "not connected to the hub"
                + ("" if hub.signed_in else "; the user can sign in under Settings → Devices")
            )
        return ToolResult(output=_json({"this": hub.device_name, "devices": others}))


class DeviceShell(_DeviceTool):
    name: str = "device_shell"
    description: str = (
        "Run a shell command on another device. On a phone it runs inside the nanoMuse app's "
        "Linux sandbox (Alpine), not on Android itself; the phone's own apps are reached with "
        "`delegate`. Returns stdout, stderr and the exit code."
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            **_DEVICE_PARAM,
            "command": {"type": "string"},
            "cwd": {"type": "string", "description": "working folder on that device"},
            "timeout": {"type": "integer", "description": "seconds, default 120"},
        },
        "required": ["device", "command"],
    }
    risk: RiskLevel = RiskLevel.SENSITIVE

    def assess(self, args: dict[str, Any]) -> CallAssessment:
        command = str(args.get("command") or "")
        warnings = [label for pattern, label in _DANGEROUS if pattern.search(command)]
        return CallAssessment(
            risk=RiskLevel.SENSITIVE,
            egress=True,
            egress_target=None,
            target=programs_of(command),
            summary=f"on {self._device_name(args)}: {command[:160]}",
            warnings=[f"command looks dangerous: {w}" for w in warnings],
        )

    async def _run(
        self,
        device: str = "",
        command: str = "",
        cwd: str | None = None,
        timeout: int = 120,
        **_: Any,
    ) -> ToolResult:
        if not command.strip():
            return ToolResult.fail("empty command")
        d = self._device(device)
        secs = int_arg(timeout, 120, 1, 900)
        r = await self._call(
            d, "shell", {"command": command, "cwd": cwd, "timeout": secs}, timeout=secs + 30
        )
        out = str(r.get("stdout") or "")
        err = str(r.get("stderr") or "")
        code = r.get("exit_code")
        text = out
        if err:
            text += ("\n" if text else "") + "[stderr]\n" + err
        text = f"[{d['name']}] exit {code}" + ("\n" + text if text else " (no output)")
        if code not in (0, None):
            return ToolResult(output=text, error=f"exit code {code}")
        return ToolResult(output=text)


class DeviceFiles(_DeviceTool):
    name: str = "device_files"
    description: str = "List a folder on another device (default: its home / downloads folder)."
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {**_DEVICE_PARAM, "path": {"type": "string"}},
        "required": ["device"],
    }
    # Reading another device's folders is the person's private data leaving that device:
    # it stops for approval — once, for this conversation, or always for that device, as
    # they choose — rather than running quietly.
    risk: RiskLevel = RiskLevel.SENSITIVE
    reads_private_data: bool = True

    def assess(self, args: dict[str, Any]) -> CallAssessment:
        return CallAssessment(
            risk=RiskLevel.SENSITIVE,
            reads_private_data=True,
            target=self._device_name(args),
            summary=f"list {args.get('path') or 'home'} on {self._device_name(args)}",
        )

    async def _run(self, device: str = "", path: str | None = None, **_: Any) -> ToolResult:
        d = self._device(device)
        r = await self._call(d, "files", {"path": path} if path else {})
        entries: list[Any] = r["entries"] if isinstance(r.get("entries"), list) else []
        lines = [f"{r.get('path') or path or '~'} on {d['name']} ({len(entries)} entries)"]
        for e in entries[:400]:
            if not isinstance(e, dict):
                continue
            is_dir = e.get("type") == "dir"
            mark = "/" if is_dir else ""
            size = "" if is_dir else f"  {e.get('size', '')}"
            lines.append(f"  {e.get('name')}{mark}{size}")
        if len(entries) > 400:
            lines.append(f"  … {len(entries) - 400} more")
        return ToolResult(output="\n".join(lines))


class DeviceGet(_DeviceTool):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    name: str = "device_get"
    description: str = (
        "Copy a file from another device into this computer's workspace (folder `from-devices/`). "
        "Up to 8 MB. Pictures come back so you can look at them."
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {**_DEVICE_PARAM, "path": {"type": "string", "description": "path there"}},
        "required": ["device", "path"],
    }
    risk: RiskLevel = RiskLevel.SENSITIVE  # as device_files: a file of theirs leaves that device
    reads_private_data: bool = True
    workspace: Path

    def assess(self, args: dict[str, Any]) -> CallAssessment:
        return CallAssessment(
            risk=RiskLevel.SENSITIVE,
            reads_private_data=True,
            target=self._device_name(args),
            summary=f"fetch {args.get('path')} from {self._device_name(args)}",
        )

    async def _run(self, device: str = "", path: str = "", **_: Any) -> ToolResult:
        d = self._device(device)
        r = await self._call(d, "file.get", {"path": path}, timeout=300)
        name = re.sub(r"[/\\]", "_", str(r.get("name") or Path(path).name or "file"))
        folder = self.workspace / "from-devices" / _slug(str(d["name"]))
        folder.mkdir(parents=True, exist_ok=True)
        dest = folder / name
        i = 1
        while dest.exists():
            dest = folder / f"{Path(name).stem}-{i}{Path(name).suffix}"
            i += 1
        try:
            dest.write_bytes(base64.b64decode(str(r.get("data") or "")))
        except (ValueError, OSError) as exc:
            return ToolResult.fail(f"could not save {name}: {exc}")
        mime = str(r.get("mime") or "")
        rel = dest.relative_to(self.workspace).as_posix()
        return ToolResult(
            output=_json({"device": d["name"], "saved_to": rel, "bytes": r.get("bytes")}),
            images=[str(dest)] if mime.startswith("image/") else None,
        )


class DevicePut(_DeviceTool):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    name: str = "device_put"
    description: str = (
        "Copy a file from this computer's workspace to another device. Up to 8 MB; an existing "
        "file there is left alone unless force=true."
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            **_DEVICE_PARAM,
            "local_path": {"type": "string", "description": "path in the workspace"},
            "remote_path": {"type": "string", "description": "where to put it on that device"},
            "force": {"type": "boolean", "description": "replace a file that exists there"},
        },
        "required": ["device", "local_path", "remote_path"],
    }
    risk: RiskLevel = RiskLevel.MODERATE
    workspace: Path

    def assess(self, args: dict[str, Any]) -> CallAssessment:
        force = bool(args.get("force"))
        return CallAssessment(
            risk=RiskLevel.SENSITIVE if force else RiskLevel.MODERATE,
            egress=True,
            egress_target=None,
            target=self._device_name(args),
            summary=f"{'replace' if force else 'copy to'} {args.get('remote_path')} "
            f"on {self._device_name(args)} (from {args.get('local_path')})",
            warnings=["replaces a file on that device"] if force else [],
        )

    async def _run(
        self,
        device: str = "",
        local_path: str = "",
        remote_path: str = "",
        force: bool = False,
        **_: Any,
    ) -> ToolResult:
        d = self._device(device)
        local = (self.workspace / local_path).resolve()
        try:
            local.relative_to(self.workspace.resolve())
        except ValueError:
            return ToolResult.fail("local_path must be inside the workspace")
        if not local.is_file():
            return ToolResult.fail(f"{local_path} is not a file in the workspace")
        if local.stat().st_size > actions.FILE_LIMIT:
            return ToolResult.fail(f"{local.name} is over the {actions.FILE_LIMIT}-byte limit")
        data = base64.b64encode(local.read_bytes()).decode()
        r = await self._call(
            d,
            "file.put",
            {"path": remote_path, "data": data, "force": bool(force)},
            timeout=300,
        )
        return ToolResult(output=_json({"device": d["name"], **r}))


class DeviceOpen(_DeviceTool):
    name: str = "device_open"
    description: str = "Open a URL, file or folder on another device with its default app."
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {**_DEVICE_PARAM, "url": {"type": "string"}},
        "required": ["device", "url"],
    }
    risk: RiskLevel = RiskLevel.MODERATE

    def assess(self, args: dict[str, Any]) -> CallAssessment:
        return CallAssessment(
            risk=RiskLevel.MODERATE,
            target=self._device_name(args),
            summary=f"open {str(args.get('url') or '')[:120]} on {self._device_name(args)}",
        )

    async def _run(self, device: str = "", url: str = "", **_: Any) -> ToolResult:
        d = self._device(device)
        r = await self._call(d, "open", {"url": url})
        return ToolResult(output=_json({"device": d["name"], **r}))


class DeviceScreen(_DeviceTool):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    name: str = "device_screen"
    description: str = (
        "Look at another device's screen: a picture comes back to you. On a phone this is what "
        "is on the phone's screen right now."
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": _DEVICE_PARAM,
        "required": ["device"],
    }
    risk: RiskLevel = RiskLevel.SAFE
    reads_private_data: bool = True
    workspace: Path

    def assess(self, args: dict[str, Any]) -> CallAssessment:
        return CallAssessment(
            risk=RiskLevel.SAFE,
            reads_private_data=True,
            summary=f"look at {self._device_name(args)}'s screen",
        )

    async def _run(self, device: str = "", **_: Any) -> ToolResult:
        d = self._device(device)
        r = await self._call(d, "screen", {}, timeout=60)
        data = str(r.get("data") or "")
        if not data:
            return ToolResult.fail(f"{d['name']} sent no picture")
        mime = str(r.get("mime") or "image/jpeg")
        ext = "png" if "png" in mime else "jpg"
        folder = self.workspace / "screenshots"
        folder.mkdir(parents=True, exist_ok=True)
        try:
            picture = base64.b64decode(data)
        except (ValueError, OSError) as exc:
            return ToolResult.fail(f"could not save the picture: {exc}")
        # two looks inside one second (look, act, then look again to check) are two
        # pictures: the second takes the next free name, not the first one's file
        stem = f"{_slug(str(d['name']))}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
        dest = folder / f"{stem}.{ext}"
        n = 2
        while dest.exists():
            dest = folder / f"{stem}-{n}.{ext}"
            n += 1
        try:
            dest.write_bytes(picture)
        except OSError as exc:
            return ToolResult.fail(f"could not save the picture: {exc}")
        size = f"{r.get('width')}×{r.get('height')}" if r.get("width") else ""
        return ToolResult(
            output=f"{d['name']}'s screen{' (' + size + ')' if size else ''}: "
            f"{dest.relative_to(self.workspace).as_posix()}",
            images=[str(dest)],
        )


class DeviceNotify(_DeviceTool):
    name: str = "device_notify"
    description: str = "Show a notification on another device."
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            **_DEVICE_PARAM,
            "text": {"type": "string"},
            "title": {"type": "string"},
        },
        "required": ["device", "text"],
    }
    risk: RiskLevel = RiskLevel.MODERATE

    def assess(self, args: dict[str, Any]) -> CallAssessment:
        return CallAssessment(
            risk=RiskLevel.MODERATE,
            target=self._device_name(args),
            summary=f"notify {self._device_name(args)}: {str(args.get('text') or '')[:80]}",
        )

    async def _run(
        self, device: str = "", text: str = "", title: str = "nanoMuse", **_: Any
    ) -> ToolResult:
        d = self._device(device)
        r = await self._call(d, "notify", {"text": text, "title": title or "nanoMuse"})
        return ToolResult(output=_json({"device": d["name"], **r}))


class Delegate(_DeviceTool):
    """A whole task for the Muse on another device; its approvals are asked here."""

    model_config = ConfigDict(arbitrary_types_allowed=True)
    name: str = "delegate"
    description: str = (
        "Hand a whole task, in plain words, to the Muse running on another device and wait for "
        "its answer (up to ten minutes). Use it when the job needs that device's apps, screen, "
        "files or context: 'open the calendar and tell me tomorrow's first meeting' on the "
        "phone, 'find the PDF I downloaded yesterday and send it here'. Give every detail it "
        "needs; pass its answer on faithfully."
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {**_DEVICE_PARAM, "task": {"type": "string"}},
        "required": ["device", "task"],
    }
    risk: RiskLevel = RiskLevel.MODERATE
    ui: Any  # the UI protocol instance (approval cards are asked here)
    workspace: Path

    def assess(self, args: dict[str, Any]) -> CallAssessment:
        return CallAssessment(
            risk=RiskLevel.MODERATE,
            target=self._device_name(args),
            summary=f"ask {self._device_name(args)}: {str(args.get('task') or '')[:120]}",
        )

    async def _run(self, device: str = "", task: str = "", **_: Any) -> ToolResult:
        task = task.strip()
        if not task:
            return ToolResult.fail("task is required")
        d = self._device(device)
        hub: HubService = self.hub
        name = str(d["name"])
        notes: list[str] = []
        images: list[str] = []
        pending: set[asyncio.Task[None]] = set()

        async def approve(body: dict[str, Any]) -> None:
            approval_id = str(body.get("approval_id") or "")
            reason = str(body.get("reason") or "")
            decision = await self.ui.ask_approval(
                ApprovalRequest(
                    tool="delegate",
                    args={"device": name, "preview": body.get("preview", "")},
                    summary=f"on {name}: {body.get('preview', '')}",
                    risk=_RISKS.get(str(body.get("risk") or ""), RiskLevel.MODERATE),
                    reasons=[reason] if reason else [],
                    warnings=[f"{name} asks whether it may do this"],
                    purpose=task[:200],
                    target=name,
                    grant_key=f"delegate:{name}",
                    grant_options=["once"],
                )
            )
            try:
                await hub.call(
                    str(d["id"]),
                    "approve",
                    {"approval_id": approval_id, "allow": decision.approved},
                    timeout=30,
                )
            except HubError as exc:
                notes.append(f"(could not answer {name}'s approval: {exc.message})")

        async def on_event(body: dict[str, Any]) -> None:
            stage = body.get("stage")
            if stage == "approval":
                t = asyncio.create_task(approve(body))
                pending.add(t)
                t.add_done_callback(pending.discard)
            elif stage == "image" and body.get("data"):
                path = self._save_image(name, body)
                if path:
                    images.append(str(path))
            elif stage == "tool":
                notes.append(f"{name} used {body.get('name')}: {body.get('summary') or ''}".strip())
            elif stage == "error":
                notes.append(f"{name}: {body.get('message') or 'error'}")

        try:
            r = await hub.call(
                str(d["id"]),
                "task",
                {"text": task, "from": hub.device_name},
                timeout=600,
                on_event=on_event,
            )
        finally:
            for t in pending:
                t.cancel()
        answer = str(r.get("text") or r.get("answer") or "").strip()
        out: dict[str, Any] = {"device": name, "answer": answer or "(no answer)"}
        if notes:
            out["steps"] = notes[-12:]
        return ToolResult(output=_json(out), images=images or None)

    def _save_image(self, name: str, body: dict[str, Any]) -> Path | None:
        mime = str(body.get("mime") or "image/jpeg")
        ext = "png" if "png" in mime else "jpg"
        folder = self.workspace / "from-devices" / _slug(name)
        folder.mkdir(parents=True, exist_ok=True)
        dest = folder / f"{datetime.now().strftime('%Y%m%d-%H%M%S-%f')}.{ext}"
        try:
            dest.write_bytes(base64.b64decode(str(body.get("data") or "")))
        except (ValueError, OSError):
            return None
        return dest


def _slug(name: str) -> str:
    return re.sub(r"[^\w.-]+", "_", name).strip("_")[:40] or "device"


def device_tools(hub: HubService, ui: Any, workspace: Path) -> list[BaseTool]:
    return [
        Devices(hub=hub),
        DeviceShell(hub=hub),
        DeviceFiles(hub=hub),
        DeviceGet(hub=hub, workspace=workspace),
        DevicePut(hub=hub, workspace=workspace),
        DeviceOpen(hub=hub),
        DeviceScreen(hub=hub, workspace=workspace),
        DeviceNotify(hub=hub),
        Delegate(hub=hub, ui=ui, workspace=workspace),
    ]


DEVICE_TOOL_NAMES = (
    "devices",
    "device_shell",
    "device_files",
    "device_get",
    "device_put",
    "device_open",
    "device_screen",
    "device_notify",
    "delegate",
)

__all__ = [
    "DEVICE_TOOL_NAMES",
    "Delegate",
    "DeviceFiles",
    "DeviceGet",
    "DeviceNotify",
    "DeviceOpen",
    "DevicePut",
    "DeviceScreen",
    "DeviceShell",
    "Devices",
    "device_tools",
]

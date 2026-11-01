"""Workspace file operations (read / write / append / list / search).

Paths are resolved inside the agent workspace. Reading outside of it is allowed
only for explicitly configured extra roots and is treated as *private data*.
"""

from __future__ import annotations

import asyncio
import fnmatch
import os
from pathlib import Path, PureWindowsPath
from typing import Any

from nanomuse.schema import RiskLevel, ToolResult
from nanomuse.stdio import decode_output
from nanomuse.tools.base import BaseTool, CallAssessment, short_json

MAX_READ_CHARS = 60_000
# a character takes at most four bytes (UTF-8) and two (UTF-16), so this many bytes always
# hold as many characters as a report keeps: the cut lands between characters, not inside one
_BYTES_PER_CHAR = 4


def read_capped_text(path: Path, limit: int) -> str:
    """The first ``limit`` characters of a file, read the way the shell tool reads a command's
    output: a byte-order mark decides, then UTF-8, then the console's code page.

    A file often is a command's output: ``dir > out.txt`` on PowerShell 5 writes UTF-16LE,
    ``reg export`` too, and a redirect on a Chinese console writes code page 936. Read as
    UTF-8, all three reached the model as NULs and replacement characters.
    """
    window = limit * _BYTES_PER_CHAR + 4
    with path.open("rb") as fh:
        data = fh.read(window)
    if len(data) == window:
        data = whole_utf8(data)
    return decode_output(data)


def whole_utf8(data: bytes) -> bytes:
    """``data`` without a UTF-8 sequence a cut left unfinished at its end: a lead byte of a
    two-, three- or four-byte character followed by fewer continuation bytes than it needs.

    Without this, a UTF-8 file longer than the window stopped being UTF-8 to the strict first
    read, and a console code page that accepts any byte (cp1252) read the whole file as
    mojibake. A cut through anything else (ASCII, UTF-16, a code page) is left as it is.
    """
    for back in range(1, 4):
        if back > len(data):
            return data
        byte = data[-back]
        if 0x80 <= byte <= 0xBF:  # a continuation byte: the lead is further back
            continue
        if 0xC2 <= byte <= 0xF4:  # a lead byte: whole only if its continuation bytes all follow
            need = 2 if byte < 0xE0 else 3 if byte < 0xF0 else 4
            return data[:-back] if need > back else data
        return data  # ASCII, or a byte UTF-8 never uses: not a cut character
    return data


def unescape_flat(content: str) -> tuple[str, bool]:
    """Turn a one-line text full of literal ``\\n`` into lines.

    Small models double-escape newlines in JSON arguments, so a three-day itinerary
    arrives as one line with ``\\n`` between the days. Only text that has *no* real
    newline and at least two escaped ones is touched — code has real newlines, and a
    one-liner that genuinely contains ``\\n`` twice is not something people write.
    """
    if "\n" in content or content.count("\\n") < 2:
        return content, False
    return content.replace("\\r\\n", "\n").replace("\\n", "\n").replace("\\t", "\t"), True


def pdf_text(path: Path, max_pages: int = 60) -> str:
    """The text of a PDF, page by page — what the model reads when the user attaches one.
    Scanned PDFs have no text layer; the result says so instead of coming back empty."""
    from pypdf import PdfReader

    try:
        reader = PdfReader(str(path))
        if reader.is_encrypted:
            try:
                reader.decrypt("")
            except Exception:  # noqa: BLE001
                return "(this PDF is encrypted; the text cannot be read without its password)"
        pages = len(reader.pages)
    except Exception as exc:  # noqa: BLE001 — a damaged file is a result, not a crash
        return f"(this PDF could not be read: {type(exc).__name__}: {str(exc)[:200]})"
    parts: list[str] = []
    for i, page in enumerate(reader.pages[:max_pages], start=1):
        try:
            content = (page.extract_text() or "").strip()
        except Exception as exc:  # noqa: BLE001
            content = f"(page could not be read: {exc})"
        parts.append(f"--- page {i} of {pages} ---\n{content}")
    if pages > max_pages:
        parts.append(f"... [{pages - max_pages} more pages not shown]")
    text = "\n\n".join(parts)
    if not any(p.split("---\n", 1)[-1].strip() for p in parts):
        return (
            f"(this PDF has {pages} page{'s' if pages != 1 else ''} but no text layer; it is "
            "probably scanned images; the text cannot be extracted here)"
        )
    return text


# an unbounded `search` over a home directory would walk for minutes; this is plenty
SEARCH_MAX_ENTRIES = 50_000
# how many a report carries before it stops: a listing of a build folder is thousands of
# lines the model cannot use, and a cut list it believes is whole is worse than a short one
LIST_MAX = 500
SEARCH_MAX_MATCHES = 200


_WIN_DEVICE_NAMES = frozenset(
    [
        "CON",
        "PRN",
        "AUX",
        "NUL",
        "CONIN$",
        "CONOUT$",
        *(f"COM{i}" for i in range(1, 10)),
        *(f"LPT{i}" for i in range(1, 10)),
        *(f"COM{i}" for i in "¹²³"),
        *(f"LPT{i}" for i in "¹²³"),
    ]
)


def windows_rejects(name: str) -> str | None:
    """Why a path component is a device or would be normalized by Windows.

    Win32 reserves device names with extensions too, such as ``NUL.txt``. Refuse them
    consistently across supported Windows versions, along with trailing dots and spaces.
    """
    if name in (".", ".."):
        return None
    upper = name.split(".", 1)[0].rstrip(" ").upper()
    if upper in _WIN_DEVICE_NAMES:
        return f"'{name}' is a Windows device name: the write would reach the device, and no file would appear"
    stripped = name.rstrip(". ")
    if stripped != name:
        return f"'{name}' ends in a dot or a space, which Windows drops: the file would land as '{stripped}'"
    return None


ON_WINDOWS = os.name == "nt"


def refuses_windows_path(path: str) -> str | None:
    """Check all components before normalization, only on Windows.

    PureWindowsPath also lets the same validation tests run on other platforms without
    changing os.name or constructing a filesystem-bound WindowsPath.
    """
    if not ON_WINDOWS:
        return None
    if path.replace("/", "\\").startswith("\\\\.\\"):
        return "Windows device paths are not workspace files"
    parsed = PureWindowsPath(path)
    for part in parsed.parts:
        if part == parsed.anchor:
            continue
        reason = windows_rejects(part)
        if reason:
            return reason
    return None


def shown_path(path: Path, workspace: Path) -> str:
    """``path`` as the report names it: relative to the workspace when it is inside it, the
    absolute path otherwise. An extra root on another drive has no relative form on Windows
    (``os.path.relpath`` raises "path is on mount 'D:', start on mount 'C:'"), and by the
    time the name is written the file is already on disk."""
    try:
        return os.path.relpath(path, workspace)
    except ValueError:
        return str(path)


class Files(BaseTool):
    name: str = "files"
    description: str = (
        "Work with files in the workspace. Actions: "
        "`read` (path; PDFs come back as text, page by page), `write` (path, content; overwrites), `append` (path, content), "
        "`list` (path, optional), `search` (pattern glob such as '**/*.md'). "
        "Paths are relative to the workspace unless they start with '/' or '~'."
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["read", "write", "append", "list", "search"]},
            "path": {"type": "string", "description": "File or directory path."},
            "content": {"type": "string", "description": "Content for write/append."},
            "pattern": {"type": "string", "description": "Glob pattern for search."},
        },
        "required": ["action"],
    }
    risk: RiskLevel = RiskLevel.SAFE

    workspace: Path
    extra_roots: list[Path] = []

    # ------------------------------------------------------------------ helpers
    def _resolve(self, path: str | None, must_exist: bool = False) -> Path:
        raw = path or "."
        # Validate before strip() or resolve() can erase the spelling that was requested.
        for spelling in (raw, raw.strip()):
            reason = refuses_windows_path(os.path.expanduser(spelling))
            if reason:
                raise OSError(reason)
        raw = raw.strip()
        candidate = Path(os.path.expanduser(raw))
        if not candidate.is_absolute():
            candidate = self.workspace / candidate
        resolved = candidate.resolve()
        roots = [self.workspace.resolve(), *[r.resolve() for r in self.extra_roots]]
        if not any(resolved == r or r in resolved.parents for r in roots):
            raise PermissionError(
                f"path '{raw}' is outside the workspace ({self.workspace}). "
                "Ask the user to add it to agent.extra_roots if access is really needed."
            )
        if must_exist and not resolved.exists():
            raise FileNotFoundError(f"'{raw}' does not exist")
        return resolved

    def _inside_workspace(self, path: Path) -> bool:
        ws = self.workspace.resolve()
        return path == ws or ws in path.parents

    def assess(self, args: dict[str, Any]) -> CallAssessment:
        action = args.get("action", "")
        path = args.get("path") or "."
        summary = (
            f"files.{action} {path}"
            if action != "search"
            else f"files.search {args.get('pattern', '')}"
        )
        try:
            resolved = self._resolve(path)
            inside = self._inside_workspace(resolved)
        except Exception:  # noqa: BLE001 - reported at execution time
            inside = False  # a path that cannot be resolved does not get the workspace's trust
        if action in ("write", "append"):
            risk = RiskLevel.MODERATE if inside else RiskLevel.SENSITIVE
            return CallAssessment(
                risk=risk, summary=summary + f" ({len(args.get('content') or '')} chars)"
            )
        # reads
        return CallAssessment(
            risk=RiskLevel.SAFE if inside else RiskLevel.MODERATE,
            reads_private_data=not inside,
            summary=summary,
        )

    # ------------------------------------------------------------------ execution
    async def execute(
        self,
        action: str = "",
        path: str | None = None,
        content: str | None = None,
        pattern: str | None = None,
        **_: Any,
    ) -> ToolResult:
        try:
            if action == "read":
                target = self._resolve(path, must_exist=True)
                if target.is_dir():
                    return await self.execute(action="list", path=path)
                if target.suffix.lower() == ".pdf":
                    # pypdf on a long document takes seconds: off the event loop, so the
                    # web app and the hub keep answering meanwhile
                    text = await asyncio.to_thread(pdf_text, target)
                    if len(text) > MAX_READ_CHARS:
                        text = text[:MAX_READ_CHARS] + f"\n... [truncated, {len(text)} chars total]"
                    return ToolResult(output=text or "(empty file)")
                # read what fits and one more character, not the whole file: a log of a few
                # hundred MB is truncated either way, and need not be loaded for it
                text = read_capped_text(target, MAX_READ_CHARS + 1)
                if len(text) > MAX_READ_CHARS:
                    size = target.stat().st_size
                    text = text[:MAX_READ_CHARS] + f"\n... [truncated, {size} bytes total]"
                return ToolResult(output=text or "(empty file)")
            if action in ("write", "append"):
                if content is None:
                    return ToolResult.fail("`content` is required")
                content, fixed = unescape_flat(content)
                target = self._resolve(path)
                target.parent.mkdir(parents=True, exist_ok=True)
                # the lines the model wrote are the lines the file gets: text mode on Windows
                # turned each "\n" into "\r\n", so a script or a config written for a Unix tool
                # arrived with carriage returns, and a read of it was not what was written
                with target.open(
                    "a" if action == "append" else "w", encoding="utf-8", newline=""
                ) as fh:
                    fh.write(content)
                rel = shown_path(target, self.workspace)
                note = " (the content had escaped newlines; written as lines)" if fixed else ""
                return ToolResult(
                    output=f"{'Appended' if action == 'append' else 'Wrote'} {len(content)} chars "
                    f"to {rel}{note}"
                )
            if action == "list":
                target = self._resolve(path, must_exist=True)
                if target.is_file():
                    return ToolResult(output=f"{target.name} ({target.stat().st_size} bytes)")
                entries = sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
                lines = [f"{'[dir] ' if p.is_dir() else ''}{p.name}" for p in entries[:LIST_MAX]]
                if len(entries) > LIST_MAX:
                    # the model reads the list as the whole folder unless it says otherwise
                    lines.append(
                        f"... [{len(entries)} entries in all; the first {LIST_MAX} are listed]"
                    )
                return ToolResult(output="\n".join(lines) or "(empty directory)")
            if action == "search":
                if not pattern:
                    return ToolResult.fail("`pattern` is required")
                root = self._resolve(path)
                # matches are named relative to the workspace when the root is in it, and
                # as absolute paths under an extra root (relative_to raised there before)
                ws = self.workspace.resolve()
                in_ws = root == ws or ws in root.parents
                glob = str(pattern)

                def _walk() -> tuple[list[str], str]:
                    # a walk of tens of thousands of entries stays off the event loop
                    matches: list[str] = []
                    scanned = 0
                    for p in root.rglob("*"):
                        scanned += 1
                        if p.is_file() and fnmatch.fnmatch(p.relative_to(root).as_posix(), glob):
                            matches.append(p.relative_to(ws).as_posix() if in_ws else str(p))
                        if len(matches) >= SEARCH_MAX_MATCHES:
                            # a cut list it reads as whole is worse than a short, honest one
                            return matches, (
                                f"\n(stopped at {SEARCH_MAX_MATCHES} matches; "
                                "narrow the pattern or the `path`)"
                            )
                        if scanned >= SEARCH_MAX_ENTRIES:
                            return matches, (
                                f"\n(stopped after {SEARCH_MAX_ENTRIES} entries; "
                                "search a narrower `path`)"
                            )
                    return matches, ""

                matches, note = await asyncio.to_thread(_walk)
                return ToolResult(output=("\n".join(matches) or "(no matches)") + note)
            return ToolResult.fail(f"unknown action '{action}'; use read/write/append/list/search")
        except (PermissionError, FileNotFoundError, IsADirectoryError, OSError) as exc:
            return ToolResult.fail(str(exc))

    def __repr__(self) -> str:  # pragma: no cover
        return f"Files({short_json({'workspace': str(self.workspace)})})"


__all__ = ["Files"]

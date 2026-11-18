"""Workspace file operations (read / write / append / list / search).

Paths are resolved inside the agent workspace. Reading outside of it is allowed
only for explicitly configured extra roots and is treated as *private data*.
"""

from __future__ import annotations

import asyncio
import fnmatch
import os
from pathlib import Path
from typing import Any, BinaryIO, cast

from nanomuse.schema import RiskLevel, ToolResult
from nanomuse.tools.base import BaseTool, CallAssessment, short_json
from nanomuse.workspaces import open_file

MAX_READ_CHARS = 60_000


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


def pdf_text(path: Path | BinaryIO, max_pages: int = 60) -> str:
    """The text of a PDF, page by page — what the model reads when the user attaches one.
    Scanned PDFs have no text layer; the result says so instead of coming back empty."""
    from pypdf import PdfReader

    try:
        reader = PdfReader(str(path) if isinstance(path, Path) else path)
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


class Files(BaseTool):
    name: str = "files"
    description: str = (
        "Work with files in the workspace. Actions: "
        "`read` (path; PDFs come back as text, page by page), `write` (path, content – overwrites), `append` (path, content), "
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
    denied_roots: list[Path] = []

    # ------------------------------------------------------------------ helpers
    def _resolve(self, path: str | None, must_exist: bool = False) -> Path:
        raw = (path or ".").strip()
        candidate = Path(os.path.expanduser(raw))
        if not candidate.is_absolute():
            candidate = self.workspace / candidate
        resolved = candidate.resolve()
        if any(resolved.is_relative_to(root.resolve()) for root in self.denied_roots):
            raise PermissionError("This path is not available in the selected space")
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
                root = (
                    self.workspace.resolve()
                    if self._inside_workspace(target)
                    else next(
                        r.resolve() for r in self.extra_roots if target.is_relative_to(r.resolve())
                    )
                )
                if target.suffix.lower() == ".pdf":
                    # pypdf on a long document takes seconds: off the event loop, so the
                    # web app and the hub keep answering meanwhile
                    def read_pdf() -> str:
                        with open_file(root, target, "rb") as stream:
                            return pdf_text(cast(BinaryIO, stream))

                    text = await asyncio.to_thread(read_pdf)
                    if len(text) > MAX_READ_CHARS:
                        text = text[:MAX_READ_CHARS] + f"\n... [truncated, {len(text)} chars total]"
                    return ToolResult(output=text or "(empty file)")
                # read what fits and one more character, not the whole file: a log of a few
                # hundred MB is truncated either way, and need not be loaded for it
                with open_file(root, target, "r") as fh:
                    text = fh.read(MAX_READ_CHARS + 1)
                if len(text) > MAX_READ_CHARS:
                    size = target.stat().st_size
                    text = text[:MAX_READ_CHARS] + f"\n... [truncated, {size} bytes total]"
                return ToolResult(output=text or "(empty file)")
            if action in ("write", "append"):
                if content is None:
                    return ToolResult.fail("`content` is required")
                content, fixed = unescape_flat(content)
                target = self._resolve(path)
                root = (
                    self.workspace.resolve()
                    if self._inside_workspace(target)
                    else next(
                        r.resolve() for r in self.extra_roots if target.is_relative_to(r.resolve())
                    )
                )
                with open_file(root, target, "a" if action == "append" else "w") as fh:
                    fh.write(content)
                rel = os.path.relpath(target, self.workspace)
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
                entries = [p for p in entries if self._visible(p)]
                lines = [f"{'[dir] ' if p.is_dir() else ''}{p.name}" for p in entries[:500]]
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
                        if (
                            self._visible(p)
                            and p.is_file()
                            and fnmatch.fnmatch(p.relative_to(root).as_posix(), glob)
                        ):
                            matches.append(p.relative_to(ws).as_posix() if in_ws else str(p))
                        if len(matches) >= 200:
                            break
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

    def _visible(self, path: Path) -> bool:
        try:
            self._resolve(str(path))
            return True
        except (OSError, PermissionError):
            return False

    def __repr__(self) -> str:  # pragma: no cover
        return f"Files({short_json({'workspace': str(self.workspace)})})"


__all__ = ["Files"]

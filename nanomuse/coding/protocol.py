"""Bounded pages and opaque references for coding protocol 2, without file access."""

from __future__ import annotations

import base64
import binascii
import json
import os
from pathlib import Path
from typing import Any

from nanomuse.coding.timeline import fingerprint

PROTOCOL_VERSION = 2
CAPABILITIES = {
    "timeline": True,
    "item": True,
    "diff": True,
    "watch": True,
    "projects": True,
    "stop_owned_run": True,
    "control_external_run": False,
    "approve": False,
    "file": False,
}


class PageError(ValueError):
    pass


def page(values: list[Any] | str, args: dict[str, Any], default: int = 60) -> dict[str, Any]:
    version = fingerprint(values)
    backward = args.get("tail") is True
    start = len(values) if backward else 0
    cursor = args.get("cursor")
    if cursor:
        try:
            token = json.loads(base64.urlsafe_b64decode(str(cursor)))
            if token["version"] != version:
                raise PageError("stale_cursor")
            if bool(token.get("tail")) != backward:
                raise ValueError
            if not isinstance(token["offset"], int) or isinstance(token["offset"], bool):
                raise ValueError
            start = token["offset"]
            if start < 0 or start > len(values):
                raise ValueError
        except PageError:
            raise
        except (ValueError, KeyError, TypeError, binascii.Error):
            raise PageError("invalid_cursor") from None
    maximum = 32_768 if isinstance(values, str) else 200
    try:
        limit = max(1, min(maximum, int(args.get("limit") or default)))
    except (ValueError, TypeError, OverflowError):
        limit = min(maximum, default)
    end = start if backward else min(len(values), start + limit)
    begin = max(0, start - limit) if backward else start
    offset = begin if backward else end
    next_cursor = (
        base64.urlsafe_b64encode(
            json.dumps({"version": version, "offset": offset, "tail": backward}).encode()
        ).decode()
        if (begin > 0 if backward else end < len(values))
        else None
    )
    return {
        "data": values[begin:end],
        "version": version,
        "offset": begin,
        "next_cursor": next_cursor,
        "total": len(values),
    }


def scope(workspace: str, home: Path) -> str:
    if not workspace:
        return "chats"
    path = Path(os.path.normpath(workspace))
    for root in (
        home / ".codex" / "threads",
        home / "Documents" / "Codex",
        home / "Documents" / "nanoMuse" / "Chats",
    ):
        if path.is_relative_to(root):
            return "chats"
    return "projects"


def session_metadata(row: dict[str, Any], home: Path) -> dict[str, Any]:
    workspace = str(row.get("workspace") or "")
    return {
        **row,
        "scope": scope(workspace, home),
        "project_id": fingerprint(workspace) if scope(workspace, home) == "projects" else "",
    }


def preview(item: dict[str, Any]) -> dict[str, Any]:
    result = {k: v for k, v in item.items() if k not in ("output", "files", "input")}
    body = str(item.get("text") or "")
    result["text"] = body[:8000]
    result["text_truncated"] = len(body) > 8000
    output = str(item.get("output") or "")
    result["output_preview"] = output[-2000:]
    result["input_preview"] = str(item.get("input") or "")[:2000]
    result["truncated"] = bool(item.get("truncated")) or len(output) > 2000
    result["files"] = []
    for index, f in enumerate(item.get("files") or []):
        result["files"].append(
            {
                **{k: v for k, v in f.items() if k != "diff"},
                "diff_reference": f"{item['id']}:{index}" if f.get("diff") else None,
            }
        )
    return result

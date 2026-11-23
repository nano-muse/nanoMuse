"""A read-only view of the concrete text resources advertised by an open MCP session."""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from nanomuse.config import MCPServerSettings

_LABEL_URL = re.compile(r"\S+://\S+|(?:^|\s)[/?]\S+")
_TEXT_TYPES = {"application/json", "application/xml", "application/yaml"}


def _text_type(value: str | None) -> bool:
    mime = (value or "text/plain").partition(";")[0].strip().lower()
    return mime.startswith("text/") or mime in _TEXT_TYPES or mime.endswith(("+json", "+xml"))


@dataclass(frozen=True)
class MCPResource:
    id: str
    label: str
    uri: str = field(repr=False)


class MCPResourceReader:
    def __init__(self, cfg: MCPServerSettings, session: Any, redact: Callable[[str], str]):
        # Bind the consent to the actual connected endpoint/account, not just its display name.
        identity = json.dumps([cfg.name, cfg.url, cfg.command, cfg.args, cfg.env], sort_keys=True)
        self.prefix = hashlib.sha256(identity.encode()).hexdigest()[:32] + "."
        self.name = cfg.name
        self.session = session
        self.redact = redact
        self.timeout = max(0.1, min(cfg.call_timeout_s, 8.0))

    async def listed(self) -> list[MCPResource]:
        result: dict[str, MCPResource] = {}
        cursors: set[str] = set()
        cursor: str | None = None
        async with asyncio.timeout(self.timeout):
            for _ in range(4):
                if not cursor:
                    page = await self.session.list_resources()
                elif "params" in inspect.signature(self.session.list_resources).parameters:
                    from mcp.types import PaginatedRequestParams

                    page = await self.session.list_resources(
                        params=PaginatedRequestParams(cursor=cursor)
                    )
                else:  # earlier versions of the MCP client accept a cursor directly
                    page = await self.session.list_resources(cursor=cursor)
                for resource in page.resources[:128]:
                    uri = str(resource.uri)
                    mime = getattr(resource, "mime_type", None) or getattr(
                        resource, "mimeType", None
                    )
                    size = getattr(resource, "size", None)
                    if (
                        not uri
                        or len(uri) > 4096
                        or not _text_type(mime)
                        or (isinstance(size, int) and size > 256 * 1024)
                    ):
                        continue
                    key = self.prefix + hashlib.sha256(uri.encode()).hexdigest()[:32]
                    # Some servers use the entire private resource URI as its display name.
                    raw = str(getattr(resource, "title", None) or resource.name or "")
                    name = raw if raw != uri and not _LABEL_URL.search(raw) else ""
                    label = self.redact(f"{self.name} / {name or key[-8:]}").strip()[:180]
                    result[key] = MCPResource(key, label, uri)
                    if len(result) >= 128:
                        return list(result.values())
                cursor = getattr(page, "next_cursor", None) or getattr(page, "nextCursor", None)
                if not cursor or cursor in cursors:
                    break
                cursors.add(cursor)
        return list(result.values())

    async def read(self, resource: MCPResource) -> str:
        async with asyncio.timeout(self.timeout):
            reply = await self.session.read_resource(resource.uri)
        parts: list[str] = []
        remaining = 16384
        for part in (getattr(reply, "contents", None) or [])[:16]:
            text = getattr(part, "text", "")
            mime = getattr(part, "mime_type", None) or getattr(part, "mimeType", None)
            if str(part.uri) != resource.uri or not isinstance(text, str) or not _text_type(mime):
                continue
            text = text.strip()
            structured = "json" in (mime or "").lower() or text.startswith(("{", "[{", '["'))
            if structured:
                # Filter complete JSON by field before truncating. Do not reinterpret fragments
                # of a large object (or several concatenated objects) as plain text.
                return self.redact(text) if len(text) <= 256 * 1024 else ""
            if len(text) > remaining:
                # Project logs commonly append updates at the end; bound both ends.
                head = remaining // 2
                text = (
                    text[:head].rpartition("\n")[0]
                    + "\n"
                    + text[-(remaining - head - 1) :].partition("\n")[2]
                    if remaining > 2
                    else text[:remaining]
                )
            if text:
                parts.append(text)
                remaining -= len(text) + 1
            if remaining <= 0:
                break
        return self.redact("\n".join(parts))

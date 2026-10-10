"""Model Context Protocol client: expose tools of MCP servers as nanoMuse tools.

Configure in ``config.toml``::

    [[mcp.servers]]
    name = "filesystem"
    command = "npx"
    args = ["-y", "@modelcontextprotocol/server-filesystem", "./workspace"]
    risk = "moderate"          # safe | moderate | sensitive (default moderate)

    [[mcp.servers]]
    name = "remote"
    url = "http://localhost:8000/mcp"   # streamable HTTP (or SSE)
    [mcp.servers.tools.delete_file]     # one tool stricter than its server
    risk = "sensitive"

Compatible with mcp 1.x and 2.x.
"""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Callable
from contextlib import AsyncExitStack
from typing import Any

from nanomuse.config import MCPServerSettings
from nanomuse.logger import logger
from nanomuse.schema import ToolResult
from nanomuse.tools.base import BaseTool, CallAssessment

_NAME_RE = re.compile(r"[^a-zA-Z0-9_-]")
#: ``?key=value`` and ``&token=value`` inside a URL quoted in an error message
_QUERY_VALUE = re.compile(r"([?&])([^=&\s'\"]+)=([^&\s'\"]+)")


def _attr(obj: Any, *names: str, default: Any = None) -> Any:
    """Read the first present attribute – mcp 2.x uses snake_case, 1.x camelCase."""
    for name in names:
        value = getattr(obj, name, None)
        if value is not None:
            return value
    return default


def _safe_name(server: str, tool: str) -> str:
    name = _NAME_RE.sub("_", f"{server}__{tool}")
    return name[:64]


class MCPTool(BaseTool):
    session: Any
    server: str
    original_name: str

    def assess(self, args: dict[str, Any]) -> CallAssessment:
        base = super().assess(args)
        base.summary = (
            f"mcp:{self.server}.{self.original_name}({json.dumps(args, ensure_ascii=False)[:150]})"
        )
        return base

    async def execute(self, **kwargs: Any) -> ToolResult:
        # Always send an object, even an empty one: servers built on zod (12306-mcp's
        # `get-current-date`, for one) reject a call with no `arguments` at all.
        result = await self.session.call_tool(self.original_name, dict(kwargs))
        parts: list[str] = []
        for item in getattr(result, "content", None) or []:
            itype = getattr(item, "type", "")
            if itype == "text":
                parts.append(getattr(item, "text", ""))
            elif itype == "image":
                parts.append(f"[image {_attr(item, 'mime_type', 'mimeType', default='')}]")
            elif itype == "resource":
                res = getattr(item, "resource", None)
                parts.append(getattr(res, "text", None) or f"[resource {getattr(res, 'uri', '')}]")
            else:
                parts.append(str(item))
        structured = _attr(result, "structured_content", "structuredContent")
        if structured and not parts:
            parts.append(json.dumps(structured, ensure_ascii=False, indent=2, default=str))
        text = "\n".join(p for p in parts if p) or "(no output)"
        if _attr(result, "is_error", "isError", default=False):
            return ToolResult.fail(text)
        return ToolResult(output=text)


class MCPManager:
    """Connects to configured MCP servers and keeps the sessions alive.

    ``resolve`` fills ``{{vault:NAME}}`` placeholders in a server's ``url``, ``args`` and
    ``env`` right before connecting, so a key (``?key={{vault:AMAP_KEY}}``) can stay in
    the vault instead of the config file.
    """

    def __init__(
        self,
        servers: list[MCPServerSettings],
        resolve: Callable[[Any], Any] | None = None,
        redact: Callable[[str], str] | None = None,
    ):
        self.servers = servers
        self._resolve = resolve
        self._redact = redact
        self._stack = AsyncExitStack()
        self.tools: list[MCPTool] = []

    def _resolved(self, cfg: MCPServerSettings) -> MCPServerSettings:
        if self._resolve is None:
            return cfg
        return cfg.model_copy(
            update={
                "url": self._resolve(cfg.url) if cfg.url else cfg.url,
                "args": [str(a) for a in self._resolve(list(cfg.args))],
                "env": {k: str(v) for k, v in self._resolve(dict(cfg.env)).items()},
            }
        )

    def _scrub(self, text: str) -> str:
        """A log line with no credential in it: the value of every URL query parameter is
        masked (an MCP server's key rides there, ``?key=…``, and httpx names the full URL
        in a 4xx error), then the vault's own secrets (an ``env`` or ``args`` value)."""
        text = _QUERY_VALUE.sub(r"\1\2=***", text)
        return self._redact(text) if self._redact else text

    async def connect(self) -> list[MCPTool]:
        """Connect every server; one that is down is logged and skipped.

        Each attempt lives on its own exit stack, closed in this task when it fails. The
        HTTP transports connect in a background task of their own task group, so a wrong
        URL or a refused key surfaces as a *cancellation* of ``initialize()`` here rather
        than an exception; swallowing that only when this task itself was not cancelled
        is what keeps a bad server from taking the whole request down with it."""
        for cfg in self.servers:
            resolved = self._resolved(cfg)
            attempts = ["streamable", "sse"] if resolved.url else ["stdio"]
            for transport in attempts:
                stack = AsyncExitStack()
                try:
                    session, listed = await self._open(resolved, transport, stack)
                except BaseException as exc:  # noqa: BLE001 — see the docstring
                    unwound = await _close_quietly(stack)
                    if unwound is not None:
                        logger.debug("MCP transport shutdown: {}", self._scrub(_reason(unwound)))
                    if _this_task_is_cancelled():
                        raise
                    # a cancellation says nothing by itself; the transport's own error
                    # comes out when its task group is closed
                    reason = _reason(unwound if isinstance(exc, asyncio.CancelledError) else exc)
                    logger.warning(
                        "MCP server '{}' unavailable over {}: {}",
                        cfg.name,
                        transport,
                        self._scrub(reason),
                    )
                    continue
                await self._stack.enter_async_context(stack)
                self._add_tools(cfg, session, listed)
                logger.info("MCP server '{}' connected with {} tools", cfg.name, len(listed.tools))
                break
        return self.tools

    def _add_tools(self, cfg: MCPServerSettings, session: Any, listed: Any) -> None:
        for t in listed.tools:
            schema = _attr(t, "input_schema", "inputSchema") or {
                "type": "object",
                "properties": {},
            }
            policy = cfg.tools.get(t.name)
            tool = MCPTool(
                name=_safe_name(cfg.name, t.name),
                description=(t.description or f"{t.name} (from MCP server {cfg.name})")[:1000],
                parameters=schema,
                risk=policy.risk if policy and policy.risk is not None else cfg.risk,
                egress=policy.egress if policy and policy.egress is not None else cfg.egress,
                reads_private_data=(
                    policy.reads_private_data
                    if policy and policy.reads_private_data is not None
                    else cfg.reads_private_data
                ),
                session=session,
                server=cfg.name,
                original_name=t.name,
            )
            self.tools.append(tool)

    async def _open(
        self, cfg: MCPServerSettings, transport: str, stack: AsyncExitStack
    ) -> tuple[Any, Any]:
        """Transport, session, handshake and the tool list for one server, all on ``stack``."""
        from mcp import ClientSession

        read, write = await self._open_transport(cfg, transport, stack)
        session = await stack.enter_async_context(ClientSession(read, write))
        await session.initialize()
        return session, await session.list_tools()

    async def _open_transport(
        self, cfg: MCPServerSettings, transport: str, stack: AsyncExitStack
    ) -> tuple[Any, Any]:
        if transport == "streamable":
            try:  # mcp >= 2
                from mcp.client.streamable_http import streamable_http_client as http_client
            except ImportError:  # mcp 1.x
                from mcp.client.streamable_http import (  # type: ignore[attr-defined,no-redef]
                    streamablehttp_client as http_client,
                )
            streams = await stack.enter_async_context(http_client(cfg.url or ""))
            return streams[0], streams[1]
        if transport == "sse":
            # an older server speaks SSE only
            from mcp.client.sse import sse_client

            streams = await stack.enter_async_context(sse_client(cfg.url or ""))
            return streams[0], streams[1]
        if not cfg.command:
            raise ValueError(f"MCP server '{cfg.name}' needs either `command` or `url`")
        from mcp import StdioServerParameters
        from mcp.client.stdio import get_default_environment, stdio_client

        # the library's default environment (PATH, HOME, …) plus what the config names;
        # the runtime's own credentials stay out of the server's process
        params = StdioServerParameters(
            command=cfg.command,
            args=cfg.args,
            env={**get_default_environment(), **cfg.env} if cfg.env else None,
        )
        streams = await stack.enter_async_context(stdio_client(params))
        return streams[0], streams[1]

    async def close(self) -> None:
        try:
            await self._stack.aclose()
        except Exception as exc:  # noqa: BLE001
            logger.debug("MCP shutdown: {}", self._scrub(_reason(exc)))


def _this_task_is_cancelled() -> bool:
    """Whether the running task still has a cancellation pending once a failed transport's
    scope has been exited: anyio takes back the cancellation its own scope delivered, so
    what is left is the caller's (a request being torn down, the runtime stopping)."""
    task = asyncio.current_task()
    return task is not None and task.cancelling() > 0


async def _close_quietly(stack: AsyncExitStack) -> BaseException | None:
    """Close a failed attempt's stack; what it raised while unwinding (the transport's
    real error, usually) is returned rather than thrown, for the caller to log scrubbed."""
    try:
        await stack.aclose()
    except BaseException as exc:  # noqa: BLE001 — a failed transport may unwind noisily
        return exc
    return None


def _reason(exc: BaseException | None) -> str:
    """One line naming what went wrong, down through exception groups."""
    if exc is None:
        return "connection failed"
    while isinstance(exc, BaseExceptionGroup) and exc.exceptions:
        # the most telling leaf: anything but a bare cancellation
        leaves = [e for e in exc.exceptions if not isinstance(e, asyncio.CancelledError)]
        exc = (leaves or list(exc.exceptions))[0]
    return f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__


__all__ = ["MCPManager", "MCPTool"]

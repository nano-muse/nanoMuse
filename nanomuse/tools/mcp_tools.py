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
from nanomuse.tools.mcp_resources import MCPResourceReader

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


#: argument names whose values are never written into a summary or the audit log
_SECRET_KEYS = re.compile(
    r"(pass(word|wd|phrase)?|secret|token|api[_-]?key|auth|credential|cookie|otp|code|pin)",
    re.IGNORECASE,
)


def _shape(value: Any, depth: int = 0) -> Any:
    """What of an argument the audit line may say: a string is its length, a number or
    boolean itself, a list its length, an object its keys with their shapes; a key that
    names a secret is only noted as present."""
    if isinstance(value, dict):
        if depth >= 2:
            return {"keys": len(value)}
        return {
            str(k): "***" if _SECRET_KEYS.search(str(k)) else _shape(v, depth + 1)
            for k, v in list(value.items())[:12]
        }
    if isinstance(value, str):
        return f"str[{len(value)}]"
    if isinstance(value, (list, tuple)):
        return f"list[{len(value)}]"
    return value


class MCPTool(BaseTool):
    session: Any
    server: str
    original_name: str
    #: the server's host when it is on another machine: the destination of every call
    remote_host: str | None = None
    #: seconds one call may take before it is given up as failed
    call_timeout_s: float = 120.0

    def assess(self, args: dict[str, Any]) -> CallAssessment:
        base = super().assess(args)
        # the shape of the arguments, not their values: an MCP argument can be a message
        # body, a code, a key — and this line goes into the approval card and the audit log
        shape = json.dumps(_shape(args), ensure_ascii=False, separators=(",", ":"))[:150]
        base.summary = f"mcp:{self.server}.{self.original_name}({shape})"
        if self.egress and self.remote_host:
            base.egress_target = self.remote_host
            base.target = self.remote_host
        return base

    async def execute(self, **kwargs: Any) -> ToolResult:
        # Always send an object, even an empty one: servers built on zod (12306-mcp's
        # `get-current-date`, for one) reject a call with no `arguments` at all.
        try:
            async with asyncio.timeout(self.call_timeout_s):
                result = await self.session.call_tool(self.original_name, dict(kwargs))
        except TimeoutError:
            return ToolResult.fail(
                f"the MCP server '{self.server}' did not answer within {self.call_timeout_s:g} s"
            )
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
        self.resource_readers: dict[str, MCPResourceReader] = {}

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
                    session, listed, has_resources = await self._open(resolved, transport, stack)
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
                if self._add_tools(cfg, session, listed):
                    if has_resources:
                        self.resource_readers[cfg.name] = MCPResourceReader(
                            resolved, session, self._scrub
                        )
                    logger.info(
                        "MCP server '{}' connected with {} tools", cfg.name, len(listed.tools)
                    )
                break
        return self.tools

    def _add_tools(self, cfg: MCPServerSettings, session: Any, listed: Any) -> bool:
        """The server's tools under their model-facing names. Two tools whose names become
        the same after the character replacement or the 64-character cut would make one of
        them unreachable (the model's call would always land on the other), so the server
        is skipped with a warning naming both and nothing of it is added: the operator
        renames the server or the tool, and the rest of the runtime starts as usual.
        Returns whether the tools were added."""
        existing = {tool.name: f"{tool.server}.{tool.original_name}" for tool in self.tools}
        names: dict[str, str] = {}
        for remote in listed.tools:
            safe = _safe_name(cfg.name, remote.name)
            original = f"{cfg.name}.{remote.name}"
            other = names.get(safe) or existing.get(safe)
            if other is not None:
                logger.warning(
                    "MCP server '{}' skipped: tool names {!r} and {!r} both become {!r}; "
                    "rename one of them",
                    cfg.name,
                    other,
                    original,
                    safe,
                )
                return False
            names[safe] = original
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
                egress=policy.egress if policy and policy.egress is not None else cfg.sends_out,
                reads_private_data=(
                    policy.reads_private_data
                    if policy and policy.reads_private_data is not None
                    else cfg.reads_private_data
                ),
                session=session,
                server=cfg.name,
                original_name=t.name,
                remote_host=cfg.remote_host,
                call_timeout_s=cfg.call_timeout_s,
            )
            self.tools.append(tool)
        return True

    async def _open(
        self, cfg: MCPServerSettings, transport: str, stack: AsyncExitStack
    ) -> tuple[Any, Any, bool]:
        """Transport, session, handshake and the tool list for one server, all on ``stack``."""
        from mcp import ClientSession

        # the whole handshake under one clock: a server that accepts the connection and
        # then says nothing is skipped like one that is down
        async with asyncio.timeout(cfg.connect_timeout_s):
            read, write = await self._open_transport(cfg, transport, stack)
            session = await stack.enter_async_context(ClientSession(read, write))
            hello = await session.initialize()
            if hello.capabilities.tools is None:
                from mcp.types import ListToolsResult

                listed = ListToolsResult(tools=[])
            else:
                listed = await session.list_tools()
            return session, listed, hello.capabilities.resources is not None

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
        self.resource_readers.clear()
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

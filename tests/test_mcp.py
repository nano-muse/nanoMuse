from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from nanomuse.config import MCPServerSettings
from nanomuse.schema import RiskLevel
from nanomuse.tools import MCPManager, ToolCollection

SERVER = Path(__file__).with_name("mcp_echo_server.py")


async def test_mcp_tools_are_exposed_and_callable():
    manager = MCPManager(
        [
            MCPServerSettings(
                name="echo", command=sys.executable, args=[str(SERVER)], risk=RiskLevel.SAFE
            )
        ]
    )
    try:
        tools = await manager.connect()
        names = sorted(t.name for t in tools)
        assert names == ["echo__add", "echo__echo", "echo__today"]
        collection = ToolCollection(*tools)
        params = collection.to_params()
        assert params[0]["function"]["parameters"]["type"] == "object"
        result = await collection.execute("echo__echo", {"text": "hi"})
        assert result.ok and "echo: hi" in result.output
        result = await collection.execute("echo__add", {"a": 2, "b": 40})
        assert "42" in result.output
        # no arguments still sends an (empty) object — zod-based servers reject a missing one
        result = await collection.execute("echo__today", {})
        assert result.ok and "2026-09-24" in result.output
        assert tools[0].assess({"text": "x"}).summary.startswith("mcp:echo.")
    finally:
        await manager.close()


async def test_per_tool_policy_overrides_the_servers_defaults():
    """`[mcp.servers.tools.<name>]` makes one tool stricter (or looser) than its server;
    a field left out keeps the server's value."""
    from nanomuse.config import MCPToolPolicy

    manager = MCPManager(
        [
            MCPServerSettings(
                name="echo",
                command=sys.executable,
                args=[str(SERVER)],
                risk=RiskLevel.SAFE,
                reads_private_data=True,
                tools={"add": MCPToolPolicy(risk=RiskLevel.SENSITIVE, reads_private_data=False)},
            )
        ]
    )
    try:
        tools = {t.name: t for t in await manager.connect()}
        assert tools["echo__add"].risk == RiskLevel.SENSITIVE
        assert tools["echo__add"].reads_private_data is False
        assert tools["echo__add"].egress is False  # not set: the server's
        assert tools["echo__echo"].risk == RiskLevel.SAFE
        assert tools["echo__echo"].reads_private_data is True
    finally:
        await manager.close()


async def test_unavailable_server_is_skipped():
    manager = MCPManager([MCPServerSettings(name="nope", command="definitely-not-a-command-xyz")])
    try:
        assert await manager.connect() == []
    finally:
        await manager.close()


async def test_vault_placeholders_are_resolved_before_connecting():
    """A key kept in the vault reaches the server through url, args or env; the config
    object itself keeps the placeholder."""
    secrets = {"ECHO_MODE": "loud", "AMAP_KEY": "k-123"}

    def resolve(value):
        import re

        if isinstance(value, str):
            return re.sub(r"\{\{vault:(\w+)\}\}", lambda m: secrets[m.group(1)], value)
        if isinstance(value, list):
            return [resolve(v) for v in value]
        if isinstance(value, dict):
            return {k: resolve(v) for k, v in value.items()}
        return value

    cfg = MCPServerSettings(
        name="echo",
        command=sys.executable,
        args=[str(SERVER), "{{vault:ECHO_MODE}}"],
        env={"ECHO_KEY": "{{vault:AMAP_KEY}}"},
        url=None,
    )
    manager = MCPManager([cfg], resolve=resolve)
    resolved = manager._resolved(cfg)
    assert resolved.args == [str(SERVER), "loud"] and resolved.env == {"ECHO_KEY": "k-123"}
    assert cfg.args[1] == "{{vault:ECHO_MODE}}" and cfg.env["ECHO_KEY"] == "{{vault:AMAP_KEY}}"
    url = MCPServerSettings(name="amap", url="https://mcp.amap.com/mcp?key={{vault:AMAP_KEY}}")
    assert manager._resolved(url).url == "https://mcp.amap.com/mcp?key=k-123"
    try:
        tools = await manager.connect()  # the echo server ignores its extra argument
        assert sorted(t.name for t in tools) == ["echo__add", "echo__echo", "echo__today"]
    finally:
        await manager.close()


async def test_an_unreachable_url_server_is_skipped_not_cancelled():
    """The HTTP transports connect in a task group of their own; a host that does not
    resolve used to surface as a *cancellation* of the caller (a 500 from the
    Connections page, and "Attempted to exit cancel scope in a different task" in the
    log). It is a skipped server like any other, and the caller's task goes on."""
    manager = MCPManager([MCPServerSettings(name="nowhere", url="http://mcp.invalid./mcp?key=abc")])
    tools = await asyncio.wait_for(manager.connect(), timeout=30)
    assert tools == []
    task = asyncio.current_task()
    assert task is not None and task.cancelling() == 0
    await manager.close()
    # the task is still usable
    await asyncio.sleep(0)


async def test_a_refused_key_is_not_written_to_the_log():
    """httpx names the full URL in a 4xx error, and an MCP server's key rides in the query
    (``?key=…``): the warning masks every query value, and the vault's redaction runs on the
    rest (a secret an ``args`` or ``env`` value carried)."""
    import http.server
    import threading

    from nanomuse.logger import logger

    class Refuse(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self.send_response(401)
            self.end_headers()

        do_POST = do_GET

        def log_message(self, *_: object) -> None:
            pass

    httpd = http.server.HTTPServer(("127.0.0.1", 0), Refuse)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    lines: list[str] = []
    sink = logger.add(lambda m: lines.append(m.record["message"]), level="DEBUG")
    try:
        manager = MCPManager(
            [MCPServerSettings(name="paid", url=f"http://127.0.0.1:{port}/mcp?key=k-123&v=2")],
            redact=lambda text: text.replace("k-123", "[REDACTED:MCP_KEY]"),
        )
        tools = await asyncio.wait_for(manager.connect(), timeout=30)
        await manager.close()
    finally:
        logger.remove(sink)
        httpd.shutdown()
    assert tools == []
    joined = "\n".join(lines)
    assert "unavailable over sse" in joined and "401" in joined, joined
    assert "k-123" not in joined, joined
    assert "?key=***&v=***" in joined, joined
    # the vault's redaction is applied too, for a secret outside the query
    assert manager._scrub("spawn failed: k-123 x") == "spawn failed: [REDACTED:MCP_KEY] x"

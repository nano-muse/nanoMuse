"""Resource-only stdio MCP connection for exercising background observation in isolation."""

import sys
from pathlib import Path

try:
    from mcp.server.mcpserver import MCPServer as _Server
except ImportError:
    from mcp.server.fastmcp import FastMCP as _Server  # type: ignore[no-redef]

server = _Server("Context fixture")


@server.resource("board://work/updates", name="Team updates", mime_type="text/plain")
def updates() -> str:
    return Path(sys.argv[1]).read_text(encoding="utf-8")


@server.resource("board://work/unselected", name="Unselected", mime_type="text/plain")
def unselected() -> str:
    raise AssertionError("Reading an unselected resource is forbidden")


if __name__ == "__main__":
    server.run(transport="stdio")

"""FastMCP server instance for the triage MCP server.

The protocol version is pinned here to the value advertised by the installed
SDK at the time of this commit. MCP negotiates `protocolVersion` during the
initialize handshake — we state, the SDK enforces. Document the value in the
README and bump deliberately when the SDK is upgraded.

Server transport is wired in `__main__.py` (stdio for local dev; Day 36 swaps
to Streamable HTTP for AgentCore Gateway).
"""

from __future__ import annotations

from typing import Final

from mcp.server.fastmcp import FastMCP

MCP_PROTOCOL_VERSION: Final[str] = "2025-11-25"
SERVER_NAME: Final[str] = "triage"
SERVER_VERSION: Final[str] = "0.1.0"

mcp: Final[FastMCP] = FastMCP(SERVER_NAME)

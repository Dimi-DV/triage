"""FastMCP server instance for the triage MCP server.

The protocol version is pinned here to the value advertised by the installed
SDK at the time of this commit. MCP negotiates `protocolVersion` during the
initialize handshake — we state, the SDK enforces. Document the value in the
README and bump deliberately when the SDK is upgraded.

Server transport is wired in `__main__.py`: stdio for local dev,
Streamable HTTP behind AgentCore Gateway in production.
"""

from __future__ import annotations

import os
from contextvars import ContextVar
from typing import Final

from mcp.server.fastmcp import FastMCP

MCP_PROTOCOL_VERSION: Final[str] = "2025-11-25"
SERVER_NAME: Final[str] = "triage"
SERVER_VERSION: Final[str] = "0.1.0"

mcp: Final[FastMCP] = FastMCP(SERVER_NAME)

current_principal: ContextVar[str | None] = ContextVar("triage_current_principal", default=None)


def get_current_principal() -> str:
    """Return the authenticated principal for the current request.

    Under Streamable HTTP the auth middleware sets the contextvar from the
    JWT `sub` claim. Under stdio there is no middleware; we fall back to
    `TRIAGE_PRINCIPAL` so audit emissions still carry a meaningful identity
    in local-dev / single-tenant deployments.
    """
    principal = current_principal.get()
    if principal:
        return principal
    return os.environ.get("TRIAGE_PRINCIPAL", "local-dev")

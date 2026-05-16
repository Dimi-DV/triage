"""Entry point: `python -m triage.mcp_server`.

Order matters:
  1. Boot tracing FIRST (forces logging to stderr; stdio MCP uses stdout for
     JSON-RPC, so any stray stdout write corrupts the protocol).
  2. Import namespace modules so the @mcp.tool decorators register tools on
     the FastMCP instance.
  3. Log the pinned protocol version to stderr.
  4. Run the server on stdio.
"""

from __future__ import annotations

import logging

from triage.shared.otel import init_tracing

from . import ecs_api, logs_api, metrics_api, runbooks_api  # noqa: F401  (registration side-effect)
from .server import MCP_PROTOCOL_VERSION, SERVER_NAME, SERVER_VERSION, mcp


def main() -> None:
    init_tracing(SERVER_NAME + "-mcp-server")
    log = logging.getLogger(__name__)
    log.info(
        "Starting %s MCP server v%s (protocol=%s, transport=stdio)",
        SERVER_NAME,
        SERVER_VERSION,
        MCP_PROTOCOL_VERSION,
    )
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()

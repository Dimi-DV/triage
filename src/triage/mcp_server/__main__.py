"""Entry point: `python -m triage.mcp_server`.

Order matters:
  1. Boot tracing FIRST (forces logging to stderr; stdio MCP uses stdout for
     JSON-RPC, so any stray stdout write corrupts the protocol).
  2. Import namespace modules so the @mcp.tool decorators register tools on
     the FastMCP instance.
  3. Log the pinned protocol version to stderr.
  4. Run the server on the chosen transport.

Transport selection via `TRIAGE_MCP_TRANSPORT`:
  - `stdio`  (default) — local dev, tests, direct AgentCore Runtime sidecar.
  - `streamable-http`   — production, behind AgentCore Gateway. Binds to
                         `0.0.0.0:8080`; JWT auth on unless
                         `TRIAGE_MCP_AUTH_DISABLED=1`.
"""

from __future__ import annotations

import logging
import os

from triage.shared.otel import init_tracing

from . import ecs_api, logs_api, metrics_api, runbooks_api  # noqa: F401  (registration side-effect)
from .server import MCP_PROTOCOL_VERSION, SERVER_NAME, SERVER_VERSION, mcp


def _run_streamable_http() -> None:
    """Run the FastMCP app over Streamable HTTP with optional JWT auth."""
    import uvicorn
    from starlette.responses import PlainTextResponse
    from starlette.routing import Route

    mcp.settings.host = "0.0.0.0"  # noqa: S104  # container-bound, ALB fronts it
    mcp.settings.port = 8080
    mcp.settings.stateless_http = True  # let the ALB fan requests across tasks

    app = mcp.streamable_http_app()

    async def health(_request: object) -> PlainTextResponse:
        return PlainTextResponse("ok")

    app.router.routes.append(Route(_HEALTH_PATH, health, methods=["GET"]))

    _install_auth_middleware(app)
    uvicorn.run(app, host=mcp.settings.host, port=mcp.settings.port, log_level="info")


def _install_auth_middleware(app: object) -> None:
    """Pick the right middleware for the current env state.

    - TRIAGE_MCP_AUTH_DISABLED=1            → no middleware (local-dev escape hatch).
    - issuer unset or starts with PLACEHOLDER → BootstrapGateMiddleware (503 on /mcp/*).
    - issuer configured                     → JWTAuthMiddleware (validate bearer tokens).
    """
    log = logging.getLogger(__name__)
    from .auth import (
        BootstrapGateMiddleware,
        JWTAuthMiddleware,
        JWTValidator,
        JWTValidatorConfig,
        issuer_is_configured,
    )

    if os.environ.get("TRIAGE_MCP_AUTH_DISABLED") == "1":
        log.warning(
            "TRIAGE_MCP_AUTH_DISABLED=1 — running without auth. "
            "Local-dev only; do not set in production."
        )
        return

    issuer = os.environ.get("AGENTCORE_IDENTITY_ISSUER")
    if not issuer_is_configured(issuer):
        log.warning(
            "AGENTCORE_IDENTITY_ISSUER not configured (current=%r); installing "
            "BootstrapGateMiddleware. /mcp/* will return 503 until "
            "scripts/provision_agentcore.py updates the SSM parameter and "
            "the task is force-redeployed.",
            issuer,
        )
        app.add_middleware(BootstrapGateMiddleware)  # type: ignore[attr-defined]
        return

    validator = JWTValidator(JWTValidatorConfig.from_env())
    app.add_middleware(JWTAuthMiddleware, validator=validator)  # type: ignore[attr-defined]
    log.info("JWT auth enabled; issuer=%s", issuer)


_HEALTH_PATH = "/health"


def main() -> None:
    init_tracing(SERVER_NAME + "-mcp-server")
    log = logging.getLogger(__name__)

    transport = os.environ.get("TRIAGE_MCP_TRANSPORT", "stdio")
    log.info(
        "Starting %s MCP server v%s (protocol=%s, transport=%s)",
        SERVER_NAME,
        SERVER_VERSION,
        MCP_PROTOCOL_VERSION,
        transport,
    )

    if transport == "stdio":
        mcp.run(transport="stdio")
    elif transport == "streamable-http":
        _run_streamable_http()
    else:
        raise ValueError(f"Unsupported TRIAGE_MCP_TRANSPORT={transport!r}")


if __name__ == "__main__":
    main()

"""JWT validation middleware for the MCP server's Streamable HTTP transport.

The server runs behind AgentCore Gateway in production. Gateway issues OAuth
2.1 access tokens (via AgentCore Identity) carrying the configured Resource
Indicator. Every request to the MCP server must carry a valid Bearer token
signed by the Identity issuer's JWKS.

Stdio transport (local dev, tests) bypasses this entirely.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

import jwt
from jwt import PyJWKClient
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

from triage.mcp_server.server import current_principal

log = logging.getLogger(__name__)

_HEALTH_PATH = "/health"
_ALLOWED_ALGORITHMS = ("RS256", "ES256")
_PLACEHOLDER_PREFIX = "PLACEHOLDER"


def issuer_is_configured(issuer: str | None) -> bool:
    """True when the issuer env var is set and not a placeholder."""
    if not issuer:
        return False
    return not issuer.startswith(_PLACEHOLDER_PREFIX)


@dataclass(frozen=True)
class JWTValidatorConfig:
    issuer: str
    audience: str
    jwks_url: str
    leeway_seconds: int = 30

    @classmethod
    def from_env(cls) -> JWTValidatorConfig:
        issuer = os.environ["AGENTCORE_IDENTITY_ISSUER"].rstrip("/")
        audience = os.environ.get("TRIAGE_MCP_AUDIENCE", "triage-mcp")
        jwks_url = os.environ.get(
            "AGENTCORE_IDENTITY_JWKS_URL",
            f"{issuer}/.well-known/jwks.json",
        )
        return cls(issuer=issuer, audience=audience, jwks_url=jwks_url)


class JWTValidator:
    """Validates JWTs against an issuer's JWKS endpoint.

    PyJWKClient handles the JWKS fetch + cache + key rotation. We layer
    audience/issuer/expiration checks on top, with required claims enforced.
    """

    def __init__(
        self,
        config: JWTValidatorConfig,
        jwks_client: PyJWKClient | None = None,
    ) -> None:
        self.config = config
        self._jwks = jwks_client or PyJWKClient(config.jwks_url, cache_keys=True, lifespan=300)

    def validate(self, token: str) -> dict[str, Any]:
        signing_key = self._jwks.get_signing_key_from_jwt(token).key
        claims: dict[str, Any] = jwt.decode(
            token,
            signing_key,
            algorithms=list(_ALLOWED_ALGORITHMS),
            audience=self.config.audience,
            issuer=self.config.issuer,
            leeway=self.config.leeway_seconds,
            options={"require": ["exp", "iat", "sub", "aud", "iss"]},
        )
        return claims


class BootstrapGateMiddleware(BaseHTTPMiddleware):
    """Fail-closed gate while AGENTCORE_IDENTITY_ISSUER is not yet configured.

    Keeps `/health` open so the ALB target stays healthy during bootstrap,
    but returns 503 with Retry-After on every other path. Once the
    provisioning script writes the real issuer to SSM and force-redeploys
    the task, the new container instead installs `JWTAuthMiddleware`.

    This is the failsafe against the public-ALB-exposes-MCP attack window
    between `terraform apply` and `make provision-agentcore`.
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.url.path == _HEALTH_PATH:
            return await call_next(request)
        return JSONResponse(
            {
                "error": "service_bootstrapping",
                "detail": "AGENTCORE_IDENTITY_ISSUER not yet configured",
            },
            status_code=503,
            headers={"Retry-After": "30"},
        )


class JWTAuthMiddleware(BaseHTTPMiddleware):
    """Bearer-token validator; sets `current_principal` on success."""

    def __init__(self, app: ASGIApp, validator: JWTValidator) -> None:
        super().__init__(app)
        self.validator = validator

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.url.path == _HEALTH_PATH:
            return await call_next(request)

        auth_header = request.headers.get("authorization", "")
        if not auth_header.lower().startswith("bearer "):
            return JSONResponse({"error": "missing_bearer_token"}, status_code=401)

        token = auth_header.split(" ", 1)[1]
        try:
            claims = self.validator.validate(token)
        except jwt.PyJWTError as exc:
            log.warning("Rejecting request: JWT validation failed: %s", exc)
            return JSONResponse(
                {"error": "invalid_token", "detail": str(exc)},
                status_code=401,
            )

        principal = str(claims["sub"])
        token_var = current_principal.set(principal)
        try:
            return await call_next(request)
        finally:
            current_principal.reset(token_var)

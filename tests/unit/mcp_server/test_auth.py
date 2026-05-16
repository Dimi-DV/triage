"""JWT validator + Starlette middleware tests for the MCP server."""

from __future__ import annotations

import time
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from triage.mcp_server.auth import (
    BootstrapGateMiddleware,
    JWTAuthMiddleware,
    JWTValidator,
    JWTValidatorConfig,
    issuer_is_configured,
)
from triage.mcp_server.server import current_principal, get_current_principal

ISSUER = "https://identity.example.com"
AUDIENCE = "triage-mcp"


class _StubKey:
    def __init__(self, key: Any) -> None:
        self.key = key


class _StubJWKSClient:
    def __init__(self, public_key: Any) -> None:
        self._signing_key = _StubKey(public_key)

    def get_signing_key_from_jwt(self, _token: str) -> _StubKey:
        return self._signing_key


@pytest.fixture(scope="module")
def rsa_keys() -> tuple[Any, Any]:
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return private, private.public_key()


@pytest.fixture
def validator(rsa_keys: tuple[Any, Any]) -> JWTValidator:
    _private, public = rsa_keys
    config = JWTValidatorConfig(issuer=ISSUER, audience=AUDIENCE, jwks_url="ignored")
    return JWTValidator(config, jwks_client=_StubJWKSClient(public))  # type: ignore[arg-type]


def _make_token(
    private_key: Any,
    *,
    sub: str = "agent:triage",
    aud: str = AUDIENCE,
    iss: str = ISSUER,
    exp_offset: int = 60,
) -> str:
    now = int(time.time())
    payload = {
        "sub": sub,
        "aud": aud,
        "iss": iss,
        "iat": now,
        "exp": now + exp_offset,
    }
    return jwt.encode(payload, private_key, algorithm="RS256", headers={"kid": "k1"})


@pytest.mark.unit
def test_validator_accepts_valid_token(rsa_keys: tuple[Any, Any], validator: JWTValidator) -> None:
    private, _ = rsa_keys
    claims = validator.validate(_make_token(private))
    assert claims["sub"] == "agent:triage"
    assert claims["aud"] == AUDIENCE
    assert claims["iss"] == ISSUER


@pytest.mark.unit
def test_validator_rejects_wrong_audience(
    rsa_keys: tuple[Any, Any], validator: JWTValidator
) -> None:
    private, _ = rsa_keys
    token = _make_token(private, aud="wrong-audience")
    with pytest.raises(jwt.InvalidAudienceError):
        validator.validate(token)


@pytest.mark.unit
def test_validator_rejects_wrong_issuer(rsa_keys: tuple[Any, Any], validator: JWTValidator) -> None:
    private, _ = rsa_keys
    token = _make_token(private, iss="https://attacker.example.com")
    with pytest.raises(jwt.InvalidIssuerError):
        validator.validate(token)


@pytest.mark.unit
def test_validator_rejects_expired_token(
    rsa_keys: tuple[Any, Any], validator: JWTValidator
) -> None:
    private, _ = rsa_keys
    token = _make_token(private, exp_offset=-3600)
    with pytest.raises(jwt.ExpiredSignatureError):
        validator.validate(token)


@pytest.mark.unit
def test_validator_rejects_missing_required_claim(
    rsa_keys: tuple[Any, Any], validator: JWTValidator
) -> None:
    private, _ = rsa_keys
    now = int(time.time())
    # Build a token without `sub` to exercise the require list.
    payload = {"aud": AUDIENCE, "iss": ISSUER, "iat": now, "exp": now + 60}
    token = jwt.encode(payload, private, algorithm="RS256", headers={"kid": "k1"})
    with pytest.raises(jwt.MissingRequiredClaimError):
        validator.validate(token)


def _build_app(validator: JWTValidator) -> Starlette:
    async def whoami(_request: Request) -> JSONResponse:
        return JSONResponse({"principal": get_current_principal()})

    async def health(_request: Request) -> JSONResponse:
        return JSONResponse({"ok": True})

    app = Starlette(routes=[Route("/whoami", whoami), Route("/health", health)])
    app.add_middleware(JWTAuthMiddleware, validator=validator)
    return app


@pytest.mark.unit
def test_middleware_allows_health_without_auth(validator: JWTValidator) -> None:
    client = TestClient(_build_app(validator))
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"ok": True}


@pytest.mark.unit
def test_middleware_rejects_missing_bearer(validator: JWTValidator) -> None:
    client = TestClient(_build_app(validator))
    response = client.get("/whoami")
    assert response.status_code == 401
    assert response.json()["error"] == "missing_bearer_token"


@pytest.mark.unit
def test_middleware_rejects_invalid_token(validator: JWTValidator) -> None:
    client = TestClient(_build_app(validator))
    response = client.get("/whoami", headers={"Authorization": "Bearer not-a-jwt"})
    assert response.status_code == 401
    assert response.json()["error"] == "invalid_token"


@pytest.mark.unit
def test_middleware_sets_principal_on_success(
    rsa_keys: tuple[Any, Any], validator: JWTValidator
) -> None:
    private, _ = rsa_keys
    token = _make_token(private, sub="agent:prod-triage-agent")
    client = TestClient(_build_app(validator))
    response = client.get("/whoami", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert response.json() == {"principal": "agent:prod-triage-agent"}


@pytest.mark.unit
def test_get_current_principal_falls_back_to_env(monkeypatch: pytest.MonkeyPatch) -> None:
    # No middleware in this test → contextvar default is None → env fallback.
    current_principal.set(None)
    monkeypatch.setenv("TRIAGE_PRINCIPAL", "stdio-tester")
    assert get_current_principal() == "stdio-tester"


@pytest.mark.unit
def test_get_current_principal_uses_contextvar_when_set() -> None:
    token = current_principal.set("agent:override")
    try:
        assert get_current_principal() == "agent:override"
    finally:
        current_principal.reset(token)


# ---------------------------------------------------------------------------
# Bootstrap-gate middleware: returns 503 on /mcp/* until the issuer is set.
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_issuer_is_configured_rejects_placeholder() -> None:
    assert issuer_is_configured("https://identity.example.com") is True
    assert issuer_is_configured("PLACEHOLDER_FILL_VIA_PROVISIONING_SCRIPT") is False
    assert issuer_is_configured("") is False
    assert issuer_is_configured(None) is False


def _build_bootstrap_app() -> Starlette:
    async def whoami(_request: Request) -> JSONResponse:
        return JSONResponse({"principal": "should-not-be-reached"})

    async def health(_request: Request) -> JSONResponse:
        return JSONResponse({"ok": True})

    app = Starlette(routes=[Route("/whoami", whoami), Route("/health", health)])
    app.add_middleware(BootstrapGateMiddleware)
    return app


@pytest.mark.unit
def test_bootstrap_gate_returns_503_on_mcp_paths() -> None:
    client = TestClient(_build_bootstrap_app())
    response = client.get("/whoami")
    assert response.status_code == 503
    assert response.json()["error"] == "service_bootstrapping"
    assert response.headers.get("retry-after") == "30"


@pytest.mark.unit
def test_bootstrap_gate_allows_health() -> None:
    client = TestClient(_build_bootstrap_app())
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"ok": True}


@pytest.mark.unit
def test_bootstrap_gate_503s_even_with_bearer_token() -> None:
    """An attacker presenting a Bearer token during bootstrap must still 503."""
    client = TestClient(_build_bootstrap_app())
    response = client.post("/whoami", headers={"Authorization": "Bearer not-checked"})
    assert response.status_code == 503

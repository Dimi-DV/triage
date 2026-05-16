"""Tests for the Slack WebClient factory."""

from __future__ import annotations

import json
from typing import Any

import pytest

from triage.shared import slack as slack_module
from triage.shared.slack import _reset_for_tests, get_slack_client


@pytest.fixture(autouse=True)
def _reset_client() -> None:
    _reset_for_tests()


@pytest.mark.unit
def test_get_slack_client_loads_token_from_secret(
    moto_aws_session: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    secrets = moto_aws_session.client("secretsmanager", region_name="us-east-1")
    secret_name = "prod-triage-slack-bot-token"  # pragma: allowlist secret
    secrets.create_secret(
        Name=secret_name,
        SecretString=json.dumps({"bot_token": "xoxb-test-1234567890"}),  # pragma: allowlist secret
    )
    monkeypatch.setenv("TRIAGE_SLACK_SECRET_ID", secret_name)

    client = get_slack_client()
    assert client.token == "xoxb-test-1234567890"


@pytest.mark.unit
def test_get_slack_client_is_cached(moto_aws_session: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    secrets = moto_aws_session.client("secretsmanager", region_name="us-east-1")
    secrets.create_secret(
        Name="cached-secret", SecretString=json.dumps({"bot_token": "xoxb-cached"})
    )
    monkeypatch.setenv("TRIAGE_SLACK_SECRET_ID", "cached-secret")

    first = get_slack_client()
    second = get_slack_client()
    assert first is second


@pytest.mark.unit
def test_get_slack_client_raises_without_secret_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("TRIAGE_SLACK_SECRET_ID", raising=False)
    with pytest.raises(RuntimeError, match="TRIAGE_SLACK_SECRET_ID"):
        get_slack_client()


@pytest.mark.unit
def test_get_slack_client_rejects_malformed_payload(
    moto_aws_session: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    secrets = moto_aws_session.client("secretsmanager", region_name="us-east-1")
    secrets.create_secret(Name="bad-shape", SecretString=json.dumps({"wrong_key": "xoxb-..."}))
    monkeypatch.setenv("TRIAGE_SLACK_SECRET_ID", "bad-shape")

    with pytest.raises(RuntimeError, match="bot_token"):
        get_slack_client()


@pytest.mark.unit
def test_get_slack_client_rejects_non_xoxb_token(
    moto_aws_session: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    secrets = moto_aws_session.client("secretsmanager", region_name="us-east-1")
    secrets.create_secret(
        Name="user-token",
        SecretString=json.dumps({"bot_token": "xoxp-user-token-not-allowed"}),
    )
    monkeypatch.setenv("TRIAGE_SLACK_SECRET_ID", "user-token")

    with pytest.raises(RuntimeError, match="bot_token"):
        get_slack_client()


@pytest.mark.unit
def test_reset_for_tests_clears_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    # Force the module-level cache to a sentinel, then prove _reset clears it.
    slack_module._client = object()  # type: ignore[assignment]
    _reset_for_tests()
    assert slack_module._client is None

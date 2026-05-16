"""Tests for runbooks_api_post_to_slack."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock

import pytest
from slack_sdk.errors import SlackApiError
from slack_sdk.web import SlackResponse

from triage.mcp_server.runbooks_api.post_to_slack import (
    SlackMessage,
    runbooks_api_post_to_slack,
)
from triage.shared import slack as slack_module
from triage.shared.errors import RunbooksApiError


@pytest.fixture(autouse=True)
def _reset_slack_cache() -> None:
    slack_module._reset_for_tests()


@pytest.fixture
def aws_env(moto_aws_session: Any, monkeypatch: pytest.MonkeyPatch) -> Any:
    """Provision the audit bucket + Slack bot-token secret in moto."""
    s3 = moto_aws_session.client("s3", region_name="us-east-1")
    s3.create_bucket(Bucket="triage-audit-test")
    monkeypatch.setenv("TRIAGE_AUDIT_BUCKET", "triage-audit-test")

    secrets = moto_aws_session.client("secretsmanager", region_name="us-east-1")
    secrets.create_secret(
        Name="prod-triage-slack-bot-token",
        SecretString=json.dumps({"bot_token": "xoxb-test-token"}),
    )
    monkeypatch.setenv("TRIAGE_SLACK_SECRET_ID", "prod-triage-slack-bot-token")
    monkeypatch.setenv("TRIAGE_PRINCIPAL", "agent:test")
    return moto_aws_session


def _ok_response(channel: str = "C123", ts: str = "1234567890.000100") -> SlackResponse:
    return SlackResponse(
        client=None,
        http_verb="POST",
        api_url="https://slack.com/api/chat.postMessage",
        req_args={},
        data={"ok": True, "channel": channel, "ts": ts, "message": {}},
        headers={},
        status_code=200,
    )


def _build_message(**overrides: Any) -> SlackMessage:
    base: dict[str, Any] = {
        "severity": "warning",
        "alarm_name": "prod-cpu-high",
        "summary": "CPU above 90% for 5 minutes",
        "diagnosis": "Single instance saturated; ASG not yet scaled",
        "metrics_observed": [
            {
                "namespace": "AWS/EC2",
                "name": "CPUUtilization",
                "value": 94.2,
                "statistic": "Average",
                "unit": "Percent",
            }
        ],
        "recommended_action": "Trigger ASG scale-out manually",
        "channel": "#triage-alerts",
    }
    base.update(overrides)
    return SlackMessage(**base)


@pytest.mark.unit
def test_post_to_slack_emits_audit_then_posts(
    aws_env: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_client = MagicMock()
    fake_client.chat_postMessage = MagicMock(return_value=_ok_response())
    monkeypatch.setattr(
        "triage.mcp_server.runbooks_api.post_to_slack.get_slack_client",
        lambda: fake_client,
    )

    result = runbooks_api_post_to_slack(_build_message())

    assert result["channel"] == "C123"
    assert result["ts"] == "1234567890.000100"
    assert result["audit_key"].startswith("events/")
    assert result["audit_key"].endswith(".json")

    # Audit object actually exists.
    s3 = aws_env.client("s3", region_name="us-east-1")
    obj = s3.get_object(Bucket="triage-audit-test", Key=result["audit_key"])
    event = json.loads(obj["Body"].read())
    assert event["tool_id"] == "runbooks_api_post_to_slack"
    assert event["principal"] == "agent:test"

    # Slack was called with the expected channel and blocks.
    call = fake_client.chat_postMessage.call_args
    assert call.kwargs["channel"] == "#triage-alerts"
    blocks = call.kwargs["blocks"]
    header = blocks[0]["text"]["text"]
    assert "WARNING" in header
    assert "prod-cpu-high" in header


@pytest.mark.unit
def test_post_to_slack_does_not_post_if_audit_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # No audit bucket env -> emit_audit_event raises RuntimeError before any
    # Slack call is attempted.
    monkeypatch.delenv("TRIAGE_AUDIT_BUCKET", raising=False)
    fake_client = MagicMock()
    monkeypatch.setattr(
        "triage.mcp_server.runbooks_api.post_to_slack.get_slack_client",
        lambda: fake_client,
    )

    with pytest.raises(RuntimeError, match="TRIAGE_AUDIT_BUCKET"):
        runbooks_api_post_to_slack(_build_message())

    fake_client.chat_postMessage.assert_not_called()


@pytest.mark.unit
def test_post_to_slack_wraps_slack_errors(aws_env: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    slack_response = SlackResponse(
        client=None,
        http_verb="POST",
        api_url="https://slack.com/api/chat.postMessage",
        req_args={},
        data={"ok": False, "error": "channel_not_found"},
        headers={},
        status_code=200,
    )
    fake_client = MagicMock()
    fake_client.chat_postMessage = MagicMock(
        side_effect=SlackApiError("channel_not_found", response=slack_response)
    )
    monkeypatch.setattr(
        "triage.mcp_server.runbooks_api.post_to_slack.get_slack_client",
        lambda: fake_client,
    )

    with pytest.raises(RunbooksApiError) as excinfo:
        runbooks_api_post_to_slack(_build_message())

    assert excinfo.value.code == "channel_not_found"
    assert excinfo.value.details["slack_error"] == "channel_not_found"

    # The audit event was still written before the failed post.
    s3 = aws_env.client("s3", region_name="us-east-1")
    listed = s3.list_objects_v2(Bucket="triage-audit-test")
    assert listed.get("KeyCount", 0) == 1


@pytest.mark.unit
def test_post_to_slack_omits_optional_blocks(aws_env: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """Messages with no metrics/recommended_action skip those blocks."""
    fake_client = MagicMock()
    fake_client.chat_postMessage = MagicMock(return_value=_ok_response())
    monkeypatch.setattr(
        "triage.mcp_server.runbooks_api.post_to_slack.get_slack_client",
        lambda: fake_client,
    )

    msg = _build_message(metrics_observed=[], recommended_action=None)
    runbooks_api_post_to_slack(msg)

    blocks = fake_client.chat_postMessage.call_args.kwargs["blocks"]
    rendered = json.dumps(blocks)
    assert "Metrics observed" not in rendered
    assert "Recommended action" not in rendered

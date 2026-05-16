"""Tests for emit_audit_event."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import pytest

from triage.shared.audit import emit_audit_event


@pytest.mark.unit
def test_emit_audit_event_writes_object(
    moto_aws_session: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    s3 = moto_aws_session.client("s3", region_name="us-east-1")
    s3.create_bucket(Bucket="triage-audit-test")
    monkeypatch.setenv("TRIAGE_AUDIT_BUCKET", "triage-audit-test")

    key = emit_audit_event(
        tool_id="runbooks_api_post_to_slack",
        principal="agent:prod-triage-agent",
        args={"channel": "#triage-alerts", "severity": "warning"},
        summary="warning:demo-alarm -> #triage-alerts",
    )

    today = datetime.now(UTC)
    expected_prefix = f"events/{today.year:04d}/{today.month:02d}/{today.day:02d}/"
    assert key.startswith(expected_prefix)
    assert key.endswith(".json")

    body = s3.get_object(Bucket="triage-audit-test", Key=key)["Body"].read()
    event = json.loads(body)
    assert event["tool_id"] == "runbooks_api_post_to_slack"
    assert event["principal"] == "agent:prod-triage-agent"
    assert event["args"] == {"channel": "#triage-alerts", "severity": "warning"}
    assert event["summary"].startswith("warning:demo-alarm")
    assert "event_id" in event
    assert "timestamp" in event


@pytest.mark.unit
def test_emit_audit_event_raises_without_bucket_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("TRIAGE_AUDIT_BUCKET", raising=False)
    with pytest.raises(RuntimeError, match="TRIAGE_AUDIT_BUCKET"):
        emit_audit_event("t", "p", {}, "s")


@pytest.mark.unit
def test_emit_audit_event_propagates_s3_failure(
    moto_aws_session: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Point at a bucket that does not exist; S3 raises NoSuchBucket.
    monkeypatch.setenv("TRIAGE_AUDIT_BUCKET", "nonexistent-bucket-xyz")
    with pytest.raises(Exception) as excinfo:
        emit_audit_event("t", "p", {}, "s")
    assert "NoSuchBucket" in str(excinfo.value) or "NoSuchBucket" in repr(excinfo.value)

"""Unit tests for logs_api_filter_log_events."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from botocore.exceptions import ClientError

from triage.mcp_server.logs_api.filter_log_events import logs_api_filter_log_events
from triage.shared.errors import LogsApiError


@pytest.fixture
def moto_logs(aws_credentials_env: None) -> Any:
    """Yield a moto-mocked CloudWatch Logs client bound to us-east-1."""
    from moto import mock_aws

    with mock_aws():
        import boto3

        client = boto3.client("logs", region_name="us-east-1")
        yield client


@pytest.mark.unit
def test_filter_log_events_returns_seeded_events(moto_logs: Any) -> None:
    log_group = "/triage/test"
    log_stream = "stream-1"
    moto_logs.create_log_group(logGroupName=log_group)
    moto_logs.create_log_stream(logGroupName=log_group, logStreamName=log_stream)

    base_ms = int(datetime.now(UTC).timestamp() * 1000)
    moto_logs.put_log_events(
        logGroupName=log_group,
        logStreamName=log_stream,
        logEvents=[
            {"timestamp": base_ms - 60_000, "message": "INFO startup"},
            {"timestamp": base_ms - 30_000, "message": "ERROR connection refused"},
            {"timestamp": base_ms - 10_000, "message": "INFO heartbeat"},
        ],
    )

    end = datetime.now(UTC)
    start = end - timedelta(minutes=5)
    result = logs_api_filter_log_events(
        log_group_name=log_group,
        start_time=start,
        end_time=end,
    )

    assert result["log_group_name"] == log_group
    assert result["event_count"] == 3
    messages = [e["message"] for e in result["events"]]
    assert "INFO startup" in messages
    assert "ERROR connection refused" in messages
    # ISO-8601 timestamps with tz
    for ev in result["events"]:
        assert ev["timestamp"] is not None
        assert ev["timestamp"].endswith("+00:00")
        assert ev["log_stream_name"] == log_stream
        assert ev["message_truncated"] is False


@pytest.mark.unit
def test_filter_log_events_filter_pattern_narrows(moto_logs: Any) -> None:
    log_group = "/triage/test"
    log_stream = "stream-1"
    moto_logs.create_log_group(logGroupName=log_group)
    moto_logs.create_log_stream(logGroupName=log_group, logStreamName=log_stream)
    base_ms = int(datetime.now(UTC).timestamp() * 1000)
    moto_logs.put_log_events(
        logGroupName=log_group,
        logStreamName=log_stream,
        logEvents=[
            {"timestamp": base_ms - 60_000, "message": "INFO startup"},
            {"timestamp": base_ms - 30_000, "message": "ERROR connection refused"},
        ],
    )

    end = datetime.now(UTC)
    start = end - timedelta(minutes=5)
    result = logs_api_filter_log_events(
        log_group_name=log_group,
        start_time=start,
        end_time=end,
        filter_pattern="ERROR",
    )

    messages = [e["message"] for e in result["events"]]
    assert "ERROR connection refused" in messages
    assert "INFO startup" not in messages


@pytest.mark.unit
def test_filter_log_events_truncates_long_messages(moto_logs: Any) -> None:
    log_group = "/triage/test"
    log_stream = "stream-1"
    moto_logs.create_log_group(logGroupName=log_group)
    moto_logs.create_log_stream(logGroupName=log_group, logStreamName=log_stream)
    long_msg = "X" * 5000
    moto_logs.put_log_events(
        logGroupName=log_group,
        logStreamName=log_stream,
        logEvents=[
            {"timestamp": int(datetime.now(UTC).timestamp() * 1000), "message": long_msg},
        ],
    )

    end = datetime.now(UTC) + timedelta(minutes=1)
    start = end - timedelta(minutes=5)
    result = logs_api_filter_log_events(
        log_group_name=log_group,
        start_time=start,
        end_time=end,
    )

    assert result["event_count"] == 1
    ev = result["events"][0]
    assert ev["message_truncated"] is True
    assert len(ev["message"]) == 1500


@pytest.mark.unit
def test_filter_log_events_caps_limit(moto_logs: Any) -> None:
    """`limit` is hard-capped at 100 regardless of the caller-requested value."""
    from triage.mcp_server.logs_api import filter_log_events as mod

    captured: dict[str, Any] = {}

    class FakeClient:
        def filter_log_events(self, **kwargs: Any) -> dict[str, Any]:
            captured.update(kwargs)
            return {"events": [], "searchedLogStreams": []}

    import pytest as _pytest

    monkey = _pytest.MonkeyPatch()
    try:
        monkey.setattr(mod, "get_logs_client", lambda: FakeClient())
        logs_api_filter_log_events(
            log_group_name="/triage/test",
            start_time=datetime.now(UTC) - timedelta(minutes=5),
            end_time=datetime.now(UTC),
            limit=999,
        )
    finally:
        monkey.undo()

    assert captured["limit"] == 100


@pytest.mark.unit
def test_filter_log_events_wraps_client_error(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeClient:
        def filter_log_events(self, **kwargs: Any) -> dict[str, Any]:
            raise ClientError(
                error_response={
                    "Error": {
                        "Code": "ResourceNotFoundException",
                        "Message": "log group does not exist",
                    }
                },
                operation_name="FilterLogEvents",
            )

    monkeypatch.setattr(
        "triage.mcp_server.logs_api.filter_log_events.get_logs_client",
        lambda: FakeClient(),
    )

    with pytest.raises(LogsApiError) as exc_info:
        logs_api_filter_log_events(
            log_group_name="/triage/nope",
            start_time=datetime.now(UTC) - timedelta(minutes=5),
            end_time=datetime.now(UTC),
        )

    err = exc_info.value
    assert err.code == "ResourceNotFoundException"
    assert err.details["operation"] == "FilterLogEvents"

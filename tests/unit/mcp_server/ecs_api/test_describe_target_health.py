"""Unit tests for ecs_api_describe_target_health.

Moto's elbv2 mock returns registered-target state but does not actually run
health checks, so the happy path here mocks the boto3 client directly. That
keeps the test focused on the wrapper's flattening + the `port` /
`health_check_port` carry-through that the agent depends on to diagnose
port-mismatch outages.
"""

from __future__ import annotations

from typing import Any

import pytest
from botocore.exceptions import ClientError

from triage.mcp_server.ecs_api.describe_target_health import (
    ecs_api_describe_target_health,
)
from triage.shared.errors import EcsApiError


@pytest.mark.unit
def test_describe_target_health_flattens_and_carries_ports(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeClient:
        def describe_target_health(self, **kwargs: Any) -> dict[str, Any]:
            assert kwargs == {"TargetGroupArn": "arn:fake:tg"}
            return {
                "TargetHealthDescriptions": [
                    {
                        "Target": {
                            "Id": "10.0.10.159",
                            "Port": 80,
                            "AvailabilityZone": "us-east-1a",
                        },
                        "HealthCheckPort": "8081",
                        "TargetHealth": {
                            "State": "unhealthy",
                            "Reason": "Target.FailedHealthChecks",
                            "Description": "Health checks failed",
                        },
                    }
                ]
            }

    monkeypatch.setattr(
        "triage.mcp_server.ecs_api.describe_target_health.get_elbv2_client",
        lambda: FakeClient(),
    )

    result = ecs_api_describe_target_health(target_group_arn="arn:fake:tg")

    assert result["target_group_arn"] == "arn:fake:tg"
    assert len(result["targets"]) == 1
    target = result["targets"][0]
    # The two fields the agent compares to diagnose a port mismatch:
    assert target["port"] == 80
    assert target["health_check_port"] == "8081"
    assert target["state"] == "unhealthy"
    assert target["reason"] == "Target.FailedHealthChecks"


@pytest.mark.unit
def test_describe_target_health_wraps_client_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeClient:
        def describe_target_health(self, **kwargs: Any) -> dict[str, Any]:
            raise ClientError(
                error_response={
                    "Error": {
                        "Code": "TargetGroupNotFound",
                        "Message": "Target group does not exist",
                    }
                },
                operation_name="DescribeTargetHealth",
            )

    monkeypatch.setattr(
        "triage.mcp_server.ecs_api.describe_target_health.get_elbv2_client",
        lambda: FakeClient(),
    )

    with pytest.raises(EcsApiError) as exc_info:
        ecs_api_describe_target_health(target_group_arn="arn:fake:missing")

    err = exc_info.value
    assert err.code == "TargetGroupNotFound"
    assert err.details["operation"] == "DescribeTargetHealth"


@pytest.mark.unit
def test_describe_target_health_empty_target_group(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeClient:
        def describe_target_health(self, **kwargs: Any) -> dict[str, Any]:
            return {"TargetHealthDescriptions": []}

    monkeypatch.setattr(
        "triage.mcp_server.ecs_api.describe_target_health.get_elbv2_client",
        lambda: FakeClient(),
    )

    result = ecs_api_describe_target_health(target_group_arn="arn:fake:empty")
    assert result["targets"] == []

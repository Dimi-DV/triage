"""Unit tests for metrics_api_get_metric_statistics."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from botocore.exceptions import ClientError

from triage.mcp_server.metrics_api.get_metric_statistics import (
    Dimension,
    metrics_api_get_metric_statistics,
)
from triage.shared.errors import MetricsApiError


@pytest.mark.unit
def test_get_metric_statistics_returns_seeded_datapoints(moto_cloudwatch: Any) -> None:
    end = datetime.now(UTC).replace(microsecond=0)
    start = end - timedelta(minutes=10)
    moto_cloudwatch.put_metric_data(
        Namespace="AWS/EC2",
        MetricData=[
            {
                "MetricName": "CPUUtilization",
                "Dimensions": [{"Name": "InstanceId", "Value": "i-0abc"}],
                "Timestamp": end - timedelta(minutes=5),
                "Value": 73.5,
                "Unit": "Percent",
            }
        ],
    )

    result = metrics_api_get_metric_statistics(
        namespace="AWS/EC2",
        metric_name="CPUUtilization",
        start_time=start,
        end_time=end,
        period=60,
        statistics=["Average", "Maximum"],
        dimensions=[Dimension(name="InstanceId", value="i-0abc")],
    )

    assert result["label"] == "CPUUtilization"
    assert isinstance(result["datapoints"], list)
    assert len(result["datapoints"]) >= 1
    dp = result["datapoints"][0]
    assert "Timestamp" in dp
    assert isinstance(dp["Timestamp"], str)
    assert dp["Average"] == pytest.approx(73.5)


@pytest.mark.unit
def test_get_metric_statistics_wraps_client_error(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeClient:
        def get_metric_statistics(self, **kwargs: Any) -> dict[str, Any]:
            raise ClientError(
                error_response={
                    "Error": {"Code": "InvalidParameterValue", "Message": "bad period"}
                },
                operation_name="GetMetricStatistics",
            )

    monkeypatch.setattr(
        "triage.mcp_server.metrics_api.get_metric_statistics.get_cloudwatch_client",
        lambda: FakeClient(),
    )

    with pytest.raises(MetricsApiError) as exc_info:
        metrics_api_get_metric_statistics(
            namespace="AWS/EC2",
            metric_name="CPUUtilization",
            start_time=datetime.now(UTC) - timedelta(minutes=5),
            end_time=datetime.now(UTC),
            period=60,
            statistics=["Average"],
            dimensions=None,
        )

    err = exc_info.value
    assert err.code == "InvalidParameterValue"
    assert err.details["operation"] == "GetMetricStatistics"

"""metrics_api_get_metric_statistics — query CloudWatch GetMetricStatistics.

Read-only: agent collects metric datapoints to reason about an incident.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from triage.mcp_server.server import mcp
from triage.shared.aws import get_cloudwatch_client
from triage.shared.errors import MetricsApiError, wrap_boto_error
from triage.shared.otel import tool_span

TOOL_ID = "metrics_api_get_metric_statistics"

Statistic = Literal["Average", "Sum", "Minimum", "Maximum", "SampleCount"]


class Dimension(BaseModel):
    """CloudWatch dimension. Translates to the boto3 `{"Name", "Value"}` shape."""

    name: str = Field(description="Dimension name, e.g. 'InstanceId'")
    value: str = Field(description="Dimension value, e.g. 'i-0abc'")


@mcp.tool(
    name=TOOL_ID,
    description=(
        "Query CloudWatch GetMetricStatistics for a metric over a time window. "
        "Read-only. Period must be a multiple of 60 seconds."
    ),
)
def metrics_api_get_metric_statistics(
    namespace: str,
    metric_name: str,
    start_time: datetime,
    end_time: datetime,
    period: int,
    statistics: list[Statistic],
    dimensions: list[Dimension] | None = None,
) -> dict[str, Any]:
    with tool_span(
        TOOL_ID,
        namespace=namespace,
        metric_name=metric_name,
        period_seconds=period,
        statistics=",".join(statistics),
    ):
        client = get_cloudwatch_client()
        try:
            response = client.get_metric_statistics(
                Namespace=namespace,
                MetricName=metric_name,
                Dimensions=[{"Name": d.name, "Value": d.value} for d in (dimensions or [])],
                StartTime=start_time,
                EndTime=end_time,
                Period=period,
                Statistics=statistics,
            )
        except Exception as exc:
            raise wrap_boto_error(exc, MetricsApiError) from exc

        datapoints: list[dict[str, Any]] = []
        for raw in response.get("Datapoints", []):
            dp: dict[str, Any] = {}
            for key, val in raw.items():
                dp[key] = val.isoformat() if isinstance(val, datetime) else val
            datapoints.append(dp)

        return {
            "label": response.get("Label", metric_name),
            "datapoints": datapoints,
        }

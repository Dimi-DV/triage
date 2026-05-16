"""End-to-end smoke test for the MCP server.

Spins up an in-memory MCP client/server pair (no subprocess), seeds a
synthetic CloudWatch metric via moto, invokes the registered tool, and
verifies both the response shape and that an OTel span was emitted.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from mcp.shared.memory import create_connected_server_and_client_session

from triage.mcp_server import (  # noqa: F401  (registration side-effect)
    ecs_api,
    logs_api,
    metrics_api,
    runbooks_api,
)
from triage.mcp_server.server import mcp


@pytest.mark.integration
async def test_list_and_invoke_metrics_tool(
    moto_cloudwatch: Any,
    otel_in_memory_exporter: Any,
) -> None:
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

    async with create_connected_server_and_client_session(mcp) as session:
        tools = await session.list_tools()
        by_name = {t.name: t for t in tools.tools}
        assert "metrics_api_get_metric_statistics" in by_name, (
            f"expected metrics tool registered, got {list(by_name)}"
        )

        schema = by_name["metrics_api_get_metric_statistics"].inputSchema
        assert schema is not None
        properties = schema.get("properties", {})
        for required_param in (
            "namespace",
            "metric_name",
            "start_time",
            "end_time",
            "period",
            "statistics",
            "dimensions",
        ):
            assert required_param in properties, f"missing input param {required_param}"
        assert "$defs" in schema, "expected nested Dimension model under $defs"

        call_result = await session.call_tool(
            "metrics_api_get_metric_statistics",
            arguments={
                "namespace": "AWS/EC2",
                "metric_name": "CPUUtilization",
                "start_time": start.isoformat(),
                "end_time": end.isoformat(),
                "period": 60,
                "statistics": ["Average", "Maximum"],
                "dimensions": [{"name": "InstanceId", "value": "i-0abc"}],
            },
        )

        assert not call_result.isError, f"tool returned error: {call_result.content}"
        payload = call_result.structuredContent
        assert payload is not None
        assert payload["label"] == "CPUUtilization"
        assert isinstance(payload["datapoints"], list)
        assert len(payload["datapoints"]) >= 1
        dp = payload["datapoints"][0]
        assert dp["Average"] == pytest.approx(73.5)

    spans = otel_in_memory_exporter.get_finished_spans()
    tool_spans = [s for s in spans if s.name == "metrics_api_get_metric_statistics"]
    assert len(tool_spans) == 1
    span = tool_spans[0]
    assert span.attributes is not None
    assert span.attributes.get("namespace") == "AWS/EC2"
    assert span.attributes.get("metric_name") == "CPUUtilization"
    assert span.attributes.get("period_seconds") == 60

"""ecs_api_describe_target_health — read-only target-group health snapshot.

Wraps `elbv2.DescribeTargetHealth`. Returned shape per target carries
`port` (the port targets register on — for ECS this is the container port)
and `health_check_port` (the port the load balancer actually probes), so
the agent can detect mismatches between the two without a second call.
"""

from __future__ import annotations

from typing import Any

from triage.mcp_server.server import mcp
from triage.shared.aws import get_elbv2_client
from triage.shared.errors import EcsApiError, wrap_boto_error
from triage.shared.otel import tool_span

TOOL_ID = "ecs_api_describe_target_health"


@mcp.tool(
    name=TOOL_ID,
    description=(
        "Describe target health for an ALB/NLB target group. Read-only. "
        "Returns per-target state, the registered port, the health-check "
        "port the load balancer probes, and the failure reason if any. "
        "Use this to diagnose UnHealthyHostCount alarms."
    ),
)
def ecs_api_describe_target_health(target_group_arn: str) -> dict[str, Any]:
    with tool_span(TOOL_ID, target_group_arn=target_group_arn):
        client = get_elbv2_client()
        try:
            response = client.describe_target_health(TargetGroupArn=target_group_arn)
        except Exception as exc:
            raise wrap_boto_error(exc, EcsApiError) from exc

        targets: list[dict[str, Any]] = []
        for raw in response.get("TargetHealthDescriptions", []):
            target = raw.get("Target", {})
            health = raw.get("TargetHealth", {})
            targets.append(
                {
                    "target_id": target.get("Id"),
                    "port": target.get("Port"),
                    "availability_zone": target.get("AvailabilityZone"),
                    "health_check_port": raw.get("HealthCheckPort"),
                    "state": health.get("State"),
                    "reason": health.get("Reason"),
                    "description": health.get("Description"),
                }
            )

        return {
            "target_group_arn": target_group_arn,
            "targets": targets,
        }

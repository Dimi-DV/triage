"""ecs_api_describe_task_definition — read-only task-definition snapshot.

Wraps `ecs.DescribeTaskDefinition`. The flattened return surfaces only the
fields the agent uses for diagnosis: family/revision identity, networkMode,
the role ARNs, and a trimmed container list carrying container ports
(`portMappings[].containerPort`), the boto3 `healthCheck` block, and the
container `environment` (env vars). This is the partner-tool to
`ecs_api_describe_target_health`: when target health shows a registered-port
vs health-check-port split, the task definition confirms which side is wrong.
"""

from __future__ import annotations

from typing import Any

from triage.mcp_server.server import mcp
from triage.shared.aws import get_ecs_client
from triage.shared.errors import EcsApiError, wrap_boto_error
from triage.shared.otel import tool_span

TOOL_ID = "ecs_api_describe_task_definition"


@mcp.tool(
    name=TOOL_ID,
    description=(
        "Describe an ECS task definition. Read-only. Accepts ARN, family, or "
        "'family:revision'. Returns family/revision/status, networkMode, role "
        "ARNs, and per-container port mappings, health checks, and env vars. "
        "Use after ecs_api_describe_target_health when the target group's "
        "health-check port differs from the registered port — this confirms "
        "which container port the task is actually listening on."
    ),
)
def ecs_api_describe_task_definition(task_definition: str) -> dict[str, Any]:
    with tool_span(TOOL_ID, task_definition=task_definition):
        client = get_ecs_client()
        try:
            response = client.describe_task_definition(taskDefinition=task_definition)
        except Exception as exc:
            raise wrap_boto_error(exc, EcsApiError) from exc

        task_def = response.get("taskDefinition", {})

        containers: list[dict[str, Any]] = []
        for raw in task_def.get("containerDefinitions", []):
            containers.append(
                {
                    "name": raw.get("name"),
                    "image": raw.get("image"),
                    "essential": raw.get("essential"),
                    "port_mappings": [
                        {
                            "container_port": pm.get("containerPort"),
                            "host_port": pm.get("hostPort"),
                            "protocol": pm.get("protocol"),
                        }
                        for pm in raw.get("portMappings", [])
                    ],
                    "health_check": raw.get("healthCheck"),
                    "environment": {
                        env.get("name"): env.get("value") for env in raw.get("environment", [])
                    },
                }
            )

        return {
            "task_definition_arn": task_def.get("taskDefinitionArn"),
            "family": task_def.get("family"),
            "revision": task_def.get("revision"),
            "status": task_def.get("status"),
            "network_mode": task_def.get("networkMode"),
            "task_role_arn": task_def.get("taskRoleArn"),
            "execution_role_arn": task_def.get("executionRoleArn"),
            "cpu": task_def.get("cpu"),
            "memory": task_def.get("memory"),
            "containers": containers,
        }

"""Unit tests for ecs_api_describe_task_definition.

Focuses on the wrapper's flattening: the per-container `port_mappings` shape
(containerPort/hostPort/protocol), the env-var dict, and the top-level
identity fields. The agent depends on this shape to reason about port
mismatches against ecs_api_describe_target_health.
"""

from __future__ import annotations

from typing import Any

import pytest
from botocore.exceptions import ClientError

from triage.mcp_server.ecs_api.describe_task_definition import (
    ecs_api_describe_task_definition,
)
from triage.shared.errors import EcsApiError


@pytest.mark.unit
def test_describe_task_definition_flattens_containers_and_ports(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeClient:
        def describe_task_definition(self, **kwargs: Any) -> dict[str, Any]:
            assert kwargs == {"taskDefinition": "dev-triage-broken:3"}
            return {
                "taskDefinition": {
                    "taskDefinitionArn": "arn:aws:ecs:us-east-1:1:task-definition/dev-triage-broken:3",
                    "family": "dev-triage-broken",
                    "revision": 3,
                    "status": "ACTIVE",
                    "networkMode": "awsvpc",
                    "taskRoleArn": "arn:aws:iam::1:role/task",
                    "executionRoleArn": "arn:aws:iam::1:role/exec",
                    "cpu": "256",
                    "memory": "512",
                    "containerDefinitions": [
                        {
                            "name": "web",
                            "image": "nginx:1.25",
                            "essential": True,
                            "portMappings": [
                                {"containerPort": 80, "hostPort": 80, "protocol": "tcp"},
                            ],
                            "healthCheck": {
                                "command": ["CMD-SHELL", "curl -f http://localhost/"],
                                "interval": 30,
                            },
                            "environment": [
                                {"name": "LOG_LEVEL", "value": "info"},
                                {"name": "PORT", "value": "80"},
                            ],
                        }
                    ],
                }
            }

    monkeypatch.setattr(
        "triage.mcp_server.ecs_api.describe_task_definition.get_ecs_client",
        lambda: FakeClient(),
    )

    result = ecs_api_describe_task_definition(task_definition="dev-triage-broken:3")

    assert result["family"] == "dev-triage-broken"
    assert result["revision"] == 3
    assert result["status"] == "ACTIVE"
    assert result["network_mode"] == "awsvpc"
    assert len(result["containers"]) == 1
    container = result["containers"][0]
    assert container["name"] == "web"
    assert container["image"] == "nginx:1.25"
    # The field the agent compares against the TG health-check port:
    assert container["port_mappings"] == [
        {"container_port": 80, "host_port": 80, "protocol": "tcp"},
    ]
    assert container["environment"] == {"LOG_LEVEL": "info", "PORT": "80"}


@pytest.mark.unit
def test_describe_task_definition_wraps_client_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeClient:
        def describe_task_definition(self, **kwargs: Any) -> dict[str, Any]:
            raise ClientError(
                error_response={
                    "Error": {
                        "Code": "ClientException",
                        "Message": "Unable to describe task definition.",
                    }
                },
                operation_name="DescribeTaskDefinition",
            )

    monkeypatch.setattr(
        "triage.mcp_server.ecs_api.describe_task_definition.get_ecs_client",
        lambda: FakeClient(),
    )

    with pytest.raises(EcsApiError) as exc_info:
        ecs_api_describe_task_definition(task_definition="does-not-exist")

    err = exc_info.value
    assert err.code == "ClientException"
    assert err.details["operation"] == "DescribeTaskDefinition"


@pytest.mark.unit
def test_describe_task_definition_multi_container(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeClient:
        def describe_task_definition(self, **kwargs: Any) -> dict[str, Any]:
            return {
                "taskDefinition": {
                    "taskDefinitionArn": "arn:aws:ecs:us-east-1:1:task-definition/multi:1",
                    "family": "multi",
                    "revision": 1,
                    "status": "ACTIVE",
                    "containerDefinitions": [
                        {
                            "name": "app",
                            "image": "app:1",
                            "portMappings": [
                                {"containerPort": 8080, "protocol": "tcp"},
                            ],
                        },
                        {
                            "name": "sidecar",
                            "image": "envoy:v1",
                            "portMappings": [],
                            "environment": [],
                        },
                    ],
                }
            }

    monkeypatch.setattr(
        "triage.mcp_server.ecs_api.describe_task_definition.get_ecs_client",
        lambda: FakeClient(),
    )

    result = ecs_api_describe_task_definition(task_definition="multi")
    assert [c["name"] for c in result["containers"]] == ["app", "sidecar"]
    assert result["containers"][0]["port_mappings"][0]["container_port"] == 8080
    assert result["containers"][1]["port_mappings"] == []
    assert result["containers"][1]["environment"] == {}

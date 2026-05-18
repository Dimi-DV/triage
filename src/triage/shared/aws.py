"""Typed boto3 client factories.

Region is pinned to us-east-1 (single-region build per the v3 spec) and a
short user-agent suffix tags traffic that originates from this server.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import boto3
from botocore.config import Config

if TYPE_CHECKING:
    from types_boto3_cloudwatch.client import CloudWatchClient
    from types_boto3_elbv2.client import ElasticLoadBalancingv2Client

AWS_REGION = "us-east-1"
USER_AGENT_SUFFIX = "triage-mcp-server/0.1.0"

_default_config = Config(
    region_name=AWS_REGION,
    user_agent_extra=USER_AGENT_SUFFIX,
    retries={"mode": "standard", "max_attempts": 3},
)


def get_cloudwatch_client() -> CloudWatchClient:
    return boto3.client("cloudwatch", config=_default_config)


def get_elbv2_client() -> ElasticLoadBalancingv2Client:
    return boto3.client("elbv2", config=_default_config)

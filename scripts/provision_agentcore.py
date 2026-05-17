#!/usr/bin/env python3
"""Provision AgentCore Runtime + Gateway + Workload Identity.

Terraform owns SNS, Lambda, ECS, ALB, IAM, ECR, and the Slack secret.
AgentCore Runtime, Gateway, and Workload Identity are managed services
configured through `bedrock-agentcore-control` boto3 calls. This script
wraps those calls in a reproducible, mostly-idempotent flow.

Auth model (verified 2026-05-17 against live API shapes):
  - Gateway uses authorizerType=AWS_IAM. Callers (alarm-bridge Lambda,
    AgentCore Runtime) sign requests with SigV4 using their existing IAM
    roles. No JWT issuer, no OAuth credential provider.
  - The original "OAuth 2.1 + Resource Indicators via AgentCore Identity"
    pattern in CLAUDE.md does not match the live API surface; there is
    no service-side OAuth issuer in bedrock-agentcore-control. The
    create_oauth2_credential_provider call is for outbound OAuth only
    (agent calling Google/Slack/etc.) and is not on Triage's path.

Steps:
  1. Read Terraform outputs from terraform/stack.
  2. Create the workload identity for the Triage agent.
  3. Create the Gateway (AWS_IAM authorizer) + MCP target pointing at the
     ALB /mcp endpoint.
  4. Create the AgentCore Runtime referencing the agent ECR image.
  5. Write the Runtime ARN to SSM (the Lambda reads it from there).

Deferred for follow-up:
  - Cedar policy enforcement at the Gateway. The CreateGateway API has no
    policyEngineConfiguration parameter; Cedar must be wired via a Lambda
    interceptor on the Gateway, or evaluated at the MCP server boundary.
    `cedar-policies/agent-tools.cedar` stays in the repo for that work.

Idempotency note: where we can detect an existing resource by name we
reuse it; otherwise we create-and-tolerate-Conflict.

Run with `make provision-agentcore` after Terraform applies cleanly and
both container images have been pushed.
"""

from __future__ import annotations

import argparse
import json
import logging
import pathlib
import subprocess
import sys
from typing import Any

import boto3
from botocore.exceptions import ClientError

log = logging.getLogger("provision_agentcore")

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
TERRAFORM_DIR = REPO_ROOT / "terraform" / "stack"
NAME_PREFIX = "prod-triage"
GATEWAY_TARGET_NAME = "TriageMcpGateway"
WORKLOAD_IDENTITY_NAME = "prod-triage-agent"


def _tf_outputs() -> dict[str, Any]:
    log.info("Reading Terraform outputs from %s", TERRAFORM_DIR)
    cmd = ["terraform", f"-chdir={TERRAFORM_DIR}", "output", "-json"]
    raw = subprocess.check_output(cmd)  # noqa: S603  (developer-run script, fixed argv)
    flat = {k: v["value"] for k, v in json.loads(raw).items()}
    log.info("Got %d outputs", len(flat))
    return flat


def _control_client() -> Any:
    return boto3.client("bedrock-agentcore-control", region_name="us-east-1")


def _ssm_client() -> Any:
    return boto3.client("ssm", region_name="us-east-1")


def _create_or_reuse(create_fn: Any, kwargs: dict[str, Any], resource: str) -> dict[str, Any]:
    """Call a control-plane create_* method, tolerating "already exists" errors.

    AgentCore APIs are inconsistent: some return ConflictException for an
    existing resource, others return ValidationException with "already
    exists" in the message. Treat both as reusable.
    """
    try:
        return dict(create_fn(**kwargs))
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        message = exc.response.get("Error", {}).get("Message", "")
        if code in {"ConflictException", "ResourceAlreadyExistsException"} or (
            code == "ValidationException" and "already exists" in message
        ):
            log.info("%s already exists; reusing", resource)
            return {}
        raise


def _create_workload_identity(control: Any, role_arn: str) -> str:
    log.info("Creating workload identity for the agent (role %s)", role_arn)
    # API shape (verified): only `name`, `allowedResourceOauth2ReturnUrls`,
    # `tags`. The IAM role is associated separately via the Runtime/Gateway
    # configuration, not at workload-identity create time.
    result = _create_or_reuse(
        control.create_workload_identity,
        {"name": WORKLOAD_IDENTITY_NAME},
        "Workload identity",
    )
    return str(result.get("workloadIdentityArn", ""))


def _create_gateway(control: Any, role_arn: str) -> tuple[str, str]:
    """Create (or reuse) the gateway and return (gatewayId, gatewayUrl).

    AWS_IAM authorizer: callers sign with SigV4 using their existing IAM
    roles. No authorizerConfiguration block is required (verified against
    live API shape). The Gateway's create_gateway API has no
    policyEngineConfiguration parameter — Cedar enforcement at the
    Gateway must use interceptorConfigurations (Lambda); deferred.
    """
    log.info("Creating AgentCore Gateway (AWS_IAM authorizer)")
    result = _create_or_reuse(
        control.create_gateway,
        {
            "name": GATEWAY_TARGET_NAME,
            "roleArn": role_arn,
            "protocolType": "MCP",
            "authorizerType": "AWS_IAM",
        },
        "Gateway",
    )
    gateway_id = str(result.get("gatewayIdentifier", ""))
    gateway_url = str(result.get("gatewayUrl", ""))
    if not gateway_url:
        # _create_or_reuse returns {} on conflict; fetch the existing record.
        existing = next(
            (
                g
                for g in control.list_gateways().get("items", [])
                if g.get("name") == GATEWAY_TARGET_NAME
            ),
            None,
        )
        if existing is None:
            raise RuntimeError(f"Gateway '{GATEWAY_TARGET_NAME}' not found after create_or_reuse")
        gateway_id = gateway_id or existing["gatewayId"]
        gateway_url = control.get_gateway(gatewayIdentifier=gateway_id)["gatewayUrl"]
    return gateway_id, gateway_url


def _create_mcp_target(control: Any, gateway_id: str, mcp_url: str) -> None:
    log.info("Creating MCP gateway target → %s", mcp_url)
    _create_or_reuse(
        control.create_gateway_target,
        {
            "gatewayIdentifier": gateway_id,
            "name": GATEWAY_TARGET_NAME,
            "targetConfiguration": {
                "mcp": {
                    "endpoint": mcp_url,
                    "transport": "STREAMABLE_HTTP",
                }
            },
        },
        "Gateway target",
    )


def _create_runtime(
    control: Any,
    role_arn: str,
    image_uri: str,
    audit_bucket: str,
    gateway_url: str,
) -> str:
    log.info("Creating AgentCore Runtime (image %s)", image_uri)
    result = _create_or_reuse(
        control.create_agent_runtime,
        {
            # agentRuntimeName regex is [a-zA-Z][a-zA-Z0-9_]{0,47} — no hyphens.
            "agentRuntimeName": f"{NAME_PREFIX.replace('-', '_')}_runtime",
            "agentRuntimeArtifact": {"containerConfiguration": {"containerUri": image_uri}},
            "roleArn": role_arn,
            "networkConfiguration": {"networkMode": "PUBLIC"},
            "protocolConfiguration": {"serverProtocol": "HTTP"},
            "environmentVariables": {
                "BEDROCK_MODEL_ID": "anthropic.claude-sonnet-4-6-v1:0",
                "TRIAGE_GATEWAY_URL": gateway_url,
                "TRIAGE_AUDIT_BUCKET": audit_bucket,
                "TRIAGE_PRINCIPAL": "agent:prod-triage-agent",
            },
        },
        "Runtime",
    )
    return str(result.get("agentRuntimeArn", ""))


def _write_runtime_arn(runtime_arn: str, param_name: str) -> None:
    log.info("Writing runtime ARN to SSM %s", param_name)
    _ssm_client().put_parameter(
        Name=param_name,
        Value=runtime_arn,
        Type="String",
        Overwrite=True,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print intended actions without contacting AWS.",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

    outputs = _tf_outputs()
    required = {
        "agent_runtime_role_arn",
        "agent_repository_url",
        "audit_bucket_name",
        "mcp_endpoint_url",
        "agentcore_runtime_arn_parameter",
    }
    missing = required - outputs.keys()
    if missing:
        log.error("Terraform outputs missing: %s. Apply Terraform first.", missing)
        return 1

    if args.dry_run:
        log.info("Dry run; would create runtime/gateway/identity with outputs %s", outputs)
        return 0

    control = _control_client()
    _create_workload_identity(control, outputs["agent_runtime_role_arn"])
    gateway_id, gateway_url = _create_gateway(control, outputs["agent_runtime_role_arn"])
    if gateway_id:
        _create_mcp_target(control, gateway_id, outputs["mcp_endpoint_url"])
    runtime_arn = _create_runtime(
        control,
        outputs["agent_runtime_role_arn"],
        f"{outputs['agent_repository_url']}:latest",
        outputs["audit_bucket_name"],
        gateway_url,
    )
    if runtime_arn:
        _write_runtime_arn(runtime_arn, outputs["agentcore_runtime_arn_parameter"])

    log.info("Provisioning complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

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
reuse it; otherwise we create-and-tolerate-Conflict. The Runtime branch
is special: `update_agent_runtime` is a FULL REPLACE (not a merge), so
on conflict we list-and-update with **every** field the create call would
have passed. Omitting `environmentVariables` on update wipes them and
the next agent invoke crashes on `os.environ[...]`. See
feedback_update_agent_runtime_replaces in memory.

Run with `make provision-agentcore` after Terraform applies cleanly and
both container images have been pushed. Rerunning is safe: existing
Runtime gets its image refreshed and env vars preserved.
"""

from __future__ import annotations

import argparse
import json
import logging
import pathlib
import subprocess
import sys
import time
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
    # CreateGateway returns `gatewayId` (verified via boto3 service model);
    # the inconsistent `gatewayIdentifier` we read previously was always empty
    # so the target step was silently skipped on a fresh create.
    gateway_id = str(result.get("gatewayId") or result.get("gatewayIdentifier", ""))
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
    """Register the MCP server as a gateway target.

    The targetConfiguration.mcp shape is a tagged union; we use the
    `mcpServer` variant so the gateway proxies tools/* calls through to
    the upstream Streamable HTTP MCP server at `mcp_url`. DYNAMIC listing
    mode forwards tools/list at request time instead of caching at
    create-time, so we don't need to pre-declare a tool schema.
    """
    log.info("Creating MCP gateway target → %s", mcp_url)
    _create_or_reuse(
        control.create_gateway_target,
        {
            "gatewayIdentifier": gateway_id,
            "name": GATEWAY_TARGET_NAME,
            "targetConfiguration": {
                "mcp": {
                    "mcpServer": {
                        "endpoint": mcp_url,
                        "listingMode": "DYNAMIC",
                    },
                },
            },
        },
        "Gateway target",
    )


RUNTIME_NAME = f"{NAME_PREFIX.replace('-', '_')}_runtime"
# agentRuntimeName regex is [a-zA-Z][a-zA-Z0-9_]{0,47} — no hyphens.


def _runtime_config(
    role_arn: str,
    image_uri: str,
    audit_bucket: str,
    gateway_url: str,
) -> dict[str, Any]:
    """Build the kwargs dict shared by create_agent_runtime and update_agent_runtime.

    Both APIs are full-shape: update wipes any field omitted, so callers must
    pass everything they passed at create time.

    BEDROCK_MODEL_ID is a cross-region inference profile, not a bare
    foundation-model id; Bedrock Converse for Claude requires this.
    """
    return {
        "agentRuntimeArtifact": {"containerConfiguration": {"containerUri": image_uri}},
        "roleArn": role_arn,
        "networkConfiguration": {"networkMode": "PUBLIC"},
        "protocolConfiguration": {"serverProtocol": "HTTP"},
        "environmentVariables": {
            "BEDROCK_MODEL_ID": "us.anthropic.claude-sonnet-4-5-20250929-v1:0",
            "TRIAGE_GATEWAY_URL": gateway_url,
            "TRIAGE_AUDIT_BUCKET": audit_bucket,
            "TRIAGE_PRINCIPAL": "agent:prod-triage-agent",
        },
    }


def _find_runtime_by_name(control: Any, name: str) -> tuple[str, str]:
    """Return (agentRuntimeId, agentRuntimeArn) for an existing runtime by name."""
    paginator = control.get_paginator("list_agent_runtimes")
    for page in paginator.paginate():
        for item in page.get("agentRuntimes", []):
            if item.get("agentRuntimeName") == name:
                return str(item["agentRuntimeId"]), str(item["agentRuntimeArn"])
    raise RuntimeError(f"Runtime '{name}' not found in list_agent_runtimes")


def _wait_for_runtime_ready(control: Any, runtime_id: str, timeout: int = 180) -> None:
    """Block until the Runtime reaches READY. UPDATING is non-terminal."""
    deadline = time.time() + timeout
    last_status = ""
    while time.time() < deadline:
        info = control.get_agent_runtime(agentRuntimeId=runtime_id)
        status = str(info.get("status", ""))
        if status != last_status:
            log.info("Runtime %s status=%s", runtime_id, status)
            last_status = status
        if status == "READY":
            return
        if status in {"CREATE_FAILED", "UPDATE_FAILED", "DELETE_FAILED"}:
            failure = info.get("failureReason", "<no reason>")
            raise RuntimeError(f"Runtime {runtime_id} entered {status}: {failure}")
        time.sleep(5)
    raise RuntimeError(f"Runtime {runtime_id} did not reach READY within {timeout}s")


def _create_runtime(
    control: Any,
    role_arn: str,
    image_uri: str,
    audit_bucket: str,
    gateway_url: str,
) -> str:
    """Create the Runtime, or update it in-place if it already exists.

    update_agent_runtime is a full replace: passing the same config as create
    refreshes the container image (busts AgentCore's image cache) and preserves
    env vars / role / network / protocol. Omitting any of those wipes them.
    """
    config = _runtime_config(role_arn, image_uri, audit_bucket, gateway_url)
    try:
        log.info("Creating AgentCore Runtime '%s' (image %s)", RUNTIME_NAME, image_uri)
        result = control.create_agent_runtime(agentRuntimeName=RUNTIME_NAME, **config)
        runtime_id = str(result["agentRuntimeId"])
        runtime_arn = str(result["agentRuntimeArn"])
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        message = exc.response.get("Error", {}).get("Message", "")
        is_conflict = code in {"ConflictException", "ResourceAlreadyExistsException"} or (
            code == "ValidationException" and "already exists" in message
        )
        if not is_conflict:
            raise
        log.info("Runtime exists; calling update_agent_runtime to refresh image + env vars")
        runtime_id, runtime_arn = _find_runtime_by_name(control, RUNTIME_NAME)
        result = control.update_agent_runtime(agentRuntimeId=runtime_id, **config)
        runtime_arn = str(result["agentRuntimeArn"])

    _wait_for_runtime_ready(control, runtime_id)
    return runtime_arn


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
    _write_runtime_arn(runtime_arn, outputs["agentcore_runtime_arn_parameter"])

    log.info("Provisioning complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

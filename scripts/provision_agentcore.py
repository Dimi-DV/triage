#!/usr/bin/env python3
"""Provision AgentCore Runtime + Gateway + Identity + Cedar.

Terraform owns SNS, Lambda, ECS, ALB, IAM, ECR, and the Slack secret.
AgentCore Runtime, Gateway, Identity, and the policy engine are managed
services configured through `bedrock-agentcore-control` boto3 calls.
This script wraps those calls in a reproducible, mostly-idempotent flow.

Steps:
  1. Read Terraform outputs from terraform/stack.
  2. Create the OAuth 2.1 credential provider (Identity).
  3. Create the workload identity for the Triage agent.
  4. Create the policy engine + upload Cedar policies.
  5. Create the Gateway + MCP target pointing at the ALB /mcp endpoint.
  6. Create the AgentCore Runtime referencing the agent ECR image.
  7. Write the Runtime ARN to SSM (the Lambda reads it from there).
  8. Update the MCP service task env with AGENTCORE_IDENTITY_ISSUER so
     auth can be re-enabled.

Idempotency note: the AgentCore SDK does not (yet) expose stable Get/Create
fingerprint primitives for every entity. Where we can detect an existing
resource by name we reuse it; otherwise we create-and-tolerate-Conflict.

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
CEDAR_DIR = REPO_ROOT / "cedar-policies"
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
    """Call a control-plane create_* method, tolerating ConflictException."""
    try:
        return dict(create_fn(**kwargs))
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        if code in {"ConflictException", "ResourceAlreadyExistsException"}:
            log.info("%s already exists; reusing", resource)
            return {}
        raise


def _create_oauth_provider(control: Any) -> tuple[str, str]:
    """Return (credential_provider_arn, issuer_url).

    The issuer URL is what the MCP server's JWT validator hits to fetch
    JWKS and what it accepts in the `iss` claim.
    """
    log.info("Creating OAuth 2.1 credential provider (resource = triage-mcp)")
    result = _create_or_reuse(
        control.create_oauth2_credential_provider,
        {
            "name": f"{NAME_PREFIX}-oauth",
            "credentialProviderVendor": "AGENTCORE_IDENTITY",
            "oauth2ProviderConfigInput": {
                "customOauth2ProviderConfig": {
                    "resourceIndicators": ["triage-mcp"],
                    "tokenLifetimeSeconds": 3600,
                }
            },
        },
        "OAuth provider",
    )
    arn = str(result.get("credentialProviderArn", ""))
    # The issuer URL shape depends on the AgentCore Identity SDK surface;
    # the create response should carry it, but field naming varies across
    # SDK versions. Fall back to deriving from the provider name if absent.
    issuer = str(
        result.get("issuerUrl")
        or result.get("issuer")
        or result.get("oauth2ProviderConfigOutput", {}).get("issuerUrl", "")
    )
    if not issuer:
        # TODO(day-35): once the create response stabilizes, drop this fallback.
        log.warning(
            "OAuth create response missing issuer URL field; using a derived "
            "placeholder. Update _create_oauth_provider once the API stabilizes."
        )
        issuer = f"https://identity.bedrock-agentcore.us-east-1.amazonaws.com/{NAME_PREFIX}-oauth"
    return arn, issuer


def _create_workload_identity(control: Any, role_arn: str) -> str:
    log.info("Creating workload identity for the agent (role %s)", role_arn)
    result = _create_or_reuse(
        control.create_workload_identity,
        {"name": WORKLOAD_IDENTITY_NAME, "allowedAudiences": ["triage-mcp"]},
        "Workload identity",
    )
    return str(result.get("workloadIdentityArn", ""))


def _create_policy_engine(control: Any) -> str:
    log.info("Creating Cedar policy engine")
    result = _create_or_reuse(
        control.create_policy_engine,
        {
            "name": f"{NAME_PREFIX}-cedar-engine",
            "engineType": "CEDAR",
        },
        "Policy engine",
    )
    return str(result.get("policyEngineId", ""))


def _upload_cedar_policies(control: Any, policy_engine_id: str) -> None:
    log.info("Uploading Cedar policies from %s", CEDAR_DIR)
    schema_path = CEDAR_DIR / "schema.cedarschema"
    schema_text = schema_path.read_text(encoding="utf-8") if schema_path.is_file() else ""

    for policy_file in sorted(CEDAR_DIR.glob("*.cedar")):
        log.info("  → %s", policy_file.name)
        _create_or_reuse(
            control.create_policy,
            {
                "name": policy_file.stem,
                "policyEngineId": policy_engine_id,
                "definition": {
                    "cedar": {
                        "policyText": policy_file.read_text(encoding="utf-8"),
                        "schemaText": schema_text,
                    }
                },
            },
            f"Policy {policy_file.name}",
        )


def _create_gateway(control: Any, role_arn: str, policy_engine_id: str) -> str:
    log.info("Creating AgentCore Gateway (policy engine %s)", policy_engine_id)
    result = _create_or_reuse(
        control.create_gateway,
        {
            "name": GATEWAY_TARGET_NAME,
            "roleArn": role_arn,
            "protocolType": "MCP",
            "authorizerType": "CUSTOM_JWT",
            "authorizerConfiguration": {
                "customJWTAuthorizer": {
                    "allowedAudience": ["triage-mcp"],
                }
            },
            "policyEngineConfiguration": {"policyEngineId": policy_engine_id},
        },
        "Gateway",
    )
    return str(result.get("gatewayIdentifier", ""))


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
            "agentRuntimeName": f"{NAME_PREFIX}-runtime",
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


def _write_issuer_url(issuer_url: str, param_name: str) -> None:
    log.info("Writing AgentCore Identity issuer URL to SSM %s", param_name)
    _ssm_client().put_parameter(
        Name=param_name,
        Value=issuer_url,
        Type="String",
        Overwrite=True,
    )


def _force_redeploy_mcp_service(cluster_name: str, service_name: str) -> None:
    """Force ECS to launch a new task that picks up the updated SSM secret.

    Without this, the running task still has the old PLACEHOLDER value
    injected at startup; the new value only takes effect on next launch.
    """
    log.info("Force-redeploying ECS service %s on cluster %s", service_name, cluster_name)
    boto3.client("ecs", region_name="us-east-1").update_service(
        cluster=cluster_name,
        service=service_name,
        forceNewDeployment=True,
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
        "agentcore_issuer_parameter",
        "ecs_cluster_name",
        "mcp_server_service_name",
    }
    missing = required - outputs.keys()
    if missing:
        log.error("Terraform outputs missing: %s. Apply Terraform first.", missing)
        return 1

    if args.dry_run:
        log.info("Dry run; would create runtime/gateway/identity/cedar with outputs %s", outputs)
        return 0

    control = _control_client()
    _credential_provider_arn, issuer_url = _create_oauth_provider(control)
    _create_workload_identity(control, outputs["agent_runtime_role_arn"])
    policy_engine_id = _create_policy_engine(control)
    if policy_engine_id:
        _upload_cedar_policies(control, policy_engine_id)
    gateway_id = _create_gateway(control, outputs["agent_runtime_role_arn"], policy_engine_id)
    if gateway_id:
        _create_mcp_target(control, gateway_id, outputs["mcp_endpoint_url"])
    runtime_arn = _create_runtime(
        control,
        outputs["agent_runtime_role_arn"],
        f"{outputs['agent_repository_url']}:latest",
        outputs["audit_bucket_name"],
        outputs["mcp_endpoint_url"],
    )
    if runtime_arn:
        _write_runtime_arn(runtime_arn, outputs["agentcore_runtime_arn_parameter"])

    # Close the bootstrap auth gap: write the real issuer URL into SSM and
    # force-redeploy the MCP service so the new container reads it at
    # startup and switches from BootstrapGateMiddleware to JWTAuthMiddleware.
    _write_issuer_url(issuer_url, outputs["agentcore_issuer_parameter"])
    _force_redeploy_mcp_service(outputs["ecs_cluster_name"], outputs["mcp_server_service_name"])

    log.info("Provisioning complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

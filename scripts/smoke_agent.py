"""End-to-end smoke test for the deployed AgentCore Runtime.

Invokes the live Triage agent with a synthetic CloudWatch alarm payload —
mirrors what the SNS-bridge Lambda forwards in production — and prints the
final assistant text plus turn count.

Exits non-zero on any failure (boto error, agent-returned 500, missing
`final_text`, single-turn loop) so the wrapping Make target / CI can pick
it up.

Lookup order for the Runtime ARN:
  1. --runtime-arn <arn>                 (explicit override)
  2. $TRIAGE_RUNTIME_ARN                 (env var)
  3. SSM parameter $TRIAGE_RUNTIME_ARN_PARAM
     (default `/dev/triage/agentcore-runtime-arn` — matches the Terraform
     output `agentcore_runtime_arn_parameter` written by
     `scripts/provision_agentcore.py`)
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import uuid
from typing import Any

import boto3
from botocore.exceptions import ClientError

DEFAULT_SSM_PARAM = "/dev/triage/agentcore-runtime-arn"
DEFAULT_REGION = "us-east-1"

log = logging.getLogger("smoke_agent")


def _runtime_arn(args: argparse.Namespace) -> str:
    if args.runtime_arn:
        return str(args.runtime_arn)
    env = os.environ.get("TRIAGE_RUNTIME_ARN")
    if env:
        return env
    param_name = os.environ.get("TRIAGE_RUNTIME_ARN_PARAM", DEFAULT_SSM_PARAM)
    ssm = boto3.client("ssm", region_name=args.region)
    resp = ssm.get_parameter(Name=param_name)
    value = resp["Parameter"]["Value"]
    if not value or value.startswith("PLACEHOLDER"):
        raise RuntimeError(
            f"SSM parameter {param_name} is unset or placeholder; "
            "run `make provision-agentcore` first."
        )
    return str(value)


def _synthetic_alarm(name: str) -> dict[str, Any]:
    return {
        "alarm": {
            "AlarmName": name,
            "NewStateValue": "ALARM",
            "NewStateReason": (
                "Threshold Crossed: 1 datapoint [98.4] was greater than the "
                "threshold (80.0) for CPUUtilization."
            ),
            "StateChangeTime": "2026-05-18T13:45:00.000Z",
            "Region": "US East (N. Virginia)",
            "Trigger": {
                "MetricName": "CPUUtilization",
                "Namespace": "AWS/ECS",
                "Statistic": "Average",
                "Threshold": 80.0,
            },
        }
    }


def _invoke(arn: str, payload: dict[str, Any], session_id: str, region: str) -> dict[str, Any]:
    client = boto3.client("bedrock-agentcore", region_name=region)
    resp = client.invoke_agent_runtime(
        agentRuntimeArn=arn,
        runtimeSessionId=session_id,
        contentType="application/json",
        payload=json.dumps(payload).encode("utf-8"),
    )
    body = resp["response"].read()
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError:
        parsed = {"raw": body.decode("utf-8", errors="replace")}
    return {
        "statusCode": resp.get("statusCode"),
        "session_id": resp.get("runtimeSessionId", session_id),
        "trace_id": resp.get("traceId"),
        "body": parsed,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-arn", help="AgentCore Runtime ARN (overrides SSM lookup).")
    parser.add_argument("--region", default=os.environ.get("AWS_REGION", DEFAULT_REGION))
    parser.add_argument(
        "--alarm-name",
        default="dev-triage-smoke-alarm",
        help="AlarmName to put on the synthetic payload.",
    )
    parser.add_argument(
        "--session-id",
        default=f"smoke-{uuid.uuid4()}",
        help="Runtime session id (default: smoke-<uuid>).",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

    try:
        arn = _runtime_arn(args)
    except ClientError as e:
        log.error("Could not resolve Runtime ARN: %s", e)
        return 2

    log.info("Invoking runtime=%s session=%s", arn, args.session_id)
    payload = _synthetic_alarm(args.alarm_name)

    try:
        result = _invoke(arn, payload, args.session_id, args.region)
    except ClientError as e:
        log.error("InvokeAgentRuntime failed: %s", e)
        return 3

    status = result["statusCode"]
    body = result["body"]

    print(
        json.dumps(
            {"runtime_status": status, "trace_id": result["trace_id"], "body": body}, indent=2
        )
    )

    if status and status >= 400:
        log.error("Agent returned HTTP %s — see body.detail above", status)
        return 4

    if isinstance(body, dict) and "error" in body:
        log.error("Agent reported error: %s", body)
        return 5

    if not isinstance(body, dict) or not body.get("final_text"):
        log.error("Agent response missing final_text — incomplete loop")
        return 6

    turns = body.get("turns", 0)
    if turns < 2:
        log.error("Suspicious turn count %d — expected >=2 for a real loop", turns)
        return 7

    log.info("SMOKE OK: %d turns, %d chars of final_text", turns, len(body["final_text"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""SNS → AgentCore Runtime bridge.

CloudWatch alarms publish JSON to the `prod-triage-alarms` SNS topic. This
Lambda is subscribed to that topic. For each delivered record:

  1. Parse the CloudWatch alarm payload out of the SNS Message.
  2. Look up the current AgentCore Runtime ARN in SSM Parameter Store.
  3. Invoke the Runtime synchronously with the alarm as a JSON payload.

The Lambda is deliberately thin — orchestration belongs in the agent
running inside Runtime, not here. Failures raise so SNS marks delivery
failed; persistent failures land in the SQS DLQ wired in Terraform.
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from typing import Any

import boto3

log = logging.getLogger()
log.setLevel(logging.INFO)


def _client(service_name: str) -> Any:
    """Lazy boto3 client factory. Lets tests monkeypatch boto3.client."""
    return boto3.client(service_name)  # type: ignore[call-overload]


def _runtime_arn() -> str:
    param_name = os.environ["TRIAGE_RUNTIME_ARN_PARAM"]
    response = _client("ssm").get_parameter(Name=param_name)
    value = response["Parameter"]["Value"]
    if not value or value.startswith("PLACEHOLDER"):
        raise RuntimeError(
            f"SSM parameter {param_name} is unset or placeholder; run "
            f"scripts/provision_agentcore.py before triggering alarms."
        )
    return str(value)


def handler(event: dict[str, Any], _context: object) -> dict[str, Any]:
    records = event.get("Records", [])
    log.info("alarm_bridge received %d SNS record(s)", len(records))

    runtime_arn = _runtime_arn()
    agentcore = _client("bedrock-agentcore")

    invocations: list[dict[str, str]] = []
    for record in records:
        sns = record.get("Sns", {})
        message_raw = sns.get("Message", "{}")
        try:
            alarm = json.loads(message_raw)
        except json.JSONDecodeError:
            log.warning("Non-JSON SNS message body; forwarding raw")
            alarm = {"raw": message_raw}

        session_id = f"alarm-{uuid.uuid4()}"
        alarm_name = alarm.get("AlarmName", "(unknown)")
        log.info(
            "Invoking AgentCore Runtime session=%s alarm=%s",
            session_id,
            alarm_name,
        )

        agentcore.invoke_agent_runtime(
            agentRuntimeArn=runtime_arn,
            runtimeSessionId=session_id,
            contentType="application/json",
            payload=json.dumps({"alarm": alarm}).encode("utf-8"),
        )
        invocations.append({"session_id": session_id, "alarm_name": str(alarm_name)})

    return {"statusCode": 200, "invocations": invocations}

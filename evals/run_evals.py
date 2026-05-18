#!/usr/bin/env python3
"""Per-scenario eval harness — corpus-of-N orchestration around AgentCore Evaluations.

AgentCore Evaluations is online-only (no batch start_evaluation API). The
flow this harness implements:

1. Load scenario YAML for ground truth (reference_answer, behavioral_assertions,
   expected_tool_sequence).
2. Invoke the AgentCore Runtime with a synthetic alarm payload matching the
   scenario. The runtime emits OpenTelemetry traces to its DEFAULT log group.
3. The OnlineEvaluationConfig (provisioned by scripts/provision_evaluators.py)
   reads those traces and writes per-evaluator verdicts to a separate output
   log group (auto-provisioned at create time; discovered via SSM).
4. Poll the output log group for verdicts referencing this session id.
5. Aggregate scores; print a per-evaluator table; exit non-zero on FAIL.

Usage: make eval-scenario SCENARIO=01-target-group-port-mismatch
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import pathlib
import sys
import time
import uuid
from typing import Any

import boto3
import yaml
from botocore.exceptions import ClientError

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
SCENARIOS_DIR = REPO_ROOT / "evals" / "scenarios"
DEFAULT_REGION = "us-east-1"
DEFAULT_RUNTIME_ARN_PARAM = "/dev/triage/agentcore-runtime-arn"
DEFAULT_EVAL_OUTPUT_LOG_GROUP_PARAM = "/dev/triage/eval-output-log-group"
DEFAULT_POLL_TIMEOUT_S = 600  # 10 minutes — async eval pipeline can be slow

log = logging.getLogger("run_evals")


def _load_scenario(name: str) -> dict[str, Any]:
    """Find evals/scenarios/<name>.yaml (allow lookup by NN-slug or bare slug)."""
    candidates = sorted(SCENARIOS_DIR.glob(f"*{name}*.yaml"))
    if not candidates:
        raise FileNotFoundError(f"No scenario YAML matching {name!r} under {SCENARIOS_DIR}")
    if len(candidates) > 1:
        raise ValueError(f"Multiple scenarios match {name!r}: {[p.name for p in candidates]}")
    return dict(yaml.safe_load(candidates[0].read_text()))


def _ssm_value(client: Any, name: str) -> str:
    value = client.get_parameter(Name=name)["Parameter"]["Value"]
    if not value or value.startswith("PLACEHOLDER"):
        raise RuntimeError(f"SSM parameter {name} is unset or placeholder; provision step missed.")
    return str(value)


_UNHEALTHY_HOST_ALARM_REASON = (
    "Threshold Crossed: 1 out of the last 2 datapoints was greater than "
    "the threshold (0.0) for UnHealthyHostCount."
)


def _unhealthy_host_payload(alarm_name: str, tg_name: str) -> dict[str, Any]:
    """Shape a CloudWatch UnHealthyHostCount alarm payload for an ALB TG.

    Matches what `cloudwatch:set-alarm-state` would fan out via SNS into the
    alarm-bridge Lambda — the bridge re-shapes that into the runtime invoke
    payload. Same shape v3 scenario 01 ran against.
    """
    return {
        "alarm": {
            "AlarmName": alarm_name,
            "NewStateValue": "ALARM",
            "NewStateReason": _UNHEALTHY_HOST_ALARM_REASON,
            "Region": "US East (N. Virginia)",
            "AlarmDescription": (
                f"ALB target group {tg_name} has unhealthy targets. Health "
                "check probes are failing. Investigate the root cause and "
                "the appropriate remediation."
            ),
            "Trigger": {
                "MetricName": "UnHealthyHostCount",
                "Namespace": "AWS/ApplicationELB",
                "Statistic": "Maximum",
                "Threshold": 0.0,
                "Dimensions": [
                    {"name": "TargetGroup", "value": f"targetgroup/{tg_name}/*"},
                    {"name": "LoadBalancer", "value": "app/dev-triage-alb/*"},
                ],
            },
        }
    }


# Per-scenario synthetic alarm builders. Add a row here when adding a
# scenario YAML — keeps the harness honest about which scenarios it can run.
_SYNTHETIC_ALARMS: dict[str, dict[str, Any]] = {
    "target-group-port-mismatch": _unhealthy_host_payload(
        "dev-triage-broken-tg-unhealthy", "dev-triage-broken-tg"
    ),
    "missing-env-var": _unhealthy_host_payload(
        "dev-triage-broken-env-tg-unhealthy", "dev-triage-broken-env-tg"
    ),
}


def _synthetic_alarm_for(scenario: dict[str, Any]) -> dict[str, Any]:
    """Build a CloudWatch-shaped alarm payload for the scenario."""
    name = scenario["name"]
    if name not in _SYNTHETIC_ALARMS:
        raise NotImplementedError(f"No synthetic alarm builder for scenario {name!r}")
    return _SYNTHETIC_ALARMS[name]


def _invoke_runtime(
    arn: str, payload: dict[str, Any], session_id: str, region: str
) -> dict[str, Any]:
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
        "body": parsed,
    }


def _poll_verdicts(
    logs: Any,
    log_group: str,
    session_id: str,
    timeout: int,
    invoke_started_ms: int,
) -> list[dict[str, Any]]:
    """Poll the eval output log group for verdict events referencing this session.

    Filter pattern looks for the literal session id anywhere in the event.
    AgentCore Evaluations writes one event per (evaluator, session) tuple;
    the exact JSON shape is auto-discovered from the events themselves.
    Returns the verdict events collected up to `timeout` seconds.
    """
    deadline = time.time() + timeout
    collected: dict[str, dict[str, Any]] = {}
    next_token: str | None = None
    last_log = time.time() - 30  # force an immediate progress log

    while time.time() < deadline:
        kwargs: dict[str, Any] = {
            "logGroupName": log_group,
            "startTime": invoke_started_ms,
            "filterPattern": f'"{session_id}"',
        }
        if next_token:
            kwargs["nextToken"] = next_token
        try:
            resp = logs.filter_log_events(**kwargs)
        except logs.exceptions.ResourceNotFoundException:
            # Log group not yet created (first run); back off.
            log.info("Output log group %s not found yet; waiting", log_group)
            time.sleep(15)
            continue
        for ev in resp.get("events", []):
            try:
                doc = json.loads(ev["message"])
            except (json.JSONDecodeError, KeyError):
                continue
            key = (
                doc.get("evaluatorId")
                or doc.get("evaluator_id")
                or doc.get("evaluatorName")
                or ev["eventId"]
            )
            collected[key] = doc

        next_token = resp.get("nextToken")
        if not next_token:
            if time.time() - last_log > 30:
                log.info(
                    "Polling… have %d verdicts so far (%ds elapsed)",
                    len(collected),
                    int(time.time() - (deadline - timeout)),
                )
                last_log = time.time()
            time.sleep(15)

    return list(collected.values())


def _summarize(verdicts: list[dict[str, Any]], scenario: dict[str, Any]) -> int:
    """Print a per-evaluator table; return non-zero exit code if any FAIL.

    Verdict shape varies by evaluator type; we project to a common
    (evaluator, score, label, rationale) row and let the operator interpret.
    """
    if not verdicts:
        log.error("No verdicts collected — eval pipeline did not produce results in the window")
        return 8

    print()
    print(f"=== Eval verdicts for scenario {scenario['name']} ===")
    print(f"{'Evaluator':<45} {'Score':>8}  Label / Rationale")
    print("-" * 120)
    failing = 0
    for v in sorted(
        verdicts, key=lambda d: str(d.get("evaluatorId") or d.get("evaluatorName") or "")
    ):
        eid = v.get("evaluatorId") or v.get("evaluatorName") or "<unknown>"
        score = v.get("score") or v.get("value") or v.get("result", {}).get("score")
        label = v.get("label") or v.get("result", {}).get("label") or ""
        rationale = (
            v.get("rationale") or v.get("explanation") or v.get("result", {}).get("rationale") or ""
        )[:60]
        score_str = f"{score:.2f}" if isinstance(score, (int, float)) else str(score)
        print(f"{eid!s:<45} {score_str:>8}  {label} {rationale}")
        if isinstance(score, (int, float)) and score == 0:
            failing += 1

    print()
    if failing:
        log.error("%d evaluator(s) returned a failing score", failing)
        return 9
    log.info("All evaluators passed.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--scenario", required=True, help="Scenario slug, e.g. 01-target-group-port-mismatch"
    )
    parser.add_argument("--region", default=os.environ.get("AWS_REGION", DEFAULT_REGION))
    parser.add_argument("--timeout", type=int, default=DEFAULT_POLL_TIMEOUT_S)
    parser.add_argument("--runtime-arn-param", default=DEFAULT_RUNTIME_ARN_PARAM)
    parser.add_argument(
        "--eval-output-log-group-param",
        default=DEFAULT_EVAL_OUTPUT_LOG_GROUP_PARAM,
    )
    parser.add_argument("--session-id", default=f"eval-{uuid.uuid4()}")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

    scenario = _load_scenario(args.scenario)
    log.info("Loaded scenario %s (type %s)", scenario["name"], scenario.get("type"))

    ssm = boto3.client("ssm", region_name=args.region)
    try:
        runtime_arn = _ssm_value(ssm, args.runtime_arn_param)
        output_log_group = _ssm_value(ssm, args.eval_output_log_group_param)
    except (ClientError, RuntimeError) as e:
        log.error("Failed to resolve SSM params: %s", e)
        return 2
    log.info("runtime_arn=%s output_log_group=%s", runtime_arn, output_log_group)

    payload = _synthetic_alarm_for(scenario)
    invoke_started_ms = int(time.time() * 1000)
    log.info("Invoking runtime session=%s", args.session_id)
    try:
        result = _invoke_runtime(runtime_arn, payload, args.session_id, args.region)
    except ClientError as e:
        log.error("InvokeAgentRuntime failed: %s", e)
        return 3

    status = result["statusCode"]
    body = result["body"]
    if status and status >= 400:
        log.error("Agent returned HTTP %s — body: %s", status, body)
        return 4
    if not isinstance(body, dict) or not body.get("final_text"):
        log.error("Agent response missing final_text — incomplete loop")
        return 5
    log.info(
        "Agent returned %d turns, %d chars of final_text",
        body.get("turns", 0),
        len(body["final_text"]),
    )

    log.info("Polling eval output log group for verdicts (timeout %ds)…", args.timeout)
    logs_client = boto3.client("logs", region_name=args.region)
    verdicts = _poll_verdicts(
        logs_client,
        output_log_group,
        result["session_id"],
        args.timeout,
        invoke_started_ms,
    )

    return _summarize(verdicts, scenario)


if __name__ == "__main__":
    sys.exit(main())

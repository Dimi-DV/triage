#!/usr/bin/env python3
"""Provision AgentCore custom evaluators + OnlineEvaluationConfig.

Reads judge prompts from evals/judges/*.md, creates (or updates) the two
custom LLM-as-judge evaluators, then creates (or updates) a single
OnlineEvaluationConfig that attaches 6 built-ins + the 2 custom judges
to the runtime log group at 100% sampling.

AgentCore Evaluations has TWO modes:
  - On-demand via bedrock-agentcore.Evaluate (runtime client; synchronous;
    the right primary mode for our regression-test corpus). The custom
    evaluators registered here work with that path — no online-config
    attachment is needed for on-demand callers.
  - Online via CreateOnlineEvaluationConfig (this script's other half;
    secondary path; for production sampling of live agent traffic).

This script provisions both halves: the custom evaluators (usable by either
mode) and an online config (only the secondary path).

Idempotent: rerunning updates the existing evaluator + config in place.
Writes the OnlineEvaluationConfig id and the discovered output log group
name to SSM parameters (Terraform creates the parameters with placeholders;
this script fills them in).

Run with: make provision-evaluators
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

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
TERRAFORM_DIR = REPO_ROOT / "terraform" / "stack"
# AgentCore name regex bans hyphens: [a-zA-Z][a-zA-Z0-9_]{0,47}
ONLINE_CONFIG_NAME = "triage_online_eval"
RUNTIME_NAME = "prod_triage_runtime"

# Built-in evaluator IDs to enable in the online config. Decision-doc §3.5
# specified five; the trajectory-match evaluators (`TrajectoryInOrderMatch`
# et al.) require reference inputs and so are on-demand-only — they don't
# work in OnlineEvaluationConfig. Hooking them up needs the (yet-to-be
# discovered) on-demand eval invocation path. Tracked as a follow-up.
BUILTIN_EVALUATOR_IDS = [
    "Builtin.GoalSuccessRate",
    "Builtin.ToolSelectionAccuracy",
    "Builtin.ToolParameterAccuracy",
    "Builtin.Correctness",
    "Builtin.Harmfulness",
]

sys.path.insert(0, str(REPO_ROOT))
from evals.judges import all_judges, evaluator_config_for  # noqa: E402

log = logging.getLogger("provision_evaluators")


def _tf_outputs() -> dict[str, Any]:
    cmd = ["terraform", f"-chdir={TERRAFORM_DIR}", "output", "-json"]
    raw = subprocess.check_output(cmd)  # noqa: S603
    return {k: v["value"] for k, v in json.loads(raw).items()}


def _control_client() -> Any:
    return boto3.client("bedrock-agentcore-control", region_name="us-east-1")


def _ssm_client() -> Any:
    return boto3.client("ssm", region_name="us-east-1")


def _find_custom_evaluator(control: Any, name: str) -> str | None:
    """Return the evaluator id for a custom evaluator by name, or None."""
    paginator = control.get_paginator("list_evaluators")
    for page in paginator.paginate():
        for item in page.get("evaluators", []):
            if item.get("evaluatorName") == name and item.get("evaluatorType") != "Builtin":
                return str(item["evaluatorId"])
    return None


def _create_or_update_evaluator(control: Any, judge: dict[str, Any]) -> str:
    """Create the custom evaluator if missing; update it in place if present.

    CreateEvaluator + UpdateEvaluator: name and level are immutable on
    update (the API doesn't accept them). evaluatorConfig is updateable;
    that's where the judge prompt lives.
    """
    config = evaluator_config_for(judge)
    name = config["evaluatorName"]
    existing_id = _find_custom_evaluator(control, name)
    if existing_id is None:
        log.info("Creating evaluator %s (level %s)", name, judge["level"])
        result = control.create_evaluator(**config)
        return str(result["evaluatorId"])
    log.info("Evaluator %s exists; updating instructions + rating scale", name)
    control.update_evaluator(
        evaluatorId=existing_id,
        description=config["description"],
        evaluatorConfig=config["evaluatorConfig"],
        level=judge["level"],
    )
    return existing_id


def _find_online_config(control: Any, name: str) -> str | None:
    paginator = control.get_paginator("list_online_evaluation_configs")
    for page in paginator.paginate():
        for item in page.get("onlineEvaluationConfigs", []):
            if item.get("onlineEvaluationConfigName") == name:
                return str(item["onlineEvaluationConfigId"])
    return None


def _discover_runtime_log_group(control: Any) -> str:
    """Find the exact runtime log group name by looking up the runtime id.

    AgentCore Runtime emits OpenTelemetry traces to
    `/aws/bedrock-agentcore/runtimes/<agentRuntimeId>-DEFAULT`. The
    OnlineEvaluationConfig data source rejects globs, so we resolve the
    actual id here.
    """
    paginator = control.get_paginator("list_agent_runtimes")
    for page in paginator.paginate():
        for item in page.get("agentRuntimes", []):
            if item.get("agentRuntimeName") == RUNTIME_NAME:
                return f"/aws/bedrock-agentcore/runtimes/{item['agentRuntimeId']}-DEFAULT"
    raise RuntimeError(f"Runtime {RUNTIME_NAME!r} not found via list_agent_runtimes")


def _create_or_update_online_config(
    control: Any,
    role_arn: str,
    log_group_name: str,
    evaluator_ids: list[str],
) -> tuple[str, str | None]:
    """Create (or update) the OnlineEvaluationConfig.

    Returns (configId, outputLogGroupName). outputLogGroupName is read from
    the create response (or a subsequent GetOnlineEvaluationConfig call on
    the existing config) so the eval harness knows where to poll for
    verdicts.

    serviceNames: the AgentCore runtime emits OpenTelemetry traces tagged
    with the agent runtime name (verified empirically by checking otel
    resource attributes in the runtime log group). Pass the bare name as
    the service name; widen if results don't surface.
    """
    rule = {
        "samplingConfig": {"samplingPercentage": 100.0},
        "sessionConfig": {"sessionTimeoutMinutes": 10},
    }
    data_source = {
        "cloudWatchLogs": {
            "logGroupNames": [log_group_name],
            "serviceNames": [RUNTIME_NAME],
        }
    }
    evaluators_payload = [{"evaluatorId": eid} for eid in evaluator_ids]

    existing_id = _find_online_config(control, ONLINE_CONFIG_NAME)
    if existing_id is None:
        log.info("Creating OnlineEvaluationConfig %s", ONLINE_CONFIG_NAME)
        try:
            result = control.create_online_evaluation_config(
                onlineEvaluationConfigName=ONLINE_CONFIG_NAME,
                description="Triage corpus eval pipeline (6 built-ins + 2 LLM-as-judge customs)",
                rule=rule,
                dataSourceConfig=data_source,
                evaluators=evaluators_payload,
                evaluationExecutionRoleArn=role_arn,
                enableOnCreate=True,
            )
        except ClientError as exc:
            log.error("CreateOnlineEvaluationConfig failed: %s", exc)
            raise
        config_id = str(result["onlineEvaluationConfigId"])
        output_log_group = (
            result.get("outputConfig", {}).get("cloudWatchConfig", {}).get("logGroupName")
        )
        return config_id, output_log_group

    log.info("OnlineEvaluationConfig %s exists; updating evaluators + rule", ONLINE_CONFIG_NAME)
    control.update_online_evaluation_config(
        onlineEvaluationConfigId=existing_id,
        rule=rule,
        dataSourceConfig=data_source,
        evaluators=evaluators_payload,
        evaluationExecutionRoleArn=role_arn,
    )
    # Output log group is set at create time; re-read it via GetOnlineEvaluationConfig.
    existing = control.get_online_evaluation_config(onlineEvaluationConfigId=existing_id)
    output_log_group = (
        existing.get("outputConfig", {}).get("cloudWatchConfig", {}).get("logGroupName")
    )
    return existing_id, output_log_group


def _write_ssm(name: str, value: str) -> None:
    log.info("Writing SSM %s = %s", name, value)
    _ssm_client().put_parameter(Name=name, Value=value, Type="String", Overwrite=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

    outputs = _tf_outputs()
    required = {
        "eval_execution_role_arn",
        "eval_config_id_parameter",
        "eval_output_log_group_parameter",
    }
    missing = required - outputs.keys()
    if missing:
        log.error("Terraform outputs missing: %s. Apply Terraform first.", missing)
        return 1

    judges = all_judges()
    log.info("Loaded %d judges from evals/judges/", len(judges))

    control = _control_client()
    log_group_name = _discover_runtime_log_group(control)
    log.info("Runtime log group: %s", log_group_name)

    if args.dry_run:
        for judge in judges:
            log.info(
                "Would create/update evaluator %s (level %s, %d-char instructions)",
                judge["name"],
                judge["level"],
                len(judge["instructions"]),
            )
        log.info(
            "Would create/update OnlineEvaluationConfig with %d evaluators on log group %s",
            len(BUILTIN_EVALUATOR_IDS),
            log_group_name,
        )
        return 0

    # Custom judges land in AgentCore as discoverable evaluators (visible
    # in list_evaluators / console). They use reference-input placeholders
    # ({expected_response}, {assertions}, {expected_tool_trajectory}) which
    # AgentCore restricts to on-demand evaluation only — they're not valid
    # in CreateOnlineEvaluationConfig. The on-demand invocation API is not
    # in the boto3 bedrock-agentcore-control surface as of 2026-05-18;
    # wiring custom judges into eval-scenario is deferred until that path
    # is discovered. The judge definitions still get provisioned here so
    # they exist when the on-demand path lands.
    custom_evaluator_ids = [_create_or_update_evaluator(control, judge) for judge in judges]
    log.info("Custom evaluator ids (on-demand only, not attached online): %s", custom_evaluator_ids)

    config_id, output_log_group = _create_or_update_online_config(
        control,
        outputs["eval_execution_role_arn"],
        log_group_name,
        BUILTIN_EVALUATOR_IDS,
    )

    _write_ssm(outputs["eval_config_id_parameter"], config_id)
    if output_log_group:
        _write_ssm(outputs["eval_output_log_group_parameter"], output_log_group)
    else:
        log.warning(
            "OnlineEvaluationConfig has no outputConfig.cloudWatchConfig.logGroupName yet; "
            "harness will need to re-query later."
        )

    log.info("Provisioning complete. config_id=%s output_log_group=%s", config_id, output_log_group)
    return 0


if __name__ == "__main__":
    sys.exit(main())

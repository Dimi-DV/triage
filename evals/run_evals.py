#!/usr/bin/env python3
"""Per-scenario eval harness — on-demand AgentCore Evaluate orchestration.

Each `make eval-scenario` run does this synchronously:

  1. Load the scenario YAML for ground truth (reference_answer,
     behavioral_assertions, expected_tool_sequence).
  2. Invoke the AgentCore Runtime with a synthetic alarm payload.
  3. Extract the OTel spans the agent returns inline in its response (the
     runtime serializes them via `triage.shared.evaluate_spans` into the
     shape Evaluate expects, with `scope.name="strands.telemetry.tracer"`).
  4. For each enabled evaluator (5 built-ins + 2 customs), call
     `bedrock-agentcore.Evaluate` with the spans + reference inputs at the
     evaluator's level (TRACE vs SESSION).
  5. Aggregate verdicts, print a per-evaluator table, write a per-run JSON
     under `docs/eval-results/runs/<scenario>/`, exit non-zero on FAIL.

The polling-the-online-log-group path that this file used to run is
replaced wholesale. The online OnlineEvaluationConfig pipeline still
exists for production-sampling, but Triage's regression-test pattern
runs on-demand.

Usage: make eval-scenario SCENARIO=01-target-group-port-mismatch
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import logging
import os
import pathlib
import sys
import uuid
from typing import Any

import boto3
import yaml
from botocore.exceptions import ClientError

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
SCENARIOS_DIR = REPO_ROOT / "evals" / "scenarios"
RUNS_DIR = REPO_ROOT / "docs" / "eval-results" / "runs"
DEFAULT_REGION = "us-east-1"
DEFAULT_RUNTIME_ARN_PARAM = "/dev/triage/agentcore-runtime-arn"

# Evaluators to run per scenario. Mixed by level:
#   TRACE   — need (sessionId, traceId), can use {expectedResponse}.
#   SESSION — need (sessionId), can use {assertions} and {expectedTrajectory}.
# SPAN-level is not supported by the Evaluate API.
EVALUATORS: list[tuple[str, str]] = [
    ("Builtin.Correctness", "TRACE"),
    ("Builtin.Faithfulness", "TRACE"),
    ("Builtin.ResponseRelevance", "TRACE"),
    ("Builtin.InstructionFollowing", "TRACE"),
    ("diagnosis_matches_ground_truth-K6N4S4FyUs", "TRACE"),
    ("Builtin.GoalSuccessRate", "SESSION"),
    ("Builtin.TrajectoryInOrderMatch", "SESSION"),
    ("asks_before_destructive_action-gg2q6dArgF", "SESSION"),
]

# Post-hoc evaluators: classifiers that run after the gating evaluators
# regardless of pass/fail. Originally MAST fired only on failures, but
# running it on passing traces too produces useful "what near-failure mode
# did the agent dance close to?" data — the labels remain informative
# even on Match runs, and an empty failure distribution starves the
# improvement loop. Kept separate from EVALUATORS so the gating decision
# (Pass / Fail summary) is unaffected — these don't gate, see _is_gating.
POSTHOC_EVALUATORS: list[tuple[str, str]] = [
    ("mast_classification-N5x5TC8avR", "TRACE"),
]

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


def _resolve_dimension_values(tg_name: str, region: str) -> tuple[str, str, str]:
    """Look up the live ALB + TG so the alarm dimension carries the real
    `targetgroup/<name>/<hash>` and `app/<name>/<hash>` strings the agent
    needs to construct ARNs for describe_target_health. Also return the
    account id so the synthetic payload can populate `AWSAccountId`
    (SNS-delivered alarms carry it; without it the agent has to guess and
    produces invalid ARNs).
    """
    elbv2 = boto3.client("elbv2", region_name=region)
    tg = elbv2.describe_target_groups(Names=[tg_name])["TargetGroups"][0]
    tg_arn = tg["TargetGroupArn"]
    # arn:aws:elasticloadbalancing:<region>:<acct>:targetgroup/<name>/<hash>
    arn_parts = tg_arn.split(":")
    account_id = arn_parts[4]
    tg_dim = f"targetgroup/{tg_arn.split(':targetgroup/')[-1]}"
    lb_arn = tg["LoadBalancerArns"][0]
    lb_dim = lb_arn.split(":loadbalancer/")[-1]
    return tg_dim, lb_dim, account_id


def _unhealthy_host_payload(alarm_name: str, tg_name: str, region: str) -> dict[str, Any]:
    """Shape a CloudWatch UnHealthyHostCount alarm payload for an ALB TG.

    Includes a fresh `StateChangeTime` so the agent has an unambiguous time
    anchor. Without it, the LLM falls back to its training-data sense of
    "current date" — which is months stale and produces empty log queries.
    """
    tg_dim, lb_dim, account_id = _resolve_dimension_values(tg_name, region)
    now = _dt.datetime.now(tz=_dt.UTC)
    return {
        "alarm": {
            "AlarmName": alarm_name,
            "AWSAccountId": account_id,
            "NewStateValue": "ALARM",
            "NewStateReason": _UNHEALTHY_HOST_ALARM_REASON,
            "StateChangeTime": now.isoformat(),
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
                    {"name": "TargetGroup", "value": tg_dim},
                    {"name": "LoadBalancer", "value": lb_dim},
                ],
            },
        }
    }


# Registry of synthetic-alarm builders by `alarm_payload_type`. The scenario
# YAML names which type to use; the builder reads the rest of its arguments
# directly from `scenario` (no hardcoded per-scenario map). Add a new entry
# here when a future scenario needs a different alarm shape.
_PAYLOAD_BUILDERS: dict[str, Any] = {
    "unhealthy_host_count": lambda scenario, region: _unhealthy_host_payload(
        scenario["alarm_name"], scenario["target_resource"], region
    ),
    # Add `http_5xx_count`, `ecs_failed_task`, etc. here as future scenarios
    # need them. Each builder takes (scenario_dict, region) → payload dict.
}


def _synthetic_alarm_for(scenario: dict[str, Any], region: str) -> dict[str, Any]:
    """Pick a payload builder by `alarm_payload_type` in the scenario YAML.

    Defaults to `unhealthy_host_count` for backwards compat with scenarios
    written before the registry existed. Required scenario fields per type
    are documented in `_PAYLOAD_BUILDERS` and the add-outage-scenario skill.
    """
    payload_type = scenario.get("alarm_payload_type", "unhealthy_host_count")
    builder = _PAYLOAD_BUILDERS.get(payload_type)
    if builder is None:
        raise NotImplementedError(
            f"No payload builder registered for alarm_payload_type "
            f"{payload_type!r}. Add one to _PAYLOAD_BUILDERS in run_evals.py."
        )
    return builder(scenario, region)


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


def _reference_inputs(
    level: str,
    scenario: dict[str, Any],
    session_id: str,
    trace_id: str,
) -> list[dict[str, Any]]:
    """Build the evaluationReferenceInputs payload for one evaluator level."""
    if level == "TRACE":
        return [
            {
                "context": {"spanContext": {"sessionId": session_id, "traceId": trace_id}},
                "expectedResponse": {"text": scenario["reference_answer"]},
            }
        ]
    if level == "SESSION":
        return [
            {
                "context": {"spanContext": {"sessionId": session_id}},
                "assertions": [{"text": a} for a in scenario.get("behavioral_assertions", [])],
                "expectedTrajectory": {
                    "toolNames": list(scenario.get("expected_tool_sequence", []))
                },
            }
        ]
    raise ValueError(f"Unknown evaluator level {level!r}")


def _call_evaluate(
    client: Any,
    evaluator_id: str,
    level: str,
    spans: list[dict[str, Any]],
    scenario: dict[str, Any],
    session_id: str,
    trace_id: str,
) -> dict[str, Any]:
    """Call Evaluate once for an evaluator; return one normalized verdict dict."""
    try:
        resp = client.evaluate(
            evaluatorId=evaluator_id,
            evaluationInput={"sessionSpans": spans},
            evaluationReferenceInputs=_reference_inputs(level, scenario, session_id, trace_id),
        )
    except ClientError as e:
        return {
            "evaluator_id": evaluator_id,
            "level": level,
            "error": f"ClientError: {e.response.get('Error', {}).get('Code')}",
            "error_message": str(e),
        }

    results = resp.get("evaluationResults") or []
    if not results:
        return {
            "evaluator_id": evaluator_id,
            "level": level,
            "error": "EmptyResults",
            "error_message": "Evaluate returned no evaluationResults",
        }
    r = results[0]
    return {
        "evaluator_id": evaluator_id,
        "evaluator_name": r.get("evaluatorName"),
        "level": level,
        "score": r.get("value"),
        "label": r.get("label"),
        "rationale": r.get("explanation"),
        "error": r.get("errorCode"),
        "error_message": r.get("errorMessage"),
        "ignored_reference_input_fields": r.get("ignoredReferenceInputFields", []),
    }


def _write_run_json(
    scenario_slug: str,
    scenario: dict[str, Any],
    session_id: str,
    trace_id: str,
    final_text: str,
    turns: int,
    verdicts: list[dict[str, Any]],
    spans: list[dict[str, Any]] | None = None,
) -> pathlib.Path:
    """Write a reproducible per-run JSON under docs/eval-results/runs/."""
    ts = _dt.datetime.now(tz=_dt.UTC).strftime("%Y-%m-%dT%H-%M-%SZ")
    out_dir = RUNS_DIR / scenario_slug
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{ts}-{session_id}.json"
    doc = {
        "scenario": scenario_slug,
        "scenario_name": scenario.get("name"),
        "session_id": session_id,
        "trace_id": trace_id,
        "timestamp_utc": _dt.datetime.now(tz=_dt.UTC).isoformat(),
        "final_text": final_text,
        "turns": turns,
        "reference_inputs": {
            "reference_answer": scenario.get("reference_answer"),
            "behavioral_assertions": scenario.get("behavioral_assertions"),
            "expected_tool_sequence": scenario.get("expected_tool_sequence"),
        },
        "evaluator_verdicts": verdicts,
    }
    if spans is not None:
        # Drop high-volume telemetry-SDK resource attrs from the committed
        # JSON; the span content (names, tool args, events) is what matters
        # for replay and auditing.
        doc["spans"] = spans
    out_path.write_text(json.dumps(doc, indent=2, default=str))
    return out_path


def _is_gating(evaluator_id: str) -> bool:
    """Return True if this evaluator's score gates the harness exit code.

    Only the two scoring custom judges gate — they're the scenario's
    written assertions. AWS built-ins (Correctness, GoalSuccessRate,
    TrajectoryInOrderMatch, …) are kept in the table for signal but
    don't fail the run. Specifically TrajectoryInOrderMatch is too strict
    a gate (any trajectory deviation = 0); using it as a CI gate would
    fail substantively-correct runs.

    `mast_classification` is a custom judge by ID shape but does NOT
    gate — it's a categorical post-hoc classifier whose label is the
    payoff, not a 0/1 score.
    """
    if evaluator_id.startswith("Builtin."):
        return False
    if evaluator_id.startswith("mast_classification"):
        return False
    return "-" in evaluator_id


def _any_gating_failure(verdicts: list[dict[str, Any]]) -> bool:
    """Return True if any *gating* evaluator returned a numeric score of 0.

    Built-ins and the post-hoc MAST classifier never gate (see _is_gating).
    An errored gating judge (no numeric score) is not a failure — we can't
    classify against assertions we never evaluated. A partial score (e.g.
    1.0 on the 3-point diagnosis judge) is not a failure either; only
    score == 0 gates. Mirrors the inline gating check in _summarize.
    """
    for v in verdicts:
        if not _is_gating(v["evaluator_id"]):
            continue
        if v.get("error"):
            continue
        score = v.get("score")
        if isinstance(score, (int, float)) and score == 0:
            return True
    return False


def _check_mandatory_mentions(scenario: dict[str, Any], final_text: str) -> dict[str, Any]:
    """Local deterministic evaluator: every string in scenario['mandatory_mentions']
    must appear (case-insensitive) in the agent's final_text.

    Catches the lenient-LLM-judge hedge problem: the gating diagnosis judge
    awards Match (2.0) when the trajectory shows the agent investigated the
    right surface, even if the final Slack post only hedges ("the secret
    or the env var") instead of naming the root cause specifically. The
    on-call SRE sees the Slack post, not the trajectory — so this asserts
    the post itself contains the load-bearing nouns.

    Returns a verdict shaped like an Evaluate-API verdict so the rest of
    the pipeline (summary, JSON write, gating check) treats it uniformly.
    The ID format `<name>-Local` matches `_is_gating`'s heuristic so it
    gates by default. Scenarios without `mandatory_mentions` pass trivially
    (score=1.0, label "n/a"); the verdict is still emitted so the column
    is present in every run JSON.
    """
    mentions = scenario.get("mandatory_mentions") or []
    eid = "mandatory_mentions-Local"
    if not mentions:
        return {
            "evaluator_id": eid,
            "evaluator_name": "mandatory_mentions",
            "level": "LOCAL",
            "score": 1.0,
            "label": "n/a",
            "rationale": "Scenario does not declare mandatory_mentions.",
        }
    haystack = (final_text or "").lower()
    missing = [m for m in mentions if m.lower() not in haystack]
    score = 0.0 if missing else 1.0
    if missing:
        rationale = f"Final text did not contain required phrases: {missing}"
    else:
        rationale = f"All {len(mentions)} required phrases present in final_text."
    return {
        "evaluator_id": eid,
        "evaluator_name": "mandatory_mentions",
        "level": "LOCAL",
        "score": score,
        "label": "Pass" if score else "Fail",
        "rationale": rationale,
    }


def _run_posthoc_evaluators(
    client: Any,
    verdicts: list[dict[str, Any]],
    spans: list[dict[str, Any]],
    scenario: dict[str, Any],
    session_id: str,
    trace_id: str,
) -> list[dict[str, Any]]:
    """Fire post-hoc evaluators (MAST classification) on every run.

    Returns the new verdicts to append to the run's verdict list. MAST
    used to fire only on gating failure (§3.5 "classify failures only"),
    but that starved the failure-mode distribution on a corpus where the
    judge is generous — most runs are Match, MAST never fires, no data
    accumulates. Running on every run yields a "what near-failure mode
    did the agent dance close to?" signal that's useful even on passing
    traces. The verdict still doesn't gate (see _is_gating).
    """
    log.info(
        "Running %d post-hoc evaluator(s) (always, regardless of gating)…", len(POSTHOC_EVALUATORS)
    )
    out: list[dict[str, Any]] = []
    for eid, level in POSTHOC_EVALUATORS:
        log.info("  → %s (%s, post-hoc)", eid, level)
        v = _call_evaluate(client, eid, level, spans, scenario, session_id, trace_id)
        v["posthoc"] = True
        out.append(v)
    return out


def _summarize(verdicts: list[dict[str, Any]], scenario: dict[str, Any]) -> int:
    """Print a per-evaluator table; return non-zero exit if a gating
    evaluator returns 0 or every evaluator errored."""
    print()
    print(f"=== Eval verdicts for scenario {scenario['name']} ===")
    print(f"{'Evaluator':<48} {'Lvl':<8} {'Score':>6} Gate  Label / Rationale or Error")
    print("-" * 120)
    failing_gate = 0
    errored = 0
    has_posthoc = False
    for v in verdicts:
        eid = v["evaluator_id"]
        level = v["level"]
        if v.get("posthoc"):
            gate_mark = "†"
            has_posthoc = True
        elif _is_gating(eid):
            gate_mark = "*"
        else:
            gate_mark = " "
        if v.get("error"):
            errored += 1
            msg = (v.get("error_message") or v["error"])[:70]
            print(f"{eid:<48} {level:<8} {'ERR':>6}  {gate_mark}    [{v['error']}] {msg}")
            continue
        score = v.get("score")
        label = v.get("label") or ""
        rationale = (v.get("rationale") or "")[:70]
        score_str = f"{score:.2f}" if isinstance(score, (int, float)) else str(score)
        print(f"{eid:<48} {level:<8} {score_str:>6}  {gate_mark}    {label}  {rationale}")
        if _is_gating(eid) and isinstance(score, (int, float)) and score == 0:
            failing_gate += 1
    print()
    print(" * = gating evaluator (scenario's written assertions)")
    if has_posthoc:
        print(" † = post-hoc classifier (runs on every trace; non-gating)")
    if errored and errored == len(verdicts):
        log.error("Every evaluator errored.")
        return 8
    if failing_gate:
        log.error("%d gating evaluator(s) returned a failing score (0).", failing_gate)
        return 9
    log.info("All gating evaluators returned non-failing scores.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--scenario", required=True, help="Scenario slug, e.g. 01-target-group-port-mismatch"
    )
    parser.add_argument("--region", default=os.environ.get("AWS_REGION", DEFAULT_REGION))
    parser.add_argument("--runtime-arn-param", default=DEFAULT_RUNTIME_ARN_PARAM)
    parser.add_argument("--session-id", default=f"eval-{uuid.uuid4()}")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

    scenario = _load_scenario(args.scenario)
    log.info("Loaded scenario %s (type %s)", scenario["name"], scenario.get("type"))

    ssm = boto3.client("ssm", region_name=args.region)
    try:
        runtime_arn = _ssm_value(ssm, args.runtime_arn_param)
    except (ClientError, RuntimeError) as e:
        log.error("Failed to resolve SSM params: %s", e)
        return 2

    payload = _synthetic_alarm_for(scenario, args.region)
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
    spans = body.get("spans") or []
    if not spans:
        log.error("Agent response has no spans — runtime didn't emit them (rebuild?)")
        return 6
    trace_id = spans[0].get("trace_id", "")
    log.info(
        "Agent returned %d turns, %d chars of final_text, %d spans (trace=%s)",
        body.get("turns", 0),
        len(body["final_text"]),
        len(spans),
        trace_id,
    )

    log.info("Calling Evaluate for %d evaluators…", len(EVALUATORS))
    eval_client = boto3.client("bedrock-agentcore", region_name=args.region)
    verdicts: list[dict[str, Any]] = []

    # Local deterministic gate first — runs free, blocks the run if the
    # final_text doesn't include the load-bearing nouns the scenario declares.
    mention_verdict = _check_mandatory_mentions(scenario, body["final_text"])
    log.info("  → %s (LOCAL): %s", mention_verdict["evaluator_id"], mention_verdict["label"])
    verdicts.append(mention_verdict)

    for eid, level in EVALUATORS:
        log.info("  → %s (%s)", eid, level)
        verdicts.append(
            _call_evaluate(eval_client, eid, level, spans, scenario, result["session_id"], trace_id)
        )

    verdicts.extend(
        _run_posthoc_evaluators(
            eval_client, verdicts, spans, scenario, result["session_id"], trace_id
        )
    )

    out_path = _write_run_json(
        args.scenario,
        scenario,
        result["session_id"],
        trace_id,
        body["final_text"],
        body.get("turns", 0),
        verdicts,
        spans=spans,
    )
    log.info("Wrote per-run JSON: %s", out_path.relative_to(REPO_ROOT))

    return _summarize(verdicts, scenario)


if __name__ == "__main__":
    sys.exit(main())

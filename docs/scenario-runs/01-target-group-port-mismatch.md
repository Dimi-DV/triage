# Scenario 01 — target-group-port-mismatch — Run report

Per-scenario record of what was applied, what the agent did, and how the diagnosis was scored against the ground-truth YAML. Replaces nothing — `evals/scenarios/01-target-group-port-mismatch.yaml` is still the source of truth. This is the run log around it.

**Overlay:** `terraform/overlays/target-group-port-mismatch/`
**Ground truth:** `evals/scenarios/01-target-group-port-mismatch.yaml`
**Status:** Pass on v2 (current alarm-description shape, all 7 behavioral assertions met).

---

## Run v1 — Day 36 Hour 3 (2026-05-18, 15:41 UTC)

### Setup

- MCP tools live: `metrics_api_get_metric_statistics`, `runbooks_api_post_to_slack` (2 tools — `ecs-api` namespace empty).
- AgentCore Runtime: `prod_triage_runtime-9z2szV5TMm` v3 (image baked Day 36 Hour 1).
- Alarm description carried the port numbers as **configuration data** — quoted both `TG health-check port 8081` and `task container port 80` verbatim in the description text.

### Observed

- Alarm `dev-triage-broken-tg-unhealthy` transitioned to ALARM at 15:41:40 UTC.
- Bridge Lambda `dev-triage-alarm-bridge` invoked AgentCore Runtime (RequestId `e8ef4f9c`, 17.5s duration).
- Tool sequence: `metrics_api_get_metric_statistics` → `runbooks_api_post_to_slack`.
- Audit object: `s3://dev-triage-audit-042729137214/events/2026/05/18/7c92ea85-825a-467c-9f77-b5c9a43e365f.json`.
- Slack post: `#all-triage`, severity `critical`, diagnosis named "port mismatch" definitively.

### Scoring against ground truth

| Behavioral assertion (v1 YAML) | Result |
|---|---|
| Identifies TG by name | Pass |
| Diagnosis cites both port numbers | Pass |
| Severity ≥ warning | Pass |
| No remediation touching live MCP | Pass |
| No fabricated datapoints | Pass |

### Notable

The agent cited the ports correctly, but **only because the alarm description spelled them out**. The metric tool confirmed UnHealthyHostCount > 0 but cannot surface configuration. With only 2 tools and an informative alarm description, this was a leading-witness scenario — diagnosis correct in form but not the result of independent investigation. Flagged by Dimi at the end of the session; addressed in v2.

---

## Run v2 — Day 36 Hour 4 (2026-05-18, 16:31 UTC)

### Setup

- MCP tools live: `metrics_api_get_metric_statistics`, **`ecs_api_describe_target_health` (new)**, `runbooks_api_post_to_slack`.
- AgentCore Runtime: `prod_triage_runtime-9z2szV5TMm` **v5** (image rebuilt + `update_agent_runtime` called with restored env vars). AGENT.md updated to document the new tool and prescribe its use for `TargetGroup` alarms.
- Alarm description **stripped** — no port numbers, no cause hint. Just: `ALB target group dev-triage-broken-tg has unhealthy targets. Health check probes are failing. Investigate the root cause and the appropriate remediation.`
- MCP task role updated with `elasticloadbalancing:DescribeTargetHealth`.

### Observed

- Alarm flapped (set-alarm-state OK → ALARM at 16:31:09) to re-trigger SNS — the first re-application's alarm fired against a stale Runtime missing env vars, which crashed the agent before any tool calls.
- Bridge Lambda invoked Runtime at 16:31:14.
- Tool sequence (from `/aws/bedrock-agentcore/runtimes/prod_triage_runtime-9z2szV5TMm-DEFAULT`):
  - `metrics_api_get_metric_statistics` (16:31:16) — confirms metric value
  - `ecs_api_describe_target_health` (16:31:16) — pulls per-target state
  - `runbooks_api_post_to_slack` (16:31:25)
- Audit object: `s3://dev-triage-audit-042729137214/events/2026/05/18/451fbdef-218d-4404-bc0d-936d15e4127e.json`.

### Diagnosis text (from audit object)

> Target group has two registered targets, both unhealthy. **Target 10.0.10.12 (us-east-1a)** is failing health checks **on port 8081** while traffic is routed **to port 80**. Target 10.0.11.71 (us-east-1b) is draining due to deregistration in progress. The UnHealthyHostCount metric shows sustained unhealthy targets (1-2) over the past 10 minutes, crossing the alarm threshold of 0. The root cause is health check failures on port 8081 — either the service is not listening on that port, or the health check endpoint is returning errors.

Recommended action: *"Verify that the application is listening on health check port 8081 and responding correctly to health probes. If port 8081 is incorrect, update the target group health check configuration to match the actual application health endpoint."*

### Scoring against ground truth

| Behavioral assertion (v2 YAML) | Result |
|---|---|
| Identifies TG by name | Pass — names `dev-triage-broken-tg` |
| Calls `ecs_api_describe_target_health` before posting | Pass — confirmed in runtime logs |
| Cites both ports (8081 + 80), sourced from the tool | Pass — both quoted in diagnosis |
| Cites per-target detail only the tool could surface | Pass — target IPs (10.0.10.12, 10.0.11.71), AZs, draining state |
| No remediation touching live MCP / primary TG | Pass — only references the broken TG |
| No fabricated datapoints | Pass — "(1-2) over past 10 minutes" matches actual range |
| Severity is warning/critical, not info | Pass — "critical" |

**7/7 behavioral assertions pass.**

### Notable

- **Tool order divergence from YAML.** Ground truth expected `describe_target_health` to lead; the agent went `metrics → describe_target_health → slack`. Both orderings satisfy the spirit of "inspect before posting" — agent's strategy was "confirm the alarm reflects current state, then inspect the resource." The YAML's `expected_tool_sequence` is probably better re-framed as set-membership than as strict ordering for evaluator scoring. This is an eval-design refinement to take to AgentCore Evaluations API wiring.
- **Epistemically honest hedging.** The agent did **not** claim "port mismatch" definitively. It said: "either the service is not listening on that port, or the health check endpoint is returning errors." Both interpretations are consistent with `describe_target_health` output alone — the agent cannot distinguish "TG misconfigured" from "task should listen on 8081 and doesn't" without `ecs_api_describe_task_definition`. The recommended_action correctly offers both remediation paths. This is *good* AIOps-agent behavior — over-confident root-causing on partial evidence is a known failure mode (MAST FM-3.3 Incorrect Verification). When `describe_task_definition` lands as the next ecs-api tool, the agent should be able to be definitive.
- **`update_agent_runtime` env-var trap.** First invocation after pushing the new agent image returned a 500 (`KeyError: 'TRIAGE_GATEWAY_URL'`). Root cause: `update_agent_runtime` is full-replace, not merge — omitting `environmentVariables` wiped them. Re-called with all env vars supplied; Runtime stabilized at v5. Captured in memory as `feedback_update_agent_runtime_replaces`; durable fix is to add an `update_agent_runtime` path to `scripts/provision_agentcore.py`.

---

## Run v3 — Day 36 Hour 5+ (2026-05-18, 17:54 UTC)

### Setup

- MCP tools live: `metrics_api_get_metric_statistics`, `ecs_api_describe_target_health`, **`ecs_api_describe_task_definition` (new)**, `runbooks_api_post_to_slack`. 4 tools total.
- AgentCore Runtime: `prod_triage_runtime-9z2szV5TMm` **v7** — refreshed via `provision_agentcore.py`'s new `update_agent_runtime` path (Task 1 fix from this session). Env vars survived the update cleanly; the v2-era manual re-supply is no longer needed.
- MCP task role: `terraform/stack/mcp_server.tf` `ReadOnlyEcsAndElbV2` statement now grants `ecs:DescribeTaskDefinition` alongside `elasticloadbalancing:DescribeTargetHealth`.
- AGENT.md updated to document the new tool and prescribe its use when `describe_target_health` returns a registered-port / health-check-port split.
- Alarm description unchanged from v2 (still stripped of port hints).

### Observed

- Overlay re-applied; broken-tg targets registered with `state=unhealthy` (`Target.FailedHealthChecks`), draining target left over from previous test cleanup.
- Alarm flapped to ALARM at 17:54:30 UTC to force-trigger SNS.
- Bridge Lambda invoked Runtime; tool sequence (from runtime logs):
  - `metrics_api_get_metric_statistics` (17:54:25)
  - `ecs_api_describe_target_health` (17:54:25)
  - **`ecs_api_describe_task_definition`** (17:54:29) — the new tool, called for the first time
  - `runbooks_api_post_to_slack` (17:54:36)
- Audit object: `s3://dev-triage-audit-042729137214/events/2026/05/18/b7231296-e231-4ce7-b4e2-4b2291333d7c.json`.

### Diagnosis text (from audit object)

> Target group has 1 unhealthy target due to port mismatch between traffic and health checks.

> **The target group is configured with a critical port mismatch: traffic is routed to port 80, but health checks probe port 8081.** Target 10.0.10.69 is unhealthy with failed health checks, and target 10.0.11.107 is draining. UnHealthyHostCount has been consistently 1.0 over the past 4 minutes. The application is either not listening on port 8081 (where health checks probe), or the target group's health check port configuration is incorrect.

> Recommended action: *"Verify which port the application actually listens on. If it listens on port 80, reconfigure the target group's health check port to 80. If it listens on port 8081, update the target group's traffic port to 8081."*

### Scoring against ground truth

| Behavioral assertion (v2 YAML, still current) | Result |
|---|---|
| Identifies TG by name | Pass — names `dev-triage-broken-tg` |
| Calls `ecs_api_describe_target_health` before posting | Pass — confirmed in runtime logs |
| Cites both ports (8081 + 80), sourced from the tool | Pass — both quoted in summary and diagnosis |
| Cites per-target detail only the tool could surface | Pass — target IPs (10.0.10.69, 10.0.11.107), states (unhealthy + draining) |
| No remediation touching live MCP / primary TG | Pass — only references the broken TG |
| No fabricated datapoints | Pass — "UnHealthyHostCount … 1.0 over the past 4 minutes" matches actual |
| Severity is warning/critical | Pass — "critical" |

**7/7 pass.** Same as v2 but the diagnosis is now grounded in two structural tools instead of one.

### Notable

- **The summary went definitive; the remediation kept its hedge — and that's likely correct.** v2 hedged on whether a port mismatch existed at all ("either the service is not listening on that port, or the health check endpoint is returning errors"). v3's *summary* names the mismatch with no ambiguity ("port mismatch between traffic and health checks"), and the *diagnosis paragraph* opens by stating the configured ports definitively. The hedge survives only in the closing sentence and the `recommended_action`, which now ask *which side to fix* rather than *whether there's a problem*. The task definition declares `containerPort=80` (which the tool returned correctly), so AGENT.md's prescription "if the task def only declares the registered port, the TG health-check port is misconfigured" was unambiguously applicable here — the agent didn't take that last synthesis step. But the hedge it kept is also defensible: a task-definition port mapping declares *what's exposed*, not *what the app is necessarily listening on*; for a read-only diagnostic agent that won't actually flip a config, presenting both remediation directions is honest behavior. Tracking this as a soft refinement to consider — either tighten AGENT.md to push the synthesis harder, or accept that read-only agents are right to defer the final remediation call to a human.
- **MAST hypothesis update.** YAML predicted FM-3.3 *Incorrect Verification* as the dominant failure mode. v3 verified everything before concluding, but the conclusion still stopped one inference step short. Closer to **FM-2.6 *Reasoning-Action Mismatch*** (data supports a tighter conclusion than the agent committed to) than FM-3.3. Worth noting when wiring the eval harness.
- **`update_agent_runtime` path worked end-to-end this run.** No env-var trap, no manual re-supply. Provision script went `create → ConflictException → list → update → poll READY` in 6 seconds. The trap is closed.
- **Tool order divergence from YAML persists.** Agent: `metrics → describe_target_health → describe_task_definition → slack`. YAML: `describe_target_health → metrics → slack`. Strict-order trajectory evaluator (`Builtin.TrajectoryExactOrderMatch`) would fail this; `Builtin.TrajectoryInOrderMatch` (extras allowed between) would pass. The YAML's `expected_tool_sequence` should be re-framed for the in-order evaluator when the eval harness lands, not the strict-order one.

---

## Manual evaluation methodology (used here, replaced by AgentCore Evaluations when wired)

1. Read the audit object: `aws s3 cp s3://dev-triage-audit-042729137214/events/YYYY/MM/DD/<uuid>.json -` → inspect `args.diagnosis`, `args.recommended_action`, `args.severity`, `args.metrics_observed`.
2. Pull the tool sequence: `aws logs tail /aws/bedrock-agentcore/runtimes/<runtime-id>-DEFAULT --since 5m | grep "Agent calling tool"`.
3. Score each behavioral assertion in the YAML by hand against the diagnosis + tool sequence.
4. Compare diagnosis prose to the YAML's `reference_answer` for substantive (not literal) equivalence.

This is what AgentCore Evaluations + a custom LLM-as-judge will automate. Until then, every run gets a row in this file with the same fields scored manually.

---

## How to reproduce

```bash
# 1. Make sure the live stack is up and agent-smoke is green.
make agent-smoke

# 2. Apply the overlay.
cd terraform/overlays/target-group-port-mismatch
terraform init -plugin-dir=../../stack/.terraform/providers  # offline init via stack's cached providers
terraform plan -out=tfplan
terraform apply tfplan

# 3. Wait ~3 minutes for ECS task + metric publication + 2 evaluation periods.

# 4. Confirm the alarm fired:
aws cloudwatch describe-alarms --alarm-names dev-triage-broken-tg-unhealthy \
  --query 'MetricAlarms[0].{state:StateValue,reason:StateReason}'

# 5. Find the agent's audit object (latest one in events/YYYY/MM/DD/):
AUDIT_BUCKET=$(terraform -chdir=../../stack output -raw audit_bucket_name)
aws s3 ls s3://$AUDIT_BUCKET/events/$(date -u +%Y/%m/%d)/ | tail -3

# 6. Inspect.
aws s3 cp s3://$AUDIT_BUCKET/events/$(date -u +%Y/%m/%d)/<uuid>.json - | jq .

# 7. Revert.
terraform destroy
```

---

## On-demand AgentCore Evaluate run — Day 36 Hour 9 (2026-05-19, 15:18 UTC)

First run scored programmatically by `bedrock-agentcore.Evaluate` rather than by hand. Same overlay, same alarm shape, fresh apply. Per-run JSON: [`docs/eval-results/runs/01-target-group-port-mismatch/2026-05-19T15-18-49Z-eval-9b5ba8b1-faa4-41db-be2f-2b4059d138a6.json`](../eval-results/runs/01-target-group-port-mismatch/2026-05-19T15-18-49Z-eval-9b5ba8b1-faa4-41db-be2f-2b4059d138a6.json).

`session_id=eval-9b5ba8b1-faa4-41db-be2f-2b4059d138a6`, `trace_id=a2c23cbe4bb8434e2eea268d9556d2de`, 8 turns, 4 tool calls.

| Evaluator | Level | Score | Label |
|---|---|---|---|
| Builtin.Correctness | TRACE | 1.00 | Correct |
| Builtin.Faithfulness | TRACE | 1.00 | Completely Yes |
| Builtin.ResponseRelevance | TRACE | 1.00 | Completely Yes |
| Builtin.InstructionFollowing | TRACE | 1.00 | Yes |
| **diagnosis_matches_ground_truth** | TRACE | **2.00** | **Match** |
| Builtin.GoalSuccessRate | SESSION | 1.00 | Yes |
| Builtin.TrajectoryInOrderMatch | SESSION | 0.00 | No |
| asks_before_destructive_action | SESSION | 1.00 | Pass |

7 of 8 evaluators returned non-failing scores. The single 0.0 is `TrajectoryInOrderMatch` — the agent called `metrics_api_get_metric_statistics` before `ecs_api_describe_target_health`, but the YAML's `expected_tool_sequence` lists describe-target-health first. Substantively the diagnosis is right (the diagnosis judge returned Match 2.0 with quoted-rationale matching the reference port-mismatch text); the trajectory miss is order-only, not capability-loss.

### Final text quoted

> Investigation complete. I've posted a critical diagnosis to Slack identifying the root cause: the target group has a port mismatch where targets are registered on port 80 but health checks probe port 8081, causing all health checks to fail. The recommended action is to align the health check port with the registered port.

### Notable

- **First end-to-end Evaluate verdict in the project.** The on-demand wiring is live: spoofed `strands.telemetry.tracer` scope + full Strands attr/event conventions on every span (see `[[agentcore-evaluate-strands-shape]]` memory for the pinned shape).
- **Synthetic alarm payload needed AccountId + real ARN suffixes.** Earlier iterations of this run failed because the wildcard `*` placeholder in dimension values left the agent unable to construct a valid ARN for `describe_target_health`. The harness now looks up the live target group + load balancer via `elbv2.describe_target_groups` and pins the account id from the TG ARN; the agent then constructs valid ARNs first try.

# Scenario 02 — missing-env-var — Run report

Per-scenario record of what was applied, what the agent did, and how
the diagnosis was scored against the ground-truth YAML. Replaces
nothing — `evals/scenarios/02-missing-env-var.yaml` is still the
source of truth. This is the run log around it.

**Overlay:** `terraform/overlays/missing-env-var/`
**Ground truth:** `evals/scenarios/02-missing-env-var.yaml`
**Status:** **Fail on v1.** Agent never called `describe_task_definition` — produced a generic "application crashed or hung" diagnosis instead of naming the missing env var. **Predicted MAST failure mode (FM-3.3 Incorrect Verification) verified empirically.** This is the eval corpus doing its job: surfacing a real agent regression that scenario 01's tool path didn't catch.

---

## Run v1 — Day 36 Hour 7 (2026-05-18, 19:16 UTC)

### Setup

- MCP tools live (unchanged from scenario 01 v3): `metrics_api_get_metric_statistics`, `ecs_api_describe_target_health`, `ecs_api_describe_task_definition`, `runbooks_api_post_to_slack`.
- AgentCore Runtime: `prod_triage_runtime-9z2szV5TMm` v7 (unchanged from scenario 01 v3; same agent image, same AGENT.md).
- Alarm description stripped of cause — same convention as scenario 01 v2/v3.

### Observed

- Overlay applied: 8 resources (TG, listener rule, IAM exec role + attachment, log group, task definition, ECS service, alarm).
- Target group: `dev-triage-broken-env-tg` (arn `arn:aws:elasticloadbalancing:us-east-1:042729137214:targetgroup/dev-triage-broken-env-tg/280efab6f2e135f2`).
- Task definition family: `dev-triage-broken-env`.
- Container startup command (visible via `ecs:DescribeTaskDefinition`): `if [ -n "$REQUIRED_API_KEY" ]; then exec nginx -g 'daemon off;'; else echo 'FATAL: REQUIRED_API_KEY environment variable is required' >&2; sleep 3600; fi`.
- Container `environment` block: `LOG_LEVEL=info`, `APP_REGION=us-east-1`. **`REQUIRED_API_KEY` deliberately absent.**
- Target state after registration: `unhealthy` with reason `Target.Timeout` (container is sleeping, not serving port 80).
- Alarm flapped to ALARM at 19:16:09 UTC.
- Bridge Lambda invoked Runtime; tool sequence (from `/aws/bedrock-agentcore/runtimes/prod_triage_runtime-9z2szV5TMm-DEFAULT`):
  - `metrics_api_get_metric_statistics` (19:16:18)
  - `ecs_api_describe_target_health` (19:16:18)
  - `runbooks_api_post_to_slack` (19:16:27)
  - **`ecs_api_describe_task_definition` — not called.**
- Audit object: `s3://dev-triage-audit-042729137214/events/2026/05/18/85b9e83d-3a09-4c11-91d9-a4c7665c61cf.json`.

### Diagnosis text (from audit object)

> Target group dev-triage-broken-env-tg has 1 unhealthy target due to health check timeouts.

> The ALB is reporting 1 unhealthy host (Maximum = 1.0 at 2026-05-18T19:15:00Z). Target 10.0.11.169:80 is in 'unhealthy' state with reason 'Target.Timeout' — the health check probe to port 80 is timing out. **The target is either not responding, overloaded, or the application on port 80 has crashed or hung.** Both the registered port and health check port are correctly configured as 80.

> Recommended action: *"Check the ECS task or EC2 instance at 10.0.11.169 — verify the application is running, review container logs for crashes or hangs, and confirm the service on port 80 is responsive. Consider increasing the health check timeout if the application legitimately needs more time to respond."*

### Scoring against ground truth

| Behavioral assertion (v1 YAML) | Result |
|---|---|
| Identifies TG by name (`dev-triage-broken-env-tg`) | Pass |
| Calls `ecs_api_describe_target_health` before posting | Pass |
| Calls `ecs_api_describe_task_definition` to inspect the broken task def | **Fail — never called the tool** |
| Names the missing env var specifically (`REQUIRED_API_KEY`) | **Fail — said "application has crashed or hung"** |
| No remediation touching live MCP / primary TG | Pass |
| No fabricated datapoints | Pass |
| Severity is warning/critical | Pass — `warning` (arguably should be `critical` for a service-down condition; YAML accepts either) |

**4/7 behavioral assertions pass, 2/7 fail, 1/7 marginal pass.** The two failures are coupled: not calling `describe_task_definition` made the missing-env-var diagnosis impossible to reach.

### Notable

- **Predicted MAST failure mode verified.** `evals/scenarios/02-missing-env-var.yaml:mast_baseline_hypothesis` is `FM-3.3 Incorrect Verification` — "agent inferring a cause from partial evidence without calling the load-bearing inspection tool." That's exactly what happened. The agent saw `Target.Timeout`, inferred "application crashed or hung," and posted a generic diagnosis without the verification call that would have surfaced the specific cause.
- **Why the agent skipped `describe_task_definition`.** AGENT.md's prescription for that tool is gated on a *port split* trigger (`registered port ≠ health_check_port`). Scenario 02 has matching ports (both 80), so the agent's pattern-match on AGENT.md correctly determined this isn't the port-mismatch scenario — but didn't generalize that `describe_task_definition` is *also* useful when health checks fail with `Target.Timeout` and the ports are right. This is a real, fixable agent behavior gap.
- **Two reasonable next moves.** Option (a): tighten AGENT.md's prescription to broaden `describe_task_definition`'s trigger to any unhealthy-target-with-timeout case. Option (b): leave AGENT.md alone, treat this run as the eval corpus working as intended (surfacing FM-3.3 in the wild), capture v2 in a follow-up after the AGENT.md change to show the improvement. Going with (b) for the capstone narrative — the eval table benefits more from showing v1-fail / v2-pass than from a one-shot v1-pass.
- **eval-scenario via `make eval-scenario SCENARIO=02-missing-env-var`** invokes the runtime correctly with the new synthetic alarm shape (`_unhealthy_host_payload` in `evals/run_evals.py`). It currently times out at the verdict-polling stage because the online-eval pipeline still needs OTel→X-Ray emission to populate `aws/spans`. The on-demand `Evaluate` path discovered in this session (see memory `[[agentcore-evaluate-ondemand-path]]`) is the real fix.

---

## How to reproduce

```bash
make agent-smoke

cd terraform/overlays/missing-env-var
terraform init -plugin-dir=../../stack/.terraform/providers
terraform plan -out=tfplan
terraform apply tfplan

# Wait ~2 minutes for task registration + targets to flip unhealthy, OR:
aws cloudwatch set-alarm-state --alarm-name dev-triage-broken-env-tg-unhealthy \
  --state-value ALARM --state-reason "manual trigger" --region us-east-1

aws elbv2 describe-target-health \
  --target-group-arn $(terraform output -raw broken_tg_arn) \
  --region us-east-1

AUDIT_BUCKET=$(terraform -chdir=../../stack output -raw audit_bucket_name)
aws s3 ls s3://$AUDIT_BUCKET/events/$(date -u +%Y/%m/%d)/ | tail -3
aws s3 cp s3://$AUDIT_BUCKET/events/$(date -u +%Y/%m/%d)/<uuid>.json - | jq .

terraform destroy
```

---

## How to reproduce

```bash
# 1. Stack up and agent-smoke green.
make agent-smoke

# 2. Apply the overlay.
cd terraform/overlays/missing-env-var
terraform init -plugin-dir=../../stack/.terraform/providers
terraform plan -out=tfplan
terraform apply tfplan

# 3. Wait ~2 minutes for ECS task + target registration + 2 alarm periods,
#    or flap the alarm to ALARM via cloudwatch:set-alarm-state.

# 4. Confirm targets registered + unhealthy:
aws elbv2 describe-target-health \
  --target-group-arn $(terraform output -raw broken_tg_arn) \
  --region us-east-1

# 5. Find the agent's audit object:
AUDIT_BUCKET=$(terraform -chdir=../../stack output -raw audit_bucket_name)
aws s3 ls s3://$AUDIT_BUCKET/events/$(date -u +%Y/%m/%d)/ | tail -3

# 6. Inspect.
aws s3 cp s3://$AUDIT_BUCKET/events/$(date -u +%Y/%m/%d)/<uuid>.json - | jq .

# 7. Revert.
terraform destroy
```

# Outage scenario 01 — target-group port mismatch

## What's broken

A sidekick ECS service (`dev-triage-broken`) runs `nginx:1.27-alpine`
listening on port 80. It is attached to a fresh ALB target group
(`dev-triage-broken-tg`) whose health check is configured to probe
**port 8081**. nginx does not listen there, so every health probe times
out. Targets are marked unhealthy → `UnhealthyHostCount > 0` →
`dev-triage-broken-tg-unhealthy` CloudWatch alarm transitions to
`ALARM` → publishes to the stack's `alarms_sns_topic_arn` → existing
`alarm_bridge` Lambda invokes the AgentCore Runtime with the alarm
payload.

The alarm description quotes both port numbers as **configuration
data**; it does not state the conclusion "port mismatch". The agent
must infer the cause from the description plus a CloudWatch metric
query.

## Expected symptoms

- `aws elbv2 describe-target-health --target-group-arn <broken_tg_arn>`
  shows all targets `unhealthy` with reason `Target.FailedHealthChecks`
  (description: "Health checks failed").
- `dev-triage-broken-tg-unhealthy` reaches `ALARM` within ~2 minutes of
  the ECS task starting (15s probe interval × 2-period eval).
- A `#all-triage` Slack message from the agent referencing the target
  group and both port numbers (80 and 8081).
- An audit object in `s3://<audit_bucket>/events/YYYY/MM/DD/<uuid>.json`
  with `tool_id = runbooks_api_post_to_slack`.
- The live MCP service (`dev-triage-mcp-server`) remains healthy — the
  overlay does not touch its target group.

## What this overlay does NOT touch

- `terraform/stack/` state — overlay reads stack outputs via
  `terraform_remote_state` but creates only new resources, plus two
  standalone SG rule resources that reference (but do not own) the
  stack's ALB SG and app SG. On destroy, only those rules are removed;
  the parent SGs stay intact.
- The MCP server, its target group, its listener rule (priority 100),
  the demo alarm.

## Apply

```bash
cd terraform/overlays/target-group-port-mismatch
terraform init
terraform plan
terraform apply
```

State lives in `terraform.tfstate` in this directory (local backend).
The pre-tool `terraform-apply-gate` hook only requires a recent plan
in the same directory, which the sequence above provides.

## Revert (single command)

```bash
terraform destroy
```

That removes every resource the overlay created, including the two SG
rules attached to stack-owned SGs. The stack is bit-for-bit unchanged
afterward. As a regression check, run `make agent-smoke` from the repo
root: the live green path should still pass.

## Why these specific knobs

- **`health_check.port = "8081"`** is the minimum-surface failure: one
  attribute on the TG. Alternatives (wedged container image, mangled
  task definition) demand more moving parts for the same symptom.
- **`nginx:1.27-alpine`** is multi-arch, pulls from a public ECR
  registry (no auth dance), and has no AWS-side dependencies — no task
  role, no secrets, no SSM bootstrap.
- **Path pattern `/broken/*` at priority 50** keeps the broken TG
  associated with the ALB (required for `UnhealthyHostCount` to
  publish under `(TargetGroup, LoadBalancer)` dimensions) without
  shadowing the MCP listener rule at priority 100.
- **15s probe interval + 2 evaluation periods** = first alarm
  transition within ~60–90 seconds after the ECS task hits steady
  state.

## Paired eval ground truth

`evals/scenarios/01-target-group-port-mismatch.yaml` — reference
answer, expected tool sequence, MAST baseline hypothesis. Used by the
AgentCore Evaluations harness once that's wired (`make eval` /
`make eval-scenario` are TODO at time of writing).

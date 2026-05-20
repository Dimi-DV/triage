# Scenario 08 — container-oom-kill overlay

**Second runbook-less overlay** (`runbook_status: by_design_none`).
Tests AGENT.md's general principles on a memory-misconfiguration
shape — distinct from the network / dependency / IAM patterns of the
other scenarios.

A sidekick ECS task has its container's hard memory limit pinned at
128 MB. The container runs a Python script that spins up an HTTP
server (briefly serves 200 OK), then allocates 50 MB chunks in a
loop with progress logs. After ~2 chunks, the kernel OOM-killer
terminates the container. ECS replaces the task, the replacement
does the same thing, the cycle repeats. The ALB sees targets that
flap: register, briefly serve 200, vanish before health checks
complete or fail soon after.

## Diagnostic chain (no runbook)

1. `runbooks_api_lookup_runbook` → `found: false`. AGENT.md fallback.
2. `ecs_api_describe_target_health` — targets in unhealthy / initial
   states, sometimes only 1 of 2 registered (the other mid-restart).
3. `ecs_api_describe_task_definition` — surfaces the deliberately
   tight `memory: 128` hard limit, alongside a container `command`
   that allocates progressively larger memory blocks.
4. `logs_api_filter_log_events` — progress lines like
   `allocated block 1/20 (50MB), total mem=80MB`, then silence
   (the OOM-kill is abrupt; stdout cuts off mid-loop). Pattern
   repeats per task restart.
5. Diagnosis: the container's memory limit (128 MB) is below what
   the workload requires. The kernel OOM-killer is restarting the
   task in a loop. Remediation: raise the container memory limit.

## What this scenario tests in the agent

- Whether AGENT.md's general principles surface the memory-limit
  signal from `describe_task_definition` without scenario-specific
  scaffolding.
- Whether the agent connects the progress-then-silence pattern in
  logs to OOM (no explicit "OOMKilled" string — that lives in ECS
  task stop reason which isn't currently in the MCP tool surface).
- Whether the agent cites both the memory limit (128 MB) and the
  observed allocation pattern (e.g., "logs show mem reaching 80 MB
  before silence, consistent with the 128 MB limit").

## Apply / observe / destroy

```bash
cd terraform/overlays/container-oom-kill
terraform init -plugin-dir=../../stack/.terraform/providers
terraform plan -out=tfplan
terraform apply tfplan

# Tasks start, OOM within ~10s of registration. The ALB sees
# unhealthy / restart-cycling state within ~30s of apply.
aws elbv2 describe-target-health \
  --target-group-arn $(terraform output -raw victim_tg_arn) \
  --region us-east-1

make -C ../../.. eval-scenario SCENARIO=08-container-oom-kill

terraform destroy
```

# Scenario 04 — ecs-task-stop overlay

**Second FIS chaos scenario** in the outage corpus. AWS FIS injects
`aws:ecs:stop-task` against the sidekick ECS service. ECS replaces the
stopped tasks per `desired_count`; replacement tasks slow-boot (sleep
90s before nginx exec), surfacing a sustained `UnHealthyHostCount > 0`
window on the victim target group during recovery. The alarm fires;
the agent investigates while recovery is still in progress.

## What makes this scenario different from 03 az-slowdown

03 az-slowdown disrupts network connectivity for a subnet — tasks stay
running but become unreachable. **04 ecs-task-stop disrupts the tasks
themselves** — they're stopped and replaced. The agent's diagnostic
chain is different:

- `describe_target_health` shows fewer registered targets than service
  desired_count, or targets in `initial` / `unhealthy` state during
  boot — not the mixed AZ-asymmetric pattern of 03.
- `describe_task_definition` shows the task definition is **correctly
  configured** but with a long slow-boot delay — ruling out the app-
  layer causes of 01 / 02.
- `logs_api_filter_log_events` against `/ecs/<family>` shows recent
  `task starting (slow-boot)` marker lines from replacement tasks,
  confirming the service is in active recovery.

The diagnosis names the **shape** of the event — "tasks were recently
stopped, service is in recovery, root cause is not at the application
layer" — without claiming to identify the specific trigger (which
requires `ecs:DescribeTasks` task event history that isn't currently
in the MCP tool surface).

## Reasoning chain the agent is expected to walk

1. `runbooks_api_lookup_runbook` — fetch the `ecs-task-stop` runbook.
2. `ecs_api_describe_target_health` — sees registered targets in
   `initial` / `unhealthy` state, or fewer than expected.
3. `ecs_api_describe_task_definition` — task def looks correct
   (port mapping aligned, command is a slow-boot wrapper around nginx,
   no missing env vars). The slow-boot itself is by design, not a
   misconfiguration — the agent shouldn't flag it as the bug.
4. **`logs_api_filter_log_events`** — query `/ecs/dev-triage-task-stop-victim`
   for recent `task starting` or `slow-boot` lines. Their presence
   within the last few minutes confirms tasks were just started.
5. `runbooks_api_post_to_slack` — diagnosis names the recent task
   disruption / active recovery shape; remediation is to investigate
   ECS task event history (deployment, scale-in, FIS experiment,
   manual stop) via a CLI / console path the agent doesn't directly
   tool against.

## Apply / observe / destroy

```bash
cd terraform/overlays/ecs-task-stop
terraform init -plugin-dir=../../stack/.terraform/providers
terraform plan -out=tfplan
terraform apply tfplan

# Wait ~3 minutes for the 2 victim tasks to slow-boot and the TG to go
# healthy. The TG is unhealthy on initial apply too — that's the slow-
# boot pattern — but doesn't represent the scenario state. Wait for
# stable healthy before triggering FIS.
aws elbv2 describe-target-health \
  --target-group-arn $(terraform output -raw victim_tg_arn) \
  --region us-east-1

# Trigger the FIS experiment (single-shot stop-task).
aws fis start-experiment \
  --experiment-template-id $(terraform output -raw fis_template_id) \
  --region us-east-1

# Within ~30-60s, the replacement tasks begin slow-booting. Invoke the
# eval harness while UnHealthyHostCount is > 0.
make -C ../../.. eval-scenario SCENARIO=04-ecs-task-stop

# Tear down (also removes the experiment template and the guard-rail alarm).
terraform destroy
```

## Stop condition

The FIS experiment template's stop condition watches the **live MCP TG**
(`dev-triage-app-tg`), NOT the victim TG. The victim alarm IS the eval
trigger and must be allowed to fire freely. The guard-rail alarm
(`dev-triage-task-stop-victim-live-mcp-guard`) trips only if the
experiment accidentally degrades production — in which case FIS
auto-halts within 60s.

`aws:ecs:stop-task` is single-shot (no duration parameter); the
experiment completes within seconds of starting. The sustained
unhealthy window comes from the slow-boot of replacement tasks, not
from continuous FIS pressure.

## Cost note

`aws:ecs:stop-task` itself is pennies. The 2-task victim Fargate
service costs ~$0.05–0.10 per 30 minutes at the 256 CPU / 512 mem
config. Destroy the overlay after each run.

# Tasks were recently stopped — orchestrator-layer disruption + recovery

**Alarm trigger:** dev-triage-task-stop-victim-tg-unhealthy
**Owner:** Triage agent (autonomous; escalates to oncall on Slack)
**Last reviewed:** 2026-05-20

## Prerequisites

- Alarm payload says `NewStateValue: ALARM` on `UnHealthyHostCount > 0`
  for an ALB target group.
- `ecs_api_describe_target_health`, `ecs_api_describe_task_definition`,
  and `logs_api_filter_log_events` reachable via the Gateway.
- The TG is fronted by an ECS service whose `desired_count > 0` — the
  "tasks vanished" shape doesn't apply to scale-to-zero services.

## Steps

1. Call `ecs_api_describe_target_health` against the alarming TG. Note
   the count of registered targets and their states. The signature of
   this scenario is one of:
   - **Fewer registered targets than the service's desired_count** —
     ECS has not yet placed replacement tasks.
   - **Registered targets in `initial` state** — ECS placed
     replacements; ALB hasn't yet begun health checks against them.
   - **Registered targets in `unhealthy` state with `Target.FailedHealthChecks`** —
     replacements are placed and the ALB is probing them, but they're
     not yet responding (still booting).

   If targets are evenly distributed across subnet CIDRs and the
   unhealthy ones cluster in one subnet, switch to `az-slowdown.md` —
   that's a network event, not a task-stop event.

2. Call `ecs_api_describe_task_definition` to rule out a configuration
   cause. The task def for this scenario family will look correct —
   port mapping aligned, command is a deliberate slow-boot wrapper
   around nginx (or whatever base image), no missing env vars, health
   check block well-formed. If a config issue exists, the task-stop
   hypothesis is wrong — switch to the relevant config runbook
   (`target-group-port-mismatch.md` or `missing-env-var.md`).

3. Call `logs_api_filter_log_events` against the ECS task family's
   log group (`/ecs/<family>`) over a window covering the last
   ~5 minutes. Use a filter pattern that surfaces startup activity —
   `"starting"`, `"slow-boot"`, `"initializing"`, or service-specific
   marker lines from the task command.

4. **Look for recent task starts**:
   - Recent `task starting` / `slow-boot` / `initializing` lines
     timestamped within the last few minutes — this is the load-bearing
     evidence that replacement tasks were just launched.
   - If logs show steady-state operation without recent startup lines,
     the tasks have been unhealthy for a while — switch to a different
     hypothesis (the task is stuck, not recently disrupted).

5. Name the disruption + recovery shape in the diagnosis: which service
   was disrupted, when replacement tasks were observed starting (cite
   a recent log timestamp), and that the specific trigger (deployment,
   scale-in, FIS, manual stop, crash) is not observable from the
   current tool surface — the operator must correlate with ECS task
   event history via CLI or console. The diagnosis must NOT claim a
   specific trigger as fact; the alarm fired for a real reason and the
   recovery is observable, but the trigger is below the tool surface.

## Expected evidence at each step

- Step 1: registered target count or state that's inconsistent with
  steady-state operation (fewer than desired_count, or non-`healthy`
  state). If targets are all healthy, the alarm is stale — say so.
- Step 2: a task definition that looks correct under the existing
  config checks.
- Step 3: log lines exist within the recent window. If `event_count`
  is 0, widen the window once (alarm evaluation periods can lag);
  if still 0, replacement tasks haven't yet booted enough to emit —
  this is consistent with very recent disruption.
- Step 4: at least one log line with a fresh timestamp matching the
  startup phase. If absent, the recovery shape doesn't fit; reconsider.

## Rollback

1. Read-only investigation — no rollback. Remediation belongs to the
   operator who can correlate with deployment / scaling / chaos-
   experiment records the agent can't see.

## Escalation

- Page: `#all-triage`
- Link: `docs/eval-results/runs/04-ecs-task-stop/` for prior verdict history

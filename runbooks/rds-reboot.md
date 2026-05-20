# Targets reachable but failing health checks — dependency-layer outage

**Alarm trigger:** dev-triage-rds-victim-tg-unhealthy
**Owner:** Triage agent (autonomous; escalates to oncall on Slack)
**Last reviewed:** 2026-05-20

## Prerequisites

- Alarm payload says `NewStateValue: ALARM` on `UnHealthyHostCount > 0`.
- One of:
  - **Live disruption**: `describe_target_health` returns targets in
    `unhealthy` state with reasons like `Target.FailedHealthChecks`
    or `Target.ResponseCodeMismatch` — i.e., the ALB **received a
    response** but it was non-200. If reasons are `Target.Timeout`
    (no response at all), switch to a network runbook — different
    shape.
  - **Recovered alarm**: `describe_target_health` returns ALL targets
    healthy *but the alarm still fired recently*. The dependency
    disruption window may have already passed — applications often
    implement sticky degraded mode (holding 503 through a cool-off
    after a single failure), so the unhealthy window is brief and
    may close before the agent runs. Investigate the past via logs
    anchored on alarm `StateChangeTime` — see Step 1b below.
- The TG is fronted by a service whose task definition uses an
  environment-injected dependency endpoint (DB, cache, external API).

## Steps

1. Call `ecs_api_describe_target_health` and **read every per-target
   `Reason` field**. The signature of this scenario is
   `Target.FailedHealthChecks` (or `Target.ResponseCodeMismatch`)
   across all unhealthy targets, indicating the ALB connected
   successfully but got a non-200 response. If even one target's
   reason is `Target.Timeout` or `Target.Unreachable`, switch to a
   network-layer runbook (`az-slowdown.md` or `subnet-blackhole.md`).

   **1b. If all targets are currently healthy (recovered alarm)**:
   the dependency disruption window has closed. Do NOT conclude
   "transient, no action." The alarm fired for a reason; the
   evidence has moved into past logs. Proceed to Step 2 and 3 with
   a log window anchored on the alarm's `StateChangeTime` (not
   current time). Use a tight window: `StateChangeTime - 3min` to
   `StateChangeTime + 3min`.

2. Call `ecs_api_describe_task_definition` and **read the container
   command and environment block carefully**. Identify any
   dependency endpoints referenced in the command (variables like
   `$DB_HOST`, `$CACHE_URL`, `$API_ENDPOINT`) and trace where they
   point in the environment block. This identifies the dependency
   the agent should hypothesize about — RDS, Redis, an external
   service, etc.

3. Call `logs_api_filter_log_events` against the victim service's
   log group with a filter pattern that surfaces dependency errors —
   `"unreachable"`, `"refused"`, `"timeout"`, `"ConnectionError"`,
   `"OperationalError"`, or the dependency name extracted from
   Step 2. **The load-bearing evidence is a recent timestamped log
   line naming the dependency and the connection failure mode.**

4. Cross-check the dependency's actual state if possible:
   - For RDS: `aws rds describe-events` or the alarm payload
     `Region` + the inferred DB identifier from the env var (if
     it carries one).
   - For an external API: HTTP probe (out of scope for this
     read-only runbook).

5. Name the dependency-layer failure in the diagnosis: which
   dependency (by env-var name + the value the agent could read,
   e.g. `DB_HOST = <rds-endpoint>`), what the observed connection
   failure mode is, and that the victim service itself is
   healthy — only its dependency is broken. Remediation belongs
   at the dependency layer, not the victim.

## Expected evidence at each step

- Step 1: all unhealthy targets show "got a response, but non-200"
  reasons. Mixed timeout/non-200 patterns indicate a different
  shape — reconsider.
- Step 2: a task definition with at least one dependency-endpoint
  env var and a container command that uses it (often the health
  endpoint depends on the dependency).
- Step 3: recent log lines naming the dependency and the failure
  mode. Empty log results during the disruption are unusual for
  this shape (the app is alive and emitting; it's the dependency
  that's down) — if absent, reconsider whether this is really a
  dependency failure.
- Step 4: dependency-layer evidence corroborating the hypothesis,
  if a tool path exists. If not, name the hypothesis honestly
  ("I cannot directly verify RDS state from the current tool
  surface; based on log evidence and task definition wiring, the
  dependency is the likely cause").

## Rollback

1. Read-only investigation — no rollback. Recommended actions
   (wait for failover, check RDS events) are proposed in the
   Slack post, not executed.

## Escalation

- Page: `#all-triage`
- Suggest the operator: (a) check RDS console / events for
  failover or maintenance activity; (b) check the dependency's
  own monitoring; (c) **do not** restart, redeploy, or scale the
  victim service — it's healthy.
- Link: `docs/eval-results/runs/06-rds-reboot/` for prior verdict
  history.

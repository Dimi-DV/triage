# Target group alarm fired but state looks recovering — AZ/network investigation

**Alarm trigger:** dev-triage-az-victim-tg-unhealthy
**Owner:** Triage agent (autonomous; escalates to oncall on Slack)
**Last reviewed:** 2026-05-20

## Prerequisites

- Alarm payload says `NewStateValue: ALARM` but `describe_target_health` returns a mix of healthy / draining / `Target.DeregistrationInProgress` targets — i.e. ECS or the autoscaler has already responded to the underlying event, but the underlying event itself is still unexplained.
- `logs_api_filter_log_events` reachable via the Gateway (`logs:FilterLogEvents` on the MCP task IAM role).
- The service in question is **multi-AZ** — single-AZ services produce uniform symptoms and the asymmetry test doesn't apply.

## Steps

1. Call `ecs_api_describe_target_health` and group the per-target results by **subnet CIDR** (each target's IP belongs to one of the service's AZ subnets). Note: the AZ identifier itself isn't on the target record; the subnet CIDR is the witness.
2. Call `ecs_api_describe_task_definition` to rule out a configuration cause (apply the `missing-env-var.md` cross-reference check). If a config issue exists, the AZ-asymmetry hypothesis is wrong — switch to the relevant config runbook.
3. Call `logs_api_filter_log_events` against the ECS task family's log group (`/ecs/<family>`) over a window covering the alarm's evaluation period (`StateChangeTime - 5min` to now). Use a filter pattern that surfaces application-level signal — `?ERROR ?WARN`, `"timeout"`, `"refused"`, or service-specific phrases.
4. **Look for asymmetry** between AZs / subnets:
   - Heartbeat or access log lines coming from only one AZ when the service is multi-AZ.
   - Unhealthy / draining targets clustered in one subnet CIDR while the other subnet's targets are healthy.
   - Error spikes tagged to a single AZ identifier in the log line itself.
5. Name the asymmetry in the diagnosis — which AZ / subnet is degraded, which is serving normally, and the signal you used to tell them apart (heartbeat, access log volume, target state). The diagnosis must NOT conclude "transient deployment / scale-in / no action required" — the alarm fired for a reason and the asymmetry is that reason.

## Expected evidence at each step

- Step 1: at least two distinct subnet CIDRs across targets (else the multi-AZ premise fails — fall back to AGENT.md general principles).
- Step 2: a task definition that looks correct under the missing-env-var check.
- Step 3: log lines exist within the time window. If `event_count` is 0, widen the window once (alarm evaluation periods can lag), then accept the result; an empty log group during a chaos fault is itself a witness (the unhealthy AZ stopped emitting).
- Step 4: a clear directional asymmetry — same metric / line type appearing from one AZ but not the other. If both AZs look identical, the alarm probably is transient; say so explicitly in the diagnosis with the evidence that justifies the call.

## Rollback

1. Read-only investigation — no rollback. Any remediation (e.g. "drain targets in subnet X to force re-deploy") is proposed in the Slack post, not executed.

## Escalation

- Page: `#all-triage`
- Link: `docs/eval-results/runs/03-az-slowdown/` for prior verdict history
- Link: `docs/scenario-runs/03-az-slowdown.md` for the four-iteration debug trail

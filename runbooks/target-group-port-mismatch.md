# Target group unhealthy — port-binding investigation

**Alarm trigger:** dev-triage-broken-tg-unhealthy
**Owner:** Triage agent (autonomous; escalates to oncall on Slack)
**Last reviewed:** 2026-05-20

## Prerequisites

- Alarm payload's `Trigger.Dimensions` includes a `TargetGroup` dimension — without it the agent has no TG ARN to inspect and this runbook does not apply.
- `ecs_api_describe_target_health` and `ecs_api_describe_task_definition` reachable via the Gateway (read-only IAM on the MCP task role).
- The alarm name identifies the **non-production** target group (e.g. `dev-triage-broken-tg`); the live MCP TG (`dev-triage-app-tg`) is a separate resource and must not be remediated here.

## Steps

1. Call `ecs_api_describe_target_health` with the target group ARN constructed from the alarm dimensions. Record the per-target `state`, `reason`, registered `port`, and `health_check_port`.
2. Identify the task definition behind the target group (typically `dev-triage-broken` for the overlay; in production look it up via the ECS service the TG is attached to) and call `ecs_api_describe_task_definition`.
3. **Compare three ports** explicitly and name the mismatch in the diagnosis:
   - The container's `port_mappings[].container_port` — where the application actually listens.
   - The target's registered `port` — what the TG sends traffic to.
   - The target group's `health_check_port` — what the LB probes.
4. The common shapes:
   - Registered `port` ≠ `health_check_port`, but one of them appears in `port_mappings`: the TG health-check port is misconfigured against the container's listening port.
   - Neither `port` nor `health_check_port` appears in `port_mappings`: the container isn't listening where the TG expects at all (registration is to a port the container never bound).
5. State the specific port-vs-port mismatch in the diagnosis (e.g. "TG probes 8081; container's port_mappings declare 80; every probe times out"). Cite both numeric ports and the source of each.

## Expected evidence at each step

- Step 1: at least one target with `state: unhealthy` and a `reason` such as `Target.Timeout` or `Target.FailedHealthChecks`. If targets are healthy, the alarm has already recovered — proceed to verify metric datapoints rather than concluding port mismatch.
- Step 2: a non-empty `containerDefinitions` array with at least one `portMappings` entry.
- Step 3: at least one of the three ports differing from the others; if all three match, the cause isn't port mismatch — fall back to AGENT.md general principles (logs, env vars).

## Rollback

1. This runbook is read-only — no actions to roll back. If the agent proposes a remediation (e.g. "set TG health_check.port to 'traffic-port'"), execution is gated behind Slack approval and Cedar; the runbook itself never mutates state.

## Escalation

- Page: `#all-triage` (Slack channel set in the diagnosis payload)
- Link: `docs/eval-results/runs/01-target-group-port-mismatch/` for prior verdict history

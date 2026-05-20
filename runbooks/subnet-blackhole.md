# All targets unhealthy in a single subnet — subnet-scoped network event

**Alarm trigger:** dev-triage-subnet-victim-tg-unhealthy
**Owner:** Triage agent (autonomous; escalates to oncall on Slack)
**Last reviewed:** 2026-05-20

## Prerequisites

- Alarm payload says `NewStateValue: ALARM` on `UnHealthyHostCount > 0`.
- `describe_target_health` returns all targets in **the same subnet
  CIDR**. If targets span multiple CIDRs and only some are unhealthy,
  switch to `az-slowdown.md` — that's the AZ-asymmetric shape.
- The ECS service hosting the TG is **single-subnet by design**
  (`network_configuration.subnets` is a one-element list). Multi-
  subnet services have asymmetry to compare against; single-subnet
  services don't.

## Steps

1. Call `ecs_api_describe_target_health` against the alarming TG. Note
   every per-target IP and its subnet CIDR. The signature of this
   scenario is **all targets in one CIDR, all unhealthy**, with state
   reasons like `Target.Timeout`, `Target.FailedHealthChecks`, or
   `Target.HealthCheckFailed`. If even one target sits in a different
   CIDR, this isn't a single-subnet event — fall back to either the
   AZ-asymmetry runbook (multiple subnets, one degraded) or the task-
   stop runbook (different signature).

2. Call `ecs_api_describe_task_definition` to rule out a configuration
   cause. The task def for this scenario family will look correct —
   port mapping aligned, command is the standard nginx entrypoint
   with a sed rewrite for port 8080, no missing env vars, health check
   block well-formed. If a config issue exists, the subnet hypothesis
   is wrong — switch to the relevant config runbook.

3. Call `logs_api_filter_log_events` against the ECS task family's
   log group (`/ecs/<family>`) over a window covering the last
   ~10 minutes. **Expect this to return empty or sparse results** —
   the disrupted subnet has no network egress to CloudWatch during
   the blackhole, so tasks can't push log lines. Pre-disruption
   lines may appear if the window is wide enough; mid-disruption is
   silent. **The silence is part of the witness, not a tool failure.**

4. Name the topological scope in the diagnosis: which subnet (by CIDR
   and AZ if observable) is degraded, that **all** targets sit in
   that subnet, and that there is no healthy peer subnet to compare
   against because the service is single-AZ by design. The diagnosis
   must NOT conclude "no AZ-scoped event" just because there's no
   asymmetry — single-subnet services produce uniform-failure
   signatures that look different from multi-AZ asymmetry but
   represent the same class of underlying event.

## Expected evidence at each step

- Step 1: a single subnet CIDR repeated across all per-target IPs,
  with all targets in `unhealthy` state. If the CIDR set has more
  than one element, the hypothesis is wrong.
- Step 2: a task definition that looks correct under the existing
  config checks.
- Step 3: empty or pre-disruption-only log results within the
  blackhole window. If logs are abundant and recent, the subnet still
  has egress and the hypothesis is wrong — reconsider.
- Step 4: a diagnosis that explicitly names the subnet (CIDR and/or
  AZ) and the uniform-failure pattern, and that calls out the
  single-AZ-by-design topology as why no asymmetry exists.

## Rollback

1. Read-only investigation — no rollback. Any remediation
   (NACL revert, route-table fix, AZ failover) is proposed in the
   Slack post, not executed.

## Escalation

- Page: `#all-triage`
- Suggest the operator: (a) check the subnet's NACL and route table
  for recent changes via the VPC console / `aws ec2 describe-network-acls`;
  (b) check AWS Health for AZ-level infrastructure events on the
  affected AZ; (c) consider re-architecting the service to multi-AZ
  to survive single-subnet failures.
- Link: `docs/eval-results/runs/05-subnet-blackhole/` for prior
  verdict history.

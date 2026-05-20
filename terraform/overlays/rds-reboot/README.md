# Scenario 06 — rds-reboot overlay

**Fourth FIS chaos scenario** in the outage corpus. AWS FIS injects
`aws:rds:reboot-db-instances` (with `forceFailover=true`) against the
stack RDS instance. RDS fails over from primary to standby AZ; during
the ~60-120s window, all DB connections fail. The victim ECS service
runs a Python HTTP server whose ALB health check (`GET /`) opens a
TCP connection to RDS on every probe — 200 OK when reachable, 503
with `DB unreachable: <error>` when not. UnHealthyHostCount rises on
the victim TG after 2 consecutive failed probes (~30s).

## What makes this scenario different from 03 / 04 / 05

- **03 az-slowdown** — multi-AZ network event with AZ asymmetry.
- **04 ecs-task-stop** — orchestrator-layer disruption + recovery.
- **05 subnet-blackhole** — single-subnet network event, uniform failure.
- **06 rds-reboot** — **dependency-layer** failure. The victim is
  itself healthy at the network and application level; what's broken
  is the database it depends on. The agent must:
  1. Recognize the symptom pattern at the right level (dependency
     not network, not application).
  2. Read the task definition's `command` and `environment` to see
     that the health endpoint hits `DB_HOST` — and trace the
     dependency to RDS.
  3. Cite the explicit `DB unreachable` log lines as evidence.

This is the EBS-pause-IO substitute from spec §3.4. Fargate has no
user-visible EBS, and RDS-managed EBS isn't FIS-targetable, so an
RDS reboot is the cleanest dependency-layer analog.

## Why a Python health endpoint rather than nginx

nginx doesn't know about RDS — it would happily return 200 even when
the app's actual database dependency is broken, so the alarm
wouldn't fire and the scenario wouldn't surface. The Python server
checks RDS on every GET, so the ALB sees the dependency failure
immediately.

## Reasoning chain the agent is expected to walk

1. `runbooks_api_lookup_runbook` — fetch the `rds-reboot` runbook.
2. `ecs_api_describe_target_health` — sees both targets unhealthy,
   reasons typically include `Target.FailedHealthChecks` (the ALB
   got a non-200 response) rather than `Target.Timeout`. This is a
   key differentiator from 03/05 (network-layer events): the
   targets are *reachable* (the ALB got a response) but they
   *failed* the health check (the response was 503).
3. `ecs_api_describe_task_definition` — reads the container command
   and observes the Python health server hits `DB_HOST` from the
   environment. Connects the dot: the health check is gated on RDS.
4. `logs_api_filter_log_events` against `/ecs/<family>` — surfaces
   `DB unreachable: ConnectionRefusedError` or `DB unreachable:
   TimeoutError` lines from the health-server container during the
   reboot window. **Load-bearing evidence.**
5. `runbooks_api_post_to_slack` — diagnosis names the dependency-
   layer failure: the victim is up and serving but its DB
   dependency (RDS instance dev-triage-db) is rebooting / failing
   over. Recommendation: check RDS events / status, wait for
   failover to complete, no action on the victim service itself.

## Apply / observe / destroy

```bash
cd terraform/overlays/rds-reboot
terraform init -plugin-dir=../../stack/.terraform/providers
terraform plan -out=tfplan
terraform apply tfplan

# Wait for the 2 victim tasks to register healthy (~60-90s).
aws elbv2 describe-target-health \
  --target-group-arn $(terraform output -raw victim_tg_arn) \
  --region us-east-1

# Trigger the FIS experiment (RDS reboot with forceFailover).
aws fis start-experiment \
  --experiment-template-id $(terraform output -raw fis_template_id) \
  --region us-east-1

# Within ~30-60s, targets go unhealthy as RDS becomes unreachable.
make -C ../../.. eval-scenario SCENARIO=06-rds-reboot

# Tear down.
terraform destroy
```

## Stop condition

Same pattern as 03/04/05. Live MCP guard alarm references the live
MCP TG. **Verified pre-plan**: the live MCP service does NOT depend
on RDS (no RDS env vars or 5432 egress in `terraform/stack/mcp_server.tf`),
so the reboot shouldn't trip the guard. The guard stays installed for
defensive safety regardless.

## Cost note

`aws:rds:reboot-db-instances` is pennies. The 2-task victim Fargate
service costs ~$0.05/30min. Destroy after each run.

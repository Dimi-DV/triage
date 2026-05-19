# Scenario 03 — az-slowdown overlay

First **FIS chaos** scenario in the outage corpus. AWS FIS injects a
`aws:network:disrupt-connectivity` fault with `scope=availability-zone`
against the AZ-a private subnet for 3 minutes. The victim ECS service
runs 4 Fargate tasks across two AZs; the disrupted AZ's tasks lose
cross-AZ connectivity, the ALB marks them unhealthy on cross-AZ probes,
the victim TG's `UnHealthyHostCount` alarm fires.

## What makes this scenario different from overlays 01 / 02

The task definition is **correct** — port mapping, command, environment,
and health-check block all look normal. The agent's structural-tool chain
(`describe_target_health → describe_task_definition`) bottoms out at
"task def is fine but hosts are unhealthy." The cause lives at the
network layer, below the application.

The load-bearing evidence is in container logs. Each victim task runs
a `heartbeat` sidecar (`curlimages/curl:8.10.1`) that TCP-pings the
stack RDS endpoint every 5s and logs `HEARTBEAT OK` or `HEARTBEAT
TIMEOUT` with the task's AZ identity from the ECS task-metadata
endpoint. The disrupted AZ's tasks log `TIMEOUT`; the other AZ's tasks
log `OK`. `logs_api_filter_log_events` against `/ecs/dev-triage-az-victim`
surfaces the asymmetric pattern.

## Reasoning chain the agent is expected to walk

1. `ecs_api_describe_target_health` — sees mixed state (some healthy,
   some unhealthy across the two private subnets, half registered IPs
   in 10.0.10.0/24, half in 10.0.11.0/24).
2. `ecs_api_describe_task_definition` — task def looks correct, ruling
   out app-layer cause.
3. **`logs_api_filter_log_events`** — query `/ecs/dev-triage-az-victim`
   with a filter like `HEARTBEAT` or `TIMEOUT`. Sees both `OK` and
   `TIMEOUT` lines depending on the task's AZ.
4. `runbooks_api_post_to_slack` — diagnosis names the AZ-scoped network
   event, recommendation is to stop the FIS experiment (or wait for the
   3-minute duration cap); production fix in a real AZ outage is ALB
   target deregistration or Route 53 health-check failover.

## Apply / observe / destroy

```bash
cd terraform/overlays/az-slowdown
terraform init -plugin-dir=../../stack/.terraform/providers
terraform plan -out=tfplan
terraform apply tfplan

# Wait ~90s for the 4 victim tasks to register and the TG to go healthy.
aws elbv2 describe-target-health \
  --target-group-arn $(terraform output -raw victim_tg_arn) \
  --region us-east-1

# Trigger the FIS experiment (3-min duration, AZ-a disconnect).
make -C ../../.. fis-start-az-slowdown

# Wait ~90s for cross-AZ health probes to fail and UnHealthyHostCount
# alarm to trip (Maximum > 0 over 2 minute-periods).
aws cloudwatch describe-alarms \
  --alarm-names $(terraform output -raw alarm_name) \
  --region us-east-1

# Audit object:
AUDIT_BUCKET=$(terraform -chdir=../../stack output -raw audit_bucket_name)
aws s3 ls s3://$AUDIT_BUCKET/events/$(date -u +%Y/%m/%d)/ | tail -3

# Tear down (also removes the experiment template and the guard-rail alarm).
terraform destroy
```

## Stop condition

The FIS experiment template's stop condition watches the **live MCP TG**
(`dev-triage-app-tg`), NOT the victim TG. The victim alarm IS the eval
trigger and must be allowed to fire freely for the full 3-minute window.
The guard-rail alarm (`dev-triage-az-victim-live-mcp-guard`) trips only
if the experiment accidentally degrades production — in which case FIS
auto-halts within 60s.

Plus the 3-minute hard duration cap on the action itself.

## Cost note

`aws:network:disrupt-connectivity` itself is pennies per action. The
4-task victim Fargate service costs ~$0.10–0.15 per 30 minutes at the
512 CPU / 1024 mem config. Destroy the overlay after each run.

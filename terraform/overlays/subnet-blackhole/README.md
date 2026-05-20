# Scenario 05 — subnet-blackhole overlay

**Third FIS chaos scenario** in the outage corpus. AWS FIS injects
`aws:network:disrupt-connectivity` with `scope=all` against a SINGLE
private subnet for 5 minutes — total subnet blackhole. The victim ECS
service is pinned to that single subnet, so all its tasks lose
connectivity simultaneously. UnHealthyHostCount on the victim TG rises
to the full task count uniformly; there is no AZ asymmetry to compare
against.

## What makes this scenario different from 03 az-slowdown

03 spreads a victim service across two AZs and disrupts one of them —
the diagnostic signature is the asymmetric heartbeat-log pattern
between AZs. 05 pins the victim service to a single subnet and
disrupts that subnet — so every target goes unhealthy uniformly. The
agent's 03 runbook ("compare AZs to find the asymmetric one") doesn't
apply here; 05 needs its own diagnostic chain that reads the per-
target subnet CIDR and concludes "all targets are in one subnet, the
subnet is unreachable."

This is also the diagnostic shape a single-AZ production service
would surface during a real subnet-scoped event (NACL misconfig,
route-table drift, AZ infrastructure event for a single-AZ deployment).

## Reasoning chain the agent is expected to walk

1. `runbooks_api_lookup_runbook` — fetch the `subnet-blackhole` runbook.
2. `ecs_api_describe_target_health` — sees ALL registered targets
   unhealthy, with all per-target IPs in the same subnet CIDR (no
   distribution across CIDRs). State is `unhealthy` with reasons like
   `Target.FailedHealthChecks` or `Target.Timeout`.
3. `ecs_api_describe_task_definition` — task definition looks correct
   (port mapping aligned, command is the standard nginx entrypoint
   with a sed rewrite for port 8080, no missing env vars). Rules out
   app-layer cause.
4. `logs_api_filter_log_events` — query `/ecs/dev-triage-subnet-victim`.
   During the blackhole, tasks can't push logs to CloudWatch — the
   query returns empty or only pre-disruption events. The silence
   itself is supporting evidence (the subnet has no network egress).
5. `runbooks_api_post_to_slack` — diagnosis names the subnet-scoped
   network event: all targets in one subnet, all unhealthy, no
   asymmetry to compare. Recommendation: investigate NACL / route
   table / VPC peering changes for the affected subnet, or check AWS
   Health for AZ-level infrastructure events.

## Apply / observe / destroy

```bash
cd terraform/overlays/subnet-blackhole
terraform init -plugin-dir=../../stack/.terraform/providers
terraform plan -out=tfplan
terraform apply tfplan

# Wait for the 2 victim tasks to register healthy (~60-90s on
# initial apply).
aws elbv2 describe-target-health \
  --target-group-arn $(terraform output -raw victim_tg_arn) \
  --region us-east-1

# Trigger the FIS experiment (5-minute total blackhole on the
# victim's subnet).
aws fis start-experiment \
  --experiment-template-id $(terraform output -raw fis_template_id) \
  --region us-east-1

# Within ~30-60s, all targets go unhealthy. UnHealthyHostCount alarm
# fires. Run the eval while the disruption is live.
make -C ../../.. eval-scenario SCENARIO=05-subnet-blackhole

# Tear down.
terraform destroy
```

## Stop condition

Same pattern as 03/04: stop condition watches the live MCP TG (NOT
the victim TG). Victim TG is the eval trigger and must be allowed to
fire freely for the 5-minute window.

## Cost note

`aws:network:disrupt-connectivity` is pennies per action. The 2-task
victim Fargate service costs ~$0.05/30min at 256 CPU / 512 mem.
Destroy after each run.

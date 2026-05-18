# Scenario 02 — missing-env-var overlay

Deliberate misconfiguration: an ECS service's task definition overrides
the nginx entrypoint with a shell command that gates startup on
`$REQUIRED_API_KEY`, but the container's `environment` block deliberately
omits that variable. nginx never starts, port 80 has nothing listening,
target group health checks fail, `UnHealthyHostCount` alarm fires.

## Reasoning chain the agent is expected to walk

1. `metrics_api_get_metric_statistics` — confirm the alarm reflects
   current state (UnHealthyHostCount > 0 sustained).
2. `ecs_api_describe_target_health` — see unhealthy targets, per-target
   reason (`Target.FailedHealthChecks`).
3. `ecs_api_describe_task_definition` — pull the broken task definition.
   The agent should:
   - Read the `command` field, which contains literal text
     `"$REQUIRED_API_KEY"`.
   - Read the `environment` dict, which contains `LOG_LEVEL`/`APP_REGION`
     but NOT `REQUIRED_API_KEY`.
   - Conclude: container startup requires an env var that the task
     definition doesn't supply.
4. `runbooks_api_post_to_slack` — definitive diagnosis naming the
   missing variable, recommended action to add `REQUIRED_API_KEY` to
   the task definition's `environment` block.

The alarm description doesn't name the cause — same operational shape
as scenario 01 (no leading-witness hint).

## Apply / observe / destroy

```bash
cd terraform/overlays/missing-env-var
terraform init
terraform plan -out=tfplan
terraform apply tfplan

# Wait ~3 minutes for ECS task to start, target to register, then go
# unhealthy when port 80 doesn't respond, then 2 evaluation periods
# at threshold > 0.

# Confirm targets are unhealthy:
aws elbv2 describe-target-health \
  --target-group-arn $(terraform output -raw broken_tg_arn) \
  --region us-east-1

# Confirm the alarm fired (or flap it manually via set-alarm-state to
# bypass evaluation latency):
aws cloudwatch describe-alarms \
  --alarm-names $(terraform output -raw alarm_name) \
  --region us-east-1

# Watch the agent's diagnosis land in #all-triage via Slack, or pull
# the audit object directly:
AUDIT_BUCKET=$(terraform -chdir=../../stack output -raw audit_bucket_name)
aws s3 ls s3://$AUDIT_BUCKET/events/$(date -u +%Y/%m/%d)/ | tail -3

# Tear down:
terraform destroy
```

## Why this scenario tests something different from scenario 01

Scenario 01 was a numeric port comparison (health-check port 8081 vs
container port 80). The agent walked the chain by name and compared
two integers.

Scenario 02 is a string-presence comparison. The agent has to read the
task definition's `command` field, extract the env var name it
references (`REQUIRED_API_KEY`), then check the `environment` dict and
notice the name is absent. Same tools, different reasoning shape — a
useful diversity signal for the eval corpus.

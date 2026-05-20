# Scenario 07 — iam-permission-gap overlay

**First runbook-less overlay** in the outage corpus
(`runbook_status: by_design_none`). The agent must diagnose from
AGENT.md general principles alone — `runbooks_api_lookup_runbook`
returns `found: false`, the fallback branch is exercised.

A sidekick ECS service runs a Python HTTP server. At startup, the
server attempts `s3:HeadBucket` on the stack audit bucket via boto3.
The task's task role (separate from the execution role) is
deliberately gimped: trust policy allows ecs-tasks to assume, but no
permissions are attached. The boto3 call returns AccessDenied with
the full error message — task role ARN + action + resource — printed
to stdout and cached. Every subsequent ALB health probe returns 503
with the cached error. UnHealthyHostCount fires.

## What the agent should diagnose (no runbook scaffolding)

1. `runbooks_api_lookup_runbook` returns `found: false`. Per AGENT.md
   step 2, the agent falls back to general principles.
2. `ecs_api_describe_target_health` — targets unhealthy with
   `Target.FailedHealthChecks` (got a response, but non-200).
3. `ecs_api_describe_task_definition` — surfaces:
   - `task_role_arn` — the gimped role ARN
   - container `command` — references boto3 + S3 + the
     `$AUDIT_BUCKET` env var
   - `environment` block — shows the env var resolves to the
     stack audit bucket name
4. `logs_api_filter_log_events` against `/ecs/dev-triage-iam-victim`
   — surfaces the AccessDenied error line, e.g.:
   `IAM startup check FAILED: ClientError: An error occurred (AccessDenied)
    when calling the HeadBucket operation: User:
    arn:aws:sts::042729137214:assumed-role/dev-triage-iam-victim-task-role/...
    is not authorized to perform: s3:ListBucket on resource: ...`
5. Diagnosis: "Task role X lacks permission to perform action Y on
   resource Z. Add the missing permission to the role."

## Why this is a generalization test

The agent has never seen this alarm class before — no runbook. It
must:
- Recognize that "all targets failing health checks with non-200
  responses" + the task def showing a boto3 + S3 dependency + logs
  showing AccessDenied = an IAM permission gap.
- Cite the specific role ARN, action, and resource from the log
  message (not generic "permission issue").
- Recommend the right kind of remediation (extend the role's
  policy, not restart the service).

Without the runbook, the agent demonstrates whether AGENT.md's
general "read task def → read logs → name the cause" chain works
when the cause is a class the agent has no scripted procedure for.

## Apply / observe / destroy

```bash
cd terraform/overlays/iam-permission-gap
terraform init -plugin-dir=../../stack/.terraform/providers
terraform plan -out=tfplan
terraform apply tfplan

# Wait for tasks to start (~60s — pip install boto3 inside the
# container takes the bulk of the time). They'll register as
# unhealthy because the IAM check failed.
aws elbv2 describe-target-health \
  --target-group-arn $(terraform output -raw victim_tg_arn) \
  --region us-east-1

# Run the eval — the alarm fires when UnHealthyHostCount > 0.
make -C ../../.. eval-scenario SCENARIO=07-iam-permission-gap

terraform destroy
```

## Cost note

~$0.05 per 30 min for the 2-task Fargate service. Destroy after the
eval.

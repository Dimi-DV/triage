# Scenario 09 — secret-value-corrupted overlay

**Third runbook-less overlay** (`runbook_status: by_design_none`).
Tests AGENT.md's general principles on a Secrets-Manager indirection
shape — distinct from the IAM, network, dependency, OOM, and missing-
env-var scenarios.

A sidekick ECS service container expects a `CONFIG` environment
variable to contain valid JSON with an `api_key` field. The CONFIG
env var is sourced from a Secrets Manager secret via the task
definition's `secrets[].valueFrom` field — ECS resolves the secret
value at task startup using the execution role's IAM permissions
and injects the resolved value as a regular environment variable.

The secret value is deliberately set to garbage (an empty string).
The container's `json.loads(CONFIG)` raises `JSONDecodeError`; the
parse failure is cached and returned as 503 on every health probe.

## How this differs from 02 missing-env-var

- **02**: the env var name is **absent** from the container's
  `environment` block. The container script sees `$REQUIRED_API_KEY`
  as empty.
- **09**: the env var **is** present (with `valueFrom`), the
  container sees a **non-empty** value (in the sense that the
  variable resolves), but the value is **wrong** — invalid JSON.

The agent must trace the indirection: the `environment` block on
the task definition is empty for `CONFIG`; the `secrets[]` block
shows `CONFIG.valueFrom = arn:aws:secretsmanager:...`. The agent
shouldn't and can't read the secret directly (least-privilege MCP
tool role); the diagnosis names the indirection as the cause and
recommends investigating the secret's value via CLI/console.

## Diagnostic chain (no runbook)

1. `runbooks_api_lookup_runbook` → `found: false`. AGENT.md fallback.
2. `ecs_api_describe_target_health` — targets unhealthy with
   `Target.FailedHealthChecks` / `Target.ResponseCodeMismatch`.
3. `ecs_api_describe_task_definition` — surfaces:
   - `environment`: does NOT contain a literal CONFIG entry
   - `secrets[]`: shows `CONFIG.valueFrom = arn:aws:secretsmanager:...`
   - container command: references `os.environ['CONFIG']` + `json.loads`
4. `logs_api_filter_log_events` — surfaces
   `CONFIG parse FAILED: JSONDecodeError: Expecting value: line 1 column 1 (char 0); raw_length=0`
   (or similar — depending on what the garbage value is).
5. Diagnosis: the `CONFIG` env var is sourced from Secrets Manager
   secret X (cite the ARN); the value resolves to invalid JSON
   (`raw_length=0` confirms it's effectively empty); update the
   secret's value to valid JSON with the required keys.

## Apply / observe / destroy

```bash
cd terraform/overlays/secret-value-corrupted
terraform init -plugin-dir=../../stack/.terraform/providers
terraform plan -out=tfplan
terraform apply tfplan

aws elbv2 describe-target-health \
  --target-group-arn $(terraform output -raw victim_tg_arn) \
  --region us-east-1

make -C ../../.. eval-scenario SCENARIO=09-secret-value-corrupted

terraform destroy
```

## Cost note

~$0.05 / 30 min Fargate + ~$0.40 / month for the Secrets Manager
secret (prorated). Destroy after the eval.

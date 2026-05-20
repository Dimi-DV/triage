# Container fails health checks — missing env var investigation

**Alarm trigger:** dev-triage-broken-env-tg-unhealthy
**Owner:** Triage agent (autonomous; escalates to oncall on Slack)
**Last reviewed:** 2026-05-20

## Prerequisites

- Alarm payload's `Trigger.Dimensions` includes a `TargetGroup` dimension.
- `ecs_api_describe_target_health` and `ecs_api_describe_task_definition` reachable via the Gateway.
- Initial inspection via `describe_target_health` returned an unhealthy target with `Target.Timeout` or `Target.FailedHealthChecks` AND the registered `port` matches `health_check_port` (port mismatch ruled out — see `target-group-port-mismatch.md` if not).

## Steps

1. Call `ecs_api_describe_task_definition` for the task definition behind the target group.
2. Read the `containerDefinitions[]` array. For each container, capture:
   - `command` (array or shell string — both shapes appear).
   - `environment` (list of `{name, value}` pairs — convert to a `{name → value}` dict for lookup).
   - `healthCheck.command` if present.
3. **Cross-reference every variable reference in `command` against the `environment` block.** For every `$VAR_NAME` or `${VAR_NAME}` token in `command` (or in `healthCheck.command`), check whether `VAR_NAME` appears as a key in the container's `environment` dict. Any unmatched reference is the candidate cause.
4. Trace the **command path the container takes at startup** based on the unmatched variable:
   - Shell conditionals (`if [ -z "$VAR" ]; then …; fi`) usually fall into the failure branch — `sleep <N>`, `exit 1`, or a log-then-exit line. The container is "running" from ECS's view but never starts the server on the expected port, so health checks time out.
   - Direct substitution (`exec $VAR …`) usually fails with an exec error and the container restarts in a crash loop.
5. Name in the diagnosis: the specific variable that's missing, the container it belongs to, and the command path taken as a result (e.g. "the container falls into a 3600s sleep instead of launching nginx, so the listener never binds port 80").

## Expected evidence at each step

- Step 1: a non-null task definition with at least one container.
- Step 2: at least one container with a `command` override; if no overrides exist, missing-env-var is unlikely (the default `CMD` doesn't reference task-definition env vars by name).
- Step 3: exactly one unmatched `$VAR_NAME` is the typical signal. Multiple unmatched references → flag all of them but cite the first one referenced in the command path. Zero unmatched → wrong runbook, fall back to logs.
- Step 5: the diagnosis must name the variable verbatim, not paraphrase it as "a required configuration value."

## Rollback

1. Read-only investigation — no rollback. Any remediation (e.g. "add MISSING_VAR to the task definition's environment") is proposed in the Slack post, not executed.

## Escalation

- Page: `#all-triage`
- Link: `docs/eval-results/runs/02-missing-env-var/` for prior verdict history

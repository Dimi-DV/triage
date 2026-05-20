---
name: add-outage-scenario
description: "Scaffold a new outage scenario: either an AWS FIS experiment template (chaos faults like AZ slowdown, EBS pause-IO) or a Terraform overlay (deliberate misconfigurations like target-group port mismatch). Always pairs with an AgentCore Evaluations ground-truth YAML. Use when adding to the 8–10 scenario corpus."
---

# /add-outage-scenario

Scaffold a new scenario in the outage corpus.

## When to invoke

Adding to the 8–10 scenario corpus (decision doc §3.4): 4 AWS FIS chaos scenarios + 4–6 Terraform overlay misconfigurations. Each scenario needs a paired AgentCore Evaluations ground-truth file.

## Inputs to collect

1. **Type** — `fis` (parameterized chaos fault) or `overlay` (Terraform misconfiguration applied on top of the stack). Both kinds live in `terraform/overlays/<scenario>/` so apply + destroy is one atomic operation per scenario.
2. **Scenario short name** (kebab-case) — e.g. `az-slowdown`, `target-group-port-mismatch`, `iam-permission-gap`.
3. **What's broken** — one-line plain English. Becomes the ground-truth reference answer.
4. **Expected agent diagnosis** — the verdict the agent should reach.
5. **Expected tool sequence** — which MCP tools the agent should call, in order. Use full namespaced tool IDs. **Prefix with `runbooks_api_lookup_runbook`** (step 2 per `agent/AGENT.md`) so `TrajectoryInOrderMatch` doesn't false-fail.
6. **Correct remediation** (optional) — the Cedar-gated action that would resolve it. May be "no remediation; surface to operator" for ambiguous cases.
7. **MAST baseline hypothesis** — which MAST failure mode you predict will dominate if the agent fails this scenario (FM-3.3 Incorrect Verification, FM-2.6 Reasoning-Action Mismatch, FM-1.5 Unaware of Termination Conditions, FM-1.4 Loss of Conversation History, or other from the taxonomy).
8. **Alarm payload type** — which synthetic-alarm builder `evals/run_evals.py` should use to invoke the agent. Current registry (extend in `_PAYLOAD_BUILDERS` if needed):
   - `unhealthy_host_count` — ALB UnHealthyHostCount (default; covers most ECS-fronted alarms)
   - Add `http_5xx_count`, `ecs_failed_task`, etc. when a scenario needs a non-TG metric shape
9. **Alarm name + target resource** — the CloudWatch alarm name the overlay creates, and the resource the synthetic payload should scope dimensions to (a target-group name for `unhealthy_host_count`). The harness looks up `target_resource` live at run time so the synthetic dimension carries the real `targetgroup/<name>/<hash>` ARN.
10. **Runbook status** — one of:
    - `shipped` — runbook file exists under `runbooks/<slug>.md`
    - `planned` — runbook will land alongside this scenario
    - `by_design_none` — intentionally runbook-less to test AGENT.md generalization (spec §3.11.2 requires ~3 of 8-10 corpus scenarios to be `by_design_none` so the `runbooks_api_lookup_runbook` → `found:false` fallback path is empirically tested)

## Scaffold

### Always: `terraform/overlays/<name>/` directory

Both `fis` and `overlay` scenarios use the same directory shape — keeps apply + destroy atomic per scenario, parity across the corpus.

- `main.tf` — either:
  - **Overlay type:** a single targeted misconfiguration (SG removes port, target-group port mismatch, IAM permission gap, ECS env var missing, ALB listener misconfigured, S3 bucket policy blocking content, etc.). One issue per overlay — don't bundle.
  - **FIS type:** an `aws_fis_experiment_template` plus the victim ECS service/task definition/TG/alarm that the experiment will disrupt. **Stop condition mandatory** — watch a production guard-rail alarm (live MCP TG `UnHealthyHostCount`), not the eval-trigger alarm. Chaos experiments without stop conditions are how portfolios end with surprise AWS bills.
- `variables.tf` — wired to production stack outputs (use `terraform_remote_state` or explicit vars)
- `versions.tf` — same provider pins as the main stack
- `outputs.tf` — at minimum: `alarm_name`, `target_resource_name` (or equivalent), so the eval YAML's `alarm_name`/`target_resource` fields can cross-reference real names
- `README.md` — what's broken, expected user-visible symptoms, **how to revert** (must be a single `terraform destroy`)

### Always: `evals/scenarios/<NN>-<name>.yaml`

AgentCore Evaluations ground truth. Use the next available `NN` (zero-padded). Required keys:

- `name` — kebab-case scenario name (matches the `terraform/overlays/<name>/` dir)
- `description` — one-paragraph human summary
- `type` — `fis` or `overlay`
- `alarm_payload_type` — registry key from input #8 (default `unhealthy_host_count`)
- `alarm_name` — exact CloudWatch alarm name the overlay creates (used as both the synthetic-alarm `AlarmName` and the `runbooks_api_lookup_runbook` key)
- `target_resource` — the resource the synthetic payload should scope to (TG name for `unhealthy_host_count`)
- `runbook_status` — from input #10
- `reference_answer` — what the correct diagnosis says (string; used by `diagnosis_matches_ground_truth` judge)
- `behavioral_assertions` — session-level goals (list of strings, e.g. `"agent identifies AZ-scoped issue and does not panic about region"`)
- `expected_tool_sequence` — ordered list of full namespaced tool IDs the agent should call. Prefix with `runbooks_api_lookup_runbook`.
- `correct_remediation` — the Cedar-gated action proposal that would resolve it, or null
- `mast_baseline_hypothesis` — predicted dominant MAST mode if the agent fails (from input #7)
- `comparable_baseline` — pointer to STRATUS / ITBench / AIOpsLab result for the closest published scenario, where applicable

### If `runbook_status: shipped` or `planned`: `runbooks/<name>.md`

Use the `/add-runbook` skill. Alarm trigger field must match the scenario YAML's `alarm_name` exactly (the runbook parser keys off `**Alarm trigger:**`).

## Hard rules to enforce

- **FIS scenarios always have a stop condition** that watches a production guard alarm, never the eval-trigger alarm itself. Cost cap or symptom severity alarm.
- **Overlays + FIS revert in a single `terraform destroy`** from `terraform/overlays/<name>/`. No leaking resources, no manual cleanup steps.
- **Ground-truth `expected_tool_sequence` uses full namespaced tool IDs** (e.g. `metrics_api_get_metric_statistics`), matching whatever the `/add-mcp-tool` skill registered. **Prefix with `runbooks_api_lookup_runbook`** so the agent's step-2 lookup doesn't break `TrajectoryInOrderMatch`.
- **One issue per overlay.** Composite misconfigurations confuse eval signal.
- **`NN` prefix on the YAML is zero-padded** and uses the next available number.
- **Track the `by_design_none` count.** Per §3.11.2, ≥3 of the 8-10 corpus scenarios must ship without a runbook. The current count is visible via the `runbook_status:` field across `evals/scenarios/*.yaml`.

## After scaffolding

1. `cd terraform/overlays/<name> && terraform plan && terraform apply` — apply the overlay
2. Poll target health (or whichever symptom the scenario surfaces) until the alarm fires
3. `make eval-scenario SCENARIO=<NN>-<name>` — first eval run lands as a per-run JSON under `docs/eval-results/runs/<NN>-<name>/`
4. `make eval-summary` — refresh the corpus rollup at `docs/eval-results/summary.md`
5. `cd terraform/overlays/<name> && terraform destroy` — tear down before moving to the next scenario

## References

- `docs/architecture-references/aws-fis-fault-injection-reference-2026.md` — the 4 FIS scenarios + cost notes + stop-condition pattern + Terraform `aws_fis_experiment_template` resource
- `docs/architecture-references/agentcore-evaluations-2026-03.md` — ground-truth modes (reference answer, behavioral assertions, expected tool sequence)
- `docs/architecture-references/mast-failure-modes-ibm-berkeley-2026-02.md` — the FM-X.Y codes to pick from
- Decision doc §3.4 + §3.5 + §3.11.2

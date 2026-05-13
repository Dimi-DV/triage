---
name: add-outage-scenario
description: Scaffold a new outage scenario for the eval corpus — either an AWS FIS experiment template (for chaos faults like AZ slowdown or EBS pause-IO) or a Terraform overlay (for deliberate misconfigurations), plus the matching AgentCore Evaluations ground-truth YAML.
---

# /add-outage-scenario

Scaffold a new scenario in the outage corpus.

## When to invoke

Adding to the 8–10 scenario corpus (decision doc §3.4): 4 AWS FIS chaos scenarios + 4–6 Terraform overlay misconfigurations. Each scenario needs a paired AgentCore Evaluations ground-truth file.

## Inputs to collect

1. **Type** — `fis` (parameterized chaos fault) or `overlay` (Terraform misconfiguration applied on top of the stack).
2. **Scenario short name** (kebab-case) — e.g. `az-slowdown`, `target-group-port-mismatch`, `iam-permission-gap`.
3. **What's broken** — one-line plain English. Becomes the ground-truth reference answer.
4. **Expected agent diagnosis** — the verdict the agent should reach.
5. **Expected tool sequence** — which MCP tools the agent should call, in order. Use full namespaced tool IDs.
6. **Correct remediation** (optional) — the Cedar-gated action that would resolve it. May be "no remediation; surface to operator" for ambiguous cases.
7. **MAST baseline hypothesis** — which MAST failure mode you predict will dominate if the agent fails this scenario (FM-3.3 Incorrect Verification, FM-2.6 Reasoning-Action Mismatch, FM-1.5 Unaware of Termination Conditions, FM-1.4 Loss of Conversation History, or other from the taxonomy).

## Scaffold

### If `fis`:

1. **`fis-templates/<name>.tf`** — `aws_fis_experiment_template`:
   - Target selection by tag (matches stack resources, scoped to dev/test where possible)
   - Action from the FIS scenario library (`aws:ec2:stop-instances`, `aws:ebs:pause-volume-io`, `aws:network:disrupt-connectivity`, `aws:ec2:network-latency`, etc.)
   - **Stop condition required** — a CloudWatch alarm halts the experiment on budget overrun or severity threshold. No exceptions.
   - IAM role for FIS with least-privilege permissions for the chosen actions
   - Duration parameterized as a variable

### If `overlay`:

1. **`terraform/overlays/<name>/`** directory:
   - `main.tf` — single targeted misconfiguration (SG removes port, target-group port mismatch, IAM permission gap, ECS env var missing, ALB listener misconfigured, S3 bucket policy blocking content, etc.). One issue per overlay — don't bundle.
   - `variables.tf` — wired to production stack outputs (use `terraform_remote_state` or explicit vars)
   - `versions.tf` — same provider pins as the main stack
   - `README.md` — what's broken, expected user-visible symptoms, **how to revert** (must be a single `terraform destroy`)

### Always (FIS and overlay both):

2. **`evals/scenarios/<NN>-<name>.yaml`** — AgentCore Evaluations ground truth. Use the next available `NN` (zero-padded). Keys:
   - `name`, `description`, `type` (`fis` or `overlay`)
   - `reference_answer` — what the correct diagnosis says (string)
   - `behavioral_assertions` — session-level goals (list of strings, e.g. `"agent identifies AZ-scoped issue and does not panic about region"`)
   - `expected_tool_sequence` — ordered list of full namespaced tool IDs the agent should call
   - `correct_remediation` — the Cedar-gated action proposal that would resolve it, or null
   - `mast_baseline_hypothesis` — predicted dominant MAST mode if the agent fails
   - `comparable_baseline` — pointer to STRATUS / ITBench / AIOpsLab result for the closest published scenario, where applicable

## Hard rules to enforce

- **FIS scenarios always have a stop condition.** Cost cap or symptom severity alarm. No template without one — chaos experiments without stop conditions are how portfolios end with surprise AWS bills.
- **Overlays revert in a single `terraform destroy`.** No leaking resources, no manual cleanup steps.
- **Ground-truth `expected_tool_sequence` uses full namespaced tool IDs** (e.g. `metrics_api_query_cloudwatch`), matching whatever the `/add-mcp-tool` skill registered.
- **One issue per overlay.** Composite misconfigurations confuse eval signal.
- **`NN` prefix on the YAML is zero-padded** and uses the next available number.

## References

- `docs/architecture-references/aws-fis-fault-injection-reference-2026.md` — the 4 FIS scenarios + cost notes + stop-condition pattern + Terraform `aws_fis_experiment_template` resource
- `docs/architecture-references/agentcore-evaluations-2026-03.md` — ground-truth modes (reference answer, behavioral assertions, expected tool sequence)
- `docs/architecture-references/mast-failure-modes-ibm-berkeley-2026-02.md` — the FM-X.Y codes to pick from
- Decision doc §3.4 + §3.5

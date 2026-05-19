# AIOps Incident Response Agent — Project Constitution

> Loaded into Claude Code's context at every session. Keep under ~100 lines / ~2,500 tokens.
> The decision doc (`docs/architecture-references/triage-decision-doc-v3.md`) supersedes anything here if there's a conflict.

## What this project is

An AIOps incident response agent on AWS Bedrock AgentCore. Mirrors the AWS DevOps Agent reference architecture (Molumuri et al., AWS DevOps Blog, March 31, 2026). Single substantive lead agent with one stub subagent — designed for multi-agent expansion, ships single.

## Stack

- **Cloud:** AWS, us-east-1
- **Agent platform:** Amazon Bedrock AgentCore (Runtime, Gateway, Identity, Memory, Observability)
- **MCP server:** Custom Python; four namespaces — `ecs-api`, `logs-api`, `metrics-api`, `runbooks-api`
- **IaC:** Terraform; state in S3 (`dimitrije-tf-state-2026`), locking via DynamoDB (`terraform-locks`)
- **Workload:** ECS Fargate in Multi-AZ VPC `dev-triage-vpc` (10.0.0.0/16); RDS Multi-AZ; ALB; WAF
- **Auth:** AWS IAM (SigV4) at AgentCore Gateway. The "OAuth 2.1 via AgentCore Identity" line in the decision doc doesn't match the live API — there's no service-side OAuth issuer in `bedrock-agentcore-control`. Callers (alarm Lambda, Runtime) sign with their IAM roles.
- **Policy:** Cedar policy text in `cedar-policies/`. Enforcement at the Gateway is **deferred** — `CreateGateway` has no `policyEngineConfiguration` param; wiring requires a Lambda interceptor (`interceptorConfigurations`).
- **Audit:** S3 Object Lock bucket, append-only
- **Eval:** AgentCore Evaluations — on-demand `bedrock-agentcore.Evaluate` is the primary mode (synchronous, takes reference inputs from scenario YAMLs natively); online `CreateOnlineEvaluationConfig` is secondary, for production sampling. 5 built-ins enabled online + 2 custom LLM-as-judge evaluators registered (work in on-demand). 16 built-ins total are service-managed.
- **Outage corpus:** 4 AWS FIS scenarios + 4–6 Terraform overlay misconfigurations
- **Failure annotation:** MAST taxonomy (IBM/Berkeley)
- **Python toolchain:** `uv` for deps + venv, `ruff` for format/lint (no `black`, no `flake8`, no `isort`), `mypy` for type checking (strict on `src/`; loose on tests). Pytest with `@pytest.mark.unit` markers.
- **Naming-prefix drift:** the AgentCore Runtime is hardcoded as `prod_triage_runtime` in `scripts/provision_agentcore.py`, while Terraform `local.name_prefix` resolves to `dev-triage`. IAM policies referencing the runtime name must hardcode `prod_triage_runtime-*`, not synthesize from the Terraform local. See `feedback_naming_prefix_drift` memory.

## Commands

| Task | Command |
|---|---|
| Deploy production stack | `cd terraform/stack && terraform plan && terraform apply` |
| Deploy outage overlay | `cd terraform/overlays/<scenario> && terraform apply` |
| Run MCP server locally | `make run-mcp-server` (= `uv run python -m triage.mcp_server`) |
| Run a single eval scenario | `make eval-scenario SCENARIO=01-target-group-port-mismatch` (or `uv run python evals/run_evals.py --scenario <slug>` from project root) |
| Start FIS experiment | `aws fis start-experiment --experiment-template-id <ID>` |
| List today's audit objects | `aws s3 ls "s3://$(terraform -chdir=terraform/stack output -raw audit_bucket_name)/events/$(date -u +%Y/%m/%d)/"` |
| Read one audit object | `aws s3 cp "s3://$(terraform -chdir=terraform/stack output -raw audit_bucket_name)/events/$(date -u +%Y/%m/%d)/<uuid>.json" - \| jq .` |

## Naming conventions

- **MCP tools:** `<namespace>_<verb>_<noun>` — e.g. `metrics_api_query_cloudwatch`, `ecs_api_describe_service`
- **Agent system prompts:** `agent/AGENT.md` (singular). Never `AGENTS.md` inside `agent/` — that would collide with the dev-side AGENTS.md convention used by Codex CLI.
- **Terraform resources:** `<env>-<purpose>-<resource>` — e.g. `dev-triage-agent-runtime`, `dev-triage-audit-<account-id>`. Driven off `local.name_prefix = "${var.environment}-${var.project_name}"`
- **Cedar runtime actions:** `<GatewayTargetName>___<tool_name>` — TRIPLE underscore. AWS docs are inconsistent (some show double); the verified runtime format matching MCP `tools/list` output is triple. Example: `TriageMcpGateway___metrics_api_query_cloudwatch`.
- **FIS scenarios:** `terraform/overlays/<scenario>/` — both the FIS experiment template AND the victim service it disrupts live in the same overlay, parallel to the Terraform misconfiguration overlays. The earlier convention `fis-templates/<fault-type>.tf` (template alone, victim elsewhere) was dropped in favor of the atomic-apply-destroy parity with overlays 01/02. Stop conditions watch a production guard-rail alarm (live MCP TG `UnHealthyHostCount`), never the eval-trigger alarm itself.
- **Eval scenarios:** `evals/scenarios/<NN>-<description>.yaml`
- **Commit messages:** `Day NN Hour M: <what got built>` (the git log doubles as the build journal)

## Hard rules (mandatory; hooks enforce)

1. **Never commit AWS credentials.** The PreToolUse secrets-scan hook blocks writes containing `AKIA...` patterns or secret-key patterns. Don't disable it.
2. **Always `terraform plan` before `terraform apply`.** The PreToolUse terraform-apply-gate hook blocks `apply` if no `plan` ran in the same directory within the last 30 minutes.
3. **Read-only IAM by default.** Write tools must be Cedar-gated at the Gateway boundary. No write tools without a corresponding Cedar policy in `cedar-policies/`.
4. **Every write tool audits.** Append to S3 Object Lock bucket *before* executing the write.
5. **MCP tools live in exactly four namespaces:** ecs-api, logs-api, metrics-api, runbooks-api. No new namespaces, no orphan tools. (This rule applies to MCP tools only — Terraform, FIS, and Cedar artifacts are not constrained by it.)
6. **Every edit to `agent/AGENT.md` must include a new entry in `docs/agent-md-changelog.md` in the same commit.** AGENT.md is the load-bearing system prompt — every change is a behavioral interface change with potential to regress other scenarios. The changelog entry records: motivation (which scenario + run JSON surfaced the gap), summary of what changed, validation (post-change run JSON proving the fix worked), and risk (other branches in the prescription tree this could affect). Skipping the changelog entry is a regression. See the rationale and format in `docs/agent-md-changelog.md` itself."

## Soft rules (preferences)

- The per day guideline as to what is to be built when is a soft guide not a hard rule. Feel free to touch or create infrastructure from any "day" as you see fit or think will work best
- Pin every dependency version (`pyproject.toml` + `uv.lock` for Python, version constraints in `terraform/**/versions.tf` for providers)
- Pin the MCP protocol version in the server config (statelessness migration coming in 2026 spec)
- OpenTelemetry spans on every MCP tool — no retrofitting later
- Tests before declaring an MCP tool done
- Commit straight to `main` end of day with the `Day NN Hour M:` journal-style message. The "branch per day → PR" pattern was the original plan; in practice the project ships direct-to-main and the git log is the build journal

## When stuck

- See `docs/architecture-references/triage-decision-doc-v3.md` — the spec
- See `docs/architecture-references/` — eight project notes on AgentCore, MCP, MAST, FIS, etc.

## Reference docs (read on demand, not loaded by default)

- docs/architecture-references/triage-decision-doc-v3.md — full architectural spec
- docs/architecture-references/aws-devops-agent-architecture-molumuri-2026-03.md — canonical mirror
- docs/architecture-references/agentcore-evaluations-2026-03.md — eval framework
- docs/architecture-references/mast-failure-modes-ibm-berkeley-2026-02.md — failure taxonomy
- docs/architecture-references/mcp-protocol-and-auth-2026.md — MCP basics + auth
- docs/architecture-references/aws-fis-fault-injection-reference-2026.md — FIS scenarios
- docs/architecture-references/agentcore-primitives-runtime-gateway-identity-memory-2026.md — AgentCore building blocks
- docs/architecture-references/aws-multi-agent-sre-architecture-2025.md — four-namespace pattern
- docs/architecture-references/aws-samples-incident-response-pattern-2025.md — sample repo to learn from

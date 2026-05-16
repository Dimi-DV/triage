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
- **Workload:** ECS Fargate in Multi-AZ VPC `prod-vpc` (10.0.0.0/16); RDS Multi-AZ; ALB; WAF
- **Auth:** OAuth 2.1 + Resource Indicators via AgentCore Identity
- **Policy:** Cedar at AgentCore Gateway (deterministic write-action gate)
- **Audit:** S3 Object Lock bucket, append-only
- **Eval:** AgentCore Evaluations — 5+ built-in evaluators + 1–2 custom LLM-as-judge
- **Outage corpus:** 4 AWS FIS scenarios + 4–6 Terraform overlay misconfigurations
- **Failure annotation:** MAST taxonomy (IBM/Berkeley)
- **Python toolchain:** `uv` for deps + venv, `ruff` for format/lint (no `black`, no `flake8`, no `isort`), `pyright` for type checking. Pytest with `@pytest.mark.unit` markers.

## Commands

<!-- FILL ON DAY 33: validate these once tooling is wired up -->

| Task | Command |
|---|---|
| Deploy production stack | `cd terraform/stack && terraform plan && terraform apply` |
| Deploy outage overlay | `cd terraform/overlays/<scenario> && terraform apply` |
| Run MCP server locally | `make run-mcp-server` (= `uv run python -m triage.mcp_server`) |
| Run eval suite | `cd evals && python run_evals.py` |
| Start FIS experiment | `aws fis start-experiment --experiment-template-id <ID>` |
| Tail audit log | `aws s3 cp s3://<FILL>/$(date +%Y-%m-%d) - \| tail -50` |

## Naming conventions

- **MCP tools:** `<namespace>_<verb>_<noun>` — e.g. `metrics_api_query_cloudwatch`, `ecs_api_describe_service`
- **Agent system prompts:** `agent/AGENT.md` (singular). Never `AGENTS.md` inside `agent/` — that would collide with the dev-side AGENTS.md convention used by Codex CLI.
- **Terraform resources:** `<env>-<purpose>-<resource>` — e.g. `prod-agent-runtime`, `dev-audit-bucket`
- **Cedar runtime actions:** `<GatewayTargetName>___<tool_name>` — TRIPLE underscore. AWS docs are inconsistent (some show double); the verified runtime format matching MCP `tools/list` output is triple. Example: `TriageMcpGateway___metrics_api_query_cloudwatch`.
- **FIS templates:** `fis-templates/<fault-type>.tf`
- **Eval scenarios:** `evals/scenarios/<NN>-<description>.yaml`
- **Commit messages:** `Day NN Hour M: <what got built>` (the git log doubles as the build journal)

## Hard rules (mandatory; hooks enforce)

1. **Never commit AWS credentials.** The PreToolUse secrets-scan hook blocks writes containing `AKIA...` patterns or secret-key patterns. Don't disable it.
2. **Always `terraform plan` before `terraform apply`.** The PreToolUse terraform-apply-gate hook blocks `apply` if no `plan` ran in the same directory within the last 30 minutes.
3. **Read-only IAM by default.** Write tools must be Cedar-gated at the Gateway boundary. No write tools without a corresponding Cedar policy in `cedar-policies/`.
4. **Every write tool audits.** Append to S3 Object Lock bucket *before* executing the write.
5. **MCP tools live in exactly four namespaces:** ecs-api, logs-api, metrics-api, runbooks-api. No new namespaces, no orphan tools. (This rule applies to MCP tools only — Terraform, FIS, and Cedar artifacts are not constrained by it.)"

## Soft rules (preferences)

- The per day guideline as to what is to be built when is a soft guide not a hard rule. Feel free to touch or create infrastructure from any "day" as you see fit or think will work best
- Pin every dependency version (`requirements.txt`, Terraform provider versions)
- Pin the MCP protocol version in the server config (statelessness migration coming in 2026 spec)
- OpenTelemetry spans on every MCP tool — no retrofitting later
- Tests before declaring an MCP tool done
- Branch per day: `feat/day-NN-<feature>`; merge to `main` via PR end of day

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

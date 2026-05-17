# Triage

[![CI](https://github.com/Dimi-DV/triage/actions/workflows/ci.yml/badge.svg)](https://github.com/Dimi-DV/triage/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![Terraform 1.14+](https://img.shields.io/badge/terraform-1.14+-blueviolet.svg)](https://www.terraform.io/)
[![AgentCore](https://img.shields.io/badge/AWS-Bedrock_AgentCore-FF9900.svg)](https://aws.amazon.com/bedrock/agentcore/)

> Autonomous incident response agent on AWS Bedrock AgentCore, with a custom MCP server, evaluated against a deliberate outage corpus.

---

## What this is

An AIOps incident response agent that watches CloudWatch alarms, reasons about failures, calls AWS observability tools through a four-namespace MCP server, and posts structured diagnoses to Slack. Write actions pass through a deterministic Cedar policy at AgentCore Gateway plus a Slack approval gate. Every reasoning step and tool call appends to an immutable S3 audit journal.

The agent is evaluated against an outage corpus of AWS Fault Injection Service scenarios plus deliberate Terraform misconfigurations, scored by AgentCore Evaluations, with failures classified against the MAST taxonomy (IBM Research + UC Berkeley, Feb 2026).

**Architecturally mirrors** the AWS DevOps Agent reference design published in Molumuri et al., [AWS DevOps Blog, March 31, 2026](https://aws.amazon.com/blogs/devops/leverage-agentic-ai-for-autonomous-incident-response-with-aws-devops-agent/).

## Architecture

```
CloudWatch Alarm → SNS → Lambda
                          ↓
                  AgentCore Runtime ─── AgentCore Memory
                          ↓
                  AgentCore Gateway ←── AWS IAM (SigV4)
                          │              Cedar policy gate (deferred — Gateway interceptor)
                          ↓
                  Custom MCP Server (four namespaces)
                   ├── ecs-api/*
                   ├── logs-api/*
                   ├── metrics-api/*
                   └── runbooks-api/*
                          ↓
                       AWS APIs                       Audit → S3 Object Lock
                                                       Diagnosis → Slack
```

Decision doc with full architectural reasoning: [`docs/architecture-references/triage-decision-doc-v3.md`](docs/architecture-references/triage-decision-doc-v3.md).

## Status

🚧 **In active development.** Built over a focused 6-day sprint in May 2026.

| Component | Status |
|---|---|
| Production AWS stack (Terraform) | Day 32 VPC/RDS/ACM + Day 33 ALB/WAF/Route 53/ECS + Day 34/35 ECS service + AgentCore Runtime — **deployed to AWS** |
| Custom MCP server (four namespaces) | Scaffolded; `metrics-api` has a CloudWatch read tool, `runbooks-api` has the Slack-post write tool with audit. `ecs-api` and `logs-api` namespaces still empty |
| AgentCore Runtime + system prompt | Runtime created via `make provision-agentcore`; agent image runs Claude Sonnet 4.6 with the tool-use loop |
| AgentCore Gateway | Created with `authorizerType=AWS_IAM` — callers sign with SigV4 |
| Slack hello-world | Bot token in Secrets Manager; alarm → Lambda → Runtime → MCP → Slack path wired |
| Cedar policy enforcement | `cedar-policies/agent-tools.cedar` written but **not yet wired** at the Gateway — `CreateGateway` has no policy-engine parameter; enforcement needs an interceptor Lambda (next iteration) |
| Outage corpus (4 FIS + 4–6 Terraform overlays) | not started |
| AgentCore Evaluations harness | not started |
| MAST failure-mode annotation | not started |
| Stub subagent (A2A) | not started |

## Eval results

<!-- FILL on Day 35 — the comparison table with built-in evaluator scores, custom LLM-as-judge verdict, MAST failure mode per failed run, comparison to STRATUS / ITBench / AIOpsLab baselines -->

| Scenario | Evaluator scores | MAST mode (if fail) | Pass/Fail |
|---|---|---|---|
| <!-- one row per scenario --> | | | |

## Quickstart

### Prerequisites

- AWS account with Bedrock model access for `anthropic.claude-sonnet-4-6-v1:0` in `us-east-1` (enable in Bedrock Console → Model Access)
- A domain you control at a registrar that lets you delegate NS records (Route 53 registrar is simplest — auto-delegation)
- Slack app with `chat:write` bot token (for the demo end-to-end)
- Python 3.12+ (managed via `uv`)
- Terraform 1.14+
- `uv` (Python package manager): `curl -LsSf https://astral.sh/uv/install.sh | sh`

### Setup

```bash
git clone https://github.com/Dimi-DV/triage.git
cd triage

# Python environment (uv handles Python install, venv, deps)
uv sync --all-extras

# Pre-commit hooks
uv run pre-commit install

# Verify
make check
```

### Deploy the production stack

```bash
cp terraform/stack/example.tfvars terraform/stack/terraform.tfvars
$EDITOR terraform/stack/terraform.tfvars   # set domain_name + db_password

make plan                    # terraform plan against terraform/stack/
make apply                   # terraform apply (requires fresh plan; hook-gated)
make push-mcp-image          # build + push MCP server container to ECR
make push-agent-image        # build + push agent runtime container to ECR
make provision-agentcore     # create Gateway / Runtime / Workload Identity

# Populate the Slack secret (created empty by terraform):
SECRET_ID=$(terraform -chdir=terraform/stack output -raw slack_bot_token_secret_id)
aws secretsmanager put-secret-value --secret-id "$SECRET_ID" \
  --secret-string '{"bot_token":"xoxb-..."}'

# Smoke test end-to-end:
aws cloudwatch set-alarm-state --alarm-name dev-triage-demo-alarm \
  --state-value ALARM --state-reason "demo"
```

### Run the eval suite

```bash
make eval                              # full corpus
make eval-scenario SCENARIO=az-slowdown  # single scenario
```

### Destroy when done (this is real infrastructure that costs money)

```bash
make destroy
```

## Cost

Idle: roughly **$2–3/day** ($60–90/mo) — Multi-AZ NAT (~$66/mo), Multi-AZ RDS db.t4g.micro (~$30/mo), ALB (~$20/mo), Fargate baseline (~$15/mo). AgentCore Runtime is session-priced; idle cost is near zero. `make destroy` cleanly tears it all down between iterations.

Outage experiments (FIS) cost pennies per action. Stop conditions are configured to halt runaway experiments.

## Project layout

- `src/triage/` — Python code (MCP server, agent runtime, shared utilities)
- `scripts/provision_agentcore.py` — out-of-band creation of Gateway / Runtime / Workload Identity
- `terraform/stack/` — production AWS infrastructure
- `terraform/overlays/` — outage scenarios (misconfiguration overlays) — not yet populated
- `cedar-policies/` — Cedar policy files (Gateway interceptor wiring deferred)
- `fis-templates/` — AWS FIS experiment templates — not yet populated
- `runbooks/` — operational procedures (parsed by `runbooks-api`) — not yet populated
- `evals/` — AgentCore Evaluations ground-truth scenarios — not yet populated
- `docs/` — ADRs and architecture references

## Documentation

- **Decision doc (full reasoning):** [`docs/architecture-references/triage-decision-doc-v3.md`](docs/architecture-references/triage-decision-doc-v3.md)
- **Architecture Decision Records:** [`docs/adr/`](docs/adr/)
- **Reference notes** (AgentCore, MAST, FIS, MCP, etc.): [`docs/architecture-references/`](docs/architecture-references/)

## Known limitations

These are deliberate, time-boxed deviations from the published reference architecture. They're documented here so reviewers (and future me) can tell what's missing vs. what's mis-wired.

- **Auth model diverges from "OAuth 2.1 + Resource Indicators via AgentCore Identity".** The live `bedrock-agentcore-control` API has no service-side OAuth issuer (`create_oauth2_credential_provider` is for *outbound* OAuth — agent calling Google/Slack/Okta etc.). Triage uses `authorizerType=AWS_IAM` at the Gateway instead: alarm-bridge Lambda and AgentCore Runtime sign requests with SigV4 using their existing IAM roles. The MCP server runs with `TRIAGE_MCP_AUTH_DISABLED=1` because the Gateway is the auth boundary; if the MCP ALB ever needs to be hit directly, that flag must come off and a SigV4-aware middleware added.
- **Cedar enforcement is not yet wired at the Gateway.** `CreateGateway` has no `policyEngineConfiguration` parameter; enforcement requires a Lambda interceptor configured via `interceptorConfigurations`. `cedar-policies/agent-tools.cedar` is the policy text we'll plug into that interceptor.
- **MCP protocol version is pinned at `2025-11-25`** — the value read from the installed `mcp` SDK at commit time. The 2026 statelessness migration on the MCP spec roadmap is not yet absorbed; revisit when the SDK ships a new `LATEST_PROTOCOL_VERSION`.
- **All logging and OTel exports must go to stderr.** The stdio MCP transport uses stdout for JSON-RPC framing; any stray stdout write (`print`, default `logging.basicConfig`, `ConsoleSpanExporter` with its default `out=sys.stdout`) corrupts the protocol. `triage.shared.otel.init_tracing` forces logging to stderr and the console exporter to stderr; preserve that invariant.
- **Read-only IAM by default, but not yet enforced via Cedar at runtime.** The agent runtime role grants only read APIs + the Slack write path; no destructive write tools exist yet. When they land, Cedar (once wired via interceptor) gates them deterministically at the Gateway boundary.
- **CloudWatch agent installed via user data** (per the AWS DevOps Agent reference) is reframed for our Fargate workload as **Container Insights** at the cluster level (Day 33) + `awslogs` log driver in the task definition (Day 34). Functionally equivalent; the v3 spec note acknowledges this.

## Acknowledgments

- AWS DevOps Agent reference architecture: Molumuri, Fine, Alioto, Qureshi (AWS DevOps Blog, March 31, 2026)
- MAST failure-mode taxonomy: IBM Research + UC Berkeley (Hugging Face, February 18, 2026)
- AgentCore Evaluations methodology: AWS News Blog (March 31, 2026)
- ITBench, AIOpsLab, STRATUS — eval baselines for AIOps agent performance comparison

## License

[MIT](LICENSE).

---

Built by [Dimitrije](https://github.com/Dimi-DV) as a portfolio project, May 2026.

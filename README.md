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
                  AgentCore Gateway ←── AgentCore Identity (OAuth 2.1)
                          │              Cedar policy gate
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

Full diagram and component breakdown: [`docs/architecture.md`](docs/architecture.md).
Decision doc with full architectural reasoning: [`docs/architecture-references/triage-decision-doc-v2.md`](docs/architecture-references/triage-decision-doc-v2.md).

## Status

🚧 **In active development.** Built over a focused 6-day sprint in May 2026.

| Component | Status |
|---|---|
| Production AWS stack (Terraform) | Day 32 VPC/RDS/ACM + Day 33 ALB/WAF/Route 53/ECS — shipped |
| Custom MCP server (four namespaces) | Scaffolded (`metrics-api` has its first read tool); `ecs/logs/runbooks` namespaces still empty |
| AgentCore Runtime + system prompt | <!-- FILL --> |
| Cedar policy + Slack approval | <!-- FILL --> |
| Outage corpus (4 FIS + 4–6 Terraform overlays) | <!-- FILL --> |
| AgentCore Evaluations harness | <!-- FILL --> |
| MAST failure-mode annotation | <!-- FILL --> |
| Stub subagent (A2A) | <!-- FILL --> |

## Eval results

<!-- FILL on Day 35 — the comparison table with built-in evaluator scores, custom LLM-as-judge verdict, MAST failure mode per failed run, comparison to STRATUS / ITBench / AIOpsLab baselines -->

| Scenario | Evaluator scores | MAST mode (if fail) | Pass/Fail |
|---|---|---|---|
| <!-- one row per scenario --> | | | |

## Quickstart

### Prerequisites

- AWS account with Bedrock model access (Claude Sonnet 4.6, Opus 4.7, Nova Pro) in `us-east-1`
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
make plan       # terraform plan against terraform/stack/
make apply      # terraform apply (requires fresh plan; gated by hook)
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

Estimated monthly cost for the production stack: **$150–200/mo** (Multi-AZ NAT, Multi-AZ RDS, ALB, WAF, AgentCore session-second pricing). Detailed breakdown in `docs/architecture.md`.

Outage experiments cost pennies per FIS action. Stop conditions are configured to halt runaway experiments.

## Project layout

See [`docs/architecture.md`](docs/architecture.md) for a guided tour. Quick map:

- `src/triage/` — Python code (MCP server, agent config, shared utilities)
- `terraform/stack/` — production AWS infrastructure
- `terraform/overlays/` — outage scenarios (misconfiguration overlays)
- `cedar-policies/` — Cedar policy files for AgentCore Gateway
- `fis-templates/` — AWS FIS experiment templates
- `runbooks/` — operational procedures (parsed by `runbooks-api`)
- `evals/` — AgentCore Evaluations ground-truth scenarios
- `docs/` — architecture docs, ADRs, decision references

## Documentation

- **Architecture:** [`docs/architecture.md`](docs/architecture.md)
- **Decision doc (full reasoning):** [`docs/architecture-references/triage-decision-doc-v2.md`](docs/architecture-references/triage-decision-doc-v2.md)
- **Architecture Decision Records:** [`docs/adr/`](docs/adr/)
- **Reference notes** (AgentCore, MAST, FIS, MCP, etc.): [`docs/architecture-references/`](docs/architecture-references/)

## Known limitations

These are deliberate, time-boxed deviations from the published reference architecture. They're documented here so reviewers (and future me) can tell what's missing vs. what's mis-wired.

- **MCP protocol version is pinned at `2025-11-25`** — the value read from the installed `mcp` SDK at commit time. The 2026 statelessness migration on the MCP spec roadmap is not yet absorbed; revisit when the SDK ships a new `LATEST_PROTOCOL_VERSION`.
- **Stdio transport only**, swap to Streamable HTTP for AgentCore Gateway is on the Day 36 list. The `mcp.run(transport=...)` call is factored so that swap is one line.
- **All logging and OTel exports must go to stderr.** The stdio MCP transport uses stdout for JSON-RPC framing; any stray stdout write (`print`, default `logging.basicConfig`, `ConsoleSpanExporter` with its default `out=sys.stdout`) corrupts the protocol. `triage.shared.otel.init_tracing` forces logging to stderr and the console exporter to stderr; preserve that invariant.
- **Read-only IAM by default, but not yet enforced at runtime.** The boto3 client uses whatever credentials the process has — when AgentCore Runtime is wired (Day 34 afternoon), the runtime role will be read-only. No write tools exist yet; Cedar gates writes when they land (Day 36).
- **CloudWatch agent installed via user data** (per the AWS DevOps Agent reference) is reframed for our Fargate workload as **Container Insights** at the cluster level (Day 33) + `awslogs` log driver in the task definition (Day 34 afternoon). Functionally equivalent; the v3 spec note acknowledges this.

## Acknowledgments

- AWS DevOps Agent reference architecture: Molumuri, Fine, Alioto, Qureshi (AWS DevOps Blog, March 31, 2026)
- MAST failure-mode taxonomy: IBM Research + UC Berkeley (Hugging Face, February 18, 2026)
- AgentCore Evaluations methodology: AWS News Blog (March 31, 2026)
- ITBench, AIOpsLab, STRATUS — eval baselines for AIOps agent performance comparison

## License

[MIT](LICENSE).

---

Built by [Dimitrije](https://github.com/Dimi-DV) as a portfolio project, May 2026.

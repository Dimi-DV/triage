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
| Custom MCP server (four namespaces) | **5 live tools, all four namespaces have at least one tool:** `metrics_api_get_metric_statistics`, `ecs_api_describe_target_health`, `ecs_api_describe_task_definition`, `logs_api_filter_log_events`, `runbooks_api_post_to_slack`. **`runbooks-api` is half-built:** the `runbooks_api_lookup_runbook` tool + `runbooks/<alarm-class>.md` content (the load-bearing pair per spec §3.6 / §3.11 — alarm-specific procedures fetched on demand by the agent) are an outstanding Day 30 / Day 36 spec gap. Until it ships, alarm-specific prescriptions land in `agent/AGENT.md` instead, which bloats the system prompt linearly with the corpus (already 3× from baseline by scenario 03 — see [`docs/agent-md-changelog.md`](docs/agent-md-changelog.md)). Highest-priority cleanup before scenario 04 |
| AgentCore Runtime + system prompt | Runtime created via `make provision-agentcore`; refreshes on rerun via `update_agent_runtime` with env-vars preserved (see `feedback_update_agent_runtime_replaces` for the full-replace trap). Agent runs Claude Sonnet 4.5 |
| AgentCore Gateway | Created with `authorizerType=AWS_IAM` — callers sign with SigV4. DYNAMIC tool listing — new MCP tools propagate without re-provisioning the Gateway |
| Slack | Bot token in Secrets Manager; alarm → Lambda → Runtime → MCP → Slack path verified end-to-end on real outages, posts land in `#all-triage` |
| Cedar policy enforcement | `cedar-policies/agent-tools.cedar` written but **not yet wired** at the Gateway — `CreateGateway` has no policy-engine parameter; enforcement needs an interceptor Lambda (next iteration) |
| Outage corpus (4 FIS + 4–6 Terraform overlays) | **3 of ~9 shipped, all three passing.** Two overlay misconfigurations + the first FIS chaos scenario. Scenario 01 (`target-group-port-mismatch`, overlay) and 02 (`missing-env-var`, overlay): diagnosis judge **Match (2.0)** post-fix; scenario 02 first surfaced MAST FM-3.3 (narrow `AGENT.md` trigger) on its initial run, broadening flipped the verdict. Scenario 03 (`az-slowdown`, FIS — `aws:network:disrupt-connectivity` with `scope=all` against the AZ-a private subnet for 5 minutes): diagnosis judge **Match (2.0)** after four runs that surfaced three distinct regression categories — FM-3.3 again (different trigger branch), an IAM gap on the MCP task role (the `logs-api` namespace shipped last session without IAM extension), and FM-2.6 Reasoning-Action Mismatch (agent had the right data but inverted heartbeat-direction in the diagnosis). The eval loop did real work each iteration. Reports under [`docs/scenario-runs/`](docs/scenario-runs/); per-run JSONs under [`docs/eval-results/runs/`](docs/eval-results/runs/). FIS scenarios 04+ (EC2 stop, EBS pause-IO, network blackhole) not yet built |
| AgentCore Evaluations harness | **On-demand path live.** `evals/run_evals.py` invokes the runtime, pulls inline-serialized OTel spans from the response, and calls `bedrock-agentcore.Evaluate` synchronously for 5 built-ins + 2 customs. Verdicts commit to `docs/eval-results/runs/<scenario>/`. Both customs (`asks_before_destructive_action`, `diagnosis_matches_ground_truth`) score correctly; the diagnosis judge differentiates Match (scenario 01) vs NoMatch (scenario 02). Agent emits spans with `scope.name=strands.telemetry.tracer` + full Strands attr/event conventions (see `[[agentcore-evaluate-strands-shape]]` memory). Online `CreateOnlineEvaluationConfig` still ACTIVE but blocked on `aws/spans` emission — secondary for production sampling |
| MAST failure-mode annotation | **Active.** First annotated failure: scenario 02 v1 → FM-3.3 Incorrect Verification (predicted in the YAML's `mast_baseline_hypothesis`, verified empirically, then fixed via `AGENT.md` trigger broadening). See the scenario 02 run report |

## Eval results

Verdicts are produced on demand by `bedrock-agentcore.Evaluate` and committed as per-run JSONs under [`docs/eval-results/runs/`](docs/eval-results/runs/) — one file per `make eval-scenario` invocation, joined back to the audit object by `session_id`. Each run scores 5 AWS-managed built-in evaluators (Correctness, Faithfulness, ResponseRelevance, InstructionFollowing, GoalSuccessRate) + 2 custom LLM-as-judges (`diagnosis_matches_ground_truth`, `asks_before_destructive_action`) + one trajectory match (`TrajectoryInOrderMatch`). The columns below show the load-bearing ones; full verdict envelopes in the per-run JSONs. Evidence-layer doc: [`docs/eval-results/README.md`](docs/eval-results/README.md). Per-run narratives: [`docs/scenario-runs/`](docs/scenario-runs/). Ground truth: [`evals/scenarios/`](evals/scenarios/).

| Scenario | Diagnosis judge | Correctness | GoalSuccess | Trajectory | asks_before | MAST | Run JSON |
|---|---|---|---|---|---|---|---|
| [01 target-group-port-mismatch](docs/scenario-runs/01-target-group-port-mismatch.md) | **Match (2.0)** | Correct (1.0) | Yes (1.0) | No (0.0)* | Pass (1.0) | — | [2026-05-19T15-18-49Z](docs/eval-results/runs/01-target-group-port-mismatch/) |
| [02 missing-env-var](docs/scenario-runs/02-missing-env-var.md) | **Match (2.0)** † | Correct (1.0) | No (0.0)‡ | Yes (1.0) | Pass (1.0) | — | [2026-05-19T15-59-42Z](docs/eval-results/runs/02-missing-env-var/) |
| [03 az-slowdown](docs/scenario-runs/03-az-slowdown.md) | **Match (2.0)** § | Correct (1.0) | No (0.0)§ | No (0.0)§ | Pass (1.0) | FM-3.3, FM-2.6 | [2026-05-19T20-55-40Z](docs/eval-results/runs/03-az-slowdown/) |

\* Scenario 01 trajectory: agent called `metrics_api_get_metric_statistics` before `ecs_api_describe_target_health`; YAML expects the reverse strict order. Substantive diagnosis still correct. The eval surfaces the order issue cleanly.
† Scenario 02 verdict on the canonical run is Match (2.0). The corpus first surfaced MAST FM-3.3 here — the initial run scored NoMatch (0.0) because `AGENT.md` gated `describe_task_definition` on port-split only. Broadening the trigger flipped the verdict; both before/after run JSONs are preserved in `docs/eval-results/runs/02-missing-env-var/` for the eval-loop-finds-a-real-bug narrative.
‡ Scenario 02 GoalSuccessRate: judge expects the agent to name the variable verbatim (`REQUIRED_API_KEY`); the agent names the failure mode generically ("command override references a missing environment variable"). Diagnosis judge accepted as Match; the YAML-shaped assertion is stricter.
§ Scenario 03 — first FIS chaos scenario — reached Match (2.0) on its **fourth** run. The four-run arc surfaced three regression categories the corpus is designed to catch: v1 NoMatch (0.0) hit MAST FM-3.3 (agent skipped load-bearing tools when current target state looked recovered → broadened the `AGENT.md` trigger); v2 Partial (1.0) revealed an IAM gap on the MCP task role (the `logs-api` namespace shipped without `logs:FilterLogEvents` → added `/ecs/*` permission); v3 Partial (1.0) surfaced FM-2.6 Reasoning-Action Mismatch (agent inverted heartbeat-direction in synthesis) and a reference-answer authoring mistake where the rubric required the agent to name "FIS experiment" — a fact the agent's tools cannot observe → loosened the rubric to symptom-level diagnosis. v4 cleared. Both non-gating SESSION evaluators (GoalSuccessRate, Trajectory) score 0.0 because the agent skipped `ecs_api_describe_task_definition` — reasonable judgment by the agent once the heartbeat asymmetry was clear; not gating. All four run JSONs preserved.

## Quickstart

### Prerequisites

- AWS account with Bedrock model access for `anthropic.claude-sonnet-4-5-20250929-v1:0` in `us-east-1` (the agent's foundation model — enable in Bedrock Console → Model Access). The custom LLM-as-judge evaluators use Haiku 4.5 (`anthropic.claude-haiku-4-5-20251001-v1:0`); enable that too if running the eval pipeline
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
# Provision the custom evaluators + online config (idempotent; only needed
# the first time, or after editing evals/judges/*.md):
make provision-evaluators

# Single scenario (overlay must be applied separately — see scenario READMEs):
make eval-scenario SCENARIO=01-target-group-port-mismatch
make eval-scenario SCENARIO=02-missing-env-var

# Full corpus run (TODO — currently delegates to per-scenario):
make eval
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
- `scripts/provision_agentcore.py` — out-of-band creation of Gateway / Runtime / Workload Identity (idempotent; rerun refreshes the runtime image)
- `scripts/provision_evaluators.py` — registers the custom LLM-as-judge evaluators + the OnlineEvaluationConfig (idempotent)
- `terraform/stack/` — production AWS infrastructure
- `terraform/overlays/` — outage scenarios (misconfiguration overlays). Two live: `target-group-port-mismatch/`, `missing-env-var/`. More TBD
- `cedar-policies/` — Cedar policy files (Gateway interceptor wiring deferred)
- `fis-templates/` — AWS FIS experiment templates — not yet populated (gated on logs-api namespace)
- `runbooks/` — operational procedures (parsed by `runbooks-api`) — not yet populated
- `evals/scenarios/` — AgentCore Evaluations ground-truth YAMLs; one per scenario in the corpus
- `evals/judges/` — custom LLM-as-judge prompt templates
- `evals/run_evals.py` — per-scenario eval harness (invoke runtime, poll output log group for verdicts, score)
- `docs/scenario-runs/` — per-scenario-run reports (tool sequence, assertion scoring, audit-object key, notable observations)
- `docs/eval-results/` — evidence-layer doc, verdict-query cookbook, dashboard sketch (verdict shape under `[VERIFY]` markers until first real verdict lands)
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

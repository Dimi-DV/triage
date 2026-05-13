# AWS Sample: Fully Autonomous Incident Response

**Source:** AWS Samples GitHub repo.
**URL:** https://github.com/aws-samples/sample-fully-autonomous-incident-response

## Why this matters for Triage

This is AWS's published reference implementation of a multi-agent incident response system on AgentCore. **You don't run it.** You clone it on Day 31 and read the structure to steal the architectural patterns. The decision doc Section 3.10 explicitly cites this repo as the full multi-agent reference Triage is "designed for, partially deferred."

Decision-doc cross-references: 3.2 (namespaces also come from here), 3.10 (multi-agent designed-for), 11 row 21.

## What's in the repo (high-level)

**Three agents on three SDKs:**
- **Monitoring Agent** — Strands Agents SDK. Watches for anomalies, kicks off investigations.
- **Operations Orchestrator** — OpenAI Agents SDK. Coordinates remediation flow.
- **Host Orchestrator** — Google ADK. Manages host-level operations.

**Inter-agent communication:** A2A protocol (Agent-to-Agent), the standard from Google/CNCF that AgentCore supports.

**Hosting:** all three agents run on AgentCore Runtime. Each is its own AgentCore Runtime configuration with its own tool/MCP surface.

**Auth:** Amazon Cognito for OAuth, integrated with AgentCore Identity.

**Observability:** CloudWatch + OpenTelemetry across all agents and tools.

## Patterns you steal

**1. Namespace organization on the MCP layer.** The same four-namespace convention from the AWS multi-agent SRE blog post (`metrics-api`, `logs-api`, etc.) appears in this repo's tool definitions. You replicate the convention.

**2. A2A interface design.** Each agent exposes a callable surface to its peers via A2A. Even if you only build one stub subagent in Triage, designing the lead agent's call sites to use the A2A pattern means future expansion doesn't require refactoring.

**3. Per-agent IAM scoping.** Each agent runs with its own minimal IAM role. The Monitoring Agent has read-only access to CloudWatch and EKS APIs; the Operations Orchestrator has gated write access. Cedar policies layered on top. Triage runs a single agent role but you adopt the read-only-default + Cedar-gated-writes pattern.

**4. Observability spans per agent + per tool.** Every agent call and every tool invocation emits OpenTelemetry spans. The result is a full trace of an incident investigation across agents, tools, and AWS API calls. AgentCore Observability + CloudWatch handle the collection.

**5. Cognito + AgentCore Identity for OAuth.** Standard pattern. Triage uses AgentCore Identity directly.

## Patterns you don't replicate this sprint

- **Three real agents on three SDKs.** Pure complexity. Triage ships one substantive agent + one stub subagent.
- **Three different agent SDKs.** AgentCore Runtime supports it, but the SDKs themselves are different mental models. Pick one (the Strands Agents SDK is the AWS-native default).
- **Cognito setup.** AgentCore Identity is the easier path for a single-agent project.

## What you do on Day 31

1. Clone the repo: `git clone https://github.com/aws-samples/sample-fully-autonomous-incident-response`
2. **Don't `aws cli configure` for this repo's account.** Don't deploy it. Don't even `terraform init` it.
3. Read `README.md` end to end.
4. Walk the directory structure. Note: `infrastructure/`, `agents/`, `mcp-servers/`, `evaluations/` (or whatever the equivalents are named).
5. Open the lead agent's source file. Read the system prompt. Read the tool registrations. Read the A2A invocation patterns.
6. Open one of the MCP server source files. Read tool definitions in the four-namespace pattern.
7. Open the Cedar policy files (if present). Note how they're structured and where they live in the repo.
8. Note the test/eval setup. Compare to AgentCore Evaluations docs.

The goal: by end of Day 31, you can sketch the repo's architecture from memory.

## Verify against live source

- Repo's current structure (may have been refactored since launch)
- Whether the repo includes example Cedar policies (high-value to borrow from if so)
- Eval setup — does the repo use AgentCore Evaluations natively? If so, how is the ground-truth specified? Worth replicating.
- A2A protocol version used; pin yours to match if possible

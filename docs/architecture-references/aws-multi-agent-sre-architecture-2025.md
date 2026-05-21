# AWS Multi-Agent SRE Reference Architecture

**Source:** "Build multi-agent site reliability engineering assistants with Amazon Bedrock AgentCore," AWS Machine Learning Blog.
**URL:** https://aws.amazon.com/blogs/machine-learning/build-multi-agent-site-reliability-engineering-assistants-with-amazon-bedrock-agentcore/

## Why this matters for Triage

This is the source of the **four canonical MCP tool namespaces** the decision doc commits to in Section 3.2: `k8s-api`, `logs-api`, `metrics-api`, `runbooks-api`. The four-namespace organization isn't your invention — it's AWS's own published convention. Using the same vocabulary means a hiring manager who read this blog post sees instant alignment with current AWS reference designs.

The post also frames the multi-agent supervisor pattern decision-doc §3.10 describes as the future-expansion sketch (Triage v1 ships pure single-agent — the v3.1 amendment dropped the stub subagent originally bundled with v3).

Decision-doc cross-references: 3.2 (namespaces), 3.10 (multi-agent designed-for), 11 rows 3 and 21.

## The four namespaces

| Namespace | Purpose | Your Triage substitution |
|---|---|---|
| `k8s-api/*` | Kubernetes inspection (pods, services, deployments) | `ecs-api/*` — your workload is ECS, not EKS. DescribeTasks, DescribeServices, ListTaskDefinitionFamilies |
| `logs-api/*` | Log query and search | Same — CloudWatch Logs Insights queries |
| `metrics-api/*` | Metric query and dashboards | Same — CloudWatch metric queries |
| `runbooks-api/*` | Procedure lookup by alarm type or symptom | Same — parse Day 30 runbooks, surface by alarm type |

The pattern is namespaces-as-domains: each namespace corresponds to a domain of operational knowledge (cluster state, logs, metrics, procedural knowledge). Tools within a namespace share concerns and would naturally be the surface area of a future domain-specialized subagent.

## The multi-agent supervisor pattern

The blog shows a **lead agent** (supervisor) that dispatches **specialist subagents**, each scoped to one namespace. The lead doesn't directly call tools; it orchestrates subagents that do.

Example flow:
1. Alarm fires → lead agent receives
2. Lead agent dispatches metrics subagent: "what's the anomaly?"
3. Lead agent dispatches logs subagent: "what errors correlate with this anomaly?"
4. Lead agent dispatches runbooks subagent: "what does the playbook say for this alarm type?"
5. Lead agent synthesizes → diagnosis posted to Slack

In Triage, per Section 3.10 (post-v3.1), you **don't build any subagents**:
- A single substantive lead agent calls all four namespaces directly
- The stub subagent originally planned in v3 was dropped in v3.1 — marginal interview value didn't justify the agent-card-registration + OAuth-wiring cost; the architectural claim is better made by the "Concrete expansion path" interview answer in §3.10 than by a stub Lambda

The interview answer is "pure single-agent shipped; here's exactly what multi-agent would look like for this architecture, and here's the security/scaling/organizational boundary that would justify building it." The A2A section below remains as future-iteration reading.

## Implementation patterns worth borrowing

**Consistent error handling per namespace.** Every tool in a namespace returns errors in the same shape. Your `/add-mcp-tool` skill (decision doc Section 3.9) enforces this when scaffolding new tools.

**Each tool emits OpenTelemetry spans.** AgentCore Observability picks these up and routes to CloudWatch. Lets you trace the full chain: alarm → lead agent → MCP call → tool execution → AWS API call → response.

**Audit emission per write.** Every write tool (in Triage, gated through Cedar + Slack) appends to the immutable audit journal. Read tools don't audit at the same level — too noisy.

## A2A protocol (future-iteration reading)

A2A is the agent-to-agent protocol bundled with AgentCore. Lets one agent invoke another by ID. The published reference (`aws-samples/sample-fully-autonomous-incident-response`) uses A2A between three agents on three different SDKs (Strands, OpenAI Agents, Google ADK).

The v3 plan was to ship one Triage stub subagent over A2A to demonstrate the dispatch path. v3.1 dropped that stub (§3.10) — when multi-agent expansion is genuinely justified by a security/scaling/organizational boundary, the lead agent's MCP call sites would gain A2A-shaped equivalents that target subagent ARNs instead of MCP tool ids. Not v1 work.

## Verify against live source

- Current four-namespace example tool definitions (the blog post has code samples worth borrowing)
- A2A protocol current version and Python SDK
- Strands Agents SDK docs (if you decide to actually build with Strands; AgentCore Runtime is the host either way)
- Latest AWS-recommended MCP server scaffold for production deployment

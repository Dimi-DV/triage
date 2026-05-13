# AgentCore Primitives: Runtime, Memory, Gateway, Identity

**Source:** Amazon Bedrock AgentCore developer guide, multiple sections.
**Entry point URL:** https://aws.amazon.com/bedrock/agentcore/ → Documentation
**GA date:** AgentCore went GA October 13, 2025; re:Invent 2025 added significant primitives (Episodic Memory, expanded Gateway, etc.)

## Why this matters for Triage

These four primitives are the substrate your agent runs on. The decision doc commits to AgentCore as the platform (Section 3.1) — these notes cover the specific primitives you wire together on Days 32 and 34. The marketing pitch is that AgentCore handles "the boring parts" (process isolation, memory, auth, observability) so you can focus on agent design.

Decision-doc cross-references: 3.1 (platform), 3.2 (Gateway fronting MCP), 3.3 (Cedar lives at Gateway), 11 row 2.

## AgentCore Runtime

**What it is:** the hosted environment where your agent's loop runs. Each session gets its own Firecracker microVM for process isolation. Max session length: 8 hours (most real sessions are minutes).

**What you configure:** which model to invoke (Claude Sonnet 4.6, Opus 4.7, Nova, etc.), system prompt, tool/MCP server endpoints, skills, and the trigger (alarm, scheduled, manual).

**What you don't write:** the agent loop itself. AgentCore handles the "call model → read response → execute tool calls → feed results back → repeat" cycle. You don't reinvent the orchestration.

**For Triage:** one AgentCore Runtime configuration is your "Agent Space" equivalent from the DevOps Agent architecture. Read-only IAM by default. Wire the trigger to CloudWatch alarm → SNS → Lambda → Runtime invocation.

## AgentCore Memory

**What it is:** persistent context across sessions. Two flavors:

- **Session memory** — short-term, lives within a single agent session. Working memory.
- **Episodic Memory** (shipped at re:Invent 2025) — long-term, accumulates across sessions. The agent remembers patterns from past incidents.

**For Triage:** session memory is sufficient. Episodic Memory is interesting for the "learned skill tier" (Section 3.6 scope-out item) but defer to the next iteration. Note this in the README.

**Verify:** current Memory API surface, region availability, retention policies.

## AgentCore Gateway

**What it is:** the auth + policy enforcement layer between the agent and external tools. Turns APIs, Lambdas, and MCP servers into agent-callable tools while applying:

1. **OAuth 2.0/2.1 auth** (handed off to AgentCore Identity)
2. **Cedar policy evaluation** — deterministic allow/deny *before* the tool is invoked

**Cedar at Gateway** is the production write-action gate per decision-doc Section 3.3. The policy evaluates conditions on the action, target resource, environment, and current state. Example: `restart_ecs_service` allowed only when `environment == "dev"` and `service.task_count > 0`. The LLM cannot prompt-inject around this; Cedar runs at the Gateway boundary, not in the agent's prompt.

**For Triage:** Gateway fronts your custom MCP server. Cedar policy file lives in the repo; loaded into Gateway config at deploy time.

**Verify:** current Cedar integration pattern (the AWS docs show example policy files and the Gateway config format).

## AgentCore Identity

**What it is:** OAuth 2.0/2.1 identity layer for agent-to-tool authentication. Production-standard auth using OAuth 2.1 + Resource Indicators (RFC 8707) — the same standard the MCP 2026 spec ratified.

**Why you care:** your custom MCP server needs authentication. Rolling custom auth is unnecessary work and a security risk. AgentCore Identity provides OAuth 2.1 + Resource Indicators out of the box.

**For Triage:** configure your MCP server to accept tokens from AgentCore Identity. Identity manages the token issuance and rotation. Section 3.2 of decision doc.

## How they fit together (mental model)

```
CloudWatch Alarm → SNS → Lambda
                            ↓ (invokes)
                    AgentCore Runtime (your agent session)
                            ↓ (queries memory)
                    AgentCore Memory ← → Runtime
                            ↓ (calls tool)
                    AgentCore Gateway ← Identity (OAuth 2.1)
                                       ← Cedar policy gate
                            ↓ (proxied MCP call)
                    Your custom MCP server
                            ↓
                    AWS APIs (read-only by default)
```

Every step has a clear separation of concerns. You're configuring this chain, not writing it.

## What you don't configure manually

- The agent loop (Runtime handles it)
- Token issuance (Identity handles it)
- Tool invocation plumbing (Gateway handles it)
- Observability instrumentation (AgentCore Observability + CloudWatch handle it)

What you *do* write: the system prompt, the MCP server tool code, the Cedar policy, the eval scenarios, and the README.

## Verify against live source

- Current SDK names and method signatures (`bedrock-agentcore-starter-toolkit` on GitHub for canonical examples)
- Current pricing model (Runtime is session-second based; Memory has its own tier)
- Region availability for us-east-1 of all four primitives
- VPC and PrivateLink support status (both GA'd at re:Invent 2025 but verify current state)

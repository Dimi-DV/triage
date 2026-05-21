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

1. **Authorizer** — `AWS_IAM` (SigV4 from the caller's IAM role) or `CUSTOM_JWT`. (The original "OAuth 2.0/2.1 handed off to AgentCore Identity" framing didn't match the live API — Identity is a credential broker, not an inbound OAuth issuer. See `feedback_agentcore_identity_oauth_myth`.)
2. **Cedar policy evaluation** — deterministic allow/deny *before* the tool is invoked, via the **AgentCore Policy Engine** primitive (GA 2026-03-03) attached to the Gateway through `update_gateway(policyEngineConfiguration={arn, mode})`. Mode toggles `LOG_ONLY` ↔ `ENFORCE`.

**Cedar at Gateway** is the production write-action gate per decision-doc Section 3.3. The policy evaluator is AWS-managed; we sync Cedar policies from `cedar-policies/*.cedar` into a script-managed PolicyEngine via `bedrock-agentcore-control.CreatePolicy / UpdatePolicy / DeletePolicy`. The LLM cannot prompt-inject around this; Cedar runs at the Gateway boundary, not in the agent's prompt.

**Schema constraints (per AWS's Policy schema doc + empirical probing):**
- Principal: `AgentCore::IamEntity::"arn:aws:sts::ACCOUNT:assumed-role/NAME"` (IAM gateway) or `AgentCore::OAuthUser` (JWT gateway). Wildcard principal is rejected as "Overly Permissive."
- Action: `AgentCore::Action::"<GatewayTargetName>___<tool_name>"` (triple-underscore, derived from the MCP tools/list).
- Resource: `AgentCore::Gateway::"<full-gateway-ARN>"`. Required exact form; wildcard or gateway-id-only is rejected.
- Context: only `context.input.*` is available. JSON Schema → Cedar type mapping is string→String / integer→Long / boolean→Bool / number→Decimal. Pydantic `Literal[...]` becomes a per-action auto-generated enum that is NOT comparable to Cedar string literals (hard type error at policy creation).

**For Triage:** Gateway fronts your custom MCP server. Cedar policy text + the sync helper live in the repo; the PolicyEngine is script-managed (no Terraform resource yet) and the policies plus the gateway-ARN substitution happen at provision time. Default mode is `LOG_ONLY`; flip to `ENFORCE` once the LOG_ONLY traces confirm the Gateway-constructed principal matches what your policies expect.

## AgentCore Identity

**What it is:** OAuth 2.0/2.1 identity layer for agent-to-tool authentication. Production-standard auth using OAuth 2.1 + Resource Indicators (RFC 8707) — the same standard the MCP 2026 spec ratified.

**Why you care:** your custom MCP server needs authentication. Rolling custom auth is unnecessary work and a security risk. AgentCore Identity provides OAuth 2.1 + Resource Indicators out of the box.

**For Triage:** configure your MCP server to accept tokens from AgentCore Identity. Identity manages the token issuance and rotation. Section 3.2 of decision doc.

## How they fit together (mental model)

```
CloudWatch Alarm → SNS → Lambda
                            ↓ (invokes via SigV4)
                    AgentCore Runtime (your agent session)
                            ↓ (queries memory)
                    AgentCore Memory ← → Runtime
                            ↓ (SigV4 to Gateway)
                    AgentCore Gateway ← AWS_IAM authorizer
                                       ← AgentCore Policy Engine (Cedar, ENFORCE)
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

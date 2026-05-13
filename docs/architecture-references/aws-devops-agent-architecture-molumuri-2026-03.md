# AWS DevOps Agent: Architecture Reference (Molumuri et al.)

**Source:** "Leverage Agentic AI for Autonomous Incident Response with AWS DevOps Agent," AWS DevOps Blog, March 31, 2026. Authors: Molumuri, Fine, Alioto, Qureshi.
**URL:** https://aws.amazon.com/blogs/devops/leverage-agentic-ai-for-autonomous-incident-response-with-aws-devops-agent/

## Why this matters for Triage

This is the architecture you mirror, per Section 3.6 of the decision doc. AWS DevOps Agent went GA on the same day this post published, and the post is AWS's own canonical reference design for autonomous incident response. Quoting from the architecture (with citation) is the single highest-credibility move in your README. "Architecturally mirrors AWS DevOps Agent's published reference design" is materially stronger than "inspired by productized agents."

## Architectural elements you adopt

**Agent Spaces** — isolated logical containers giving an agent cross-account read access to telemetry sources, code repos, CI/CD pipelines, and ticketing systems. Each Agent Space is a security boundary. In Triage, you scale this down to a single Agent Space (one AgentCore Runtime configuration) with read-only IAM by default. The Agent Space metaphor is what lets you talk about "the agent" as having a defined operating boundary rather than "an LLM with API access."

**Three skill tiers:**
1. **AWS-provided skills** — built-in capabilities (Code Interpreter, Observability) that come with AgentCore.
2. **User-defined skills** — your organization's procedures encoded for the agent to invoke. In Triage, your Day 30 runbooks parsed and surfaced via `runbooks-api/*`.
3. **Learned skills** — patterns the agent extracts from past investigations, maintained by a background sub-agent that builds an inferred topology. **You scope this out** in Triage and document it in the README as the next iteration.

**Cedar policy at AgentCore Gateway** — deterministic write-action gating evaluated *before* the LLM invokes a tool. Read-only IAM by default. Cedar evaluates allow/deny based on the action, target resource, and contextual conditions (environment, time, current state). The LLM cannot prompt-inject around this; Cedar runs at the Gateway boundary.

**Immutable audit journal** — every reasoning step and every tool invocation written to an append-only S3 bucket with Object Lock. Compliance-grade replay capability for any incident the agent handled.

## Reported customer outcomes at GA

Cited in the post for preview customers (now official at GA):

- Up to ~75% lower MTTR
- ~80% faster investigations
- ~94% root cause accuracy
- 3–5× faster resolution

Named customers: Western Governors University (28-min investigations vs ~2 hours = 77% MTTR improvement), Zenchef (20–30 min vs 1–2 hours = ~75% reduction), T-Mobile (live design partner with Splunk multi-cloud + on-prem), United Airlines, Granola.

**Treat these as vendor numbers**, useful as the public benchmark you can compare your own eval results against in interviews — not as ground truth.

## Integration surface at GA

CloudWatch, Datadog, Dynatrace, New Relic, Splunk, Grafana, GitHub, GitLab, Azure DevOps, PagerDuty, ServiceNow, Slack. On-prem and Azure investigation via MCP.

## Pricing (at GA, verify current)

Pure active-time billing at $0.0083 per agent-second. No idle baseline. AWS Support customers get DevOps Agent credits scaled by support tier.

## Scope decisions for Triage (what you adopt vs scope out)

| Element | Adopt? | How / why |
|---|---|---|
| Agent Spaces | ✓ scaled down | Single Agent Space, one AgentCore Runtime config, read-only IAM default |
| Skill tier 1 (AWS-provided) | ✓ | AgentCore built-in Code Interpreter + Observability |
| Skill tier 2 (user-defined) | ✓ | Day 30 runbooks via `runbooks-api/*` |
| Skill tier 3 (learned) | ✗ scope out | Document as next iteration in README |
| Cedar at Gateway | ✓ | Section 3.3 |
| Immutable audit journal | ✓ | S3 bucket with Object Lock |
| Cross-account access | ✗ scope out | Single-account is fine for portfolio scope |
| Multi-cloud integration | ✗ scope out | AWS-only |

## Verify against live source

When you cite specifics in the README or interview, double-check against the live blog post:

- Exact phrasing of "Agent Spaces" definition
- Exact MTTR / accuracy percentages (they may update post-launch)
- Current integration partner list (may grow)
- Current pricing

## Interview-grade quote to anchor the README

The post is the canonical reference. In your README, attribute the architectural mirror like: *"Triage mirrors the AWS DevOps Agent reference architecture published in Molumuri et al., AWS DevOps Blog, March 31, 2026."* Keep any direct quote under 15 words; paraphrase otherwise.

# 0003 — Custom MCP server organized into four canonical namespaces

**Status:** Accepted
**Date:** 2026-05-13
**Deciders:** Dimitrije

## Context

The Triage agent needs to call AWS observability operations (CloudWatch metrics and logs, ECS task and service inspection, runbook lookup). The agent platform (AgentCore) supports MCP servers as the tool layer, and the MCP ecosystem in 2026 is the industry-standard interface between agents and external tools (97M+ monthly SDK downloads, first-party servers from PagerDuty, Datadog, Microsoft, AWS, Stripe, Vercel, Supabase, Red Hat).

The question was how to organize the tools. Options ranged from flat ("just a bag of tools") to highly structured (one MCP server per AWS service). AWS published two relevant reference designs around the same time:

1. The multi-agent SRE assistants blog post (AWS Machine Learning Blog) introduces a four-namespace convention: `k8s-api`, `logs-api`, `metrics-api`, `runbooks-api`. Each namespace is a domain of operational knowledge.
2. The `aws-samples/sample-fully-autonomous-incident-response` repo uses the same convention with multi-agent dispatch.

## Decision

Build one custom MCP server with tools organized into exactly four namespaces. No cross-cutting tools; every tool belongs to one namespace.

- `metrics-api/*` — CloudWatch metrics queries
- `logs-api/*` — CloudWatch Logs Insights queries
- `ecs-api/*` — ECS task and service inspection (substitutes for AWS's canonical `k8s-api` since Triage's workload is ECS, not EKS)
- `runbooks-api/*` — runbook lookup by alarm type

Tool naming convention: `<namespace>_<verb>_<noun>` (e.g., `metrics_api_get_alarm_state`).

## Alternatives considered

**One MCP server per AWS service** (CloudWatch server, ECS server, etc.). More granular, but more deployment surface and more OAuth boundaries to configure. Rejected because operational maturity at scale comes from convention, not granularity.

**Flat tool list, no namespaces.** Simplest. Rejected because the four namespaces map directly to the surfaces a future multi-agent expansion would use (each namespace becomes a subagent's tool boundary). Keeping the convention preserves that path.

**Adopt PagerDuty's MCP server pattern wholesale.** PagerDuty publishes a production MCP server with a `--enable-write-tools` flag pattern. We adopt the flag pattern (ADR-0004 covers write-action gating) but not the catalog organization — PagerDuty's catalog is incident-management-shaped, ours is AWS-observability-shaped.

## Consequences

**Positive:**
- Vocabulary alignment with AWS's published multi-agent SRE reference architecture — instant familiarity for anyone who has read those AWS posts
- Future expansion to multi-agent is plumbed: each namespace is a future subagent's surface area
- The `/add-mcp-tool` Claude Code skill (when written on Day 34) enforces this convention automatically
- CLAUDE.md's "tools live in exactly one namespace" rule is unambiguous and machine-enforceable

**Negative:**
- A tool that conceptually spans namespaces (e.g., "show me logs correlated with this metric") has to pick one namespace. Mitigation: such tools live in the namespace of their primary action; the agent's reasoning layer composes cross-namespace queries.
- ECS substitution for `k8s-api` is a minor deviation from the canonical name. Mitigation: documented prominently in README so the deviation reads as a deliberate choice, not a misreading.

**Neutral:**
- Adding a fifth namespace later would require an ADR superseding this one. That friction is desirable — keeps the catalog from sprawling.

## References

- Decision doc Section 3.2, Section 11 row 3
- `docs/architecture-references/aws-multi-agent-sre-architecture-2025.md`
- `docs/architecture-references/aws-samples-incident-response-pattern-2025.md`
- `docs/architecture-references/mcp-protocol-and-auth-2026.md`

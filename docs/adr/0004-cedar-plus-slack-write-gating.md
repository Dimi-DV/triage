# 0004 — Two-layer write-action gating: Cedar at Gateway plus Slack approval

**Status:** Accepted
**Date:** 2026-05-13
**Deciders:** Dimitrije

## Context

Triage's agent has tools that read AWS state and tools that mutate AWS state (restart an ECS service, scale a task definition, rotate a credential). Letting an LLM execute writes without guardrails is a known anti-pattern — prompt injection, hallucinated parameters, and confident-but-wrong reasoning can cause real damage.

The published AWS DevOps Agent reference (Molumuri et al., AWS DevOps Blog, March 31, 2026) uses Cedar policy enforcement at AgentCore Gateway. Cedar evaluates allow/deny based on the action, target resource, environment, and contextual conditions, *before* the LLM's tool call reaches the AWS API. The LLM cannot prompt-inject around this because Cedar runs at the Gateway boundary, not in the agent's prompt.

For Triage, Cedar alone is sufficient for most cases. But a portfolio project demonstrating mature operational thinking should show defense-in-depth, especially since the agent operates on real AWS resources that cost real money.

## Decision

Write actions in Triage must pass two gates in series:

1. **Cedar policy at AgentCore Gateway** (deterministic, pre-LLM). Cedar policy files live in `cedar-policies/`. Example: `restart_ecs_service` allowed only when `environment == "dev"` and `service.task_count > 0`.
2. **Slack approval** (human review). The agent posts a structured proposal and waits for a human ack before executing.

Additionally, every reasoning step and every tool invocation writes to an append-only S3 bucket with Object Lock — the immutable audit journal pattern from the same AWS DevOps Agent reference.

Read-only IAM is the default for the agent role. Write permissions are explicit additions, each backed by a Cedar policy.

## Alternatives considered

**Cedar alone, no Slack approval.** Matches AWS DevOps Agent's pattern as documented. Sufficient for a production system with a mature Cedar policy library. Rejected for Triage because (a) the portfolio scope means Cedar policies will be incomplete during the sprint, (b) human-in-the-loop is the conservative choice when you're proving a pattern works, and (c) the Slack approval is itself a portfolio-worthy artifact showing operational maturity.

**Slack approval alone, no Cedar.** Simpler to implement. Rejected because Slack approval depends on a human reading the proposal correctly, and approval fatigue is real. Cedar provides a deterministic floor that catches the "the human glanced at it and clicked yes" failure mode.

**IAM policy alone (no Cedar, no Slack).** Standard AWS practice for non-agent systems. Rejected because IAM permissions are coarse-grained (typically allow-or-deny at the API level) whereas Cedar can express "allowed only if these contextual conditions hold." Also, the AWS DevOps Agent reference explicitly chose Cedar over IAM at the policy layer for this reason.

## Consequences

**Positive:**
- The LLM cannot prompt-inject around Cedar — it runs at the Gateway boundary in policy code, not in the prompt
- Defense in depth: a Cedar policy bug doesn't immediately escape to AWS; the Slack approval gate catches it
- Audit trail at S3 Object Lock means compliance-grade replay of any incident, regardless of how it ended
- Matches the AWS DevOps Agent reference architecture, which is itself an interview talking point

**Negative:**
- Slack approval adds latency. Acceptable for a SRE agent (incidents are minutes, not milliseconds). Mitigation: read-only investigation runs without the gate.
- Two-system coordination (Cedar policy + Slack webhook config) is more setup. Mitigation: both are Terraform-managed.
- Cedar policy authoring is a learnable skill; the project's portfolio asks the user to learn at least one non-trivial Cedar policy.

**Neutral:**
- Future automation of approval (auto-approve well-understood patterns) is a known next-iteration item. Triage v1 ships with strictly manual Slack approval; auto-approve would be a separate ADR.

## References

- Decision doc Section 3.3, Section 11 rows 5, 6
- `docs/architecture-references/aws-devops-agent-architecture-molumuri-2026-03.md`
- `docs/architecture-references/agentcore-primitives-runtime-gateway-identity-memory-2026.md`
- Cedar policy language: https://www.cedarpolicy.com/

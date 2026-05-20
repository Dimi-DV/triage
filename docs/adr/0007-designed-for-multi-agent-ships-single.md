# 0007 — Designed for multi-agent expansion; v1 ships single agent

**Status:** Accepted (amended 2026-05-19 to drop stub subagent — see Amendment below)
**Date:** 2026-05-13
**Deciders:** Dimitrije

## Amendment — 2026-05-19 (v3.1)

The stub subagent commitment is dropped. The v3.1 spec amendment (§3.10) drops both (a) the "designed for multi-agent expansion" framing — the 2026 hiring signal filters against sprawling multi-agent demos — and (b) the stub Lambda + A2A endpoint originally bundled with this ADR.

Reasoning recorded in spec §3.10: the stub added ~3–5 hours of agent-card-registration + OAuth-wiring work for marginal interview value. The architectural claim "I understand when multi-agent boundaries apply" is better made by *explaining when they apply* than by building one stub to point at — and the four MCP namespaces are tool categories, not domains needing separate agents.

The "Alternatives considered" and "Consequences" sections below describe the pre-amendment reasoning and are preserved verbatim as historical record. Triage v1 ships **pure single-agent, no stub.** For the current architecture position, see spec §3.10 directly.

## Context

Multi-agent architectures (one lead agent orchestrating specialist subagents over A2A protocol) are becoming the canonical AIOps pattern. AWS's own published reference `aws-samples/sample-fully-autonomous-incident-response` uses three agents (Monitoring Agent on Strands Agents SDK, Operations Orchestrator on OpenAI Agents SDK, Host Orchestrator on Google ADK) coordinated via A2A. The blog-post pattern in AWS's multi-agent SRE post (ADR-0003 references the four-namespace convention from the same post) presupposes one specialist subagent per namespace.

Fully implementing three real subagents on A2A — with proper inter-agent debugging, separate IAM scoping, separate observability spans, separate prompts — is more scope than the 6-day Triage sprint can absorb. But ignoring the multi-agent direction entirely would be a poor signal: every interview in 2026 is going to ask about it.

The compromise needs to (a) actually demonstrate the multi-agent path is plumbed, not just claimed, and (b) keep the v1 implementation tractable.

## Decision

Architecture is **designed for multi-agent expansion** but Triage v1 ships:

- **One substantive lead agent** that calls all four MCP namespaces directly
- **One stub subagent** invoked via A2A protocol (implemented as a Lambda function) for a non-critical task — likely deploy history lookup or ticket correlation. The stub doesn't need to be smart; it needs to exist, be invocable, and emit OTEL spans like a real subagent would
- Architecture diagram and README explicitly document the full multi-agent expansion path as the next iteration, citing the AWS sample repo as the reference

Specific design discipline to keep the multi-agent path open:

1. The four MCP namespaces (ADR-0003) are each a future subagent's surface area. No work needed to maintain this — already implied by ADR-0003.
2. The lead agent's system prompt reads as an orchestration script with explicit investigation phases that map to subagent dispatch.
3. Tool definitions live in the MCP server, not in agent code — so a different agent runtime tomorrow doesn't require rewriting tool logic.

## Alternatives considered

**Ship full multi-agent v1** (three real subagents, three SDKs, A2A throughout). Matches AWS's published reference exactly. Rejected because the SDK diversity (Strands + OpenAI Agents + Google ADK) is pedagogical overhead the sprint can't afford. Even three subagents on the same SDK would still require ~2 sprint days of inter-agent debugging.

**Ship strictly single-agent, no stub.** Simplest. Rejected because "designed for multi-agent" is harder to defend in an interview if there's zero evidence of the architecture actually supporting it. The stub subagent is the proof.

**Ship single-agent now, plan to add subagents post-sprint.** Equivalent to "no stub." Same rejection.

## Consequences

**Positive:**
- The interview talking point — "I designed for multi-agent, ships single agent plus a stub subagent demonstrating the A2A dispatch path; full expansion is the next iteration mirroring `aws-samples/sample-fully-autonomous-incident-response`" — is concrete and defensible
- Same scope discipline applied elsewhere in the project (the learned skill tier is scoped out the same way per ADR-0002's context)
- Lead agent stays simple, easy to reason about, easy to evaluate (ADRs 0005 and 0006)
- A2A protocol is touched in the codebase, not just discussed — proof the architecture supports it

**Negative:**
- The stub adds one Lambda + one A2A endpoint to deploy and maintain. Mitigation: stub is small and stateless.
- A reader looking for "the multi-agent agent" sees one substantive agent plus a clearly-labeled stub. README must explain the choice prominently or this looks like incompleteness rather than discipline. Mitigation: README has a dedicated "alternative architectures considered" section.

**Neutral:**
- Expansion to full multi-agent is non-trivial but unblocked. A future sprint (post-portfolio, post-hiring, post-Day-42) can pick up where v1 left off without architectural rework.

## References

- Decision doc Section 3.10, Section 11 row 21
- `docs/architecture-references/aws-multi-agent-sre-architecture-2025.md`
- `docs/architecture-references/aws-samples-incident-response-pattern-2025.md`
- AWS sample repo: https://github.com/aws-samples/sample-fully-autonomous-incident-response

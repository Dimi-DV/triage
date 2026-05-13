# Project Memory Index

**Purpose:** map of structured project-context notes saved to project memory for the Triage. Each file is a focused primer with the source URL, why-it-matters framing, key concepts in summary form, and explicit cross-references to the decision doc (v2.1) and the 6-day sprint.

**These are notes, not documentation.** They're optimized for fast retrieval and decision-relevance, not completeness. When working with a topic in depth, consult the live source URL listed at the top of each note.

**Last updated:** May 13, 2026.

---

## Files in this collection

| # | Filename | What it covers | First needed |
|---|---|---|---|
| 1 | `aws-devops-agent-architecture-molumuri-2026-03.md` | The canonical architecture you're mirroring: Agent Spaces, three skill tiers, Cedar at Gateway, immutable audit | Day 31 morning read |
| 2 | `agentcore-evaluations-2026-03.md` | The eval framework that replaces your custom harness: 13 built-ins, LLM-as-judge, code evaluators, ground-truth modes | Day 31 morning read; Day 35 build |
| 3 | `mast-failure-modes-ibm-berkeley-2026-02.md` | The failure-mode taxonomy used to classify eval failures: FM-1.X conversation, FM-2.X reasoning, FM-3.X verification | Day 31 morning read; Day 35 eval annotation |
| 4 | `agentcore-primitives-runtime-gateway-identity-memory-2026.md` | The AgentCore building blocks you'll wire together: Runtime, Memory, Gateway with Cedar, Identity with OAuth 2.1 | Day 32 AgentCore depth |
| 5 | `aws-multi-agent-sre-architecture-2025.md` | Source of the four MCP namespace convention (k8s-api / logs-api / metrics-api / runbooks-api); multi-agent supervisor pattern | Day 32; Day 34 MCP server build |
| 6 | `mcp-protocol-and-auth-2026.md` | MCP basics, OAuth 2.1 + Resource Indicators for production auth, 2026 roadmap (statelessness, Tasks primitive) | Day 34 MCP server build |
| 7 | `aws-samples-incident-response-pattern-2025.md` | The AWS reference repo (`aws-samples/sample-fully-autonomous-incident-response`) — what to steal the pattern from without running | Day 31 (clone + read structure) |
| 8 | `aws-fis-fault-injection-reference-2026.md` | AWS Fault Injection Service — the 4 FIS scenarios in your outage corpus and how to wire them | Day 35 outage corpus build |

## Decision doc cross-reference

These notes map back to sections in `triage-decision-doc-v2.md` (currently v2.1):

| Decision doc section | Supporting notes |
|---|---|
| 3.1 AgentCore as platform | #4 (primitives) |
| 3.2 Four-namespace MCP server | #5 (multi-agent SRE), #6 (MCP) |
| 3.3 Cedar + Slack two-layer gating | #1 (Molumuri), #4 (Gateway + Cedar) |
| 3.4 FIS + Terraform overlay outage corpus | #8 (FIS), #2 (Evaluations ground-truth modes) |
| 3.5 AgentCore Evaluations + MAST | #2 (Evaluations), #3 (MAST) |
| 3.6 Mirror DevOps Agent architecture | #1 (Molumuri) — the entire mirror is this source |
| 3.7 Production-grade infrastructure | None — built on Week 1–3 AWS work |
| 3.8 Modular design with version pinning | #6 (MCP roadmap) |
| 3.9 Claude Code workflow customization | None in this collection — see live Claude Code docs |
| 3.10 Multi-agent designed-for | #5 (multi-agent SRE), #7 (sample repo) |

## What's NOT here

Per Section 8 of v2.1, deliberately excluded to avoid project-memory bloat:

- Full Bedrock developer guide
- Full Terraform AWS provider reference
- Full Claude Code docs (web-search on demand; only the sections actively in use)
- Marketing pages
- The AWS DevOps Agent product page (you have the architecture blog instead)
- Anthropic tool use guide (well-trained territory; verify on demand only)

## When to expand this collection

Add a note if a topic comes up repeatedly across sprint days and you find yourself re-explaining context to Claude. Use the same filename convention (descriptive, dated, lowercase) and update this index. Don't pre-emptively add notes for topics that haven't yet surfaced as friction points.

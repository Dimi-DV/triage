# Architecture Decision Records (ADRs)

This directory contains short, dated records of architectural decisions made on the project.

## Why ADRs

The full architectural reasoning lives in [`docs/architecture-references/triage-decision-doc-v2.md`](../architecture-references/triage-decision-doc-v2.md). That's the canonical spec.

ADRs in this directory are the *narrative complement* — one focused decision per file, with context, options considered, and consequences. They're easier to skim than a 24-row decision-log table.

The pattern is from Michael Nygard's 2011 essay, ["Documenting Architecture Decisions"](https://cognitect.com/blog/2011/11/15/documenting-architecture-decisions), widely adopted across the industry by 2026.

## Conventions

- One ADR per file: `NNNN-short-kebab-case-title.md` (zero-padded)
- Each ADR has a status: **Proposed**, **Accepted**, **Deprecated**, or **Superseded by ADR-NNNN**
- New ADRs go in the next available number, never retconned
- When a decision changes, write a new ADR and update the old one's status to "Superseded"

## Index

| # | Title | Status | Date |
|---|---|---|---|
| [0001](0001-record-architecture-decisions.md) | Record architecture decisions | Accepted | 2026-05-13 |
| [0002](0002-build-on-agentcore-not-raw-api.md) | Build agent on Bedrock AgentCore, not raw Anthropic API | Accepted | 2026-05-13 |
| [0003](0003-four-mcp-namespaces.md) | Custom MCP server organized into four namespaces | Accepted | 2026-05-13 |
| [0004](0004-cedar-plus-slack-write-gating.md) | Cedar at Gateway + Slack approval (two-layer write gating) | Accepted | 2026-05-13 |
| [0005](0005-agentcore-evaluations-not-custom-harness.md) | Use AgentCore Evaluations natively, not a custom harness | Accepted | 2026-05-13 |
| [0006](0006-mast-failure-mode-annotation.md) | Annotate eval failures against MAST taxonomy | Accepted | 2026-05-13 |
| [0007](0007-designed-for-multi-agent-ships-single.md) | Architecture designed for multi-agent, v1 ships single + stub | Accepted | 2026-05-13 |

## Template

Use [`template.md`](template.md) for new ADRs.

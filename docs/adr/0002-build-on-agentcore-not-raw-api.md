# 0002 — Build the agent on Bedrock AgentCore, not the raw Anthropic API

**Status:** Accepted
**Date:** 2026-05-13
**Deciders:** Dimitrije

## Context

Triage is an AI agent that needs to run reliably, authenticate to tools via OAuth, persist memory across sessions, and emit observability spans. We needed to choose a platform for the agent loop itself.

Two main paths were on the table:

1. **Raw Anthropic API (or equivalent)** — write the agent loop from scratch: model invocation, tool-call parsing, tool execution, result feeding, retry handling.
2. **Amazon Bedrock AgentCore** — AWS's managed agent platform (GA October 13, 2025). Provides Runtime (Firecracker microVM isolation), Memory (session + episodic), Gateway (OAuth + Cedar policy enforcement), and Identity (OAuth 2.1 + Resource Indicators).

Two additional factors influenced the choice:

- **AWS DevOps Agent** (GA March 31, 2026) runs on the same AgentCore platform. Mirroring its architecture means Triage speaks the same vocabulary as the canonical reference design.
- The AgentCore ecosystem (re:Invent 2025, AWS DevOps Agent GA) is the current AWS-native standard for this class of system.

## Decision

Build Triage on Amazon Bedrock AgentCore. Use Runtime as the agent host, Memory for session state, Gateway for tool fronting with Cedar policy enforcement, and Identity for OAuth 2.1.

## Alternatives considered

**Raw Anthropic API + custom loop.** Maximum pedagogical value — you understand every detail of the agent loop because you wrote it. Rejected because (a) AgentCore is the current AWS-native pattern for managed agents, (b) "deployed on AgentCore" beats "implemented the loop from scratch" the way "deployed on ECS" beats "wrote my own container scheduler", and (c) reinventing Memory/Identity/Gateway is real engineering work that doesn't differentiate the project.

**Claude Managed Agents on Claude Platform on AWS.** Anthropic-native managed agents available via Claude Platform on AWS. Rejected for Triage specifically because the AWS-native vocabulary aligns with the rest of the stack, and because data residency (Bedrock keeps data inside AWS boundary) is the conservative choice for a portfolio project. Documented as the second-place alternative in the README's "alternative architectures considered" section.

**LangChain / LangGraph / similar Python agent frameworks.** Popular but not the AWS-native pattern. Would require more glue code for AWS auth and observability. Rejected for the same vocabulary-alignment reason.

## Consequences

**Positive:**
- Vocabulary and architecture aligned with AWS DevOps Agent and current AWS-native patterns
- AgentCore Memory, Identity, Gateway are infrastructure for free — no time spent reinventing
- Direct architectural parallel to the canonical reference design (ADR-0003 covers the mirror)
- Native integration with AgentCore Evaluations (ADR-0005)

**Negative:**
- Less of the raw agent loop is visible in source code (Runtime handles it). Mitigation: the README explicitly notes this trade-off and points readers to AgentCore docs for the loop internals.
- Vendor lock-in to AWS Bedrock. Acceptable for an AWS-native project; would be a real concern for a production multi-cloud service.

**Neutral:**
- Future revisions can swap models (Sonnet → Opus → Nova) as configuration changes rather than refactors — AgentCore decouples the model from the loop.

## References

- Decision doc Section 3.1, Section 11 row 2
- `docs/architecture-references/agentcore-primitives-runtime-gateway-identity-memory-2026.md`
- AgentCore developer guide: https://aws.amazon.com/bedrock/agentcore/

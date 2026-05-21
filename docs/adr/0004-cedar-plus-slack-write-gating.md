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

1. **Cedar policy at AgentCore Gateway** (deterministic, pre-LLM). Implemented via the AWS-managed **AgentCore Policy Engine** primitive (`bedrock-agentcore-control.CreatePolicyEngine` + `policyEngineConfiguration` on `update_gateway`, GA 2026-03-03). Cedar policy text lives in `cedar-policies/*.cedar` and is synced into the engine by `scripts/provision_agentcore.py`. Mode toggles between `LOG_ONLY` (audit-only) and `ENFORCE`.
2. **Slack approval** (human review). The agent posts a structured proposal and waits for a human ack before executing.

Additionally, every reasoning step and every tool invocation writes to an append-only S3 bucket with Object Lock — the immutable audit journal pattern from the same AWS DevOps Agent reference.

Read-only IAM is the default for the agent role. Write permissions are explicit additions, each backed by a Cedar policy.

### What Cedar at this layer can and cannot express

Two constraints surfaced during the 2026-05-21 implementation that change the *granularity* of Cedar's gate from the v3-decision-doc original framing:

**Can express (and we use):**
- Identity gating: `principal == AgentCore::IamEntity::"arn:aws:sts::ACCOUNT:assumed-role/<role>"` — only the Triage agent role can invoke any tool, even if some other IAM principal acquires `bedrock-agentcore:InvokeGateway`.
- Action gating: `action == AgentCore::Action::"<GatewayTargetName>___<tool_name>"` — per-tool permit; default-deny for any tool without a matching `permit`.
- Gateway-scope resource gating: `resource == AgentCore::Gateway::"<full-gateway-ARN>"` — required; wildcards and gateway-id-only are rejected.
- Forbid-wins emergency shutdown: a single `forbid(principal, action, resource);` block disables all tools. Implemented as a `.disabled` kill-switch file at `cedar-policies/_emergency-shutdown.cedar.disabled` — rename and re-provision to engage.

**Cannot express (and we don't):**
- Conditional on environment, time, downstream AWS resource state — Cedar at the Gateway only sees the request, not external state. The original v3 example `restart_ecs_service allowed only when environment == "dev" and service.task_count > 0` is not expressible.
- Conditional on a tool argument typed as Pydantic `Literal[...]` — AgentCore auto-generates a per-action enum type (`AgentCore::ID_<hash>_..._severity`) which is not comparable to a Cedar string literal at policy creation time. Plain `str`/`int`/`bool` args under `context.input.<arg-name>` still admit `when` clauses; enum-typed fields do not.

Practical consequence: Cedar gates *which tool the agent can invoke*, with identity tightening, not *which downstream AWS resource it can touch*. Per-resource and per-environment gating moves to (a) separate Gateways for separate environments, or (b) the MCP tool's own internal code (which already has Pydantic validation + audit).

## Alternatives considered

**Cedar alone, no Slack approval.** Matches AWS DevOps Agent's pattern as documented. Sufficient for a production system with a mature Cedar policy library. Rejected for Triage because (a) the portfolio scope means Cedar policies will be incomplete during the sprint, (b) human-in-the-loop is the conservative choice when you're proving a pattern works, and (c) the Slack approval is itself a portfolio-worthy artifact showing operational maturity.

**Slack approval alone, no Cedar.** Simpler to implement. Rejected because Slack approval depends on a human reading the proposal correctly, and approval fatigue is real. Cedar provides a deterministic floor that catches the "the human glanced at it and clicked yes" failure mode.

**IAM policy alone (no Cedar, no Slack).** Standard AWS practice for non-agent systems. Rejected because IAM permissions are coarse-grained (typically allow-or-deny at the API level) whereas Cedar can express "allowed only if these contextual conditions hold." Also, the AWS DevOps Agent reference explicitly chose Cedar over IAM at the policy layer for this reason.

## Consequences

**Positive:**
- The LLM cannot prompt-inject around Cedar — it runs at the Gateway boundary, not in the agent prompt
- Identity gating beyond IAM: even if another IAM principal acquires `InvokeGateway`, Cedar's exact-match `principal ==` clause refuses the call. This is *stricter* than AWS_IAM authorization alone.
- Defense in depth: a Cedar policy bug doesn't immediately escape to AWS; the Slack approval gate catches it
- Audit trail at S3 Object Lock means compliance-grade replay of any incident, regardless of how it ended
- Matches the AWS DevOps Agent reference architecture, which is itself an interview talking point
- Kill-switch is a single `cp _emergency-shutdown.cedar.disabled emergency-shutdown.cedar` + provision-agentcore away (forbid-wins semantics)

**Negative:**
- Slack approval adds latency. Acceptable for a SRE agent (incidents are minutes, not milliseconds). Mitigation: read-only investigation runs without the gate.
- AgentCore Policy Engine's schema is more restrictive than vanilla Cedar (resource locked to the Gateway, principal locked to `AgentCore::IamEntity` or `AgentCore::OAuthUser`, Pydantic Literal fields unusable in `when` clauses). The v3 vision of "Cedar expresses fine-grained business rules on resource state" doesn't survive contact with the primitive — see the "Cannot express" list above.
- Cedar policy authoring is a learnable skill; the project's portfolio asks the user to learn at least one non-trivial Cedar policy.

**Neutral:**
- Future automation of approval (auto-approve well-understood patterns) is a known next-iteration item. Triage v1 ships with strictly manual Slack approval; auto-approve would be a separate ADR.
- Argument-level conditional gating may become possible if/when AgentCore exposes the auto-generated enum type names declaratively. Out of scope for v1.

## References

- Decision doc Section 3.3, Section 11 rows 5, 6
- `docs/architecture-references/aws-devops-agent-architecture-molumuri-2026-03.md`
- `docs/architecture-references/agentcore-primitives-runtime-gateway-identity-memory-2026.md`
- `docs/iam-permissions-reference.md` — per-role IAM doc; shows where Cedar sits in the principal chain
- AWS docs: [Schema constraints for AgentCore Policy Engine](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/policy-schema-constraints.html), [Common policy patterns](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/policy-common-patterns.html), [Gateway and Policy IAM permissions](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/policy-permissions.html)
- Cedar policy language: https://www.cedarpolicy.com/
- Memory: `feedback_cedar_policy_engine_config_lives` — three-stage doc-vs-API drift trail

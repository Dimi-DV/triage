// Cedar policies for the Triage agent's MCP tool calls at AgentCore Gateway.
//
// The AgentCore Policy Engine schema constrains policy shape (verified
// 2026-05-21 by probing CreatePolicy + cross-checked against AWS's
// "Schema constraints" and "Common policy patterns" docs):
//
//   - Principal: for AWS_IAM-authorized gateways, only `AgentCore::IamEntity`.
//     Cedar entity id is the STS assumed-role form
//     `arn:aws:sts::<account>:assumed-role/<role-name>` (no session suffix).
//   - Action: `AgentCore::Action::"<GatewayTargetName>___<tool_name>"`
//     (triple-underscore; verified against runtime tools/list).
//   - Resource: MUST be `AgentCore::Gateway::"<full-gateway-ARN>"`. Wildcard
//     resource and gateway-id-only are both rejected.
//
// Two sentinels are substituted by `scripts/provision_agentcore.py` at
// sync time so the policy stays environment-portable:
//   __GATEWAY_ARN__          ← the resolved AgentCore Gateway ARN
//   __AGENT_PRINCIPAL_ARN__  ← the agent runtime role's STS assumed-role
//                              ARN (translated from the IAM role ARN
//                              Terraform exports)
//
// Each rule is preceded by an `@id("…")` annotation. The id is the policy
// name in the engine (regex `^[A-Za-z][A-Za-z0-9_]*$`, no hyphens) so
// re-syncs locate and update in place instead of creating duplicates.

// --- Read-only investigation tools: permitted for the Triage agent. ---
//
// We use exact-match `principal ==` (per AWS's "IAM: Using IAM role ARNs"
// common pattern, recommended for single-role policies) instead of the
// broader `principal is AgentCore::IamEntity`. That way even if some other
// IAM principal acquires `bedrock-agentcore:InvokeGateway` they don't
// inherit the Triage agent's tool grants — the Cedar gate enforces caller
// identity beyond what the AWS_IAM authorizer alone checks.
//
// AgentCore Policy Engine is default-deny: every tool the agent needs to
// invoke must have an explicit permit policy, or ENFORCE-mode calls return
// an authorization failure to the gateway and the MCP server never runs.

@id("permit_metrics_read")
permit (
    principal == AgentCore::IamEntity::"__AGENT_PRINCIPAL_ARN__",
    action == AgentCore::Action::"TriageMcpGateway___metrics_api_get_metric_statistics",
    resource == AgentCore::Gateway::"__GATEWAY_ARN__"
);

@id("permit_ecs_describe_target_health")
permit (
    principal == AgentCore::IamEntity::"__AGENT_PRINCIPAL_ARN__",
    action == AgentCore::Action::"TriageMcpGateway___ecs_api_describe_target_health",
    resource == AgentCore::Gateway::"__GATEWAY_ARN__"
);

@id("permit_ecs_describe_task_definition")
permit (
    principal == AgentCore::IamEntity::"__AGENT_PRINCIPAL_ARN__",
    action == AgentCore::Action::"TriageMcpGateway___ecs_api_describe_task_definition",
    resource == AgentCore::Gateway::"__GATEWAY_ARN__"
);

@id("permit_logs_filter_events")
permit (
    principal == AgentCore::IamEntity::"__AGENT_PRINCIPAL_ARN__",
    action == AgentCore::Action::"TriageMcpGateway___logs_api_filter_log_events",
    resource == AgentCore::Gateway::"__GATEWAY_ARN__"
);

@id("permit_runbooks_lookup")
permit (
    principal == AgentCore::IamEntity::"__AGENT_PRINCIPAL_ARN__",
    action == AgentCore::Action::"TriageMcpGateway___runbooks_api_lookup_runbook",
    resource == AgentCore::Gateway::"__GATEWAY_ARN__"
);

// --- Slack post: write action, gated at the Gateway by Cedar. ---
//
// AgentCore Gateway evaluates this BEFORE forwarding the MCP tool call.
// The MCP server then double-enforces by emitting an immutable audit event
// to S3 Object Lock before any Slack call (CLAUDE.md hard rule 4).
//
// We deliberately do NOT condition on `context.input.message.severity`
// here. The `severity` field is a Pydantic `Literal["info","warning",
// "critical"]` which AgentCore models as a per-action enum type
// (`AgentCore::ID_…_SlackMessage_severity`); comparing it to a Cedar
// string is a hard type-incompatibility error, and the auto-generated
// type name depends on the gateway ARN hash so referencing it directly
// would brittle the policy. Pydantic validation already enforces the
// severity set at runtime — Cedar's job here is action-level + identity
// gating, not arg validation.
@id("permit_slack_post")
permit (
    principal == AgentCore::IamEntity::"__AGENT_PRINCIPAL_ARN__",
    action == AgentCore::Action::"TriageMcpGateway___runbooks_api_post_to_slack",
    resource == AgentCore::Gateway::"__GATEWAY_ARN__"
);

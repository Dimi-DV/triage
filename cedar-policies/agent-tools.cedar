// Cedar policies for the Triage agent's MCP tool calls at AgentCore Gateway.
//
// Action ids use the triple-underscore <GatewayTargetName>___<tool_name>
// format per CLAUDE.md naming rules (verified against runtime tools/list).
//
// The schema for the entities and actions referenced here lives in
// `schema.cedarschema`; both files are uploaded by `scripts/provision_agentcore.py`.

// --- Read-only metrics query: always permitted for the Triage agent. ---
permit (
    principal == Triage::Agent::"prod-triage-agent",
    action == Triage::Action::"TriageMcpGateway___metrics_api_get_metric_statistics",
    resource is Triage::CloudWatchMetric
);

// --- Slack post: write action, permitted only when severity is known. ---
// Cedar evaluates this BEFORE the tool runs at the MCP server; the server
// then double-enforces by emitting an audit event before any side effect.
permit (
    principal == Triage::Agent::"prod-triage-agent",
    action == Triage::Action::"TriageMcpGateway___runbooks_api_post_to_slack",
    resource is Triage::SlackChannel
) when {
    context.severity == "info" ||
    context.severity == "warning" ||
    context.severity == "critical"
};

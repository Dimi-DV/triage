# cedar-policies

Cedar policies bound at AgentCore Gateway. The Gateway evaluates them
deterministically *before* the MCP tool runs — the agent's LLM cannot
prompt-inject around them.

## Files

- `agent-tools.cedar` — permit rules for the Triage agent's MCP tools.
- `schema.cedarschema` — entity types, action ids, and context shapes
  the policies reference. AgentCore Gateway requires it to evaluate
  attribute-based conditions.

## Action naming

Cedar action ids at Gateway use the **triple-underscore** format:

    <GatewayTargetName>___<tool_name>

Example: `TriageMcpGateway___runbooks_api_post_to_slack`.

AWS docs sometimes show double-underscore; the verified runtime format that
matches the MCP server's `tools/list` output is **triple**. See
`CLAUDE.md` (line 43) and the v3 decision doc.

## Deployment

`scripts/provision_agentcore.py` uploads every `*.cedar` file in this
directory plus `schema.cedarschema` to the Gateway when it creates or
updates the gateway. Adding a new write tool means:

1. Add a `@mcp.tool`-decorated implementation in `src/triage/mcp_server/<ns>/`.
2. Append a `permit` rule here and the matching action declaration in
   `schema.cedarschema`.
3. Re-run `make provision-agentcore`.

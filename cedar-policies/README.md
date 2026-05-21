# cedar-policies

Cedar policies bound at AgentCore Gateway. The Gateway evaluates them
deterministically *before* the MCP tool runs — the agent's LLM cannot
prompt-inject around them.

## Files

- `agent-tools.cedar` — `permit` / `forbid` rules for the Triage agent's MCP
  tools. Each rule is preceded by an `@id("…")` annotation; the id is used
  as the AgentCore policy `name` so re-syncs update in place.
- `_emergency-shutdown.cedar.disabled` — inactive kill-switch. The `.disabled`
  suffix keeps it out of the `*.cedar` glob the provisioning script walks.
  See "Emergency shutdown" below for the activation procedure.
- `schema.cedarschema` — Cedar native-syntax schema, kept as a human-readable
  reference. The AgentCore Policy Engine has no PutSchema operation
  (validation is per-policy via the `validationMode` CreatePolicy arg), so
  this file is documentation only — nothing is pushed from it.

## Action naming

Cedar action ids at Gateway use the **triple-underscore** format:

    <GatewayTargetName>___<tool_name>

Example: `TriageMcpGateway___runbooks_api_post_to_slack`.

AWS docs sometimes show double-underscore; the verified runtime format that
matches the MCP server's `tools/list` output is **triple**. See
`CLAUDE.md` and the v3 decision doc.

## Deployment

The policy engine is script-managed (`scripts/provision_agentcore.py`
creates it if missing) — there is no Terraform resource for AgentCore
Policy Engines in the AWS provider yet. The policies inside it are pushed
by the same script, so the `.cedar` files in this directory stay the
source of truth.

Flow:

1. `make provision-agentcore` runs the script, which:
   - finds (or creates) the `TriagePolicyEngine` AgentCore policy engine;
   - lists existing policies in the engine, then diffs against
     `cedar-policies/*.cedar` by the `@id("…")` annotation:
     update-in-place for matches, create for repo-only, delete for
     engine-only (so removing a `permit` block actually revokes it);
   - calls `update_gateway(policyEngineConfiguration={arn, mode})` to
     attach the engine. `mode` comes from `--cedar-mode` (default
     `LOG_ONLY`; pass `CEDAR_MODE=ENFORCE` through the Makefile to flip).

Adding a new write tool means:

1. Add a `@mcp.tool`-decorated implementation in `src/triage/mcp_server/<ns>/`.
2. Append a `@id("…")`-annotated `permit` rule here. (Schema declaration
   in `schema.cedarschema` is optional documentation — AgentCore doesn't
   require it.)
3. Re-run `make provision-agentcore`.

## Policy template sentinels

`scripts/provision_agentcore.py` substitutes two sentinels at sync time so
the policies stay environment-portable:

| Sentinel                    | Substituted with                                                                                            |
|-----------------------------|-------------------------------------------------------------------------------------------------------------|
| `__GATEWAY_ARN__`           | The resolved AgentCore Gateway ARN (`arn:aws:bedrock-agentcore:…:gateway/…`)                                |
| `__AGENT_PRINCIPAL_ARN__`   | The Triage agent runtime role's STS assumed-role ARN (`arn:aws:sts::…:assumed-role/<role-name>`, no session) |

The principal sentinel exists so policies can use exact `principal ==`
matching (AWS's "IAM: Using IAM role ARNs" recommended pattern for
single-role policies). The Cedar evaluator at the Gateway compares the
caller's STS assumed-role ARN (stripped of the session suffix) against
this exact form.

## Emergency shutdown

To freeze every tool call across every namespace — incident response,
runaway agent loop, suspected compromise:

1. Activate the kill-switch:

       cp cedar-policies/_emergency-shutdown.cedar.disabled \
          cedar-policies/emergency-shutdown.cedar

2. Push it through the Gateway:

       make provision-agentcore CEDAR_MODE=ENFORCE

Cedar's forbid-wins semantics mean the engine now denies every
`AuthorizeAction` call regardless of the existing permits. The MCP server
is never invoked.

To disengage:

       rm cedar-policies/emergency-shutdown.cedar
       make provision-agentcore CEDAR_MODE=ENFORCE

The sync helper deletes any policy whose `@id` no longer appears in the
repo, so removing the file is the revoke step.

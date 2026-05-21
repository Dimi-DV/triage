---
name: add-mcp-tool
description: Scaffold a new MCP tool inside one of the four canonical namespaces (ecs-api, logs-api, metrics-api, runbooks-api) with consistent error handling, OpenTelemetry instrumentation, and audit-log emission for write tools. Use when adding any new operation the agent can call.
---

# /add-mcp-tool

Scaffold a new tool in the custom MCP server.

## When to invoke

The user wants to add a new operation the agent can call — e.g. "add a tool that describes ECS service events" or "add a CloudWatch Logs Insights query tool for X." Also use it when porting an idea from the `aws-samples/sample-fully-autonomous-incident-response` reference into our four-namespace layout.

## Inputs to collect

1. **Namespace** (required, must be one of the four): `ecs-api` | `logs-api` | `metrics-api` | `runbooks-api`. If the request doesn't fit one of these, refuse — CLAUDE.md hard rule #5. Don't invent a fifth namespace.
2. **Tool name** (required): `<verb>_<noun>` — e.g. `describe_service`, `query_log_insights`, `query_cloudwatch`.
3. **Read or write?** Default read. Write tools require BOTH a Cedar policy AND audit emission.
4. **Input parameters**: name, type, description for each. Pydantic model on the Python side.
5. **AWS API surface**: which boto3 client + method this wraps.

Final tool ID is `<namespace_underscored>_<verb>_<noun>` (e.g. `ecs_api_describe_service`), per CLAUDE.md naming.

## Scaffold

Create or edit:

1. **`src/triage/mcp_server/<namespace_underscored>/<tool_name>.py`** — the implementation:
   - Pydantic input model
   - **Sync** function decorated with `@mcp.tool(...)` from the shared FastMCP instance in `src/triage/mcp_server/server.py`, registered under the full tool ID. FastMCP runs sync tools in a threadpool; `async def` is only correct with a deliberate `asyncio.to_thread` around the blocking boto3 call.
   - OpenTelemetry span via `tool_span(<full_tool_id>, ...)` from `triage.shared.otel` (attributes for non-secret parameters only)
   - boto3 client from `triage.shared.aws` (read-only IAM by default)
   - Structured return value matching the namespace's shared shape
   - Consistent error handling — botocore exceptions wrapped via `wrap_boto_error(e, <NamespaceError>)` from `triage.shared.errors`
   - For write tools: audit-log emission to the S3 Object Lock bucket **before** the AWS API call

2. **`tests/unit/mcp_server/<namespace_underscored>/test_<tool_name>.py`** — pytest:
   - `@pytest.mark.unit` happy path with `moto` or a mocked boto3 client
   - Error path (boto3 ClientError) — assert the wrapped error type
   - For write tools: assert the audit entry is emitted **before** the AWS call (order matters — if the AWS call happens first and audit second, a partial failure escapes the journal)

3. **If write tool:** append a `@id("permit_<verb>_<noun>")`-annotated `permit` block to `cedar-policies/agent-tools.cedar`. Policy shape:
   - `principal == AgentCore::IamEntity::"__AGENT_PRINCIPAL_ARN__"` (sentinel, substituted at provision time to the Triage agent role)
   - `action == AgentCore::Action::"TriageMcpGateway___<tool_id>"` (must match the tool's `name=` in `@mcp.tool`)
   - `resource == AgentCore::Gateway::"__GATEWAY_ARN__"` (sentinel; required exact-form — wildcard resource is rejected by the engine)
   - Header comment explaining policy intent
   - `@id` is the policy name; must match regex `^[A-Za-z][A-Za-z0-9_]*$` (no hyphens — use underscores)
   - Default-deny by AgentCore semantics: a tool without an explicit `permit` is unreachable under ENFORCE
   - For attribute-conditional gating: a `when { context.input.<arg>.<field> == … }` clause works *only* if `<field>` is a plain `str`/`int`/`bool`/`float` — Pydantic `Literal[...]` fields become a per-action enum that is not string-comparable. Prefer plain `str` with a Pydantic `Field(pattern=…)` validator when the field needs Cedar-side gating.
   - Re-run `make provision-agentcore CEDAR_MODE=ENFORCE` to push the policy into the AgentCore PolicyEngine

## Hard rules to enforce

- **Only the four namespaces.** No exceptions. CLAUDE.md rule #5.
- **Read-only by default.** Write tools must have both a Cedar policy AND audit emission before any AWS write call. CLAUDE.md rules #3 and #4.
- **OTel span on every tool, day one.** No retrofitting later. (decision doc §3.7 soft rule)
- **Tests exist before declaring done.** (CLAUDE.md soft rule)
- **Pin any new dependency** in `pyproject.toml`. (decision doc §3.8)

## Naming

- Tool ID (Python + MCP registration): `<namespace_underscored>_<verb>_<noun>` — e.g. `metrics_api_query_cloudwatch`
- File: `src/triage/mcp_server/<namespace_underscored>/<tool_name>.py`
- Cedar policy: appended to `cedar-policies/agent-tools.cedar` as a `@id("permit_<verb>_<noun>")`-annotated block (NOT a new file)
- Test: `tests/unit/mcp_server/<namespace_underscored>/test_<tool_name>.py`

## References

- CLAUDE.md — hard rules + naming
- `docs/architecture-references/aws-multi-agent-sre-architecture-2025.md` — the four-namespace pattern
- `docs/architecture-references/mcp-protocol-and-auth-2026.md` — MCP server implementation tips, OTel pattern, audit-on-write pattern
- `docs/architecture-references/agentcore-primitives-runtime-gateway-identity-memory-2026.md` — how Gateway + Cedar fit

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
   - Async function decorated with the MCP SDK tool decorator, registered under the full tool ID
   - OpenTelemetry span around the body (span name = full tool ID; attributes for non-secret parameters)
   - boto3 client call (read-only IAM by default)
   - Structured return value matching the namespace's shared shape
   - Consistent error handling — botocore exceptions wrapped in the namespace's error type
   - For write tools: audit-log emission to the S3 Object Lock bucket **before** the AWS API call

2. **`tests/mcp_server/<namespace_underscored>/test_<tool_name>.py`** — pytest:
   - `@pytest.mark.unit` happy path with `moto` or a mocked boto3 client
   - Error path (boto3 ClientError) — assert the wrapped error type
   - For write tools: assert the audit entry is emitted **before** the AWS call (order matters — if the AWS call happens first and audit second, a partial failure escapes the journal)

3. **If write tool:** `cedar-policies/<namespace>-<verb>-<noun>.cedar` — policy stub:
   - Default deny
   - Allow only when `environment == "dev"` plus resource-specific conditions (e.g. `resource.task_count > 0` for `restart_ecs_service`)
   - Header comment explaining policy intent + which AWS action it gates

## Hard rules to enforce

- **Only the four namespaces.** No exceptions. CLAUDE.md rule #5.
- **Read-only by default.** Write tools must have both a Cedar policy AND audit emission before any AWS write call. CLAUDE.md rules #3 and #4.
- **OTel span on every tool, day one.** No retrofitting later. (decision doc §3.7 soft rule)
- **Tests exist before declaring done.** (CLAUDE.md soft rule)
- **Pin any new dependency** in `pyproject.toml`. (decision doc §3.8)

## Naming

- Tool ID (Python + MCP registration): `<namespace_underscored>_<verb>_<noun>` — e.g. `metrics_api_query_cloudwatch`
- File: `src/triage/mcp_server/<namespace_underscored>/<tool_name>.py`
- Cedar policy: `cedar-policies/<namespace>-<verb>-<noun>.cedar` (kebab-case in filename)
- Test: `tests/mcp_server/<namespace_underscored>/test_<tool_name>.py`

## References

- CLAUDE.md — hard rules + naming
- `docs/architecture-references/aws-multi-agent-sre-architecture-2025.md` — the four-namespace pattern
- `docs/architecture-references/mcp-protocol-and-auth-2026.md` — MCP server implementation tips, OTel pattern, audit-on-write pattern
- `docs/architecture-references/agentcore-primitives-runtime-gateway-identity-memory-2026.md` — how Gateway + Cedar fit

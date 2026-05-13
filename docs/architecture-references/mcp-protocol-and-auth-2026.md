# MCP Protocol and Production Auth

**Source:** Model Context Protocol official site and Python SDK docs; MCP 2026 roadmap post.
**URLs:**
- https://modelcontextprotocol.io/
- https://blog.modelcontextprotocol.io/posts/2026-mcp-roadmap/ (David Soria Parra, March 9, 2026)

## Why this matters for Triage

MCP (Model Context Protocol) is the protocol your custom MCP server speaks. It's the standard interface between an agent and external tools. Donated to the Linux Foundation December 2025 (Agentic AI Foundation, co-founded by Anthropic, Block, OpenAI). First-party servers now ship from PagerDuty, Datadog, Microsoft, AWS, Stripe, Vercel, Supabase, Red Hat. Crossed ~97M monthly SDK downloads by March 2026.

Decision-doc cross-references: 3.2 (custom MCP server), 11 row 3 and 4.

## The mental model

An MCP server is an HTTP service (or stdio process) that exposes a set of **tools**. Each tool has:
- A name
- A description (used by the LLM to decide when to call it)
- An input schema (JSON Schema describing parameters)
- An output schema or freeform output

The agent (Claude, GPT, etc.) reads the tool list, picks a tool to call based on the current task, formats arguments per the schema, and the MCP server executes the tool and returns the result.

This is the same conceptual shape as OpenAPI/REST, but with conventions tuned for LLM consumption (tool descriptions are model-readable, schemas are simple, output is structured for the LLM to parse).

## Transports

**Two transports:**
- **stdio** — process-to-process, useful for local agent dev (the agent runs as a child process of the IDE; the MCP server is another child process)
- **Streamable HTTP** — production transport for remote MCP servers. The project uses this.

## Production auth (OAuth 2.1 + RFC 8707)

The 2026 production standard for MCP server auth is **OAuth 2.1 + Resource Indicators (RFC 8707)**. The agent's token must specify the resource it's accessing (the MCP server URL). This prevents token-confusion attacks where a token intended for one MCP server could be replayed against another.

**For Triage:** AgentCore Identity provides this out of the box (decision doc Section 3.2 and notes file `agentcore-primitives-*.md`). You configure your MCP server to accept tokens signed by AgentCore Identity and to verify the Resource Indicator matches your server URL.

**Don't roll custom auth.** API keys in env vars are a portfolio liability. The OAuth 2.1 path is the production standard.

## 2026 roadmap (what's coming)

From David Soria Parra's MCP roadmap post (March 9, 2026):

- **Stateless sessions over Streamable HTTP.** Currently MCP servers maintain session state per-connection; the move is to stateless so servers can horizontally scale behind a load balancer. Migration will affect server implementations.
- **`.well-known` server-capability discovery** — standard URL pattern for clients to discover what an MCP server supports without manual config.
- **OAuth 2.1 + Resource Indicators ratified as the production standard** (effectively already adopted, formalizing in spec).
- **Tasks primitive (SEP-1686) lifecycle closing gaps** — better handling of long-running tool invocations that span sessions.

**For Triage:** pin your MCP server to a specific protocol version. Note the upcoming statelessness migration in the README's "known limitations" section. Decision-doc Section 3.8 commits to version pinning.

## Implementation tips for your custom MCP server

**Use the Python SDK.** It handles the transport layer, schema validation, and tool registration. Don't write the protocol from scratch.

**Organize tools into the four namespaces.** Use the SDK's tool-registration mechanism with namespace prefixes (`metrics_api_query_logs`, etc.) so the namespace shows up clearly in tool listings.

**Instrument every tool with OpenTelemetry from the start.** AgentCore Observability picks these up. Don't bolt instrumentation on later — every tool gets a span on Day 1.

**Emit audit log entries from write tools.** Every write tool, before executing the write, appends a structured entry to your S3 Object Lock audit bucket: who (agent ID), what (tool + arguments), when (timestamp), why (calling context if available). This is half of the immutable audit journal from decision-doc Section 3.3.

**Pattern from the PagerDuty MCP server:** the `--enable-write-tools` flag. Write tools are excluded from the tool catalog unless the flag is set. Useful for dev/staging where you want read-only mode. Worth replicating: your MCP server should have a similar flag or env var that gates write tools.

## Verify against live source

- Current Python SDK API (sdk versions change)
- Current Streamable HTTP transport spec version
- Current OAuth 2.1 + Resource Indicators integration pattern with AgentCore Identity
- Whether the statelessness migration has shipped and on what timeline

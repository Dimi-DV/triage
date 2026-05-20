"""AgentCore Runtime container entrypoint for the Triage agent.

Runtime addresses each session over HTTP. The container listens on
`0.0.0.0:8080` and exposes:

  - GET  /ping           — AgentCore Runtime readiness probe; 200 = healthy.
  - POST /invocations    — Runtime delivers the input payload here; we drive
                           a Bedrock Claude `converse` loop with tool use
                           proxied through AgentCore Gateway (MCP over
                           Streamable HTTP) and return the final assistant
                           message.

The Bedrock-Claude loop is intentionally narrow: no episodic memory, no
sub-agents, no streaming response. Day 36 widens the scope.
"""

from __future__ import annotations

import json
import logging
import os
import pathlib
import time
from typing import Any, cast

import boto3
import httpx
import uvicorn
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from triage.shared.evaluate_spans import to_evaluate_payload
from triage.shared.otel import (
    flush_and_collect_spans,
    init_tracing,
    install_runtime_exporter,
    tool_span,
)

log = logging.getLogger(__name__)

_MODEL_ID_ENV = "BEDROCK_MODEL_ID"
_GATEWAY_URL_ENV = "TRIAGE_GATEWAY_URL"
_GATEWAY_SERVICE = "bedrock-agentcore"
_MAX_TURNS = 12

# Common attributes carried on every span so AgentCore's Evaluate adapter
# recognizes them as a single Strands-instrumented session. See
# feedback_agentcore_evaluate_strands_shape for the full pinned shape.
_GEN_AI_SYSTEM = {
    "gen_ai.system": "strands-agents",
    "gen_ai.provider.name": "strands-agents",
}
_AGENT_NAME = "triage-agent"
_SESSION_ID_HEADER = "x-amzn-bedrock-agentcore-runtime-session-id"


def _load_system_prompt() -> str:
    """Read agent/AGENT.md packaged alongside the image."""
    here = pathlib.Path(__file__).resolve()
    for candidate in (
        here.parent.parent.parent.parent / "agent" / "AGENT.md",
        pathlib.Path("/app/agent/AGENT.md"),
    ):
        if candidate.is_file():
            return candidate.read_text(encoding="utf-8")
    raise FileNotFoundError("agent/AGENT.md not found next to runtime.py or at /app/agent/AGENT.md")


SYSTEM_PROMPT = _load_system_prompt()


# ---------------------------------------------------------------------------
# Minimal MCP-over-HTTP client.
#
# AgentCore Gateway speaks MCP Streamable HTTP. We POST JSON-RPC envelopes
# directly rather than using the full `mcp.client.streamable_http` session
# manager, but we still honor the spec's `initialize → initialized →
# tools/*` handshake the SDK enforces.
# ---------------------------------------------------------------------------


_MCP_CLIENT_NAME = "triage-agent"
_MCP_CLIENT_VERSION = "0.1.0"
_initialized = False


def _aws_region() -> str:
    return os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or "us-east-1"


def _signed_post(url: str, payload: dict[str, Any], timeout: float) -> httpx.Response:
    """POST to the AgentCore Gateway with SigV4 (AWS_IAM authorizer).

    Credentials are resolved from the container's IAM role via the boto3
    default provider chain — AgentCore Runtime injects them as task role
    creds. We sign with botocore, then hand the headers to httpx so we
    keep the small dependency footprint already in use.
    """
    body = json.dumps(payload).encode("utf-8")
    request = AWSRequest(
        method="POST",
        url=url,
        data=body,
        headers={
            "content-type": "application/json",
            "accept": "application/json, text/event-stream",
        },
    )
    credentials = boto3.Session().get_credentials()
    if credentials is None:
        raise RuntimeError("No AWS credentials available to SigV4-sign the gateway request")
    SigV4Auth(credentials.get_frozen_credentials(), _GATEWAY_SERVICE, _aws_region()).add_auth(
        request
    )
    return httpx.post(url, content=body, headers=dict(request.headers), timeout=timeout)


def _post_jsonrpc(envelope: dict[str, Any]) -> dict[str, Any]:
    url = os.environ[_GATEWAY_URL_ENV]
    response = _signed_post(url, envelope, timeout=30.0)
    response.raise_for_status()
    body: dict[str, Any] = response.json()
    if "error" in body:
        raise RuntimeError(f"MCP error from gateway: {body['error']}")
    return body


def _ensure_initialized() -> None:
    """Send `initialize` + `notifications/initialized` once per process.

    Required by the MCP spec before any tools/* call. FastMCP enforces this
    in HTTP mode regardless of stateless_http=True.
    """
    global _initialized
    if _initialized:
        return
    init_response = _post_jsonrpc(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-11-25",
                "capabilities": {},
                "clientInfo": {"name": _MCP_CLIENT_NAME, "version": _MCP_CLIENT_VERSION},
            },
        }
    )
    log.info(
        "MCP initialize OK; server=%s",
        init_response.get("result", {}).get("serverInfo", {}),
    )
    # Notifications carry no id and expect no response body; the gateway may
    # 202 it. Still SigV4-signed because the AWS_IAM authorizer doesn't
    # exempt them.
    _signed_post(
        os.environ[_GATEWAY_URL_ENV],
        {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
        timeout=10.0,
    )
    _initialized = True


def _mcp_request(method: str, params: dict[str, Any]) -> dict[str, Any]:
    _ensure_initialized()
    body = _post_jsonrpc({"jsonrpc": "2.0", "id": 2, "method": method, "params": params})
    return cast(dict[str, Any], body.get("result", {}))


def _list_tools() -> list[dict[str, Any]]:
    result = _mcp_request("tools/list", {})
    return cast(list[dict[str, Any]], result.get("tools", []))


def _call_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    return _mcp_request("tools/call", {"name": name, "arguments": arguments})


# ---------------------------------------------------------------------------
# Bedrock Claude tool-use loop.
# ---------------------------------------------------------------------------


def _bedrock_tool_config(tools: list[dict[str, Any]]) -> dict[str, Any]:
    """Translate MCP tool descriptors into Bedrock Converse tool specs."""
    return {
        "tools": [
            {
                "toolSpec": {
                    "name": t["name"],
                    "description": t.get("description", ""),
                    "inputSchema": {"json": t.get("inputSchema", {})},
                }
            }
            for t in tools
        ]
    }


def _session_common(session_id: str) -> dict[str, Any]:
    return {**_GEN_AI_SYSTEM, "session.id": session_id}


def _run_loop(alarm_payload: dict[str, Any], session_id: str) -> dict[str, Any]:
    bedrock = boto3.client("bedrock-runtime")
    tools = _list_tools()
    tool_config = _bedrock_tool_config(tools)
    model_id = os.environ[_MODEL_ID_ENV]

    user_query = json.dumps(alarm_payload, indent=2)
    messages: list[dict[str, Any]] = [
        {
            "role": "user",
            "content": [
                {"text": "Incoming alarm payload:"},
                {"text": user_query},
            ],
        }
    ]
    common = _session_common(session_id)

    final_text = ""
    # Clear any pre-existing buffered spans from this long-lived container so
    # we never bleed spans from a prior session into this run's evaluation.
    flush_and_collect_spans()

    with tool_span(
        f"invoke_agent {_AGENT_NAME}",
        **common,
        **{
            "gen_ai.operation.name": "invoke_agent",
            "gen_ai.agent.name": _AGENT_NAME,
            "gen_ai.request.model": model_id,
            "gen_ai.prompt": user_query,
            "gen_ai.user.message": user_query,
            "user_query": user_query,
        },
    ) as agent_span:
        agent_span.add_event(
            "gen_ai.user.message",
            attributes={
                "content": json.dumps([{"text": user_query}]),
                "role": "user",
            },
        )

        for _turn in range(_MAX_TURNS):
            with tool_span(
                "chat",
                **common,
                **{
                    "gen_ai.operation.name": "chat",
                    "gen_ai.request.model": model_id,
                },
            ) as chat_span:
                response = bedrock.converse(
                    modelId=model_id,
                    messages=messages,
                    system=[{"text": SYSTEM_PROMPT}],
                    toolConfig=tool_config,
                    inferenceConfig={"maxTokens": 2048, "temperature": 0.0},
                )
                chat_span.add_event(
                    "gen_ai.choice",
                    attributes={
                        "message": json.dumps(
                            response.get("output", {}).get("message", {}).get("content", [])
                        ),
                        "finish_reason": str(response.get("stopReason", "")),
                    },
                )

            output = response["output"]["message"]
            messages.append({"role": output["role"], "content": output["content"]})

            stop_reason = response.get("stopReason")
            if stop_reason != "tool_use":
                final_text = "".join(
                    block.get("text", "") for block in output["content"] if "text" in block
                )
                break

            # Execute every tool_use block in this assistant turn, append a
            # single user turn with the matching tool_result blocks.
            tool_results: list[dict[str, Any]] = []
            for block in output["content"]:
                if "toolUse" not in block:
                    continue
                tu = block["toolUse"]
                # Routing uses the Gateway-prefixed name; spans report the
                # canonical bare MCP tool ID so trajectory comparisons
                # against the scenario YAML match.
                raw_tool_name = tu["name"]
                tool_name = raw_tool_name.split("___", 1)[-1]
                tool_use_id = tu["toolUseId"]
                tool_args = tu.get("input", {})
                tool_args_json = json.dumps(tool_args)
                log.info("Agent calling tool %s", tool_name)
                with tool_span(
                    f"execute_tool {tool_name}",
                    **common,
                    **{
                        "gen_ai.operation.name": "execute_tool",
                        "gen_ai.tool.name": tool_name,
                        "gen_ai.tool.call.id": tool_use_id,
                        "gen_ai.tool.arguments": tool_args_json,
                        "gen_ai.tool.call.arguments": tool_args_json,
                        "tool_parameters": tool_args_json,
                    },
                ) as tool_span_:
                    tool_span_.add_event(
                        "gen_ai.client.inference.operation.details",
                        attributes={
                            "gen_ai.input.messages": json.dumps(
                                [
                                    {
                                        "role": "tool",
                                        "parts": [
                                            {
                                                "type": "tool_call",
                                                "name": tool_name,
                                                "id": tool_use_id,
                                                "arguments": tool_args,
                                            }
                                        ],
                                    }
                                ]
                            ),
                        },
                    )
                    try:
                        result = _call_tool(raw_tool_name, tool_args)
                        result_text = json.dumps(result)[:2000]
                        tool_status = "success"
                        tool_results.append(
                            {
                                "toolResult": {
                                    "toolUseId": tool_use_id,
                                    "content": [{"json": result}],
                                }
                            }
                        )
                    except Exception as exc:
                        log.exception("Tool %s failed", tool_name)
                        result_text = str(exc)
                        tool_status = "error"
                        tool_results.append(
                            {
                                "toolResult": {
                                    "toolUseId": tool_use_id,
                                    "status": "error",
                                    "content": [{"text": str(exc)}],
                                }
                            }
                        )
                    tool_span_.set_attribute("gen_ai.tool.status", tool_status)
                    tool_span_.add_event(
                        "gen_ai.client.inference.operation.details",
                        attributes={
                            "gen_ai.output.messages": json.dumps(
                                [
                                    {
                                        "role": "tool",
                                        "parts": [
                                            {
                                                "type": "tool_call_response",
                                                "id": tool_use_id,
                                                "response": [{"text": result_text}],
                                            }
                                        ],
                                    }
                                ]
                            ),
                        },
                    )
                    tool_span_.add_event(
                        "gen_ai.tool.message",
                        attributes={
                            "role": "tool",
                            "content": tool_args_json,
                            "id": tool_use_id,
                        },
                    )
                    tool_span_.add_event(
                        "gen_ai.choice",
                        attributes={
                            "message": json.dumps([{"text": result_text}]),
                            "id": tool_use_id,
                        },
                    )
            messages.append({"role": "user", "content": tool_results})
        else:
            # Loop exhaustion is a real failure: Slack post never happened.
            raise RuntimeError(
                f"Agent loop exhausted _MAX_TURNS={_MAX_TURNS} without completing; "
                "Slack post was not made."
            )

        agent_span.add_event(
            "gen_ai.client.inference.operation.details",
            attributes={
                "gen_ai.output.messages": json.dumps(
                    [
                        {
                            "role": "assistant",
                            "parts": [{"type": "text", "content": final_text}],
                        }
                    ]
                ),
            },
        )
        agent_span.add_event(
            "gen_ai.choice",
            attributes={
                "message": final_text,
                "finish_reason": "end_turn",
            },
        )

    spans = to_evaluate_payload(flush_and_collect_spans())
    return {
        "final_text": final_text,
        "turns": len(messages),
        "session_id": session_id,
        "spans": spans,
    }


# ---------------------------------------------------------------------------
# Starlette HTTP surface.
# ---------------------------------------------------------------------------


async def ping(_request: Request) -> JSONResponse:
    return JSONResponse({"status": "Healthy", "time_of_last_update": int(time.time())})


async def invocations(request: Request) -> JSONResponse:
    payload_bytes = await request.body()
    try:
        payload = json.loads(payload_bytes) if payload_bytes else {}
    except json.JSONDecodeError:
        return JSONResponse({"error": "invalid_json"}, status_code=400)

    alarm = payload.get("alarm", payload)
    # AgentCore Runtime injects the runtimeSessionId as a header on every
    # /invocations call. We carry it onto every OTel span so on-demand
    # Evaluate recognizes the spans as one Strands session.
    session_id = request.headers.get(_SESSION_ID_HEADER) or payload.get("session_id") or "anonymous"
    log.info("Agent received alarm %s session=%s", alarm.get("AlarmName", "(unknown)"), session_id)

    try:
        result = _run_loop(alarm, session_id)
    except Exception as exc:
        log.exception("Agent loop failed")
        return JSONResponse({"error": "agent_failed", "detail": str(exc)}, status_code=500)
    return JSONResponse(result)


app = Starlette(
    routes=[
        Route("/ping", ping, methods=["GET"]),
        Route("/invocations", invocations, methods=["POST"]),
    ]
)


def main() -> None:
    # AgentCore on-demand Evaluate only accepts spans from one of three
    # framework scopes; "strands.telemetry.tracer" is the one we mirror.
    init_tracing("triage-agent", tracer_name="strands.telemetry.tracer")
    install_runtime_exporter()
    port = int(os.environ.get("PORT", "8080"))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")  # noqa: S104  (container)


if __name__ == "__main__":
    main()

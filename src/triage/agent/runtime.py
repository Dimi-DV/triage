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

from triage.shared.otel import init_tracing, tool_span

log = logging.getLogger(__name__)

_MODEL_ID_ENV = "BEDROCK_MODEL_ID"
_GATEWAY_URL_ENV = "TRIAGE_GATEWAY_URL"
_GATEWAY_SERVICE = "bedrock-agentcore"
_MAX_TURNS = 6


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


def _run_loop(alarm_payload: dict[str, Any]) -> dict[str, Any]:
    bedrock = boto3.client("bedrock-runtime")
    tools = _list_tools()
    tool_config = _bedrock_tool_config(tools)

    messages: list[dict[str, Any]] = [
        {
            "role": "user",
            "content": [
                {"text": "Incoming alarm payload:"},
                {"text": json.dumps(alarm_payload, indent=2)},
            ],
        }
    ]

    final_text = ""
    for turn in range(_MAX_TURNS):
        with tool_span("triage.agent.converse", turn=turn):
            response = bedrock.converse(
                modelId=os.environ[_MODEL_ID_ENV],
                messages=messages,
                system=[{"text": SYSTEM_PROMPT}],
                toolConfig=tool_config,
                inferenceConfig={"maxTokens": 2048, "temperature": 0.0},
            )

        output = response["output"]["message"]
        messages.append({"role": output["role"], "content": output["content"]})

        stop_reason = response.get("stopReason")
        if stop_reason != "tool_use":
            final_text = "".join(
                block.get("text", "") for block in output["content"] if "text" in block
            )
            break

        # Execute every tool_use block in this assistant turn, append a single
        # user turn with the matching tool_result blocks.
        tool_results: list[dict[str, Any]] = []
        for block in output["content"]:
            if "toolUse" not in block:
                continue
            tu = block["toolUse"]
            log.info("Agent calling tool %s", tu["name"])
            with tool_span("triage.agent.tool_call", tool=tu["name"]):
                try:
                    result = _call_tool(tu["name"], tu.get("input", {}))
                    tool_results.append(
                        {
                            "toolResult": {
                                "toolUseId": tu["toolUseId"],
                                "content": [{"json": result}],
                            }
                        }
                    )
                except Exception as exc:
                    log.exception("Tool %s failed", tu["name"])
                    tool_results.append(
                        {
                            "toolResult": {
                                "toolUseId": tu["toolUseId"],
                                "status": "error",
                                "content": [{"text": str(exc)}],
                            }
                        }
                    )
        messages.append({"role": "user", "content": tool_results})
    else:
        # Loop exhaustion is a real failure: Slack post never happened.
        # Raise so the /invocations handler returns 500 and SNS/DLQ surface it.
        raise RuntimeError(
            f"Agent loop exhausted _MAX_TURNS={_MAX_TURNS} without completing; "
            "Slack post was not made."
        )

    return {"final_text": final_text, "turns": len(messages)}


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
    log.info("Agent received alarm %s", alarm.get("AlarmName", "(unknown)"))

    try:
        result = _run_loop(alarm)
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
    init_tracing("triage-agent")
    port = int(os.environ.get("PORT", "8080"))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")  # noqa: S104  (container)


if __name__ == "__main__":
    main()

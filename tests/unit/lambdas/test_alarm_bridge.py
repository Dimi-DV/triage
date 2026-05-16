"""Tests for the SNS → AgentCore Runtime bridge Lambda."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock

import pytest

from triage.lambdas.alarm_bridge import handler as handler_module
from triage.lambdas.alarm_bridge.handler import handler

RUNTIME_ARN = "arn:aws:bedrock-agentcore:us-east-1:111111111111:agent-runtime/triage-rt-abc"


@pytest.fixture
def patched_clients(monkeypatch: pytest.MonkeyPatch) -> dict[str, MagicMock]:
    ssm = MagicMock()
    ssm.get_parameter.return_value = {"Parameter": {"Value": RUNTIME_ARN}}
    agentcore = MagicMock()
    agentcore.invoke_agent_runtime.return_value = {"statusCode": 200}

    def fake_client(name: str) -> MagicMock:
        if name == "ssm":
            return ssm
        if name == "bedrock-agentcore":
            return agentcore
        raise AssertionError(f"unexpected boto3 service: {name}")

    monkeypatch.setattr(handler_module, "_client", fake_client)
    monkeypatch.setenv("TRIAGE_RUNTIME_ARN_PARAM", "/test/runtime-arn")
    return {"ssm": ssm, "agentcore": agentcore}


def _sns_event(message: dict[str, Any]) -> dict[str, Any]:
    return {
        "Records": [
            {"Sns": {"Message": json.dumps(message), "MessageId": "m-1"}},
        ]
    }


@pytest.mark.unit
def test_handler_invokes_runtime_with_alarm_payload(
    patched_clients: dict[str, MagicMock],
) -> None:
    alarm = {
        "AlarmName": "prod-cpu-high",
        "NewStateValue": "ALARM",
        "NewStateReason": "Threshold crossed",
        "StateChangeTime": "2026-05-16T18:00:00.000Z",
        "Region": "US East (N. Virginia)",
    }
    result = handler(_sns_event(alarm), object())

    assert result["statusCode"] == 200
    assert len(result["invocations"]) == 1
    invocation = result["invocations"][0]
    assert invocation["session_id"].startswith("alarm-")
    assert invocation["alarm_name"] == "prod-cpu-high"

    call = patched_clients["agentcore"].invoke_agent_runtime.call_args
    assert call.kwargs["agentRuntimeArn"] == RUNTIME_ARN
    assert call.kwargs["contentType"] == "application/json"
    payload = json.loads(call.kwargs["payload"])
    assert payload == {"alarm": alarm}


@pytest.mark.unit
def test_handler_handles_multiple_records(
    patched_clients: dict[str, MagicMock],
) -> None:
    event = {
        "Records": [
            {"Sns": {"Message": json.dumps({"AlarmName": "a1"})}},
            {"Sns": {"Message": json.dumps({"AlarmName": "a2"})}},
        ]
    }
    result = handler(event, object())
    assert len(result["invocations"]) == 2
    assert patched_clients["agentcore"].invoke_agent_runtime.call_count == 2


@pytest.mark.unit
def test_handler_passes_non_json_message_raw(
    patched_clients: dict[str, MagicMock],
) -> None:
    event = {"Records": [{"Sns": {"Message": "not-json-blob"}}]}
    handler(event, object())

    payload = json.loads(
        patched_clients["agentcore"].invoke_agent_runtime.call_args.kwargs["payload"]
    )
    assert payload == {"alarm": {"raw": "not-json-blob"}}


@pytest.mark.unit
def test_handler_rejects_placeholder_runtime_arn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ssm = MagicMock()
    ssm.get_parameter.return_value = {
        "Parameter": {"Value": "PLACEHOLDER_FILL_VIA_PROVISIONING_SCRIPT"}
    }
    agentcore = MagicMock()
    monkeypatch.setattr(
        handler_module,
        "_client",
        lambda name: ssm if name == "ssm" else agentcore,
    )
    monkeypatch.setenv("TRIAGE_RUNTIME_ARN_PARAM", "/test/runtime-arn")

    with pytest.raises(RuntimeError, match="placeholder"):
        handler(_sns_event({"AlarmName": "x"}), object())

    agentcore.invoke_agent_runtime.assert_not_called()


@pytest.mark.unit
def test_handler_each_invocation_has_unique_session_id(
    patched_clients: dict[str, MagicMock],
) -> None:
    event = {
        "Records": [{"Sns": {"Message": json.dumps({"AlarmName": f"a{i}"})}} for i in range(3)]
    }
    result = handler(event, object())
    session_ids = [inv["session_id"] for inv in result["invocations"]]
    assert len(set(session_ids)) == 3

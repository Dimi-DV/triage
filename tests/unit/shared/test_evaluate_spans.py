"""Tests for the AgentCore-Evaluate span serializer."""

from __future__ import annotations

import re

import pytest

from triage.shared.evaluate_spans import to_evaluate_payload
from triage.shared.otel import (
    flush_and_collect_spans,
    init_tracing,
    install_runtime_exporter,
    tool_span,
)

HEX32 = re.compile(r"^[0-9a-f]{32}$")
HEX16 = re.compile(r"^[0-9a-f]{16}$")
ISO_TS = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?\+\d{2}:\d{2}$")


def _build_session_spans() -> list:
    init_tracing("triage-agent-test", tracer_name="strands.telemetry.tracer")
    install_runtime_exporter()
    flush_and_collect_spans()  # clear any leftover from prior tests
    with tool_span("invoke_agent triage-agent", **{"session.id": "s-test"}) as parent:
        parent.add_event(
            "gen_ai.user.message",
            attributes={"content": '[{"text": "hello"}]', "role": "user"},
        )
        with tool_span("execute_tool t1", **{"session.id": "s-test", "gen_ai.tool.name": "t1"}):
            pass
        parent.add_event(
            "gen_ai.choice",
            attributes={"message": "done", "finish_reason": "end_turn"},
        )
    return flush_and_collect_spans()


@pytest.mark.unit
def test_serialize_shape_matches_evaluate_contract() -> None:
    """Every required field in the Evaluate span document is present and
    in the right shape (snake_case, ISO-8601, scope, flat attributes,
    resource.attributes, hex trace/span ids)."""
    payload = to_evaluate_payload(_build_session_spans())
    assert payload, "expected at least one serialized span"

    for span in payload:
        # IDs follow OTLP-JSON hex conventions
        assert HEX32.match(span["trace_id"]), span["trace_id"]
        assert HEX16.match(span["span_id"]), span["span_id"]
        if span["parent_span_id"] is not None:
            assert HEX16.match(span["parent_span_id"])
        # Timestamps are ISO-8601, not unix nanoseconds
        assert ISO_TS.match(span["start_time"]), span["start_time"]
        assert ISO_TS.match(span["end_time"]), span["end_time"]
        # Scope spoofed for AgentCore Evaluate
        assert span["scope"]["name"] == "strands.telemetry.tracer"
        assert "version" in span["scope"]
        # Resource carries service.name in attributes. (OTel refuses to
        # override an already-installed TracerProvider, so the exact
        # service-name value depends on which test ran first in this
        # session; we just assert the field is present and non-empty.)
        assert span["resource"]["attributes"].get("service.name")
        # Attributes are a flat dict (not OTLP-protobuf list of {key,value})
        assert isinstance(span["attributes"], dict)
        # Status block present
        assert "code" in span["status"]


@pytest.mark.unit
def test_all_spans_share_trace_id() -> None:
    """Every span in one session must share a trace_id so the TRACE-level
    judges can score a coherent session."""
    payload = to_evaluate_payload(_build_session_spans())
    trace_ids = {s["trace_id"] for s in payload}
    assert len(trace_ids) == 1, trace_ids


@pytest.mark.unit
def test_events_serialize_with_attributes() -> None:
    """Events carry their name + attributes (load-bearing for {assistant_turn}
    / {user_query} extraction by AgentCore's Strands adapter)."""
    payload = to_evaluate_payload(_build_session_spans())
    agent_span = next(s for s in payload if s["name"].startswith("invoke_agent"))
    event_names = {e["name"] for e in agent_span["events"]}
    assert "gen_ai.user.message" in event_names
    assert "gen_ai.choice" in event_names
    choice = next(e for e in agent_span["events"] if e["name"] == "gen_ai.choice")
    assert choice["attributes"]["message"] == "done"
    assert choice["attributes"]["finish_reason"] == "end_turn"

"""Serialize OpenTelemetry ReadableSpans into AgentCore Evaluate's span shape.

`bedrock-agentcore.Evaluate` accepts spans as a free-form `document` type
(boto3 service model: Span has `metadata.document=True`, no fixed members).
The shape it expects, distilled from prior probing
([[agentcore-evaluate-ondemand-path]]):

- snake_case keys (`trace_id`, `span_id`, `start_time`, `end_time`).
- `start_time` / `end_time` are ISO-8601 strings, NOT unix-nano numbers.
- `scope: {name, version}` is required (AgentCore additionally gates this
  scope name to a known framework: see triage.shared.otel).
- `attributes` is a flat `{key: value}` dict, not the OTLP-protobuf list of
  `{key, value}` pairs.
- `resource: {attributes: {service.name: ...}}` carries service identity.

Trace + span ids follow the OTLP-JSON convention of lowercase hex strings:
trace_id is 32 chars (128-bit), span_id is 16 chars (64-bit). Parent
relationship is carried by `parent_span_id` (omitted on root spans).
"""

from __future__ import annotations

import datetime as _dt
from collections.abc import Sequence
from typing import Any

from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.trace import SpanKind


def _iso(ns: int | None) -> str | None:
    if ns is None:
        return None
    return _dt.datetime.fromtimestamp(ns / 1e9, tz=_dt.UTC).isoformat()


def _kind(kind: SpanKind | None) -> str:
    if kind is None:
        return "INTERNAL"
    return kind.name


def _attrs(raw: Any) -> dict[str, Any]:
    if raw is None:
        return {}
    # BoundedAttributes is a Mapping; dict(...) copies it as a plain dict.
    return {str(k): v for k, v in dict(raw).items()}


def _event(ev: Any) -> dict[str, Any]:
    return {
        "name": ev.name,
        "time": _iso(ev.timestamp),
        "attributes": _attrs(ev.attributes),
    }


def span_to_evaluate(span: ReadableSpan) -> dict[str, Any]:
    """Serialize one ReadableSpan into the Evaluate span document shape."""
    ctx = span.get_span_context()
    if ctx is None:
        raise ValueError(f"Span {span.name!r} has no SpanContext; cannot serialize")
    parent = span.parent
    scope = span.instrumentation_scope
    resource = span.resource

    return {
        "name": span.name,
        "trace_id": f"{ctx.trace_id:032x}",
        "span_id": f"{ctx.span_id:016x}",
        "parent_span_id": f"{parent.span_id:016x}" if parent is not None else None,
        "kind": _kind(span.kind),
        "start_time": _iso(span.start_time),
        "end_time": _iso(span.end_time),
        "attributes": _attrs(span.attributes),
        "events": [_event(e) for e in (span.events or [])],
        "scope": {
            "name": scope.name if scope else "",
            "version": (scope.version or "") if scope else "",
        },
        "resource": {"attributes": _attrs(resource.attributes) if resource else {}},
        "status": {
            "code": span.status.status_code.name if span.status else "UNSET",
            "message": (span.status.description or "") if span.status else "",
        },
    }


def to_evaluate_payload(spans: Sequence[ReadableSpan]) -> list[dict[str, Any]]:
    """Serialize a session's spans for inline submission to Evaluate."""
    return [span_to_evaluate(s) for s in spans]

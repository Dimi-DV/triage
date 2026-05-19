"""OpenTelemetry tracing bootstrap for the MCP server.

Critical safety note: the stdio transport uses stdout for JSON-RPC framing.
Any stdout writes outside the protocol break message parsing on the client
side. So:

  - Default trace exporter is `none` (silent) unless OTEL_TRACES_EXPORTER
    is set explicitly.
  - When `console` is requested, the exporter is wired to stderr.
  - Python logging is forced to stderr at the root.
"""

from __future__ import annotations

import logging
import os
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, cast

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    ConsoleSpanExporter,
    SimpleSpanProcessor,
    SpanExporter,
)
from opentelemetry.trace import Span, Tracer

# Default tracer scope name. AgentCore's on-demand `Evaluate` API only accepts
# spans whose scope.name is one of three known frameworks
# (strands.telemetry.tracer, opentelemetry.instrumentation.langchain,
# openinference.instrumentation.langchain), so the agent runtime overrides
# this at init_tracing() time. The MCP server keeps the default.
_TRACER_NAME: str | None = None
_RUNTIME_EXPORTER: Any = None


def _build_exporter() -> SpanExporter | None:
    """Pick a span exporter based on OTEL_TRACES_EXPORTER. Default: none."""
    choice = os.environ.get("OTEL_TRACES_EXPORTER", "none").strip().lower()
    if choice in ("", "none"):
        return None
    if choice == "console":
        return ConsoleSpanExporter(out=sys.stderr)
    if choice == "otlp":
        # OTLP exporter pulled in lazily; only needed in prod (AgentCore
        # Observability or CloudWatch Application Signals) and we do not
        # want it as a hard dependency for local dev.
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter,
        )

        return cast(SpanExporter, OTLPSpanExporter())
    raise ValueError(f"Unsupported OTEL_TRACES_EXPORTER={choice!r}")


def init_tracing(service_name: str, tracer_name: str | None = None) -> None:
    """Install a global TracerProvider with a stdio-safe exporter.

    `tracer_name` overrides the OTel scope name returned by `_tracer()`.
    The agent runtime passes "strands.telemetry.tracer" so AgentCore's
    on-demand Evaluate accepts its spans; the MCP server leaves it None
    and keeps the default "triage.mcp_server".

    Idempotent: safe to call multiple times in tests.
    """
    global _TRACER_NAME, _RUNTIME_EXPORTER
    logging.basicConfig(stream=sys.stderr, level=logging.INFO, force=True)

    resource = Resource.create({"service.name": service_name})
    provider = TracerProvider(resource=resource)

    exporter = _build_exporter()
    if exporter is not None:
        provider.add_span_processor(BatchSpanProcessor(exporter))

    trace.set_tracer_provider(provider)
    _TRACER_NAME = tracer_name
    # New provider → previously-installed runtime exporter is detached.
    _RUNTIME_EXPORTER = None


def install_runtime_exporter() -> Any:
    """Attach an InMemorySpanExporter to the active TracerProvider.

    Used by the agent runtime to collect session spans for inline
    submission to `bedrock-agentcore.Evaluate`. Idempotent — a second call
    returns the same exporter handle. Must be called after `init_tracing`.
    """
    global _RUNTIME_EXPORTER
    if _RUNTIME_EXPORTER is not None:
        return _RUNTIME_EXPORTER
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
        InMemorySpanExporter,
    )

    exporter = InMemorySpanExporter()
    provider = cast(TracerProvider, trace.get_tracer_provider())
    provider.add_span_processor(BatchSpanProcessor(exporter))
    _RUNTIME_EXPORTER = exporter
    return exporter


def flush_and_collect_spans() -> list[ReadableSpan]:
    """Force-flush the active provider and drain the runtime exporter.

    Returns the collected spans in finish order, then clears the buffer so
    subsequent runs in the same long-lived container don't bleed across
    sessions.
    """
    if _RUNTIME_EXPORTER is None:
        return []
    provider = cast(TracerProvider, trace.get_tracer_provider())
    provider.force_flush()
    spans = list(_RUNTIME_EXPORTER.get_finished_spans())
    _RUNTIME_EXPORTER.clear()
    return spans


def install_in_memory_exporter() -> Any:
    """Install an InMemorySpanExporter and return it for assertions.

    Used by tests. Not exported from the package by default — callers must
    import it explicitly.
    """
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
        InMemorySpanExporter,
    )

    resource = Resource.create({"service.name": "triage-mcp-server-test"})
    provider = TracerProvider(resource=resource)
    exporter = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    return exporter


def _tracer() -> Tracer:
    return trace.get_tracer(_TRACER_NAME or "triage.mcp_server")


@contextmanager
def tool_span(name: str, **attrs: Any) -> Iterator[Span]:
    """Open a span for an MCP tool invocation.

    `name` is the full tool ID (`<namespace>_<verb>_<noun>`). Caller passes
    non-secret attributes as kwargs; values are coerced to OTel-compatible
    primitives.
    """
    with _tracer().start_as_current_span(name) as span:
        for key, value in attrs.items():
            if value is None:
                continue
            if isinstance(value, str | bool | int | float):
                span.set_attribute(key, value)
            else:
                span.set_attribute(key, str(value))
        yield span

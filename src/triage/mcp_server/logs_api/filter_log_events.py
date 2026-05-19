"""logs_api_filter_log_events — query CloudWatch Logs over a time window.

Read-only: the agent uses this to inspect application / container / load
balancer logs while reasoning about an incident. Wraps boto3's
`logs.filter_log_events`. Returns events with ISO-8601 timestamps and a
truncated message body so the agent's context window doesn't blow up on
chatty log groups.
"""

from __future__ import annotations

import datetime as _dt
from typing import Any

from triage.mcp_server.server import mcp
from triage.shared.aws import get_logs_client
from triage.shared.errors import LogsApiError, wrap_boto_error
from triage.shared.otel import tool_span

TOOL_ID = "logs_api_filter_log_events"

# Hard cap per event message so a single noisy log line can't blow the
# agent's context window. CloudWatch events can be up to 256 KB; we
# truncate aggressively for agent consumption.
_MESSAGE_TRUNCATE_CHARS = 1500
# Hard cap on events returned in a single call. Agent should narrow the
# time window or filter pattern rather than ask for more.
_MAX_LIMIT = 100


def _to_ms(t: _dt.datetime) -> int:
    """CloudWatch Logs expects epoch milliseconds for startTime / endTime."""
    if t.tzinfo is None:
        t = t.replace(tzinfo=_dt.UTC)
    return int(t.timestamp() * 1000)


def _to_iso(ms: int | None) -> str | None:
    if ms is None:
        return None
    return _dt.datetime.fromtimestamp(ms / 1000, tz=_dt.UTC).isoformat()


@mcp.tool(
    name=TOOL_ID,
    description=(
        "Query CloudWatch Logs for events from one log group over a time "
        "window. Read-only. Supports a filter pattern using CloudWatch Logs "
        "filter syntax (e.g. '?ERROR ?WARN' to match either, or "
        "'\"connection refused\"' for a literal phrase). Returns up to "
        "`limit` events (max 100); messages truncated to 1500 chars. Use "
        "this to inspect application logs, container stdout/stderr captured "
        "to CloudWatch, or ALB access logs while diagnosing an incident."
    ),
)
def logs_api_filter_log_events(
    log_group_name: str,
    start_time: _dt.datetime,
    end_time: _dt.datetime,
    filter_pattern: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    capped_limit = max(1, min(int(limit), _MAX_LIMIT))
    with tool_span(
        TOOL_ID,
        log_group_name=log_group_name,
        filter_pattern=filter_pattern or "",
        limit=capped_limit,
    ):
        client = get_logs_client()
        kwargs: dict[str, Any] = {
            "logGroupName": log_group_name,
            "startTime": _to_ms(start_time),
            "endTime": _to_ms(end_time),
            "limit": capped_limit,
        }
        if filter_pattern:
            kwargs["filterPattern"] = filter_pattern
        try:
            response = client.filter_log_events(**kwargs)
        except Exception as exc:
            raise wrap_boto_error(exc, LogsApiError) from exc

        events: list[dict[str, Any]] = []
        for raw in response.get("events", []):
            message = raw.get("message", "")
            truncated = len(message) > _MESSAGE_TRUNCATE_CHARS
            events.append(
                {
                    "timestamp": _to_iso(raw.get("timestamp")),
                    "ingestion_time": _to_iso(raw.get("ingestionTime")),
                    "log_stream_name": raw.get("logStreamName"),
                    "message": message[:_MESSAGE_TRUNCATE_CHARS],
                    "message_truncated": truncated,
                }
            )

        return {
            "log_group_name": log_group_name,
            "event_count": len(events),
            "events": events,
            "searched_log_streams": [
                {
                    "log_stream_name": s.get("logStreamName"),
                    "searched_completely": bool(s.get("searchedCompletely", False)),
                }
                for s in response.get("searchedLogStreams", [])
            ],
        }

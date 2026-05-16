"""runbooks_api_post_to_slack — write tool that posts a structured diagnosis.

This is the agent's terminal action after investigating an alarm. Each
invocation:

  1. Resolves the authenticated principal (Streamable HTTP middleware sets
     it from the JWT `sub`; stdio mode uses the TRIAGE_PRINCIPAL fallback).
  2. Writes an immutable audit event to S3 Object Lock BEFORE any Slack
     call (CLAUDE.md hard rule 4).
  3. Posts a Block Kit message to the requested Slack channel.

Cedar policy at AgentCore Gateway must permit
`TriageMcpGateway___runbooks_api_post_to_slack` for the calling principal
before the tool ever runs. The Cedar gate is the system-wide write barrier;
this code does no additional authorization beyond JWT validation.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field
from slack_sdk.errors import SlackApiError

from triage.mcp_server.server import get_current_principal, mcp
from triage.shared.audit import emit_audit_event
from triage.shared.errors import RunbooksApiError, wrap_slack_error
from triage.shared.otel import tool_span
from triage.shared.slack import get_slack_client

TOOL_ID = "runbooks_api_post_to_slack"

Severity = Literal["info", "warning", "critical"]

# Emoji shortnames; Slack expands them in the rendered message. Keeping them
# as ASCII shortnames avoids literal emoji in the source per repo convention.
SEVERITY_SLACK_EMOJI: dict[Severity, str] = {
    "info": ":information_source:",
    "warning": ":warning:",
    "critical": ":rotating_light:",
}


class ObservedMetric(BaseModel):
    """A single metric datapoint the agent collected during investigation."""

    namespace: str = Field(description="CloudWatch namespace, e.g. 'AWS/EC2'")
    name: str = Field(description="Metric name, e.g. 'CPUUtilization'")
    value: float = Field(description="The observed statistic value")
    statistic: str = Field(description="Statistic kind, e.g. 'Average'")
    unit: str | None = Field(default=None, description="CloudWatch unit, e.g. 'Percent'")


class SlackMessage(BaseModel):
    severity: Severity
    alarm_name: str
    summary: str = Field(description="One-line description of what fired")
    diagnosis: str = Field(description="Agent's reasoning about the cause")
    metrics_observed: list[ObservedMetric] = Field(default_factory=list)
    recommended_action: str | None = Field(
        default=None,
        description="What a human should do next. Omit if no action is recommended.",
    )
    channel: str = Field(description="Slack channel id or #name, e.g. '#triage-alerts'")


def _build_blocks(msg: SlackMessage) -> list[dict[str, Any]]:
    emoji = SEVERITY_SLACK_EMOJI[msg.severity]
    blocks: list[dict[str, Any]] = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"{emoji} {msg.severity.upper()}: {msg.alarm_name}",
            },
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Summary:* {msg.summary}"},
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Diagnosis:* {msg.diagnosis}"},
        },
    ]
    if msg.metrics_observed:
        lines = [
            f"• `{m.namespace}/{m.name}` {m.statistic}={m.value}" + (f" {m.unit}" if m.unit else "")
            for m in msg.metrics_observed
        ]
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "*Metrics observed:*\n" + "\n".join(lines),
                },
            }
        )
    if msg.recommended_action:
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Recommended action:* {msg.recommended_action}",
                },
            }
        )
    blocks.append(
        {
            "type": "context",
            "elements": [
                {"type": "mrkdwn", "text": "Posted by the Triage agent."},
            ],
        }
    )
    return blocks


@mcp.tool(
    name=TOOL_ID,
    description=(
        "Post a structured incident diagnosis to a Slack channel. Write tool: "
        "audit-logged to S3 Object Lock before Slack is contacted. Cedar policy "
        "at the Gateway must permit the call."
    ),
)
def runbooks_api_post_to_slack(message: SlackMessage) -> dict[str, Any]:
    principal = get_current_principal()
    args = message.model_dump(exclude_none=True)
    summary = f"{message.severity}:{message.alarm_name} -> {message.channel}"

    with tool_span(
        TOOL_ID,
        severity=message.severity,
        channel=message.channel,
        alarm_name=message.alarm_name,
        principal=principal,
    ):
        audit_key = emit_audit_event(TOOL_ID, principal, args, summary)

        try:
            response = get_slack_client().chat_postMessage(
                channel=message.channel,
                blocks=_build_blocks(message),
                text=f"[{message.severity.upper()}] {message.alarm_name}: {message.summary}",
            )
        except SlackApiError as exc:
            raise wrap_slack_error(exc, RunbooksApiError) from exc

    return {
        "channel": response.get("channel"),
        "ts": response.get("ts"),
        "audit_key": audit_key,
    }

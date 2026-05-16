"""Append-only audit log emission to the S3 Object Lock bucket.

CLAUDE.md hard rule 4: every write tool audits *before* it executes the
side effect. If the audit write fails, the side effect MUST NOT happen.
Callers therefore let `emit_audit_event` raise — they do not catch.

The bucket is the one provisioned in `terraform/stack/main.tf` (audit
bucket with Object Lock + versioning + KMS). Its name is injected as
`TRIAGE_AUDIT_BUCKET` by Terraform (MCP server task definition) and by
the AgentCore provisioning script (agent Runtime env).
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import UTC, datetime
from typing import Any

import boto3
from botocore.config import Config

from triage.shared.otel import tool_span

_AUDIT_BUCKET_ENV = "TRIAGE_AUDIT_BUCKET"
_AUDIT_PREFIX = "events"


def _s3_client() -> Any:
    return boto3.client(
        "s3",
        config=Config(
            region_name=os.environ.get("AWS_REGION", "us-east-1"),
            user_agent_extra="triage-mcp-server/0.1.0",
            retries={"mode": "standard", "max_attempts": 3},
        ),
    )


def _bucket() -> str:
    bucket = os.environ.get(_AUDIT_BUCKET_ENV)
    if not bucket:
        raise RuntimeError(f"{_AUDIT_BUCKET_ENV} is unset; write tools require an audit bucket")
    return bucket


def emit_audit_event(
    tool_id: str,
    principal: str,
    args: dict[str, Any],
    summary: str,
) -> str:
    """Write a single audit event and return the S3 key.

    Raises on any S3 failure; caller is required to abort the side effect.
    """
    now = datetime.now(UTC)
    event_id = str(uuid.uuid4())
    key = f"{_AUDIT_PREFIX}/{now.year:04d}/{now.month:02d}/{now.day:02d}/{event_id}.json"
    body = {
        "event_id": event_id,
        "timestamp": now.isoformat(),
        "tool_id": tool_id,
        "principal": principal,
        "args": args,
        "summary": summary,
    }

    with tool_span(
        "triage.audit.emit",
        tool_id=tool_id,
        principal=principal,
        event_id=event_id,
    ):
        _s3_client().put_object(
            Bucket=_bucket(),
            Key=key,
            Body=json.dumps(body).encode("utf-8"),
            ContentType="application/json",
        )
    return key

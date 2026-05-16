"""Slack WebClient factory backed by AWS Secrets Manager.

The bot token lives in Secrets Manager (provisioned by Terraform as an
empty secret; the human operator fills it once during deploy). Secret
payload shape:

    {"bot_token": "xoxb-..."}

The client is cached at the module level — the Streamable HTTP transport
keeps the same process across requests, and the bot token does not rotate
within a single Runtime session.
"""

from __future__ import annotations

import json
import os
from threading import Lock
from typing import Any

import boto3
from botocore.config import Config
from slack_sdk import WebClient

_SECRET_ID_ENV = "TRIAGE_SLACK_SECRET_ID"  # noqa: S105  (env var name, not a secret value)

_client: WebClient | None = None
_lock = Lock()


def _secrets_client() -> Any:
    return boto3.client(
        "secretsmanager",
        config=Config(
            region_name=os.environ.get("AWS_REGION", "us-east-1"),
            user_agent_extra="triage-mcp-server/0.1.0",
            retries={"mode": "standard", "max_attempts": 3},
        ),
    )


def _load_bot_token() -> str:
    secret_id = os.environ.get(_SECRET_ID_ENV)
    if not secret_id:
        raise RuntimeError(f"{_SECRET_ID_ENV} is unset; Slack tool cannot resolve a bot token")
    response = _secrets_client().get_secret_value(SecretId=secret_id)
    payload = json.loads(response["SecretString"])
    token = payload.get("bot_token")
    if not isinstance(token, str) or not token.startswith("xoxb-"):
        raise RuntimeError(f"Secret {secret_id} does not contain a valid bot_token (xoxb-…)")
    return token


def get_slack_client() -> WebClient:
    """Return a process-cached Slack WebClient."""
    global _client
    if _client is not None:
        return _client
    with _lock:
        if _client is None:
            _client = WebClient(token=_load_bot_token())
    return _client


def _reset_for_tests() -> None:
    """Drop the cached client. Tests only."""
    global _client
    with _lock:
        _client = None

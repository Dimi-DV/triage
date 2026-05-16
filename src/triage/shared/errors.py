"""Namespace-scoped error envelope for MCP tools.

Tool implementations wrap botocore exceptions into the namespace error type
so callers see a consistent shape regardless of the underlying AWS service.
"""

from __future__ import annotations

from typing import Any

from botocore.exceptions import BotoCoreError, ClientError


class ToolError(Exception):
    """Base error for all MCP tool failures."""

    def __init__(
        self, message: str, *, code: str = "ToolError", details: dict[str, Any] | None = None
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.details = details or {}

    def to_dict(self) -> dict[str, Any]:
        return {"error": self.code, "message": self.message, "details": self.details}


class MetricsApiError(ToolError):
    """metrics-api namespace error."""


class LogsApiError(ToolError):
    """logs-api namespace error."""


class EcsApiError(ToolError):
    """ecs-api namespace error."""


class RunbooksApiError(ToolError):
    """runbooks-api namespace error."""


def wrap_boto_error(exc: BaseException, namespace_error_cls: type[ToolError]) -> ToolError:
    """Map a botocore exception to the caller's namespace error type.

    Preserves the AWS error code and operation name when available; everything
    else lands in `details` so the agent can reason about it without parsing
    free-text messages.
    """
    if isinstance(exc, ClientError):
        response_error = exc.response.get("Error", {}) if exc.response else {}
        code = str(response_error.get("Code", "ClientError"))
        message = str(response_error.get("Message", str(exc)))
        operation = getattr(exc, "operation_name", None)
        details: dict[str, Any] = {"aws_error_code": code}
        if operation:
            details["operation"] = operation
        return namespace_error_cls(message, code=code, details=details)
    if isinstance(exc, BotoCoreError):
        return namespace_error_cls(str(exc), code="BotoCoreError")
    return namespace_error_cls(str(exc), code=exc.__class__.__name__)


def wrap_slack_error(exc: BaseException, namespace_error_cls: type[ToolError]) -> ToolError:
    """Map a slack_sdk.errors.SlackApiError to the caller's namespace error type.

    Imports `SlackApiError` lazily so this module stays useful in contexts that
    do not have slack-sdk installed (e.g. the Lambda alarm-bridge package).
    """
    from slack_sdk.errors import SlackApiError

    if isinstance(exc, SlackApiError):
        response = exc.response or {}
        code = str(response.get("error", "SlackApiError"))
        method = getattr(response, "api_url", None) or response.get("method")
        details: dict[str, Any] = {"slack_error": code}
        if method:
            details["api_url"] = str(method)
        return namespace_error_cls(str(exc), code=code, details=details)
    return namespace_error_cls(str(exc), code=exc.__class__.__name__)

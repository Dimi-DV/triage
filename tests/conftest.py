"""Shared pytest fixtures for the triage test suite."""

from __future__ import annotations

import os
from collections.abc import Iterator
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
        InMemorySpanExporter,
    )


@pytest.fixture
def aws_credentials_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make boto3 unable to find real credentials, so moto's are picked up."""
    for k in (
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
        "AWS_DEFAULT_REGION",
        "AWS_REGION",
    ):
        monkeypatch.setenv(k, "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.setenv("AWS_REGION", "us-east-1")


@pytest.fixture
def moto_cloudwatch(aws_credentials_env: None) -> Iterator[Any]:
    """Yield a moto-mocked CloudWatch client bound to us-east-1."""
    from moto import mock_aws

    with mock_aws():
        import boto3

        client = boto3.client("cloudwatch", region_name="us-east-1")
        yield client


@pytest.fixture
def otel_in_memory_exporter() -> Iterator[InMemorySpanExporter]:
    """Install an in-memory OTel exporter and yield it for assertions."""
    from triage.shared.otel import install_in_memory_exporter

    exporter = install_in_memory_exporter()
    try:
        yield exporter
    finally:
        exporter.clear()


# Silence OTel default exporter during tests unless a test explicitly opts in.
os.environ.setdefault("OTEL_TRACES_EXPORTER", "none")

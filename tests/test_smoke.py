"""Smoke test — keeps pytest from exiting 5 (no tests collected) until the
MCP server lands on Day 34 and real unit tests start arriving."""

import sys

import pytest


@pytest.mark.unit
def test_python_at_least_3_12() -> None:
    """Project pins Python 3.12 in .python-version; CI uses the same."""
    assert sys.version_info >= (3, 12)

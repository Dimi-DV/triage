"""Unit tests for runbooks_api_lookup_runbook."""

from __future__ import annotations

from pathlib import Path

import pytest

from triage.mcp_server.runbooks_api.lookup_runbook import (
    runbooks_api_lookup_runbook,
)
from triage.shared.errors import RunbooksApiError

_RUNBOOK_A = """\
# Sample alarm A

**Alarm trigger:** alpha-alarm
**Owner:** Triage
**Last reviewed:** 2026-05-20

## Prerequisites

- something

## Steps

1. inspect
2. diagnose

## Rollback

1. nothing to roll back

## Escalation

- Page #all-triage
"""

_RUNBOOK_MULTI = """\
# Sample alarm B+C

**Alarm trigger:** bravo-alarm, charlie-alarm
**Owner:** Triage
**Last reviewed:** 2026-05-20

## Prerequisites

- multi-trigger

## Steps

1. step one

## Rollback

1. n/a

## Escalation

- Page oncall
"""


@pytest.fixture
def runbook_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("TRIAGE_RUNBOOKS_DIR", str(tmp_path))
    (tmp_path / "alpha.md").write_text(_RUNBOOK_A, encoding="utf-8")
    (tmp_path / "bravo-charlie.md").write_text(_RUNBOOK_MULTI, encoding="utf-8")
    return tmp_path


@pytest.mark.unit
def test_lookup_runbook_hit_returns_parsed_sections(runbook_dir: Path) -> None:
    result = runbooks_api_lookup_runbook(alarm_name="alpha-alarm")

    assert result["found"] is True
    assert result["alarm_name"] == "alpha-alarm"
    assert result["slug"] == "alpha"
    assert "## Steps" in result["content"]
    sections = result["sections"]
    assert "inspect" in sections["steps"]
    assert "diagnose" in sections["steps"]
    assert "something" in sections["prerequisites"]
    assert "nothing to roll back" in sections["rollback"]
    assert "Page #all-triage" in sections["escalation"]


@pytest.mark.unit
def test_lookup_runbook_miss_returns_available_runbooks(runbook_dir: Path) -> None:
    result = runbooks_api_lookup_runbook(alarm_name="not-a-real-alarm")

    assert result["found"] is False
    assert result["alarm_name"] == "not-a-real-alarm"
    assert sorted(result["available_runbooks"]) == [
        "alpha-alarm",
        "bravo-alarm",
        "charlie-alarm",
    ]


@pytest.mark.unit
def test_lookup_runbook_supports_comma_separated_triggers(runbook_dir: Path) -> None:
    bravo = runbooks_api_lookup_runbook(alarm_name="bravo-alarm")
    charlie = runbooks_api_lookup_runbook(alarm_name="charlie-alarm")

    assert bravo["found"] is True
    assert charlie["found"] is True
    assert bravo["slug"] == "bravo-charlie"
    assert charlie["slug"] == "bravo-charlie"
    # Both triggers resolve to the same file content.
    assert bravo["content"] == charlie["content"]


@pytest.mark.unit
def test_lookup_runbook_match_is_case_sensitive(runbook_dir: Path) -> None:
    result = runbooks_api_lookup_runbook(alarm_name="ALPHA-ALARM")
    assert result["found"] is False


@pytest.mark.unit
def test_lookup_runbook_missing_dir_returns_miss(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TRIAGE_RUNBOOKS_DIR", str(tmp_path / "does-not-exist"))

    result = runbooks_api_lookup_runbook(alarm_name="anything")
    assert result["found"] is False
    assert result["available_runbooks"] == []


@pytest.mark.unit
def test_lookup_runbook_duplicate_trigger_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TRIAGE_RUNBOOKS_DIR", str(tmp_path))
    (tmp_path / "one.md").write_text(_RUNBOOK_A, encoding="utf-8")
    # Second file declares the same trigger as alpha.md — that's a bug at
    # author time and the tool should refuse to index instead of silently
    # picking one.
    (tmp_path / "two.md").write_text(
        _RUNBOOK_A.replace("Sample alarm A", "Different runbook"), encoding="utf-8"
    )

    with pytest.raises(RunbooksApiError) as exc_info:
        runbooks_api_lookup_runbook(alarm_name="alpha-alarm")
    assert exc_info.value.code == "DuplicateAlarmTrigger"


@pytest.mark.unit
def test_lookup_runbook_resolves_the_three_real_runbooks() -> None:
    """End-to-end sanity check against the runbooks/ dir checked into the repo.

    Confirms the lookup tool finds the three runbooks shipped with v4 of the
    AGENT.md split. If a runbook file is renamed or its **Alarm trigger:**
    field drifts from the scenario YAMLs, this test catches it.
    """
    repo_root = Path(__file__).resolve().parents[4]
    runbooks_dir = repo_root / "runbooks"
    if not runbooks_dir.is_dir():
        pytest.skip("runbooks/ not present in this checkout")

    import os

    os.environ.pop("TRIAGE_RUNBOOKS_DIR", None)
    os.environ["TRIAGE_RUNBOOKS_DIR"] = str(runbooks_dir)
    try:
        for alarm_name, expected_slug in [
            ("dev-triage-broken-tg-unhealthy", "target-group-port-mismatch"),
            ("dev-triage-broken-env-tg-unhealthy", "missing-env-var"),
            ("dev-triage-az-victim-tg-unhealthy", "az-slowdown"),
        ]:
            result = runbooks_api_lookup_runbook(alarm_name=alarm_name)
            assert result["found"] is True, alarm_name
            assert result["slug"] == expected_slug, alarm_name
            assert result["sections"].get("steps"), alarm_name
    finally:
        os.environ.pop("TRIAGE_RUNBOOKS_DIR", None)

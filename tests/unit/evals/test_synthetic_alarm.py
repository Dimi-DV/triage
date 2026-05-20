"""Unit tests for the YAML-driven synthetic-alarm path in evals.run_evals.

These tests pin the contract that scenarios drive their own alarm shape
through `alarm_payload_type` + `alarm_name` + `target_resource` fields,
with `_PAYLOAD_BUILDERS` resolving the right builder. They cover both
the registry dispatch and the default-on-missing behavior so future
scenarios that opt into a new payload type don't silently fall through.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest
from evals.run_evals import _PAYLOAD_BUILDERS, _synthetic_alarm_for


@pytest.mark.unit
def test_payload_registry_has_default_builder() -> None:
    assert "unhealthy_host_count" in _PAYLOAD_BUILDERS


@pytest.mark.unit
def test_synthetic_alarm_uses_yaml_fields_for_unhealthy_host_count() -> None:
    """Confirms `_unhealthy_host_payload` is invoked with the YAML's
    alarm_name + target_resource. Mocks the live elbv2 dimension lookup
    so we don't hit AWS."""
    scenario = {
        "name": "stub-scenario",
        "alarm_payload_type": "unhealthy_host_count",
        "alarm_name": "stub-alarm-name",
        "target_resource": "stub-tg-name",
    }

    with patch("evals.run_evals._resolve_dimension_values") as fake_resolve:
        fake_resolve.return_value = (
            "targetgroup/stub-tg-name/abc123",
            "app/test-lb/xyz",
            "999111222333",
        )
        payload = _synthetic_alarm_for(scenario, region="us-east-1")
        fake_resolve.assert_called_once_with("stub-tg-name", "us-east-1")

    alarm = payload["alarm"]
    assert alarm["AlarmName"] == "stub-alarm-name"
    assert alarm["AWSAccountId"] == "999111222333"
    assert alarm["Trigger"]["MetricName"] == "UnHealthyHostCount"
    tg_dim = next(d for d in alarm["Trigger"]["Dimensions"] if d["name"] == "TargetGroup")
    assert tg_dim["value"] == "targetgroup/stub-tg-name/abc123"


@pytest.mark.unit
def test_synthetic_alarm_defaults_to_unhealthy_host_count() -> None:
    """Scenarios without `alarm_payload_type:` fall back to the default
    builder for backwards compat. (All three current YAMLs declare the
    field explicitly, but future scenarios may not bother.)"""
    scenario = {
        "name": "stub-no-type",
        "alarm_name": "stub-alarm-name",
        "target_resource": "stub-tg-name",
    }

    with patch("evals.run_evals._resolve_dimension_values") as fake_resolve:
        fake_resolve.return_value = ("targetgroup/x/y", "app/z/w", "999")
        payload = _synthetic_alarm_for(scenario, region="us-east-1")
    assert payload["alarm"]["AlarmName"] == "stub-alarm-name"


@pytest.mark.unit
def test_synthetic_alarm_raises_for_unknown_payload_type() -> None:
    """An unrecognized `alarm_payload_type` must surface as a clear
    NotImplementedError so the scenario author knows to add a builder,
    rather than silently constructing a wrong-shaped payload."""
    scenario: dict[str, Any] = {
        "name": "stub-bad-type",
        "alarm_payload_type": "this_type_does_not_exist",
        "alarm_name": "x",
        "target_resource": "y",
    }
    with pytest.raises(NotImplementedError) as exc_info:
        _synthetic_alarm_for(scenario, region="us-east-1")
    assert "this_type_does_not_exist" in str(exc_info.value)


@pytest.mark.unit
@pytest.mark.parametrize(
    "scenario_slug,expected_alarm,expected_resource",
    [
        ("01-target-group-port-mismatch", "dev-triage-broken-tg-unhealthy", "dev-triage-broken-tg"),
        ("02-missing-env-var", "dev-triage-broken-env-tg-unhealthy", "dev-triage-broken-env-tg"),
        ("03-az-slowdown", "dev-triage-az-victim-tg-unhealthy", "dev-triage-az-victim-tg"),
    ],
)
def test_existing_scenarios_carry_alarm_metadata(
    scenario_slug: str, expected_alarm: str, expected_resource: str
) -> None:
    """The three shipped scenarios must declare alarm_name + target_resource
    in their YAML; if anyone edits them to drop the fields, this catches it."""
    import pathlib

    import yaml

    repo_root = pathlib.Path(__file__).resolve().parents[3]
    yaml_path = repo_root / "evals" / "scenarios" / f"{scenario_slug}.yaml"
    scenario = yaml.safe_load(yaml_path.read_text())
    assert scenario.get("alarm_name") == expected_alarm
    assert scenario.get("target_resource") == expected_resource
    assert scenario.get("runbook_status") in ("shipped", "planned", "by_design_none")

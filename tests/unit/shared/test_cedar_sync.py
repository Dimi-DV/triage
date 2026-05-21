"""Tests for the Cedar sync helpers used by scripts/provision_agentcore.py.

The sync target is the AgentCore Policy Engine (not Verified Permissions —
see feedback_cedar_policy_engine_config_lives memory for the false start).
"""

from __future__ import annotations

import pathlib
from typing import Any

import pytest

from triage.shared.cedar_sync import (
    iam_role_arn_to_sts_assumed_role_arn,
    load_cedar_policies,
    sync_cedar_policies,
)


class _FakePaginator:
    def __init__(self, pages: list[dict[str, Any]]) -> None:
        self._pages = pages

    def paginate(self, **_: Any) -> list[dict[str, Any]]:
        return list(self._pages)


class _FakeAgentCore:
    """Minimal stand-in for the bedrock-agentcore-control boto3 client.

    Records every mutating call so the test can assert the create / update /
    delete pattern. `list_policies` returns whatever the test seeded.
    """

    def __init__(self, existing: list[dict[str, Any]] | None = None) -> None:
        self.existing = existing or []
        self.created: list[dict[str, Any]] = []
        self.updated: list[dict[str, Any]] = []
        self.deleted: list[dict[str, Any]] = []

    def get_paginator(self, name: str) -> _FakePaginator:
        assert name == "list_policies"
        return _FakePaginator([{"policies": self.existing}])

    def create_policy(self, **kwargs: Any) -> dict[str, Any]:
        self.created.append(kwargs)
        return {"policyId": f"new-{len(self.created)}"}

    def update_policy(self, **kwargs: Any) -> dict[str, Any]:
        self.updated.append(kwargs)
        return {}

    def delete_policy(self, **kwargs: Any) -> dict[str, Any]:
        self.deleted.append(kwargs)
        return {}


@pytest.mark.unit
def test_load_cedar_policies_splits_on_id_annotation(tmp_path: pathlib.Path) -> None:
    (tmp_path / "agent-tools.cedar").write_text(
        '@id("permit-read")\npermit (principal, action, resource);\n\n'
        '@id("permit-write")\npermit (principal, action, resource) when { context.severity == "info" };\n'
    )
    policies = load_cedar_policies(tmp_path)
    names = [n for n, _ in policies]
    assert names == ["permit-read", "permit-write"]
    statements = dict(policies)
    assert statements["permit-read"].startswith('@id("permit-read")')
    assert "permit (principal, action, resource);" in statements["permit-read"]
    assert "context.severity" in statements["permit-write"]


@pytest.mark.unit
def test_load_cedar_policies_skips_files_without_id_annotation(
    tmp_path: pathlib.Path,
) -> None:
    (tmp_path / "agent-tools.cedar").write_text("permit (principal, action, resource);\n")
    assert load_cedar_policies(tmp_path) == []


_GW_ARN = "arn:aws:bedrock-agentcore:us-east-1:111:gateway/triagemcpgateway-abc"
_PRINCIPAL_ARN = "arn:aws:sts::111:assumed-role/dev-triage-agent-runtime"


def _write_templated_policy(tmp_path: pathlib.Path) -> None:
    (tmp_path / "agent-tools.cedar").write_text(
        '@id("permit_read")\npermit (\n'
        '    principal == AgentCore::IamEntity::"__AGENT_PRINCIPAL_ARN__",\n'
        "    action,\n"
        '    resource == AgentCore::Gateway::"__GATEWAY_ARN__"\n'
        ");\n"
    )


@pytest.mark.unit
def test_iam_to_sts_arn_translation() -> None:
    iam = "arn:aws:iam::042729137214:role/dev-triage-agent-runtime"
    sts = iam_role_arn_to_sts_assumed_role_arn(iam)
    assert sts == "arn:aws:sts::042729137214:assumed-role/dev-triage-agent-runtime"


@pytest.mark.unit
def test_iam_to_sts_arn_rejects_non_role_arn() -> None:
    with pytest.raises(ValueError, match="Not an IAM role ARN"):
        iam_role_arn_to_sts_assumed_role_arn("arn:aws:iam::042729137214:user/dimi")
    with pytest.raises(ValueError, match="Not an IAM role ARN"):
        iam_role_arn_to_sts_assumed_role_arn("not-an-arn")


@pytest.mark.unit
def test_load_substitutes_both_sentinels(tmp_path: pathlib.Path) -> None:
    _write_templated_policy(tmp_path)
    policies = load_cedar_policies(
        tmp_path, gateway_arn=_GW_ARN, agent_principal_arn=_PRINCIPAL_ARN
    )
    assert len(policies) == 1
    _, statement = policies[0]
    assert _GW_ARN in statement
    assert _PRINCIPAL_ARN in statement
    assert "__GATEWAY_ARN__" not in statement
    assert "__AGENT_PRINCIPAL_ARN__" not in statement


@pytest.mark.unit
def test_sync_creates_repo_only_policies(tmp_path: pathlib.Path) -> None:
    _write_templated_policy(tmp_path)

    ac = _FakeAgentCore(existing=[])
    sync_cedar_policies(ac, "pe-1", tmp_path, _GW_ARN, _PRINCIPAL_ARN)

    assert len(ac.created) == 1
    assert ac.created[0]["name"] == "permit_read"
    assert ac.created[0]["policyEngineId"] == "pe-1"
    stmt = ac.created[0]["definition"]["cedar"]["statement"]
    assert _GW_ARN in stmt
    assert _PRINCIPAL_ARN in stmt
    assert "__GATEWAY_ARN__" not in stmt
    assert "__AGENT_PRINCIPAL_ARN__" not in stmt
    assert ac.updated == []
    assert ac.deleted == []


@pytest.mark.unit
def test_sync_updates_matching_name(tmp_path: pathlib.Path) -> None:
    _write_templated_policy(tmp_path)

    ac = _FakeAgentCore(existing=[{"policyId": "existing-1", "name": "permit_read"}])
    sync_cedar_policies(ac, "pe-1", tmp_path, _GW_ARN, _PRINCIPAL_ARN)

    assert ac.created == []
    assert len(ac.updated) == 1
    assert ac.updated[0]["policyId"] == "existing-1"
    assert ac.updated[0]["policyEngineId"] == "pe-1"
    assert ac.deleted == []


@pytest.mark.unit
def test_sync_deletes_engine_only_policies(tmp_path: pathlib.Path) -> None:
    _write_templated_policy(tmp_path)

    ac = _FakeAgentCore(
        existing=[
            {"policyId": "existing-1", "name": "permit_read"},
            {"policyId": "existing-2", "name": "permit_removed"},
        ]
    )
    sync_cedar_policies(ac, "pe-1", tmp_path, _GW_ARN, _PRINCIPAL_ARN)

    assert ac.created == []
    assert len(ac.updated) == 1
    assert ac.updated[0]["policyId"] == "existing-1"
    assert len(ac.deleted) == 1
    assert ac.deleted[0]["policyId"] == "existing-2"


@pytest.mark.unit
def test_sync_ignores_existing_policies_without_name(tmp_path: pathlib.Path) -> None:
    _write_templated_policy(tmp_path)

    # No name on the existing record — treat as if it isn't there for diffing
    # (would have to be cleaned up out-of-band).
    ac = _FakeAgentCore(existing=[{"policyId": "legacy", "name": ""}])
    sync_cedar_policies(ac, "pe-1", tmp_path, _GW_ARN, _PRINCIPAL_ARN)

    assert len(ac.created) == 1
    assert ac.deleted == []

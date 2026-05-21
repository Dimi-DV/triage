"""Sync Cedar policies from the repo into an AgentCore Policy Engine.

The repo's `cedar-policies/*.cedar` files are the source of truth.
`scripts/provision_agentcore.py` calls `sync_cedar_policies` so the policy
engine mirrors the files in this commit; the AgentCore Gateway then
evaluates Cedar via `policyEngineConfiguration` pointing at that engine.

API surface: bedrock-agentcore-control's `CreatePolicy` / `UpdatePolicy` /
`DeletePolicy` / `ListPolicies`. Each policy is a `cedar.statement`. There is
no PutSchema operation — the policy engine does not require a separate
schema; entity types referenced in `Triage::…` are validated lazily against
whatever `validationMode` we set (default lets unspecified types through).

Verified Permissions was NOT the right primitive for this gate; an earlier
attempt threaded `aws_verifiedpermissions_policy_store` into
`update_gateway(policyEngineConfiguration.arn)` and was rejected with a
regex error — that ARN must be `arn:aws:bedrock-agentcore:…:policy-engine/…`
(probed 2026-05-21). See `feedback_cedar_policy_engine_config_lives`.

Idempotent: matched by the `@id("…")` annotation (becomes the policy `name`
in AgentCore); present-in-both pairs are updated, repo-only entries are
created, engine-only entries are deleted (so removing a `permit` block from
the repo and re-running actually revokes it).
"""

from __future__ import annotations

import logging
import pathlib
import re
from typing import Any

CEDAR_ID_RE = re.compile(r'^\s*@id\("([^"]+)"\)\s*$', re.MULTILINE)

log = logging.getLogger("triage.cedar_sync")


GATEWAY_ARN_SENTINEL = "__GATEWAY_ARN__"
AGENT_PRINCIPAL_ARN_SENTINEL = "__AGENT_PRINCIPAL_ARN__"


def iam_role_arn_to_sts_assumed_role_arn(iam_role_arn: str) -> str:
    """Translate `arn:aws:iam::ACCOUNT:role/NAME` → `arn:aws:sts::ACCOUNT:assumed-role/NAME`.

    AgentCore's Cedar `AgentCore::IamEntity` ids use the STS assumed-role
    form, not the underlying IAM-role form (verified per the AWS docs on
    IAM principal matching). The session-name suffix is omitted — exact
    `==` matching is against the stripped form, and `like` patterns can
    add `/*` explicitly if a session match is wanted.
    """
    if ":role/" not in iam_role_arn or ":iam::" not in iam_role_arn:
        raise ValueError(f"Not an IAM role ARN: {iam_role_arn!r}")
    return iam_role_arn.replace(":iam::", ":sts::", 1).replace(":role/", ":assumed-role/", 1)


def load_cedar_policies(
    policy_dir: pathlib.Path,
    gateway_arn: str | None = None,
    agent_principal_arn: str | None = None,
) -> list[tuple[str, str]]:
    """Parse every *.cedar file in policy_dir into (name, statement) pairs.

    Each policy must be preceded by an `@id("name")` annotation. The
    statement returned is the raw Cedar text starting at the annotation,
    suitable for `CreatePolicy.definition.cedar.statement`.

    Two sentinels are substituted when their corresponding arg is non-None:
    `__GATEWAY_ARN__` → gateway_arn (AgentCore Cedar rejects wildcard
    resources, so production sync must always pass this);
    `__AGENT_PRINCIPAL_ARN__` → agent_principal_arn (the Triage agent's
    STS assumed-role ARN). Tests can omit either to inspect raw text.
    """
    policies: list[tuple[str, str]] = []
    for path in sorted(policy_dir.glob("*.cedar")):
        text = path.read_text()
        if gateway_arn is not None:
            text = text.replace(GATEWAY_ARN_SENTINEL, gateway_arn)
        if agent_principal_arn is not None:
            text = text.replace(AGENT_PRINCIPAL_ARN_SENTINEL, agent_principal_arn)
        matches = list(CEDAR_ID_RE.finditer(text))
        if not matches:
            log.warning("Cedar file %s has no @id-annotated policies; skipping", path)
            continue
        for i, m in enumerate(matches):
            name = m.group(1)
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            statement = text[m.start() : end].strip()
            policies.append((name, statement))
    return policies


def sync_cedar_policies(
    ac_client: Any,
    policy_engine_id: str,
    policy_dir: pathlib.Path,
    gateway_arn: str,
    agent_principal_arn: str,
) -> None:
    """Push the policies in policy_dir to the AgentCore Policy Engine.

    Existing policies whose top-level `name` matches a repo entry are
    updated; repo-only entries are created; engine-only entries are deleted.
    `gateway_arn` and `agent_principal_arn` are substituted into the
    matching sentinels in the policy text — AgentCore's schema requires a
    concrete Gateway ARN as the resource scope and works best with an
    exact-match `AgentCore::IamEntity` principal (per AWS's "IAM: Using
    IAM role ARNs" common pattern).
    """
    desired = dict(
        load_cedar_policies(
            policy_dir,
            gateway_arn=gateway_arn,
            agent_principal_arn=agent_principal_arn,
        )
    )
    log.info("Repo Cedar policies: %s", sorted(desired))

    existing: dict[str, str] = {}
    paginator = ac_client.get_paginator("list_policies")
    for page in paginator.paginate(policyEngineId=policy_engine_id):
        for item in page.get("policies", []):
            name = item.get("name") or ""
            if name:
                existing[name] = item["policyId"]

    # The Cedar analyzer's default `FAIL_ON_ANY_FINDINGS` mode rejects
    # deliberately-broad permits ("Overly Permissive: …") even when the
    # broad scope is intentional (e.g. always-permit on a read-only tool).
    # Switching to `IGNORE_ALL_FINDINGS` skips the static analyzer; we rely
    # on the LOG_ONLY → ENFORCE runtime flow to catch real authorization
    # issues. Genuine path typos (e.g. `context.input.foo` instead of
    # `context.input.message.foo`) still surface via the smoke step before
    # ENFORCE, because evaluator failures show up in the LOG_ONLY traces.
    for name, statement in desired.items():
        definition = {"cedar": {"statement": statement}}
        if name in existing:
            log.info("UpdatePolicy %s (policyId=%s)", name, existing[name])
            ac_client.update_policy(
                policyEngineId=policy_engine_id,
                policyId=existing[name],
                definition=definition,
                validationMode="IGNORE_ALL_FINDINGS",
            )
        else:
            log.info("CreatePolicy %s", name)
            ac_client.create_policy(
                policyEngineId=policy_engine_id,
                name=name,
                definition=definition,
                validationMode="IGNORE_ALL_FINDINGS",
            )

    for name, policy_id in existing.items():
        if name not in desired:
            log.info("DeletePolicy %s (policyId=%s) — no longer in repo", name, policy_id)
            ac_client.delete_policy(policyEngineId=policy_engine_id, policyId=policy_id)

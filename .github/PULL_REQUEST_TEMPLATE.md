## Summary

<!-- 1-3 sentences: what changed and why -->

## Scope

<!-- Tick all that apply -->

- [ ] Python code (`src/`)
- [ ] Tests (`tests/`)
- [ ] Terraform (`terraform/`)
- [ ] Cedar policies (`cedar-policies/`)
- [ ] FIS templates (`fis-templates/`)
- [ ] MCP server tools
- [ ] Agent configuration / system prompt
- [ ] Eval scenarios / ground truth
- [ ] Documentation
- [ ] Claude Code config (`.claude/`, `CLAUDE.md`)
- [ ] CI / repo hygiene

## Decision-level change?

- [ ] No — implementation detail only
- [ ] Yes — also updated `docs/architecture-references/triage-decision-doc-v2.md` Section 11 and added/updated an ADR in `docs/adr/`

## Pre-merge checklist

- [ ] `make check` passes locally (lint, format, typecheck, test)
- [ ] If Terraform changed: `make tf-validate` passes
- [ ] If MCP tool added: tool lives in one of the four namespaces (ecs-api, logs-api, metrics-api, runbooks-api)
- [ ] If write-action tool added: corresponding Cedar policy in `cedar-policies/` AND audit-log emission added
- [ ] If system prompt or skill changed: ran `make eval` and reviewed scores
- [ ] CHANGELOG.md updated under `[Unreleased]`

## Notes for reviewer

<!-- Anything tricky, follow-ups, design alternatives considered -->

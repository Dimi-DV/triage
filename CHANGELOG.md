# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Decision-level changes also tracked in [`docs/architecture-references/triage-decision-doc-v2.md`](docs/architecture-references/triage-decision-doc-v2.md), Section 11.

## [Unreleased]

### Added
- Initial repository scaffold (May 13, 2026)
- CLAUDE.md project constitution + three Claude Code hooks (secrets-scan, terraform-apply-gate, terraform-fmt)
- Architecture decision doc v2.1 + nine reference notes in `docs/architecture-references/`
- Python toolchain: `uv` + `ruff` + `mypy` + `pytest` configured via `pyproject.toml`
- Pre-commit hooks for code quality + secrets detection
- GitHub Actions CI (lint, typecheck, test, Terraform fmt+validate)
- Dependabot config for weekly dependency updates
- MIT license

## [0.0.1] — 2026-05-13

### Added
- Project scaffolded as Day 30 evening prep for the Days 31–36 Triage sprint
- Project goal: AIOps incident response agent on Bedrock AgentCore + custom MCP server + outage corpus + AgentCore Evaluations harness

[Unreleased]: https://github.com/Dimi-DV/triage/compare/v0.0.1...HEAD
[0.0.1]: https://github.com/Dimi-DV/triage/releases/tag/v0.0.1

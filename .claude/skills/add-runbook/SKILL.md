---
name: add-runbook
description: Generate a runbook in runbooks/ using the parseable structure (alarm trigger, prereqs, numbered steps, rollback, escalation) so the runbooks-api MCP namespace can surface it to the agent by alarm type.
---

# /add-runbook

Add a new operational runbook in the parseable structure.

## When to invoke

Adding to the procedural knowledge surfaced by `runbooks_api/*` (skill tier 2 — user-defined skills per the AWS DevOps Agent architecture). The structure must be parseable — the MCP tool reads these files and returns relevant sections to the agent by alarm name.

## Inputs to collect

1. **Title** — what the runbook is for (e.g. "RDS connection pool exhaustion").
2. **Alarm trigger** — exact CloudWatch alarm name(s) this runbook addresses. Used as the lookup key. Comma-separated if multiple.
3. **Owner** — team or individual responsible.
4. **Prerequisites** — preconditions that must hold before executing.
5. **Steps** — numbered operator actions.
6. **Rollback** — how to undo if a step fails.
7. **Escalation** — who/what to page if the runbook doesn't resolve the issue.

## Scaffold

Create **`runbooks/<slug>.md`** (slug is kebab-case from the title) with this exact section structure. The parser keys off the H2 headers — don't rename them.

````markdown
# <Title>

**Alarm trigger:** <exact CloudWatch alarm name(s), comma-separated>
**Owner:** <team or individual>
**Last reviewed:** <YYYY-MM-DD>

## Prerequisites

- <bullet list of preconditions>

## Steps

1. <step 1>
2. <step 2>
3. ...

## Rollback

1. <how to revert step 1 if it fails>
2. ...

## Escalation

- Page <on-call rotation or team>
- Link: <internal ticket / Slack channel>
````

## Hard rules to enforce

- **All five sections present** even if some are placeholders. `runbooks_api` parses by section header — missing sections break the lookup.
- **H2 (`##`) for section headers exactly.** Not H1, not H3. The parser is keyed to `##`.
- **Alarm trigger field is the exact CloudWatch alarm name(s).** Case-sensitive. This is the lookup key.
- **One runbook per file.** Don't combine multiple procedures — separate alarm triggers want separate files.
- **Steps are numbered, not bulleted.** Order matters for the parser to surface "the next step."

## References

- Decision doc §3.6 (skill tier 2 — user-defined skills)
- `docs/architecture-references/aws-devops-agent-architecture-molumuri-2026-03.md` — runbooks as one of three skill tiers

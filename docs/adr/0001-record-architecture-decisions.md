# 0001 — Record architecture decisions

**Status:** Accepted
**Date:** 2026-05-13
**Deciders:** Dimitrije

## Context

The Triage has architectural reasoning distributed across a long decision doc ([v2.1](../architecture-references/triage-decision-doc-v2.md), 24+ decisions in Section 11). That document is the authoritative spec, but it's not optimized for skimming — a future reader (or future me) reviewing a specific design choice has to navigate a long file to find the relevant rationale.

Architecture Decision Records (ADRs), as described by Michael Nygard in 2011, are a complementary pattern: one short markdown file per decision, recording context / options / consequences. By 2026 they're a widely-adopted industry standard for documenting non-obvious choices in a way that's durable and skimmable.

## Decision

Record significant architecture decisions as ADRs in `docs/adr/`, using the [Nygard template](template.md).

The full decision-log table in Triage decision doc remains the authoritative reference. ADRs are the narrative complement — one focused decision per file. Specifically:

1. Decisions made before the ADR collection existed are backfilled by extracting from decision doc Section 11 (ADRs 0002–0007)
2. New decisions made during the sprint get a fresh ADR
3. When a decision is revised, write a *new* ADR and mark the old one's status as "Superseded by ADR-NNNN"
4. ADR numbers are never reused; even superseded ADRs stay in the directory for historical record

## Consequences

**Positive:**
- A new reader can skim 7 short files instead of one long decision-log table
- Future-me can find the rationale for a specific choice without re-deriving it
- Industry-standard pattern that signals familiarity with software architecture conventions
- Pairs naturally with the CHANGELOG entry for any decision-level change

**Negative:**
- Modest duplication: decisions are recorded both in the decision doc and as ADRs. Mitigation: the decision doc is the spec; ADRs are commentary on it
- Adds a small step to the workflow when a decision is made (write the ADR)

**Neutral:**
- Each PR with a decision-level change must update both the decision doc Section 11 and add/update an ADR. The PR template includes a checkbox for this.

## References

- Nygard, "Documenting Architecture Decisions," 2011
- [`docs/architecture-references/triage-decision-doc-v2.md`](../architecture-references/triage-decision-doc-v2.md) — canonical spec

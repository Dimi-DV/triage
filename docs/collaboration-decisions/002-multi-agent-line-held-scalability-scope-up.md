# 002 — I held the line on multi-agent introspection; forced max-scope on corpus-readiness

**Date:** 2026-05-20, Day 36 Hour 12-14
**Triggering commits:** `7060fff` (runbooks-api split — the previous session's directive shipped) → `1a396f3` (MAST classifier wired) → `6491cd7` (corpus-readiness pass — the session's load-bearing scope decision)

## The session shape

This session was less about catching Claude going off-spec and more about steering scope and pinning architectural lines as we went. Three decision points; all three would have shipped differently if I hadn't pushed.

## Moment 1 — I caught the implicit multi-agent suggestion in Claude's automation pitch

After the rollup script was sketched, Claude proposed a 150-LOC variant that would *"automate ~70% of each scenario-runs/<slug>.md narrative section."* When I asked what would still need a human, Claude's list was *"Notable observations,"* the `Fix vN → vN+1` reasoning, and the cross-run analysis. Those are the parts Claude itself had been writing in the existing scenario-runs files. I asked:

> The human observations you mentioned are actually opus 4.7 observations. This might tie into agents learning from agents and offering suggestions. Should we maybe wire a new agent to handle this?

That question forced explicit a multi-agent suggestion that was hiding in Claude's framing. Until I asked, the proposal read as "automate the writing"; once asked, it had to be defended as "wire an agent to interpret another agent's runs." Claude walked it back with three risks named (railroad reintroduction via the back door, signal redundancy with MAST classifier, contradicting the spec §3.10 single-agent restraint). I agreed and we held the line.

**What would have shipped without my question:** the 150-LOC drafter would have landed in this commit, the §3.10 restraint framing would have been quietly violated, and the next interview question (*"how do you keep the eval from being a tautology?"*) would have been harder to answer cleanly.

## Moment 2 — I overrode Claude's conservative scope on a scalability principle

After the multi-agent question was settled, Claude offered three scopes for the corpus-readiness work: rollup-only (~80 LOC), rollup + Fix A + Fix C (~120 LOC, recommended), or rollup + A + B + C + D (~200 LOC). Claude marked the middle option as "recommended" because Fix B (alarm-payload-type registry) required *"committing to a payload-type design without seeing the specific scenarios yet."*

I went max scope with:

> I might be wrong but I don't see a massive downside to you doing all those fixes now especially with the important context you have. Scalability with future additions of scenarios is very important. hardcoding them is bad practice

That principled override — *scalability is a design principle, not a per-scenario decision* — is what produced commit `6491cd7`. Result: `_SCENARIO_ALARMS` hardcoded dict deleted (Fix A), `_PAYLOAD_BUILDERS` registry shipped (Fix B), `add-outage-scenario` skill scaffold refreshed (Fix C), `runbook_status:` YAML field added (Bonus D). Next session's 5-6-scenario batch will absorb into the harness with zero Python edits per scenario.

**What would have shipped without my override:** rollup-only, or rollup + A + C. Next session would have hit Fix B's friction live and had to refactor inline before adding scenarios. Worst case: a Python edit per new scenario throughout the batch.

## Moment 3 — I pinned the observing-only contract before shipping the MAST wiring

After Claude described the MAST classifier wiring as a post-hoc judge, I asked:

> I just want to make sure that what youre doing now is going to have the judges evaluate the agents actions after the agent made his suggestions. We are NOT using this as a classifier for how the agent should behave correct?

That question pinned the no-railroading separation (spec §3.11.1, codified in last session) onto the new wiring before it landed. The unidirectional-data-flow contract had been implicit in Claude's design — "post-hoc evaluator" — but not explicitly named in those terms. My ask forced a clean statement of the contract back: agent never reads MAST output, no feedback into AGENT.md, no feedback into runbooks, MAST is for human readers and corpus aggregate only.

**Why it mattered:** the §3.11.1 no-railroading rule is the load-bearing architectural commitment that keeps the eval corpus from collapsing into a tautology. New wiring that touches the eval pipeline has to honor it explicitly, not just spiritually. By making me articulate the one-way data flow before shipping the wiring, the contract is now repeated in the v4 changelog entry, the MAST judge MD, and `run_evals.py` comments. Cross-session.

## Other moments worth noting

- **I forced a spec-vs-actual audit mid-session.** "Did we stray at all from the triage v3 spec file we are supposed to follow given everything we've done in this session?" Claude wouldn't have systematically reconciled unprompted. The audit surfaced six implementation-detail divergences from the spec (MAST prompt was authored rather than verbatim-ported, YAML schema grew without spec mention, `runbook_status` vocabulary is ours not the spec's, etc.). Most importantly the **MAST prompt drift** — Claude wouldn't have flagged that without my asking. It's now a known item to fix before interviews so the published-classifier accuracy citation holds.

- **I fact-corrected Claude's assumption about past sessions.** I had asked "Im guessing whenever a claude session ran a scenario he also invoked that agent at the end of it" — Claude grep'd the repo and found zero references to `mast-classifier-reviewer` anywhere outside the agent definition file. The sub-agent had been defined but never invoked across ~15 prior sessions. I was guessing; the data corrected me. That fact made the auto-MAST wiring's value sharper than my framing alone would have made it.

- **I refused the backfill on MAST classifications.** When Claude offered to retroactively apply MAST to the 3 existing failure JSONs, I declined — only forward-only annotation. Preserves audit history; the §3.5 claim is now scoped as "every failed run post Day 36 Hour 13 carries MAST."

- **I made Claude check live AWS state after an SSH crash.** Mid-session VSCode died with overlays 01/02/03 in unknown states. I caught the cost-leak risk before it ran another day. Three live ECS services running, ~$0.90/day. Cleaned up inline; not a big leak but worth noting for end-of-session discipline.

## What changed (concrete)

- **3 commits** all on `main`:
  - `7060fff` — runbooks-api split (closes last session's directive; runbooks ship as load-bearing pillar)
  - `1a396f3` — MAST classifier wired as post-hoc auto-judge (closes §3.5 "annotate every failure" claim from aspirational to artifact-level)
  - `6491cd7` — corpus-readiness pass (YAML-driven alarms + payload registry + skill refresh + rollup script)
- **`agent/AGENT.md`** restructured: 169 → 128 lines, 🔴 alarm-specific prescriptions migrated into runbook files, step 2 calls `lookup_runbook`
- **3 runbooks shipped** in `runbooks/{target-group-port-mismatch, missing-env-var, az-slowdown}.md`
- **MAST classifier** as `evals/judges/mast_classification.md`, categorical scale, fires only on diagnosis-judge-score-0; verdict carries `posthoc:true` marker
- **`docs/eval-results/summary.md`** — derived rollup; `make eval-summary` regenerates
- **Eval harness refactored**: `_SCENARIO_ALARMS` deleted, `_PAYLOAD_BUILDERS` registry added, YAML schema gained `alarm_name` + `target_resource` + `alarm_payload_type` + `runbook_status`
- **`add-outage-scenario` skill scaffold** updated to reflect current FIS convention + new YAML fields
- **16 new unit tests** across MAST gating (9) and synthetic-alarm path (7); 72 total passing
- **Scenarios 01/02/03 all re-scored Match (2.0)** post-runbooks-split end-to-end

## Why it mattered

Three reasons, ranked:

1. **The single-agent restraint pitch held.** v3.1 of the spec drops the multi-agent framing as the central restraint signal (HN 2026 hiring filters against sprawling multi-agent demos). My catch on Moment 1 kept that restraint intact. *"I considered an agent-writer pattern for narrative drafting; here are three reasons it would have weakened the project's actual claim"* is a strong interview answer. Shipping the drafter quietly would have been a weaker one.

2. **Next session is unblocked at scale.** Without Moment 2's scope override, the 5-6-scenario batch would have hit per-scenario friction. Now it's truly scalable: scenario authors write a YAML + an overlay; the harness absorbs. The corpus can grow to 8-10 without harness edits. *"I built a scalable corpus architecture and shipped 8-10 scenarios on it"* is a better story than *"I built a 3-scenario demo and refactored at the eighth one."*

3. **Cross-session architectural discipline survived.** Yesterday's no-railroading rule (§3.11.1) was tested today by the MAST wiring. Moment 3 forced explicit articulation of the contract on the new wiring, not just *"of course it doesn't railroad."* That's the difference between rules that survive and rules that quietly erode session by session.

## Portfolio-relevant signal

A reviewer reading just the git log sees "three commits Day 36 Hour 12-14." A reviewer reading this file sees:

- I notice when an automation pitch is implicitly proposing a new architectural pattern that contradicts the project's positioning — even when the implementation looks neutral.
- I weigh scope-creep risk against scalability-cost over time and choose deliberately, even against Claude's defaulted-conservative recommendation when the principle is sound.
- I treat cross-session architectural rules (no-railroading, runbooks pillar, single-agent restraint) as live contracts that have to be re-pinned on every relevant new wiring — not assumed.
- I push back on Claude's defaulted recommendations when my own architectural judgment differs, and Claude's response to the pushback (here: three crisp risks named; specific design choices reversed) is itself the receipt of the collaboration shape.

That's the difference between "Claude shipped a corpus-ready harness" and "I directed Claude through a scope override, a multi-agent line, and a no-railroading re-pinning, and the artifact is structurally better because of all three."

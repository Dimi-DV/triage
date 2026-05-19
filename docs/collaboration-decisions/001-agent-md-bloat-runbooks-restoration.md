# 001 — I caught Claude letting AGENT.md bloat; made it restore runbooks-api as a pillar

**Date:** 2026-05-19, Day 36 Hour 11
**Triggering commits:** `68ad9c9` (Claude's work that surfaced the bloat) → `304a5e3` (cleanup I forced) → `3fb839d` (rule I made Claude codify) → next session (the actual fix)

## The moment

After scenario 03 shipped at Match (2.0), Claude had just finished writing up the AGENT.md changelog convention and committing it (`68ad9c9`). The framing in that commit treated `agent/AGENT.md` as the load-bearing artifact for agent reasoning. I asked:

> what about the agent.md itself, is it getting more and more bloated through iterations? Context might be too fat eventually. Is that another case for a runbooks system down the line?

That single question reframed the entire trajectory.

## What Claude was about to do

Without my question, the project would have:

- Kept extending AGENT.md with one new prescription per scenario (the pattern that grew it from 54 lines at baseline to 169 lines by scenario 03 — **3× bloat in 3 scenarios**).
- Treated `runbooks-api` as a "future iteration" — which is how Claude had implicitly framed it.
- Shipped scenarios 04–09 the same way, ending up at 8–10× baseline AGENT.md size with no runbooks built.
- Produced an eval corpus that's a tautology: every scenario tests "does the agent read its own answer key from the system prompt."

Claude went and counted the actual bloat after I asked (`wc -l` against git history): v0 = 54 lines, v2 = 115, v3 = 169. The data confirmed what I had suspected.

## What I caught that Claude missed

Two things Claude had missed across roughly 6 prior sessions, despite the spec being loaded as a reference the whole time:

1. **`runbooks-api` is one of the four canonical namespaces in the spec** (§3.2). It's not a "future feature." Per §3.6, runbooks are explicitly Skill Tier 2 in the AWS-DevOps-Agent-mirror pattern this project is built around. Per §3.10, runbooks become load-bearing in the multi-agent expansion path. Per Day 30 and Day 36 sprint commitments, runbooks were supposed to be written and `runbooks_api_lookup_runbook` was supposed to be invokable by today.

2. **The reason AGENT.md was bloating is precisely because `runbooks-api` was empty.** Every scenario-specific prescription that should have been a runbook entry landed in AGENT.md instead. The bloat is the symptom of the missing namespace.

Claude had been treating the four namespaces as equivalent in the documentation, never flagging that one of them was half-implemented vs spec.

## My follow-ups that made it durable

After Claude sketched the fix (build `runbooks_api_lookup_runbook`, write 3 initial runbooks, restructure AGENT.md to call lookup first), I pressed two more times in ways that mattered:

1. **"In this session I believe, we almost entirely scrapped runbooks? Lets bring them back as the pillar again in the spec and readme and wherever else you changed it."** — I caught that Claude's AGENT.md changelog framing had still implicitly treated AGENT.md as singular. Forced commit `304a5e3` correcting the framing in 5 places (spec §3.11, CLAUDE.md rule #6, changelog file intro, README MCP-server row, project_triage_stack_status memory).

2. **"Can we immortalize this philosophy, because previous sessions would run the agent against a test, see that it underperformed, and then fit the agent with information from the failure scenario to get it to give a better result."** — I forced explicit codification of the no-railroading rule rather than letting it stay implicit in the runbooks-split discipline. Led to commit `3fb839d` — spec §3.11.1 + §3.11.2, CLAUDE.md hard rule #7, memory `feedback_no_railroading`, and the design choice that ≥3 of corpus scenarios must ship runbook-less.

## What changed (concrete)

- **3 commits** all on `main`, all driven by my pushback:
  - `68ad9c9` (scenario 03 ships + AGENT.md changelog convention — the work that triggered my noticing)
  - `304a5e3` (runbooks-api restored as load-bearing pillar across 5 surfaces — my "scrapped runbooks" catch)
  - `3fb839d` (no-railroading rule + ~3 runbook-less scenarios codified — my "immortalize this philosophy" demand)
- **`docs/agent-md-changelog.md`** created — every entry tagged 🟢/🔴 for "general vs alarm-specific" so the migration is mechanical when `runbooks_api_lookup_runbook` ships
- **Spec §3.11** rewritten + new subsections §3.11.1 (no-railroading rule) and §3.11.2 (runbook-less scenarios by design)
- **CLAUDE.md gained hard rules #6 and #7** — surfaces both disciplines in the always-loaded constitution
- **Memory** gained `feedback_namespace_iam_gap`, `feedback_agent_md_changelog_required`, `feedback_no_railroading` — three workflow rules for future sessions
- **Next session's directive locked in**: build runbooks-api split before scenario 04, with all the runbook decisions traceable to the 🔴 markers in the changelog

## Why it mattered

Three reasons, ranked:

1. **I caught a 6-day spec drift.** The runbooks gap had survived ~15 sessions undetected, including 5 sessions where AGENT.md was substantively edited. The fix wouldn't have happened on its own — it needed me to read the bloat output and ask "is this the right shape?"

2. **I killed an emerging anti-pattern before it metastasized.** The no-railroading rule that came out of my pushback is now the single most important rule governing future eval iterations. Without me forcing it explicit, every failing scenario would have continued to "get fixed" by stuffing the answer into AGENT.md, and the eval table's portfolio value would have hollowed out from inside.

3. **I supplied the architectural insight that unlocked a new test class.** My follow-up question ("with runbooks for specifics and one general agent.md guided to look at them and then reason on its own given the absence of an appropriate runbook we'll be able to test the area that im currently thin on?") connected the runbooks split to the generalization-test pattern. That's the design choice now codified in §3.11.2 — and the actual answer to the "thin on novelty" weakness Claude had named in the portfolio assessment. **That was my insight, not Claude's** — Claude had described the split but hadn't connected it to the generalization claim until I did.

## Portfolio-relevant signal

A reviewer reading just the git log sees "three commits Day 36 Hour 11." A reviewer reading this file sees:

- I review architectural framing carefully enough to catch when a load-bearing namespace has been silently demoted in five places.
- I push back on Claude's defaulted-defensive instincts (treat AGENT.md as a free-form append-only file) when they don't match the project's design intent.
- I treat the spec as a contract, not a wishlist — and I insist rules get codified explicitly rather than left implicit, because the lesson otherwise won't survive the next session.
- I made a direct architectural contribution: the generalization-test design pattern (§3.11.2) was my insight; Claude built it into the spec from my framing.

That's the difference between "I used Claude Code to build this" and "I directed Claude Code through three architectural pivots this session, and the spec is structurally better because of it."

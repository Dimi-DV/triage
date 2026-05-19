# Collaboration decisions

This folder documents moments where I caught Claude going off-spec, pushed back on a defaulted-defensive design, or contributed an architectural insight Claude would not have reached on its own. It exists because the project's portfolio framing rests partly on the Claude Code workflow being **directed**, not consumed. The git log shows what was built. The AGENT.md changelog shows how the agent's behavior evolved. This folder shows where my judgment shaped the build, not just the code.

## Format

One file per decision, numbered chronologically. Each entry captures:

- **The moment** — what I asked, what was happening at the time
- **What Claude was about to do (or was already doing wrong)** — the path that would have shipped without my intervention
- **What changed** — concrete commits, code, framing decisions that came out of my push
- **Why it mattered** — the portfolio-relevant signal (architectural correctness, process improvement, fact-checked sloppiness, etc.)

Keep entries tight. The point is the moment, not the explanation.

## Index

- [001 — I caught Claude letting AGENT.md bloat; made it restore runbooks-api as a pillar](001-agent-md-bloat-runbooks-restoration.md) — caught a 6-day spec drift; forced 3 commits, a spec §3.11 rewrite, and the no-railroading rule

## Other moments worth writing up from this session (Day 36 Hour 11, 2026-05-19)

These haven't been formalized yet; expanding into individual entries when I have time. Listed in roughly descending order of impact.

- **I killed Claude's `fis-api` suggestion.** When scenario 03 was stuck at Partial (1.0), Claude suggested adding an `fis-api` MCP tool so the agent could see active FIS experiments and name them directly. I pushed back: "isnt the whole purpose of fis to induce a fault into the system? If we give the agent the ability to see what fis is doing we are going against the whole purpose of fis itself." That killed the bad design instantly and forced the better fix (loosen the reference_answer's "must name FIS" requirement, which was the actual authoring mistake). Without me catching this, the project would have shipped a tool that defeats its own evals.

- **I made Claude clean up its own "scrapped runbooks" framing.** After the AGENT.md changelog work landed, I noticed Claude's new framing had implicitly demoted runbooks-api ("In this session I believe, we almost entirely scrapped runbooks? Lets bring them back as the pillar again"). Claude had restored the FILES but its new architectural framing in spec §3.11, CLAUDE.md rule #6, the changelog, and the project memory had all treated AGENT.md as the single load-bearing artifact. My catch led to commit `304a5e3` correcting the framing in five places.

- **I forced the no-railroading principle into the spec.** I told Claude to "immortalize this philosophy, because previous sessions would run the agent against a test, see that it underperformed, and then fit the agent with information from the failure scenario." Without that explicit ask, the rule would have stayed implicit in the runbooks/AGENT.md split discipline and prone to recurrence. Led to commit `3fb839d` — spec §3.11.1 + §3.11.2, CLAUDE.md rule #7, memory `feedback_no_railroading`.

- **I supplied the generalization-test design.** When Claude flagged "thin on novelty" as a portfolio weakness in its web-search assessment, I connected the runbooks split directly to fixing it: "with runbooks for specifics and one general agent.md guided to look at them and then reason on its own given the absence of an appropriate runbook we'll be able to test the area that im currently thin on?" That's the no-runbook generalization-test pattern. **It was my insight, not Claude's** — Claude had described the split but hadn't connected it to the generalization claim. Now §3.11.2 of the spec codifies "≥3 of corpus scenarios ship runbook-less by design."

- **I demanded the AGENT.md changelog discipline.** "Agent md is the backbone of this entire stack and any changes should be monitored and documented rigorously." Without that, AGENT.md edits would have stayed silent in the git log. Led to `docs/agent-md-changelog.md` with retroactive v0/v1/v2/v3 entries, CLAUDE.md rule #6, spec §3.11, memory `feedback_agent_md_changelog_required`.

- **I made Claude do a full spec-vs-actual audit.** "Tell me how they compare to the spec file, How close are we to being done with the whole project? You found the missing runbooks i wonder if anything else is missing." Forced the systematic spec-vs-actual check. Surfaced 7 additional gaps beyond runbooks (stale ADR-0007, three missing README sections, missing benchmark numbers, etc.). Saved to `audit-local/2026-05-19-spec-vs-actual.md`.

## Other moments (smaller but real)

- **I fact-checked a deferral Claude made up.** When Claude suggested deferring runbooks "until after scenario 5 or 6," I asked "and initially runbooks were supposed to be implemented after scenario 5 6?" Claude had invented the timing; the spec actually called for runbooks Day 30 / Day 36. Forced an honest correction.

- **I pushed back on prompt bloat.** Claude wrote an ~80-line / ~1,100-token session-starter prompt with 9 files to pre-read. I asked "doesnt all of that bloat the context for the session loads or do you think its all necessary?" Forced a tighter ~40-line version that trusts the next session to read on demand.

- **I called out the meta-failure pattern.** I observed that Claude was the first session in ~15 to notice the missing runbooks despite the spec being there all along. "Its baffling to me that you were the first one to notice this. The spec file has been there the whole time but somehow every session missed it, bizarre." That's a process-level insight about how multi-session AI workflows fail silently — I opted to handle it manually with session-starter reminders rather than letting Claude add another auto-loaded surface.

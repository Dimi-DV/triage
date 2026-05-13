# Sprint Workflow Pattern

**Owner:** Dimitrije
**Applies to:** Triage (Days 31–36) and any future Claude Code-heavy build sprint
**Last updated:** May 13, 2026

## Why this doc exists

The project build divides cleanly across two Claude environments with different strengths. This pattern captures how they're used together so a future browser Claude session knows what workflow context to assume. Without this, browser Claude defaults to behaviors that aren't a fit for a Claude-Code-primary sprint (e.g. assuming filesystem access).

## The three-phase daily rhythm

### Morning — browser Claude (15–30 min)

Purpose: spec the day. Architectural reasoning, planning, decisions.

- Open the project's browser Claude
- Re-establish state: paste `git log --oneline -20` or use `recent_chats` / `conversation_search` for yesterday's continuity
- Ask: "What am I building today, and what's the right approach?"
- End with: a written one-paragraph build spec for the day's Claude Code session(s)

### Daytime — Claude Code (~4–6 hours)

Purpose: execute the spec. Implementation, file edits, terminal work.

- Open Claude Code in the repo (CLAUDE.md auto-loads)
- Paste the morning brief
- For first-of-kind work: use plan mode (Shift+Tab or `/plan`) — Claude Code proposes structure first, then implements
- For variations on an established pattern: pointed commands ("add X following the pattern of Y")
- Commit frequently with descriptive messages: `Day NN Hour M: <what>`
- Each session has one clear goal; close + start fresh at task boundaries (context degrades in long sessions)

### Evening — browser Claude (15–20 min)

Purpose: review, identify weakness, prepare tomorrow.

- Paste `git log --oneline -20` or `git diff main...HEAD` into browser
- Ask: "Review what got built today; what's weak; what should I prioritize tomorrow?"
- Optional: write a 3-sentence journal entry to `docs/journal/<date>.md` for next-morning continuity via `conversation_search`

## Information flow between environments

**Browser → Claude Code:**
- The morning brief, pasted at session start
- CLAUDE.md and `docs/architecture-references/` provide persistent context (committed to repo)
- The 8 project memory notes summarize all key architectural references

**Claude Code → Browser:**
- The user is the bridge. Browser Claude has no filesystem access.
- Paste `git log --oneline`, `git diff`, or `tree -L 3 src/` output to bring browser current
- Recent chat history (via past-chats tools) carries the rest

## When to use what — quick reference

| Task | Best environment |
|---|---|
| "Help me decide between X and Y" | Browser |
| "I want to build something but unsure of approach" | Claude Code, plan mode |
| "Build feature Z (clearly specified)" | Claude Code, pointed |
| "Why is my AgentCore Gateway returning 401?" | Claude Code first (it sees actual errors); browser if stuck |
| "Mock interview me on this project" | Browser |
| "Review what I built today" | Browser, paste git diff |
| "Refactor file X to match pattern Y" | Claude Code |
| "Write README architecture prose" | Browser (artifacts mode) |
| "Explore unfamiliar repo / codebase structure" | Claude Code in read-only mode |
| "Synthesize 3 source documents into a plan" | Browser |
| "Find all instances of pattern Z across the repo" | Claude Code (grep) |

## Conventions

- **Branch per day:** `feat/day-NN-<feature>`. Merge to main via PR end of day.
- **Commit messages:** `Day NN Hour M: <what got built>`. Git log doubles as build journal.
- **Optional daily journal:** `docs/journal/2026-MM-DD.md` — short, just continuity bridge for next morning
- **Plan mode for first-of-kind work**; pointed mode for variations on existing patterns
- **Don't manually re-explain the project on each new browser session** — project memory holds the architectural spec (decision doc v2.1) and 8 reference notes

## What to paste when continuity matters

In order of usefulness:

1. `git log --oneline -20` — what happened recently
2. `git diff HEAD~3` — what changed
3. `tree -L 3 src/` or `ls -R` — current structure
4. One-paragraph status: "I built X, Y is stuck because Z, tomorrow I plan W"

Five seconds of pasting brings browser current. The user is the bridge.

## Anti-patterns

- **Don't plan architecture in Claude Code** — narrower context, plans bloat session token budget
- **Don't ask browser Claude to edit files** — it can't; wasted turn
- **Don't run long single Claude Code sessions** — context degrades; prefer short focused sessions with CLAUDE.md re-anchoring
- **Don't bypass the hooks** — they exist because CLAUDE.md is advisory and hooks are mandatory. The whole point is deterministic enforcement.

## Existing user conventions (continue as-is)

- Linux VM (UTM on Mac M2) accessed via VS Code Remote SSH (`labvm`) is the primary CLI environment for git operations
- GitHub CLI (`gh pr create`, `gh pr merge --squash --delete-branch`) for PR workflow
- The project may run under `~/triage/` as a new repo or `~/devops-learning/triage/` as a subdirectory — decision pinned in Day 33 checklist

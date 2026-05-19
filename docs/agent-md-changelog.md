# AGENT.md changelog

`agent/AGENT.md` is one of two load-bearing artifacts that drive the agent's reasoning. The other is the `runbooks-api` runbook store (`runbooks/<alarm-class>.md`, fetched on demand via `runbooks_api_lookup_runbook`). Per spec [§3.11](architecture-references/triage-decision-doc-v3.md): **AGENT.md holds general investigation principles + the tool surface + hard rules; runbooks hold alarm-specific procedures**. Scenario-specific reasoning belongs in a runbook, not AGENT.md.

**Current reality vs that design:** `runbooks_api_lookup_runbook` hasn't shipped yet (overdue per the Day 30 / Day 36 spec commitments). Until it does, scenario-specific prescriptions have been landing in AGENT.md, which is why this file exists in the first place — to make the drift visible and the eventual migration tractable. Every entry below tagged with a 🔴 "should-be-a-runbook" marker is a prescription that will move out of AGENT.md once the lookup tool lands.

Changes to either artifact directly affect every scenario in the outage corpus and every production alarm the agent handles. Treat both as **versioned behavioral interfaces**, not free-form text files. This file tracks AGENT.md specifically; a parallel changelog discipline will apply to runbooks once they exist.

**Every substantive change to `agent/AGENT.md` gets an entry below.** A substantive change is anything that adds, removes, or modifies a prescription, trigger condition, or required field — not pure formatting or typo fixes. Each entry records:

- **Version + date + commit SHA**
- **Motivation** — which scenario, which run JSON surfaced the gap
- **Change summary** — what was added/removed/modified (the full diff lives in git)
- **Validation** — the post-change run JSON that demonstrates the fix worked
- **Risk** — what else this change could affect (other scenarios, branches in the prescription tree)
- **Runbook check** — 🔴 if the prescription is alarm-specific and should migrate to a runbook once `runbooks-api` lookup ships; 🟢 if it's general enough to stay in AGENT.md

The git log is the authoritative line-level diff; this file is the *why* and the *evidence*.

---

## v0 — 2026-05-18 (Day 34 afternoon)

**Commit:** `51f2b8f` — Day 34 afternoon+evening: AgentCore Runtime + alarm SNS path + Slack hello-world

**Motivation:** Baseline. Initial system prompt drafted before any outage scenarios existed, alongside the first end-to-end agent loop.

**Change summary:** Initial design. Single MCP tool surfaced (`metrics_api_get_metric_statistics` + `runbooks_api_post_to_slack`). Investigation flow had three steps: parse the alarm, call one metric query, compose Slack message. No structural-inspection prescriptions yet.

**Validation:** Hello-world smoke (synthetic alarm → agent → Slack) verified end-to-end at Day 34 evening.

**Risk:** None known — baseline.

---

## v1 — 2026-05-18 (Day 36 Hour 3-5)

**Commits:** `06daf60` (scenario 01 end-to-end), `96ec8a4` (first ecs-api tool), `1394e83` (describe_task_definition)

**Motivation:** Scenario 01 (`target-group-port-mismatch`) needed the agent to walk a chain: `metrics → describe_target_health → describe_task_definition` to see the port-mismatch cause. Without prescriptions, the agent would just call the one metric tool and post a generic diagnosis.

**Change summary:** Added the "Target-group alarms" branch under step 2 (Decide what evidence to gather). Prescribed `ecs_api_describe_target_health` whenever alarm dimensions include `TargetGroup`. Added the `ecs_api_describe_task_definition` follow-up gated on "any unhealthy target where the cause isn't already in `reason`", with sub-cases for **port split**, **matching ports / Target.Timeout** (inspect command and environment), and **empty registration**.

**Validation:** Scenario 01 v3 — `docs/eval-results/runs/01-target-group-port-mismatch/2026-05-19T15-18-49Z-*.json` — diagnosis judge **Match (2.0)**.

**Risk:** Initial trigger for `describe_task_definition` was gated narrowly on "port split confirmed by target health" — too narrow. This surfaced as scenario 02's v1 NoMatch (see v2 below). Lesson recorded in `[[agent-md-trigger-too-narrow]]` memory.

**Runbook check:** 🟢 (mostly general) for the structural-tool prescriptions (`describe_target_health` for any TG alarm, `describe_task_definition` for unhealthy targets) — these are general investigation principles that apply across alarms. 🔴 for the port-split-specific sub-case wording, which is alarm-class-specific and will move into a `target-group-port-mismatch.md` runbook entry once `runbooks-api` lookup ships.

---

## v2 — 2026-05-19 (Day 36 Hour 10)

**Commit:** `6f0cccd` — Day 36 Hour 10: scenario 02 — AGENT.md fix flips NoMatch → Match

**Motivation:** Scenario 02 (`missing-env-var`) v2 baseline run — `docs/eval-results/runs/02-missing-env-var/2026-05-19T15-25-23Z-*.json` — scored **NoMatch (0.0)** on the diagnosis judge. The agent never called `ecs_api_describe_task_definition` because v1's trigger was gated on a port split (`registered port ≠ health_check_port`); scenario 02 has matching ports (both 80). MAST FM-3.3 Incorrect Verification — predicted in the YAML, verified empirically.

**Change summary:** Two edits, both targeted at the describe_task_definition branch:

1. Broadened the trigger from "port split confirmed by target health" to **"any unhealthy target where the cause isn't already in `reason`"**, with sub-bullets for port split, matching-ports timeout, and empty registration.
2. Added an explicit cross-reference instruction: **"for every `$VAR_NAME` (or `${VAR_NAME}`) referenced in `command`, check whether `VAR_NAME` appears as a key in the `environment` block"** — the load-bearing reasoning step that names the specific missing variable rather than hedging on "container might not be running."

**Validation:** Scenario 02 v3 — `docs/eval-results/runs/02-missing-env-var/2026-05-19T15-59-42Z-*.json` — diagnosis judge flipped to **Match (2.0)**. Correctness 1.0, TrajectoryInOrderMatch 1.0. Full before/after preserved.

**Risk:** Broader trigger may cause `describe_task_definition` to fire on alarms where the task def is irrelevant (e.g. infrastructure-layer faults like scenario 03 → AZ disconnect). That risk materialized — see v3 below, where the agent's subsequent reasoning was: "task def is fine → done." Needed an additional branch for "what to do AFTER describe_task_definition returns clean."

**Runbook check:** 🔴 (alarm-specific). The "$VAR_NAME in command vs environment block" cross-reference is the load-bearing reasoning step for the `missing-env-var` alarm class specifically. It does not apply to port mismatches, AZ outages, or any non-env-var failure mode. This prescription will move into a `missing-env-var.md` runbook entry once `runbooks-api` lookup ships, and AGENT.md will lose it.

---

## v3 — 2026-05-19 (Day 36 Hour 11)

**Commits:** uncommitted at write time of this entry (will land in the `Day 36 Hour 11` commit for scenario 03).

**Motivation:** Scenario 03 (`az-slowdown`, first FIS chaos) v1 run — `docs/eval-results/runs/03-az-slowdown/2026-05-19T20-10-20Z-*.json` — scored **NoMatch (0.0)**. The agent saw `UnHealthyHostCount > 0` in the alarm, called `describe_target_health`, saw ECS already rebalancing tasks into the surviving AZ (mixed healthy + draining state), and concluded **"transient event during a deployment or scale-in operation, no action required."** MAST FM-3.3 again — same family as scenario 02, different trigger condition. The agent skipped both `describe_task_definition` AND `logs_api_filter_log_events` because v2's prescription tree had no branch for "alarm fired but current state looks recovering."

**Change summary:** Three edits:

1. **New step 2** added to the investigation flow: **"Anchor all time-window arguments on the alarm payload's `StateChangeTime` field."** Without this, the LLM hallucinated a 2025-06-15 timestamp (training-data sense of "current date") and queried an empty time window. Renumbered subsequent steps (3-6).
2. **New branch in step 3** under "Decide what evidence to gather": **"An alarm fired but current state looks recovered / transient"**. Explicit prescription: **do not conclude "transient, no action required" without evidence**. Two follow-ups required in order: (a) call `describe_task_definition` to rule out app-layer cause, and (b) if task def looks correct, call `logs_api_filter_log_events` with a window covering the alarm's evaluation period. Names the chaos-injected-fault pattern explicitly (asymmetric heartbeat/access lines from only one AZ in a multi-AZ service; unhealthy targets clustered in one subnet CIDR).
3. Reinforced existing "logs are load-bearing evidence" branch with concrete filter-pattern guidance.

**Validation:** Scenario 03 v4 — `docs/eval-results/runs/03-az-slowdown/2026-05-19T20-55-40Z-*.json` — diagnosis judge **Match (2.0)**. Correctness flipped 0.0 → 1.0. Full v1→v4 progression preserved. (v2 and v3 of scenario 03 scored Partial (1.0) — those runs surfaced an IAM gap on the MCP task role + a reference-answer authoring mistake, not AGENT.md issues. See `[[namespace-iam-gap]]` memory and `docs/scenario-runs/03-az-slowdown.md`.)

**Risk:** The "alarm fired but recovering" branch is broad — it could fire on benign deployments and trigger unnecessary log queries. Acceptable trade-off: the cost of one extra `logs_api_filter_log_events` call (~$0.0001 + ~2s latency) is much less than the cost of missing a real chaos event. Monitor whether this branch causes false-positive log queries on real benign alarms in the future.

**Runbook check:** Mixed. 🟢 The "anchor on StateChangeTime" step is general — every investigation needs a time anchor; stays in AGENT.md. 🟢 The "do not conclude 'transient' without evidence" rule is general; stays in AGENT.md. 🔴 The specific guidance about "asymmetric heartbeat/access lines from only one AZ in a multi-AZ service, or unhealthy targets clustered in one subnet CIDR" is an AZ-outage-class pattern specifically — it will move into an `az-slowdown.md` runbook entry once `runbooks-api` lookup ships. The agent should default to runbook content for "what asymmetric pattern looks like for THIS alarm class," with AGENT.md only providing the meta-rule "look for asymmetry when alarm fires but state looks recovering."

---

## Change-control rule

Going forward (codified in `CLAUDE.md` "Hard rules" and the spec at `docs/architecture-references/triage-decision-doc-v3.md` §3.11):

**Every edit to `agent/AGENT.md` must include a new entry in this changelog in the same commit.** Skipping the changelog entry is a regression — the file is the audit trail for behavioral changes that the eval corpus is supposed to catch. PR review (when there's a PR) or commit review (direct-to-main, current pattern) must check both files together.

Validation evidence is mandatory. An AGENT.md change without a corresponding run JSON showing the fix worked is half a change.

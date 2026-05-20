# AGENT.md changelog

`agent/AGENT.md` is one of two load-bearing artifacts that drive the agent's reasoning. The other is the `runbooks-api` runbook store (`runbooks/<alarm-class>.md`, fetched on demand via `runbooks_api_lookup_runbook`). Per spec [§3.11](architecture-references/triage-decision-doc-v3.md): **AGENT.md holds general investigation principles + the tool surface + hard rules; runbooks hold alarm-specific procedures**. Scenario-specific reasoning belongs in a runbook, not AGENT.md.

**Current state:** `runbooks_api_lookup_runbook` shipped in v4 (Day 36 Hour 12, this changelog). The 🔴-tagged prescriptions in v1/v2/v3 entries below have all been migrated out of AGENT.md into `runbooks/<alarm-class>.md` and are now fetched on demand by the lookup tool. The 🔴 markers are kept on those entries as audit history — they document **what migrated and from where**, not outstanding work. Going forward, alarm-specific prescriptions land in runbook files directly (one-per-alarm-class) and only general principles go in AGENT.md.

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

## v4 — 2026-05-20 (Day 36 Hour 12)

**Commit:** lands with this changelog entry (Day 36 Hour 12 commit, "runbooks-api split — lookup_runbook + 3 runbooks + AGENT.md trim").

**Motivation:** The architectural cleanup spec §3.11 has been describing as a current spec gap since Day 30 — alarm-specific prescriptions kept landing in AGENT.md across scenarios 01-03, which grew the file from 54 → 169 lines and turned it into a per-alarm wiki. Closing it before scenario 04 prevents linear bloat with the rest of the corpus.

**Change summary:** Four coordinated edits.

1. **`runbooks_api_lookup_runbook` MCP tool shipped** (`src/triage/mcp_server/runbooks_api/lookup_runbook.py`). Read-only; matches `alarm_name` against the `**Alarm trigger:**` field of `runbooks/<slug>.md` files using the `/add-runbook` skill's parseable structure. Returns `{found, alarm_name, slug, content, sections}` on hit, `{found: false, alarm_name, available_runbooks}` on miss. OTel-instrumented like the other read-only tools; no audit emission (read-only); no Cedar policy required (Cedar gates write tools only).
2. **Three runbooks populated** (`runbooks/{target-group-port-mismatch, missing-env-var, az-slowdown}.md`), each one carrying the 🔴-tagged alarm-specific prescription from v1/v2/v3 respectively. Each follows the `/add-runbook` skill scaffold (H2 Prerequisites / Steps / Rollback / Escalation; numbered steps).
3. **AGENT.md restructured.** Added a new section explaining the lookup tool and added **step 2 (runbook fetch)** to the investigation flow with explicit fallback semantics: `found: false` does NOT mean "nothing to investigate" — §3.11.2 requires ~3 corpus scenarios to ship runbook-less by design as generalization tests. Deleted the 🔴-tagged prescriptions:
   - **v1 🔴 port-split sub-case wording** (compare three ports) → migrated to `runbooks/target-group-port-mismatch.md`.
   - **v2 🔴 `$VAR_NAME` in command vs environment cross-reference** → migrated to `runbooks/missing-env-var.md`.
   - **v3 🔴 AZ-asymmetry pattern** (heartbeat lines / subnet-CIDR clustering) → migrated to `runbooks/az-slowdown.md`.
   Kept the 🟢 general meta-rules: anchor on `StateChangeTime`; don't conclude "transient" without evidence; look for asymmetry; the trigger conditions for `describe_target_health` and `describe_task_definition`. File went 169 → 128 lines; the remaining text is structurally different (principles + runbook-first + tool surface, not per-alarm wiki).
4. **Framing flipped from "current spec gap" → "shipped"** in spec §3.11, README MCP-server row, and the `project_triage_stack_status` memory.

**Validation:** Scenarios 01, 02, 03 re-run with the new AGENT.md + runbooks. All three at **Match (2.0)** on the gating `diagnosis_matches_ground_truth` judge — the migration preserved diagnosis quality across all three alarm classes. Per-run JSONs:

- Scenario 01: `docs/eval-results/runs/01-target-group-port-mismatch/2026-05-20T01-22-50Z-eval-1aaca953-a2f2-4d4c-a92b-b4a2f29cce87.json` — Match (2.0); Correctness 1.0; Faithfulness 1.0; ResponseRelevance 1.0; InstructionFollowing 1.0; GoalSuccessRate 1.0; TrajectoryInOrderMatch 1.0; asks_before_destructive_action Pass. (First attempt at 01:21:03 scored NoMatch — timing artifact, just-applied overlay had its target deregistered before the agent investigated. Retry after the overlay settled passed cleanly; both JSONs preserved as the audit trail.)
- Scenario 02: `docs/eval-results/runs/02-missing-env-var/2026-05-20T13-29-26Z-eval-19302ca8-c7db-4699-91d8-a9451b07579e.json` — Match (2.0); Correctness 1.0; GoalSuccessRate 1.0 (the verbatim-`REQUIRED_API_KEY` mention the judge wants is now produced reliably, where v3 of the prior scenario 02 run was at 0.0); TrajectoryInOrderMatch 1.0.
- Scenario 03: `docs/eval-results/runs/03-az-slowdown/2026-05-20T13-32-50Z-eval-c21dd571-2630-4fe3-8f53-582ffe144270.json` — Match (2.0); Correctness 1.0; GoalSuccessRate 1.0; TrajectoryInOrderMatch 0.0 (agent skipped `describe_task_definition` in this run — judged non-gating, the runbook says rule out config first but the agent inferred it from `Target.Timeout` + the asymmetric subnet-CIDR clustering it saw on `describe_target_health`); Faithfulness 0.75 (slight rationale-vs-content gap, non-gating).

**Risk:** Two new risk vectors:

1. **Runbook-lookup-miss path is now load-bearing AND empirically untested.** AGENT.md step 2 says: on `found: false`, fall back to general principles. If the agent collapses to "no runbook = no investigation," the runbook-less scenarios (§3.11.2) will silently regress. **None of scenarios 01-03 exercise this branch** — all three have a runbook shipped in v4. The lookup-miss fallback rule will only get empirical validation once a scenario 04+ ships as runbook-less by design (§3.11.2 requires ~3 of the corpus to be runbook-less). Mitigation: AGENT.md step 2 wording is explicit ("Do not treat the absence of a runbook as 'nothing to investigate'") and the lookup tool's response shape includes `available_runbooks` so the agent sees the alternatives a fuzzy name would have matched. Empirical regression test deferred to scenario 04+ design.
2. **Runbook content can railroad.** Per §3.11.1, a runbook listing "the answer is Y" for alarm class X is just as much railroading as putting the answer in AGENT.md. Mitigation: each of the three runbooks describes **procedure + expected evidence at each step + how to recognize when the procedure doesn't match observed reality**, not "the answer is X." If a future scenario in the same alarm class regresses because the runbook over-fitted to its motivating scenario, the runbook needs decomposition — same iteration discipline as AGENT.md.

**Runbook check:** 🟢 (general). The step 0/2 lookup logic, the fallback rule, and the kept meta-rules all apply across every alarm class — they belong in AGENT.md. The alarm-specific procedures live in the new runbook files, which carry their own (future) per-runbook change history.

---

## v5 — 2026-05-20 (Day 36 Hour 17, scenario 06)

**Commit:** (this commit) — Day 36 Hour 17: scenario 06 — rds-reboot

**Motivation:** Scenario 06 (`rds-reboot`, FIS dependency chaos) first run scored **NoMatch (0.0)** on the gating diagnosis judge — `docs/eval-results/runs/06-rds-reboot/2026-05-20T19-25-32Z-eval-f1d36a91-61ec-407b-accb-33200dfdaf01.json`. The agent saw all targets currently healthy (the sticky degraded window had just expired before the eval started, ~T+150s after FIS trigger), filtered logs with `?ERROR ?WARN ?unhealthy ?failed ?timeout` against the recent 10-minute window, got 0 matches (the actual error log line was `DB unreachable: TimeoutError: timed out` — CloudWatch filter terms are case-sensitive so `?timeout` didn't match `TimeoutError`), then queried unfiltered with `limit=50` and got 50 of the post-recovery `DB heartbeat OK` lines without ever reaching the past disruption window. The agent **never called `describe_task_definition`** — the existing trigger was gated on "any unhealthy target where cause isn't in reason," which didn't fire when targets were currently healthy. Without the task def, the agent never learned the health endpoint hits `$DB_HOST` and missed the dependency-failure shape entirely. Concluded "transient health check failure that self-resolved." MAST post-hoc classifier: FM-3.3 (Incorrect Verification).

**Change summary:** Strengthened the existing **"Alarm fired but current state looks recovered / transient"** branch under investigation flow step 4. Was: "Rule out configuration with `describe_task_definition`, then check logs over a window covering the alarm's evaluation period." Now mandates all three of:

1. **`describe_task_definition` is required** for this branch (not optional / not gated on per-target unhealthiness). The cause may live in wiring the current target state can't reveal — env vars, secret refs, container command, dependency endpoints.
2. **Log window anchored on `StateChangeTime` ± 2min**, not current time. Tight, past-anchored window — the disruption is in the past by definition for the recovered-alarm branch.
3. **Broad filter vocabulary** beyond `?ERROR ?WARN` — include `?unreachable ?refused ?timeout ?Timeout ?Error ?Exception ?failed`. CloudWatch filter terms are case-sensitive and word-bounded; if a filter returns zero events, try a broader pattern OR an unfiltered query with a tight window.

Paired runbook change: `runbooks/rds-reboot.md` Prerequisites now explicitly distinguishes "Live disruption" from "Recovered alarm" and adds a Step 1b for the recovered-alarm branch (log window anchored on `StateChangeTime`).

**Validation:** Scenario 06 v2 — `docs/eval-results/runs/06-rds-reboot/2026-05-20T19-36-03Z-eval-04887751-6e54-45ba-addb-cf3c5c0a88bb.json` — diagnosis judge **Match (2.0)** (up from NoMatch 0.0 on v1). GoalSuccessRate also flipped to 1.0. The agent's trajectory now includes `describe_task_definition` (which it skipped in v1), saw the `DB_HOST` env wiring + the Python health server's TCP-connect-to-RDS pattern, queried logs anchored on the alarm window, and named the dependency-layer failure correctly.

**Risk:** Three vectors:

1. Other scenarios where the alarm is unambiguously "still firing right now" may now over-investigate (calling `describe_task_definition` when target state already pinpoints the cause). Mitigation: the new prescription is scoped to the "recovered / transient" branch — the live-failure branches still gate `describe_task_definition` on "cause isn't in reason." Live-failure scenarios (01/02) re-running should not regress.
2. The "broad filter vocabulary" list is alarm-class-suggestive (it leans toward dependency/network failure vocabulary). If a new scenario surfaces failures using yet-different vocabulary (e.g., custom application error formats), the suggestion list will need extension. Mitigation: the "if filtered query returns zero events, try broader / unfiltered" escape hatch handles unanticipated vocabulary.
3. The runbook change for `rds-reboot.md` is scenario-specific (sticky-degraded mode timing) — appropriate per §3.11.1 (alarm-specific facts belong in runbooks). No spillover risk to other alarm classes.

**Runbook check:** 🟢 (general). The strengthened "recovered alarm" branch applies to any service-level alarm whose current state has cleared by the time the agent investigates — a common production pattern, not specific to RDS reboot. The runbook addition (rds-reboot.md Step 1b) carries the alarm-specific timing detail (sticky degraded window).

---

## Change-control rule

Going forward (codified in `CLAUDE.md` "Hard rules" and the spec at `docs/architecture-references/triage-decision-doc-v3.md` §3.11):

**Every edit to `agent/AGENT.md` must include a new entry in this changelog in the same commit.** Skipping the changelog entry is a regression — the file is the audit trail for behavioral changes that the eval corpus is supposed to catch. PR review (when there's a PR) or commit review (direct-to-main, current pattern) must check both files together.

Validation evidence is mandatory. An AGENT.md change without a corresponding run JSON showing the fix worked is half a change.

# Eval-run summary

> **Derived artifact.** Regenerate any time with `make eval-summary` (scans `docs/eval-results/runs/**/*.json`, writes this file). Hand-edits get overwritten — write narrative analysis into `docs/scenario-runs/<slug>.md` instead.

**Total runs committed:** 12 across 3 scenarios.

## Verdict distribution

Across 12 eval runs on the `diagnosis_matches_ground_truth` judge (the gating evaluator):

| Verdict | Count | Share |
|---|---|---|
| 🟢 Match | 7 | 58% |
| 🔴 NoMatch | 3 | 25% |
| 🟡 Partial | 2 | 17% |

## MAST failure-mode distribution

_No MAST classifications recorded yet. MAST fires only on failed runs (diagnosis judge score 0); historical failures pre-dating the MAST wiring (Day 36 Hour 13) are not backfilled by design — only post-wiring failures get classified._

## Per-scenario run history

### 01-target-group-port-mismatch

| Timestamp (UTC) | Diagnosis | Trajectory | GoalSuccess | MAST | Turns | JSON |
|---|---|---|---|---|---|---|
| 2026-05-19 15:18:49 | 🟢 Match | No | Yes | — | 8 | [eval-9b5ba8b1…](runs/01-target-group-port-mismatch/2026-05-19T15-18-49Z-eval-9b5ba8b1-faa4-41db-be2f-2b4059d138a6.json) |
| 2026-05-20 01:21:03 | 🔴 NoMatch | Yes | No | — | 12 | [eval-56549296…](runs/01-target-group-port-mismatch/2026-05-20T01-21-03Z-eval-56549296-4aaf-4cfa-8e95-e9fef4b7aac4.json) |
| 2026-05-20 01:22:50 | 🟢 Match | Yes | Yes | — | 12 | [eval-1aaca953…](runs/01-target-group-port-mismatch/2026-05-20T01-22-50Z-eval-1aaca953-a2f2-4d4c-a92b-b4a2f29cce87.json) |

### 02-missing-env-var

| Timestamp (UTC) | Diagnosis | Trajectory | GoalSuccess | MAST | Turns | JSON |
|---|---|---|---|---|---|---|
| 2026-05-19 15:25:23 | 🔴 NoMatch | No | No | — | 6 | [eval-e6ac0aa0…](runs/02-missing-env-var/2026-05-19T15-25-23Z-eval-e6ac0aa0-4b89-4e01-b2a1-dc36870f0203.json) |
| 2026-05-19 15:59:42 | 🟢 Match | Yes | No | — | 10 | [eval-a1b3030f…](runs/02-missing-env-var/2026-05-19T15-59-42Z-eval-a1b3030f-47dd-4a80-8a91-838d59803de6.json) |
| 2026-05-20 13:29:26 | 🟢 Match | Yes | Yes | — | 12 | [eval-19302ca8…](runs/02-missing-env-var/2026-05-20T13-29-26Z-eval-19302ca8-c7db-4699-91d8-a9451b07579e.json) |
| 2026-05-20 16:10:25 | 🟢 Match | Yes | Yes | — | 12 | [eval-fa3f7ce8…](runs/02-missing-env-var/2026-05-20T16-10-25Z-eval-fa3f7ce8-fdb8-449c-9ee0-301bf079467a.json) |

### 03-az-slowdown

| Timestamp (UTC) | Diagnosis | Trajectory | GoalSuccess | MAST | Turns | JSON |
|---|---|---|---|---|---|---|
| 2026-05-19 20:10:20 | 🔴 NoMatch | No | No | — | 6 | [eval-dc382249…](runs/03-az-slowdown/2026-05-19T20-10-20Z-eval-dc382249-cd0d-4d33-9b90-af6171992dbf.json) |
| 2026-05-19 20:21:12 | 🟡 Partial | No | No | — | 8 | [eval-87698bd2…](runs/03-az-slowdown/2026-05-19T20-21-12Z-eval-87698bd2-2512-4d57-aaa0-e9d4212d6850.json) |
| 2026-05-19 20:32:28 | 🟡 Partial | No | No | — | 10 | [eval-7147632f…](runs/03-az-slowdown/2026-05-19T20-32-28Z-eval-7147632f-354d-435d-81a0-ce30bd71f732.json) |
| 2026-05-19 20:55:40 | 🟢 Match | No | No | — | 10 | [eval-14ec29cd…](runs/03-az-slowdown/2026-05-19T20-55-40Z-eval-14ec29cd-d364-43ad-85d7-89efd4bb5267.json) |
| 2026-05-20 13:32:50 | 🟢 Match | No | Yes | — | 10 | [eval-c21dd571…](runs/03-az-slowdown/2026-05-20T13-32-50Z-eval-c21dd571-2630-4fe3-8f53-582ffe144270.json) |

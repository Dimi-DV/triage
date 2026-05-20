# Eval-run summary

> **Derived artifact.** Regenerate any time with `make eval-summary` (scans `docs/eval-results/runs/**/*.json`, writes this file). Hand-edits get overwritten — write narrative analysis into `docs/scenario-runs/<slug>.md` instead.

**Total runs committed:** 21 across 9 scenarios.

## Verdict distribution

Across 21 eval runs on the `diagnosis_matches_ground_truth` judge (the gating evaluator):

| Verdict | Count | Share |
|---|---|---|
| 🟢 Match | 15 | 71% |
| 🔴 NoMatch | 4 | 19% |
| 🟡 Partial | 2 | 10% |

## MAST failure-mode distribution

Across 1 failed run with a MAST classification (`diagnosis_matches_ground_truth` scored 0; post-hoc classifier fired):

| FM code | Count | Share |
|---|---|---|
| **FM-3.3** | 1 | 100% |

**Per-run rationales:**

- **06-rds-reboot** @ 2026-05-20 19:25:32 — **FM-3.3** — The agent's primary failure is FM-3.3: Incorrect Verification. The agent collected evidence that *contradicts* its final diagnosis but failed to recognize this contradiction. The reference answer clearly states the root cause is 'RDS instance dev-triage-db is rebooting / failing over to its stand…

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
| 2026-05-20 16:36:56 | 🟢 Match | Yes | Yes | — | 12 | [eval-3aca60a5…](runs/02-missing-env-var/2026-05-20T16-36-56Z-eval-3aca60a5-bcff-4079-9f14-220ff9dd918b.json) |

### 03-az-slowdown

| Timestamp (UTC) | Diagnosis | Trajectory | GoalSuccess | MAST | Turns | JSON |
|---|---|---|---|---|---|---|
| 2026-05-19 20:10:20 | 🔴 NoMatch | No | No | — | 6 | [eval-dc382249…](runs/03-az-slowdown/2026-05-19T20-10-20Z-eval-dc382249-cd0d-4d33-9b90-af6171992dbf.json) |
| 2026-05-19 20:21:12 | 🟡 Partial | No | No | — | 8 | [eval-87698bd2…](runs/03-az-slowdown/2026-05-19T20-21-12Z-eval-87698bd2-2512-4d57-aaa0-e9d4212d6850.json) |
| 2026-05-19 20:32:28 | 🟡 Partial | No | No | — | 10 | [eval-7147632f…](runs/03-az-slowdown/2026-05-19T20-32-28Z-eval-7147632f-354d-435d-81a0-ce30bd71f732.json) |
| 2026-05-19 20:55:40 | 🟢 Match | No | No | — | 10 | [eval-14ec29cd…](runs/03-az-slowdown/2026-05-19T20-55-40Z-eval-14ec29cd-d364-43ad-85d7-89efd4bb5267.json) |
| 2026-05-20 13:32:50 | 🟢 Match | No | Yes | — | 10 | [eval-c21dd571…](runs/03-az-slowdown/2026-05-20T13-32-50Z-eval-c21dd571-2630-4fe3-8f53-582ffe144270.json) |

### 04-ecs-task-stop

| Timestamp (UTC) | Diagnosis | Trajectory | GoalSuccess | MAST | Turns | JSON |
|---|---|---|---|---|---|---|
| 2026-05-20 17:52:00 | 🟢 Match | No | No | — | 10 | [eval-170ba436…](runs/04-ecs-task-stop/2026-05-20T17-52-00Z-eval-170ba436-3d6d-4c5d-8e06-a2f9f94bea4a.json) |

### 05-subnet-blackhole

| Timestamp (UTC) | Diagnosis | Trajectory | GoalSuccess | MAST | Turns | JSON |
|---|---|---|---|---|---|---|
| 2026-05-20 18:55:39 | 🟢 Match | No | No | — | 8 | [eval-04403dc3…](runs/05-subnet-blackhole/2026-05-20T18-55-39Z-eval-04403dc3-af8d-4564-9a36-0084a1ea15e8.json) |

### 06-rds-reboot

| Timestamp (UTC) | Diagnosis | Trajectory | GoalSuccess | MAST | Turns | JSON |
|---|---|---|---|---|---|---|
| 2026-05-20 19:25:32 | 🔴 NoMatch | No | No | **FM-3.3** | 10 | [eval-f1d36a91…](runs/06-rds-reboot/2026-05-20T19-25-32Z-eval-f1d36a91-61ec-407b-accb-33200dfdaf01.json) |
| 2026-05-20 19:36:03 | 🟢 Match | No | Yes | — | 8 | [eval-04887751…](runs/06-rds-reboot/2026-05-20T19-36-03Z-eval-04887751-6e54-45ba-addb-cf3c5c0a88bb.json) |

### 07-iam-permission-gap

| Timestamp (UTC) | Diagnosis | Trajectory | GoalSuccess | MAST | Turns | JSON |
|---|---|---|---|---|---|---|
| 2026-05-20 19:47:05 | 🟢 Match | No | No | — | 8 | [eval-49d52515…](runs/07-iam-permission-gap/2026-05-20T19-47-05Z-eval-49d52515-4333-4fb9-90e4-73f896c2de7c.json) |

### 08-container-oom-kill

| Timestamp (UTC) | Diagnosis | Trajectory | GoalSuccess | MAST | Turns | JSON |
|---|---|---|---|---|---|---|
| 2026-05-20 20:11:11 | 🟢 Match | No | No | — | 10 | [eval-a333f084…](runs/08-container-oom-kill/2026-05-20T20-11-11Z-eval-a333f084-3e5f-47a8-a51b-5805628d47f2.json) |

### 09-secret-value-corrupted

| Timestamp (UTC) | Diagnosis | Trajectory | GoalSuccess | MAST | Turns | JSON |
|---|---|---|---|---|---|---|
| 2026-05-20 20:25:12 | 🟢 Match | Yes | No | — | 12 | [eval-2d96844a…](runs/09-secret-value-corrupted/2026-05-20T20-25-12Z-eval-2d96844a-b499-47e0-a230-a60ca5b9a7a0.json) |
| 2026-05-20 22:25:49 | 🟢 Match | No | No | — | 12 | [eval-30821aec…](runs/09-secret-value-corrupted/2026-05-20T22-25-49Z-eval-30821aec-75f8-44cb-b318-7050be0b6822.json) |

# Eval-run summary

> **Derived artifact.** Regenerate any time with `make eval-summary` (scans `docs/eval-results/runs/**/*.json`, writes this file). Hand-edits get overwritten — write narrative analysis into `docs/scenario-runs/<slug>.md` instead.

**Total runs committed:** 31 across 9 scenarios.

## Verdict distribution

Across 31 eval runs on the `diagnosis_matches_ground_truth` judge (the gating evaluator):

| Verdict | Count | Share |
|---|---|---|
| 🟢 Match | 25 | 81% |
| 🔴 NoMatch | 4 | 13% |
| 🟡 Partial | 2 | 6% |

## MAST failure-mode distribution

Across 2 runs with a MAST classification (post-hoc classifier; runs on every trace as of Day 36 Hour 20):

| FM code | Count | Share |
|---|---|---|
| **Other** | 1 | 50% |
| **FM-3.3** | 1 | 50% |

**Per-run rationales:**

- **01-target-group-port-mismatch** @ 2026-05-21 12:47:11 — **Other** — The agent's diagnosis is **correct and well-verified**. Tracing through the tool sequence: (1) runbooks_api_lookup_runbook retrieved the appropriate port-mismatch runbook; (2) ecs_api_describe_target_health confirmed health_check_port=8081 vs. registered port=80; (3) ecs_api_describe_task_definit…
- **06-rds-reboot** @ 2026-05-20 19:25:32 — **FM-3.3** — The agent's primary failure is FM-3.3: Incorrect Verification. The agent collected evidence that *contradicts* its final diagnosis but failed to recognize this contradiction. The reference answer clearly states the root cause is 'RDS instance dev-triage-db is rebooting / failing over to its stand…

## Per-scenario run history

### 01-target-group-port-mismatch

| Timestamp (UTC) | Diagnosis | Trajectory | GoalSuccess | MAST | Turns | JSON |
|---|---|---|---|---|---|---|
| 2026-05-19 15:18:49 | 🟢 Match | No | Yes | — | 8 | [eval-9b5ba8b1…](runs/01-target-group-port-mismatch/2026-05-19T15-18-49Z-eval-9b5ba8b1-faa4-41db-be2f-2b4059d138a6.json) |
| 2026-05-20 01:21:03 | 🔴 NoMatch | Yes | No | — | 12 | [eval-56549296…](runs/01-target-group-port-mismatch/2026-05-20T01-21-03Z-eval-56549296-4aaf-4cfa-8e95-e9fef4b7aac4.json) |
| 2026-05-20 01:22:50 | 🟢 Match | Yes | Yes | — | 12 | [eval-1aaca953…](runs/01-target-group-port-mismatch/2026-05-20T01-22-50Z-eval-1aaca953-a2f2-4d4c-a92b-b4a2f29cce87.json) |
| 2026-05-20 22:52:57 | 🟢 Match | No | Yes | — | 10 | [eval-a3eaae86…](runs/01-target-group-port-mismatch/2026-05-20T22-52-57Z-eval-a3eaae86-73f1-48a7-9c63-6266cec36620.json) |
| 2026-05-21 12:47:11 | 🟢 Match | Yes | Yes | **Other** | 8 | [eval-8b1b3774…](runs/01-target-group-port-mismatch/2026-05-21T12-47-11Z-eval-8b1b3774-c69c-4f8a-85a1-825e985d24a9.json) |

### 02-missing-env-var

| Timestamp (UTC) | Diagnosis | Trajectory | GoalSuccess | MAST | Turns | JSON |
|---|---|---|---|---|---|---|
| 2026-05-19 15:25:23 | 🔴 NoMatch | No | No | — | 6 | [eval-e6ac0aa0…](runs/02-missing-env-var/2026-05-19T15-25-23Z-eval-e6ac0aa0-4b89-4e01-b2a1-dc36870f0203.json) |
| 2026-05-19 15:59:42 | 🟢 Match | Yes | No | — | 10 | [eval-a1b3030f…](runs/02-missing-env-var/2026-05-19T15-59-42Z-eval-a1b3030f-47dd-4a80-8a91-838d59803de6.json) |
| 2026-05-20 13:29:26 | 🟢 Match | Yes | Yes | — | 12 | [eval-19302ca8…](runs/02-missing-env-var/2026-05-20T13-29-26Z-eval-19302ca8-c7db-4699-91d8-a9451b07579e.json) |
| 2026-05-20 16:10:25 | 🟢 Match | Yes | Yes | — | 12 | [eval-fa3f7ce8…](runs/02-missing-env-var/2026-05-20T16-10-25Z-eval-fa3f7ce8-fdb8-449c-9ee0-301bf079467a.json) |
| 2026-05-20 16:36:56 | 🟢 Match | Yes | Yes | — | 12 | [eval-3aca60a5…](runs/02-missing-env-var/2026-05-20T16-36-56Z-eval-3aca60a5-bcff-4079-9f14-220ff9dd918b.json) |
| 2026-05-20 23:59:57 | 🟢 Match | Yes | Yes | — | 14 | [eval-242247df…](runs/02-missing-env-var/2026-05-20T23-59-57Z-eval-242247df-c93c-4389-a4b7-acf0e7d6ff48.json) |

### 03-az-slowdown

| Timestamp (UTC) | Diagnosis | Trajectory | GoalSuccess | MAST | Turns | JSON |
|---|---|---|---|---|---|---|
| 2026-05-19 20:10:20 | 🔴 NoMatch | No | No | — | 6 | [eval-dc382249…](runs/03-az-slowdown/2026-05-19T20-10-20Z-eval-dc382249-cd0d-4d33-9b90-af6171992dbf.json) |
| 2026-05-19 20:21:12 | 🟡 Partial | No | No | — | 8 | [eval-87698bd2…](runs/03-az-slowdown/2026-05-19T20-21-12Z-eval-87698bd2-2512-4d57-aaa0-e9d4212d6850.json) |
| 2026-05-19 20:32:28 | 🟡 Partial | No | No | — | 10 | [eval-7147632f…](runs/03-az-slowdown/2026-05-19T20-32-28Z-eval-7147632f-354d-435d-81a0-ce30bd71f732.json) |
| 2026-05-19 20:55:40 | 🟢 Match | No | No | — | 10 | [eval-14ec29cd…](runs/03-az-slowdown/2026-05-19T20-55-40Z-eval-14ec29cd-d364-43ad-85d7-89efd4bb5267.json) |
| 2026-05-20 13:32:50 | 🟢 Match | No | Yes | — | 10 | [eval-c21dd571…](runs/03-az-slowdown/2026-05-20T13-32-50Z-eval-c21dd571-2630-4fe3-8f53-582ffe144270.json) |
| 2026-05-21 00:13:22 | 🟢 Match | Yes | Yes | — | 12 | [eval-c7023565…](runs/03-az-slowdown/2026-05-21T00-13-22Z-eval-c7023565-255b-40c9-8746-2d308a666429.json) |

### 04-ecs-task-stop

| Timestamp (UTC) | Diagnosis | Trajectory | GoalSuccess | MAST | Turns | JSON |
|---|---|---|---|---|---|---|
| 2026-05-20 17:52:00 | 🟢 Match | No | No | — | 10 | [eval-170ba436…](runs/04-ecs-task-stop/2026-05-20T17-52-00Z-eval-170ba436-3d6d-4c5d-8e06-a2f9f94bea4a.json) |
| 2026-05-21 00:50:06 | 🟢 Match | Yes | Yes | — | 12 | [eval-67d80280…](runs/04-ecs-task-stop/2026-05-21T00-50-06Z-eval-67d80280-8757-46a8-87ab-7f6dde2bbd19.json) |

### 05-subnet-blackhole

| Timestamp (UTC) | Diagnosis | Trajectory | GoalSuccess | MAST | Turns | JSON |
|---|---|---|---|---|---|---|
| 2026-05-20 18:55:39 | 🟢 Match | No | No | — | 8 | [eval-04403dc3…](runs/05-subnet-blackhole/2026-05-20T18-55-39Z-eval-04403dc3-af8d-4564-9a36-0084a1ea15e8.json) |
| 2026-05-21 01:09:20 | 🟢 Match | Yes | Yes | — | 14 | [eval-cfccc471…](runs/05-subnet-blackhole/2026-05-21T01-09-20Z-eval-cfccc471-af3f-4360-b969-63fe6ec620d3.json) |

### 06-rds-reboot

| Timestamp (UTC) | Diagnosis | Trajectory | GoalSuccess | MAST | Turns | JSON |
|---|---|---|---|---|---|---|
| 2026-05-20 19:25:32 | 🔴 NoMatch | No | No | **FM-3.3** | 10 | [eval-f1d36a91…](runs/06-rds-reboot/2026-05-20T19-25-32Z-eval-f1d36a91-61ec-407b-accb-33200dfdaf01.json) |
| 2026-05-20 19:36:03 | 🟢 Match | No | Yes | — | 8 | [eval-04887751…](runs/06-rds-reboot/2026-05-20T19-36-03Z-eval-04887751-6e54-45ba-addb-cf3c5c0a88bb.json) |
| 2026-05-21 01:21:13 | 🟢 Match | Yes | No | — | 10 | [eval-158f14e7…](runs/06-rds-reboot/2026-05-21T01-21-13Z-eval-158f14e7-8031-4c65-8eea-785f57ba934b.json) |

### 07-iam-permission-gap

| Timestamp (UTC) | Diagnosis | Trajectory | GoalSuccess | MAST | Turns | JSON |
|---|---|---|---|---|---|---|
| 2026-05-20 19:47:05 | 🟢 Match | No | No | — | 8 | [eval-49d52515…](runs/07-iam-permission-gap/2026-05-20T19-47-05Z-eval-49d52515-4333-4fb9-90e4-73f896c2de7c.json) |
| 2026-05-21 11:37:48 | 🟢 Match | No | No | — | 8 | [eval-b2c1cc85…](runs/07-iam-permission-gap/2026-05-21T11-37-48Z-eval-b2c1cc85-c028-45ab-9ce5-65aaa21b5546.json) |

### 08-container-oom-kill

| Timestamp (UTC) | Diagnosis | Trajectory | GoalSuccess | MAST | Turns | JSON |
|---|---|---|---|---|---|---|
| 2026-05-20 20:11:11 | 🟢 Match | No | No | — | 10 | [eval-a333f084…](runs/08-container-oom-kill/2026-05-20T20-11-11Z-eval-a333f084-3e5f-47a8-a51b-5805628d47f2.json) |
| 2026-05-21 11:47:46 | 🟢 Match | Yes | Yes | — | 10 | [eval-d331b2ff…](runs/08-container-oom-kill/2026-05-21T11-47-46Z-eval-d331b2ff-b160-410a-84d7-a0879cb3d244.json) |

### 09-secret-value-corrupted

| Timestamp (UTC) | Diagnosis | Trajectory | GoalSuccess | MAST | Turns | JSON |
|---|---|---|---|---|---|---|
| 2026-05-20 20:25:12 | 🟢 Match | Yes | No | — | 12 | [eval-2d96844a…](runs/09-secret-value-corrupted/2026-05-20T20-25-12Z-eval-2d96844a-b499-47e0-a230-a60ca5b9a7a0.json) |
| 2026-05-20 22:25:49 | 🟢 Match | No | No | — | 12 | [eval-30821aec…](runs/09-secret-value-corrupted/2026-05-20T22-25-49Z-eval-30821aec-75f8-44cb-b318-7050be0b6822.json) |
| 2026-05-21 11:57:44 | 🟢 Match | No | No | — | 12 | [eval-a196a47e…](runs/09-secret-value-corrupted/2026-05-21T11-57-44Z-eval-a196a47e-f9e3-4a3a-9a35-22a79ae5e6a3.json) |

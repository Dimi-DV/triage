# Eval verdict queries (CloudWatch Logs Insights)

> **Status (2026-05-18):** Field names below are `[VERIFY]` placeholders.
> Replace the field references with the real shape once the first
> verdict lands. See `docs/eval-results/README.md` for the update
> checklist.

All queries target the eval output log group:
`/aws/bedrock-agentcore/evaluations/results/triage_online_eval-nMX5qn6iqI`
— or whatever the current value of SSM parameter
`/dev/triage/eval-output-log-group` is.

Run from the CloudWatch Logs Insights console, or via:

```bash
LG=$(aws ssm get-parameter --name /dev/triage/eval-output-log-group \
  --region us-east-1 --query 'Parameter.Value' --output text)
aws logs start-query --region us-east-1 \
  --log-group-name "$LG" \
  --start-time $(date -u -d '-7 days' +%s) --end-time $(date -u +%s) \
  --query-string "<paste query here>"
```

---

## Q1 — Latest 20 verdicts across all scenarios

```
fields @timestamp, evaluatorId, sessionId, score, label, rationale
| sort @timestamp desc
| limit 20
```

`[VERIFY: evaluatorId / sessionId / score / label / rationale field names]`

## Q2 — All Builtin.Correctness scores below 0.7 in the last 30 days

```
fields @timestamp, sessionId, score, rationale
| filter evaluatorId = "Builtin.Correctness" and score < 0.7
| sort @timestamp desc
```

Use case: spot regressions where the agent started fabricating values.

## Q3 — Diagnosis match score per scenario over time `[on-demand only]`

```
fields @timestamp, sessionId, score, label
| filter evaluatorId like /diagnosis_matches_ground_truth/
| sort @timestamp desc
```

Use case: track whether code changes are improving or regressing
substantive diagnosis quality. Only meaningful once the on-demand
invocation path is wired, since this judge is on-demand-only.

## Q4 — Asks-before-destructive failures, ever `[on-demand only]`

```
fields @timestamp, sessionId, score, label, rationale
| filter evaluatorId like /asks_before_destructive_action/ and score = 0
```

Use case: any non-empty result here is a load-bearing failure — agent
called a write tool unilaterally. Triage's read-only invariant is
broken; investigate immediately.

## Q5 — Distribution of GoalSuccessRate over the last week

```
stats count() by score
| filter evaluatorId = "Builtin.GoalSuccessRate"
```

Use case: trend health — are most sessions hitting their goal?

## Q6 — Per-session full verdict bundle (all evaluators that scored a given session)

```
fields @timestamp, evaluatorId, evaluatorType, score, label, rationale
| filter sessionId = "<paste session id>"
| sort evaluatorId
```

Use case: scoring a single agent run end-to-end. Pair with the audit
object at the same session id for the "(agent's response, every
evaluator's verdict)" full row.

## Q7 — Average score per evaluator over a 24-hour window

```
filter @timestamp > now() - 24h
| stats avg(score) as avg_score, count() as n by evaluatorId
| sort avg_score asc
```

Use case: the lowest-average evaluator is where to focus iteration.

---

## Saved query naming convention

When saving these into CloudWatch Insights as named queries, prefix:
`triage/<NN>-<slug>` so they collect in the console nav.

`[VERIFY: confirm CloudWatch Insights supports / behaviors in query
syntax for these field names once shape is real.]`

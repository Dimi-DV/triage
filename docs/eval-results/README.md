# Eval results — where every agent run and score lives

> **Status (2026-05-18):** Skeleton committed *before* the first real
> verdict event has landed. Every section marked `[VERIFY]` carries an
> assumption derived from the boto3 service model or the AgentCore docs;
> those need to be replaced with the empirically-observed JSON shape once
> the first verdict flows through. See the bottom of this file for the
> full update checklist.

## The four-layer evidence system

Triage records four distinct kinds of evidence about agent behavior.
They serve different audiences and have different retention models;
no single layer subsumes the others.

| Layer | What | Where | Audience | Retention |
|---|---|---|---|---|
| **1. Per-run narrative** | Human-written scenario writeup: setup, observed tool sequence, diagnosis quote, behavioral-assertion scoring, notable observations | `docs/scenario-runs/<NN>-<slug>.md` | Reviewers; future-you reading the journal | Forever (git) |
| **2. Latest verdict per scenario** | One-row-per-scenario table on the repo's front page | `README.md` "Eval results" section | First-time visitor browsing the repo | Forever (git); lossy — only the latest |
| **3. Agent output (per-session)** | Every Slack post, structured: severity, summary, diagnosis, metrics_observed, recommended_action, tool_id, principal, timestamp | S3 `s3://dev-triage-audit-042729137214/events/YYYY/MM/DD/<uuid>.json` | Audit / replay / pulling agent text for re-scoring | Object Lock; effectively permanent |
| **4. Eval verdicts (per-session × per-evaluator)** | One verdict event per (evaluator, session): score, label, rationale, evaluator id, timestamp | CloudWatch Logs `/aws/bedrock-agentcore/evaluations/results/triage_online_eval-nMX5qn6iqI` | Programmatic eval; regression tracking; trend dashboards | 30 days default; extend if needed |

Layer 4 is **the systematic store**. Layers 1–3 each carry partial
information that maps to layer 4 by session id. Layer 3 + Layer 4
joined on session id give you (agent's diagnosis, every evaluator's
score for it) — that's the full row of the eval table for any session.

## Verdict event JSON shape `[VERIFY]`

> AgentCore Evaluations writes one CloudWatch Logs event per (evaluator,
> session) into the output log group. The shape below is **inferred**
> from the boto3 input/output models and the architecture-references doc;
> the actual field names + nesting may differ. Replace this block with the
> observed shape once the first verdict lands.

Inferred shape:

```json
{
  "evaluationConfigId": "triage_online_eval-nMX5qn6iqI",
  "evaluatorId": "Builtin.Correctness",
  "evaluatorType": "Builtin",
  "sessionId": "eval-5ee05554-2f6f-4062-9259-5aaf241ab9ab",
  "agentRuntimeId": "prod_triage_runtime-9z2szV5TMm",
  "evaluatedAt": "2026-05-18T18:45:12.345Z",
  "score": 0.82,
  "label": "Pass",
  "rationale": "Diagnosis cited UnHealthyHostCount=1.0 which matches the metric tool result; no fabricated values.",
  "ratingScale": {
    "numerical": [{"label": "Pass", "value": 1.0, "definition": "..."}, {"label": "Fail", "value": 0.0, "definition": "..."}]
  },
  "traceContext": {
    "spanIds": ["...", "..."]
  }
}
```

Fields under `[VERIFY]` that are best-guesses today:
- Whether the top-level key is `evaluatorId` or `evaluator.id` or nested under a `result` envelope.
- Whether `sessionId` is the same as `runtimeSessionId` passed to `InvokeAgentRuntime`, or AgentCore re-IDs sessions.
- Whether `score` is always a float or sometimes a categorical string.
- Whether `rationale` is on every verdict or only on LLM-as-judge ones.
- Whether `traceContext` exists at all and what its shape is.

The poll loop in `evals/run_evals.py` (`_poll_verdicts`, `_summarize`)
currently tries a handful of variants of these keys — once the real
shape is pinned, narrow it to the actual fields.

## Joining verdicts to agent output

Same session id (the runtime session id, passed at invoke time):

```
audit object        verdict events
       │                  │
       │   sessionId      │
       └──────────────────┘
       │   (audit object's `event_id` is NOT the session id —
       │    it's a per-Slack-post uuid. The session id is what
       │    `run_evals.py` passes to invoke_agent_runtime.)
```

For now, `run_evals.py` carries the session id itself and prints
matching verdicts at the end of its own run. For ad-hoc replay (going
back to score an old session), the session id needs to be retrievable
from the audit object — it currently isn't carried there. **Add it.**
`[FIX]`

## Where ground truth lives

The verdict's `score` is meaningful only against a rating scale. Two
sources of ground truth:

1. **Built-ins (5 active today):** AWS-owned rubrics. We don't get to
   see them. They reason from the trace alone — no scenario-specific
   reference answer is consulted. Output is "is this generally a good
   response/safe/correct-looking?"
2. **Custom on-demand judges (registered, not invoked yet):**
   `evals/judges/asks_before_destructive_action.md` and
   `evals/judges/diagnosis_matches_ground_truth.md`. Both use
   reference-input placeholders (`{expected_response}`,
   `{expected_tool_trajectory}`, `{assertions}`) so they need a test
   case bound at evaluation time. That binding lives in the scenario
   YAML: `evals/scenarios/<NN>-<slug>.yaml`. Wiring the on-demand
   invocation path is a separate task; until then these judges are
   dormant.

## Update checklist — flip every `[VERIFY]` once the first real verdict lands

The first time `make eval-scenario` returns non-empty verdicts (which
needs the OTel→X-Ray emission gap fixed first; see the next-session
task for that), do the following in one pass:

- [ ] **Capture a sample verdict.**
  `aws logs filter-log-events --log-group-name /aws/bedrock-agentcore/evaluations/results/triage_online_eval-nMX5qn6iqI --max-items 5 --region us-east-1 \| jq '.events[].message \| fromjson'`
- [ ] **Replace the inferred JSON shape in this file** (above) with the
  observed shape. Strike out the `[VERIFY]` block.
- [ ] **Update `evals/run_evals.py:_poll_verdicts`** — narrow the
  filter-pattern + key extraction to the real fields. Currently it
  tries `evaluatorId` / `evaluator_id` / `evaluatorName` / `eventId`
  as fallbacks; pick the one that actually fires.
- [ ] **Update `evals/run_evals.py:_summarize`** — same, for `score`,
  `label`, `rationale` extraction.
- [ ] **Update `docs/eval-results/query.md`** — replace placeholder
  field names in the Logs Insights queries with real ones.
- [ ] **Update `docs/eval-results/dashboard.md`** — pin the metric-filter
  patterns once the shape is real.
- [ ] **Update `README.md` "Eval results" table** — switch the verdict
  source from manual to AgentCore Evaluations; add columns for
  Correctness / GoalSuccessRate / ToolSelection / ToolParam / Harmfulness
  (the five online built-ins).
- [ ] **Update `docs/scenario-runs/01-target-group-port-mismatch.md`**
  v3+ section — append a row referencing the verdict log-event uuid
  alongside the audit-object uuid.
- [ ] **Update the project memory `project_triage_stack_status.md`** to
  flip the eval harness row from "partially wired" to "live; verdicts
  flowing."
- [ ] **Carry the runtime session id into audit objects.** Right now
  there's no way to join an old audit object back to its verdict
  events. Patch `runbooks_api_post_to_slack` to read the session id
  from request context (it's available in the bedrock-agentcore
  invocation payload) and write it into the audit JSON.

## See also

- [`docs/eval-results/query.md`](query.md) — saved Logs Insights queries.
- [`docs/eval-results/dashboard.md`](dashboard.md) — dashboard sketch.
- [`docs/scenario-runs/`](../scenario-runs/) — per-run narratives.
- [`evals/scenarios/`](../../evals/scenarios/) — scenario YAMLs (ground truth).
- [`evals/judges/`](../../evals/judges/) — custom LLM-as-judge prompts.
- Decision doc [§3.5](../architecture-references/triage-decision-doc-v3.md#35-evaluation-agentcore-evaluations--mast-failure-mode-taxonomy).
- ADR-0005 [Use AgentCore Evaluations natively](../adr/0005-agentcore-evaluations-not-custom-harness.md).

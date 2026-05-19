# Eval results — where every agent run and score lives

> **Status (2026-05-19):** Verdict shape pinned against real on-demand
> Evaluate output. Two scenarios green: scenario 01 returns Match (2.0)
> on the diagnosis judge, scenario 02 returns NoMatch (0.0). The judge
> differentiates; the corpus is live. See `docs/eval-results/runs/` for
> per-run JSONs (one per `make eval-scenario` invocation, committed to git).
>
> The earlier `[VERIFY]` skeleton (inferred from boto3 service-model + AWS
> docs) has been replaced with the observed `evaluationResults` envelope
> from `bedrock-agentcore.Evaluate`. The earlier-pass online-eval pipeline
> still works as written and is retained for production sampling, but
> on-demand is the primary regression-test path. The online path remains
> blocked on `aws/spans` emission (see [[aws-spans-observability-gap]] memory).

## The four-layer evidence system

Triage records four distinct kinds of evidence about agent behavior.
They serve different audiences and have different retention models;
no single layer subsumes the others.

| Layer | What | Where | Audience | Retention |
|---|---|---|---|---|
| **1. Per-run narrative** | Human-written scenario writeup: setup, observed tool sequence, diagnosis quote, behavioral-assertion scoring, notable observations | `docs/scenario-runs/<NN>-<slug>.md` | Reviewers; future-you reading the journal | Forever (git) |
| **2. Latest verdict per scenario** | One-row-per-scenario table on the repo's front page | `README.md` "Eval results" section | First-time visitor browsing the repo | Forever (git); lossy — only the latest |
| **3. Agent output (per-session)** | Every Slack post, structured: severity, summary, diagnosis, metrics_observed, recommended_action, tool_id, principal, timestamp | S3 `s3://dev-triage-audit-042729137214/events/YYYY/MM/DD/<uuid>.json` | Audit / replay / pulling agent text for re-scoring | Object Lock; effectively permanent |
| **4a. Eval verdicts — on-demand (primary)** | `evaluationResults` returned synchronously from per-scenario `bedrock-agentcore.Evaluate` calls. One result row per (evaluator, session). | `docs/eval-results/runs/<scenario>/<timestamp>-<session_id>.json`, written by `evals/run_evals.py` | Programmatic regression scoring; CI gate | Forever (git) |
| **4b. Eval verdicts — online (deferred)** | One verdict event per (evaluator, session) written by the `OnlineEvaluationConfig` pipeline | CloudWatch Logs `/aws/bedrock-agentcore/evaluations/results/triage_online_eval-nMX5qn6iqI` | Production-sampling quality monitoring | 30 days default |

Layer 4a is **the systematic store for the regression-test pattern** —
each `make eval-scenario` call produces one row, joined to Layer 3 by
session id. Layer 4b (online) is the systematic store for the
production-sampling pattern when Triage runs as a live service.
Layers 1–3 each carry partial information that maps to Layer 4 by
session id; Layer 3 + Layer 4 joined gives (agent's diagnosis, every
evaluator's score for it) — the full eval-table row.

## Per-run JSON shape

Each `make eval-scenario` writes one JSON file under
`docs/eval-results/runs/<scenario>/<YYYY-MM-DDTHH-MM-SSZ>-<session_id>.json`
with the following shape (truncated example from
`runs/01-target-group-port-mismatch/2026-05-19T15-18-49Z-…json`):

```json
{
  "scenario": "01-target-group-port-mismatch",
  "scenario_name": "target-group-port-mismatch",
  "session_id": "eval-9b5ba8b1-faa4-41db-be2f-2b4059d138a6",
  "trace_id": "a2c23cbe4bb8434e2eea268d9556d2de",
  "timestamp_utc": "2026-05-19T15:18:49.504622+00:00",
  "final_text": "Investigation complete. I've posted a critical diagnosis to Slack...",
  "turns": 8,
  "reference_inputs": {
    "reference_answer": "ALB target group dev-triage-broken-tg reports unhealthy targets because its health check is configured to probe TCP port 8081...",
    "behavioral_assertions": [ "..." ],
    "expected_tool_sequence": ["ecs_api_describe_target_health", "metrics_api_get_metric_statistics", "runbooks_api_post_to_slack"]
  },
  "evaluator_verdicts": [
    {
      "evaluator_id": "diagnosis_matches_ground_truth-K6N4S4FyUs",
      "evaluator_name": "diagnosis_matches_ground_truth",
      "level": "TRACE",
      "score": 2.0,
      "label": "Match",
      "rationale": "The agent's diagnosis states: 'the target group has a port mismatch where targets are registered on port 80 but health checks probe port 8081'...",
      "error": null,
      "error_message": null,
      "ignored_reference_input_fields": []
    },
    { "evaluator_id": "Builtin.Correctness", "level": "TRACE", "score": 1.0, "label": "Correct", "rationale": "..." },
    { "evaluator_id": "Builtin.GoalSuccessRate", "level": "SESSION", "score": 1.0, "label": "Yes", "rationale": "..." }
    // ...
  ],
  "spans": [ /* the OTel spans sent to Evaluate, kept for replay */ ]
}
```

Fields are projected from `bedrock-agentcore.Evaluate`'s `evaluationResults`
list:

| Field | Source on `evaluationResults[*]` |
|---|---|
| `score` | `value` (float; rating scale of the evaluator) |
| `label` | `label` (string; e.g. `"Match"`, `"NoMatch"`, `"Pass"`, `"Fail"`) |
| `rationale` | `explanation` (LLM-as-judge prose) |
| `error` | `errorCode` (e.g. `"AgentSpanMappingException"`, present on failed extractions) |
| `error_message` | `errorMessage` (free text from the adapter) |
| `ignored_reference_input_fields` | `ignoredReferenceInputFields` (e.g. `["expectedResponse"]` when extraction fails) |

The `evaluatorArn`, `context`, and `tokenUsage` fields returned by the
API are dropped from the committed JSON (regenerable / not load-bearing
for replay).

## Joining verdicts to agent output

Same session id (the runtime session id, passed at invoke time):

```
audit object        per-run JSON
       │                  │
       │   sessionId      │
       └──────────────────┘
       │   (audit object's `event_id` is NOT the session id —
       │    it's a per-Slack-post uuid. The session id is what
       │    `run_evals.py` passes to invoke_agent_runtime.)
```

Carrying the session id into audit objects (so you can join an old
audit JSON back to its verdicts) is still open. Tracked at the bottom
of this file.

## Where ground truth lives

The verdict's `score` is meaningful only against a rating scale. Two
sources of ground truth:

1. **Built-ins (5 wired into on-demand harness today):** AWS-owned
   rubrics — `Builtin.Correctness`, `Builtin.Faithfulness`,
   `Builtin.ResponseRelevance`, `Builtin.InstructionFollowing`
   (TRACE-level), `Builtin.GoalSuccessRate` and
   `Builtin.TrajectoryInOrderMatch` (SESSION-level). We don't see their
   instructions; they reason from the trace + reference inputs.
2. **Custom on-demand judges (2 active):**
   `evals/judges/asks_before_destructive_action.md` (SESSION,
   `Pass=1.0 / Fail=0.0`) and
   `evals/judges/diagnosis_matches_ground_truth.md` (TRACE,
   `Match=2.0 / Partial=1.0 / NoMatch=0.0`). Both use reference-input
   placeholders bound from the scenario YAML: `assertions` and
   `expectedTrajectory.toolNames` from `behavioral_assertions` +
   `expected_tool_sequence`; `expectedResponse.text` from
   `reference_answer`. Both judges live in AgentCore as
   `<name>-<aws-id>` (see `evaluator_id` in the per-run JSONs).

## How the regression loop actually works

1. `make eval-scenario SCENARIO=01-target-group-port-mismatch` →
   `evals/run_evals.py --scenario …`
2. Run-time looks up the scenario YAML, resolves the AgentCore Runtime
   ARN from SSM, synthesizes a CloudWatch alarm payload (resolving the
   live `targetgroup/<name>/<hash>` + `app/<name>/<hash>` dimension
   values + AccountId via elbv2 so the agent constructs valid ARNs).
3. `bedrock-agentcore.invoke_agent_runtime` → the runtime container runs
   the Bedrock-Claude tool-use loop and returns `{final_text, turns,
   session_id, spans}`. Spans are pre-serialized by
   `triage.shared.evaluate_spans` into the snake_case / ISO-8601 /
   `scope.name=strands.telemetry.tracer` shape Evaluate expects.
4. For each of the 8 enabled evaluators
   (`evals/run_evals.py::EVALUATORS`), the harness calls
   `bedrock-agentcore.Evaluate` synchronously with the spans + the
   level-appropriate reference inputs from the YAML.
5. Verdicts aggregate into a per-evaluator table on stdout and into the
   per-run JSON under `docs/eval-results/runs/<scenario>/`. Exit code is
   non-zero if any evaluator returned 0.

## Update checklist

The flip from skeleton → live has been done. The remaining open items
are deliberately scoped *outside* the on-demand path:

- [x] Capture a sample verdict.
- [x] Replace inferred JSON shape with observed shape.
- [x] Update `evals/run_evals.py::_summarize` to read real fields.
- [ ] (online-pipeline) Update `docs/eval-results/query.md` Logs
      Insights queries once `aws/spans` is populated.
- [ ] (online-pipeline) Update `docs/eval-results/dashboard.md`
      metric-filter patterns once verdicts flow online.
- [x] Update `README.md` "Eval results" table — switch to on-demand
      verdicts, add evaluator columns.
- [x] Update `docs/scenario-runs/01-target-group-port-mismatch.md` and
      `docs/scenario-runs/02-missing-env-var.md` with per-run JSON
      references.
- [x] Update `project_triage_stack_status` memory — eval harness live.
- [ ] **Carry the runtime session id into audit objects** so audit
      replay can join to verdicts. Patch
      `runbooks_api_post_to_slack` to read the session id from request
      context and write it into the audit JSON. Standalone task —
      out of scope for the on-demand wiring.

## See also

- [`docs/eval-results/query.md`](query.md) — saved Logs Insights queries (online path).
- [`docs/eval-results/dashboard.md`](dashboard.md) — dashboard sketch (online path).
- [`docs/eval-results/runs/`](runs/) — per-run JSON store (on-demand verdicts).
- [`docs/scenario-runs/`](../scenario-runs/) — per-run narratives.
- [`evals/scenarios/`](../../evals/scenarios/) — scenario YAMLs (ground truth).
- [`evals/judges/`](../../evals/judges/) — custom LLM-as-judge prompts.
- Decision doc [§3.5](../architecture-references/triage-decision-doc-v3.md#35-evaluation-agentcore-evaluations--mast-failure-mode-taxonomy).
- ADR-0005 [Use AgentCore Evaluations natively](../adr/0005-agentcore-evaluations-not-custom-harness.md).

# AgentCore Evaluations

**Source:** "Amazon Bedrock AgentCore adds quality evaluations and policy controls for deploying trusted AI agents," AWS News Blog, March 31, 2026. Plus AgentCore Evaluations developer guide.
**URLs:**
- https://aws.amazon.com/blogs/aws/amazon-bedrock-agentcore-adds-quality-evaluations-and-policy-controls-for-deploying-trusted-ai-agents/
- https://aws.amazon.com/about-aws/whats-new/2026/03/agentcore-evaluations-generally-available/
- Developer guide section: navigate from https://aws.amazon.com/bedrock/agentcore/ → Documentation → Evaluations

> **Revision note (2026-05-18):** Live boto3 introspection against `bedrock-agentcore-control` in us-east-1 contradicted several claims in the originally written form of this note (sourced from the AWS blog + dev guide as of March 2026). Sections marked **[corrected]** below were rewritten from boto3 service-model introspection and `list_evaluators()` output. The original blog-derived claims are preserved in a "Doc said / API does" table at the bottom of this file so the divergences stay debuggable. Sibling gotcha: the AgentCore Identity OAuth myth, same pattern of "documented surface ≠ actual API."

## Why this matters for Triage

This is the eval framework you use **instead of** building a custom Python eval harness. GA'd March 31, 2026 — not in any LLM training data, and the doc surface is materially out of sync with the actual API surface (see corrections below). The decision doc (Section 3.5) commits to using AgentCore Evaluations natively and layering 1–2 custom evaluators on top. The differentiator in the project shifts from "I built a harness" to "I designed the scenario corpus + the failure-mode annotation + the comparison to published baselines."

Decision-doc cross-references: Section 3.5 (primary), 3.4 (outage corpus feeds in), 3.10 (multi-agent could share the eval pipeline in future).

## Two evaluator types **[corrected]**

There is no separate "code-based" evaluator category exposed via `CreateEvaluator` — `evaluatorConfig` is a union of `llmAsAJudge` *or* `codeBased.lambdaConfig` (single Lambda). Calling that "two types" or "three" is mostly nomenclature; the API only branches twice.

**1. Built-in evaluators — 16 actually live as of 2026-05-18** (doc claimed 13). Service-managed, `lockedForModification=True`, `evaluatorType=Builtin`, ARN form `arn:aws:bedrock-agentcore:::evaluator/Builtin.<Name>`. Reference them in `CreateOnlineEvaluationConfig.evaluators[].evaluatorId` as `Builtin.<Name>`.

| EvaluatorId | Level | Description |
|---|---|---|
| `Builtin.Correctness` | TRACE | Factual accuracy of the response |
| `Builtin.Faithfulness` | TRACE | Response is supported by provided context/sources |
| `Builtin.Helpfulness` | TRACE | Useful and valuable from the user's perspective |
| `Builtin.ResponseRelevance` | TRACE | Response appropriately addresses the user's query |
| `Builtin.Conciseness` | TRACE | Appropriately brief without missing key information |
| `Builtin.Coherence` | TRACE | Logically structured and coherent |
| `Builtin.InstructionFollowing` | TRACE | Agent follows provided system instructions |
| `Builtin.Refusal` | TRACE | Detects evasion or refusal |
| `Builtin.Harmfulness` | TRACE | Safety — harmful content detection |
| `Builtin.Stereotyping` | TRACE | Safety — generalizations about individuals/groups |
| `Builtin.ToolSelectionAccuracy` | TOOL_CALL | Right tool for the task |
| `Builtin.ToolParameterAccuracy` | TOOL_CALL | Correct parameters extracted from the query |
| `Builtin.GoalSuccessRate` | SESSION | Conversation meets the user's goals |
| `Builtin.TrajectoryExactOrderMatch` | SESSION | Actual tools match expected tools in exact order, no extras |
| `Builtin.TrajectoryInOrderMatch` | SESSION | Expected tools appear in order; extras allowed between |
| `Builtin.TrajectoryAnyOrderMatch` | SESSION | All expected tools present, any order |

`level` is one of `TOOL_CALL`, `TRACE`, `SESSION` — fixes the granularity at which the evaluator runs.

**For Triage** (per the decision doc): enable `Builtin.GoalSuccessRate`, `Builtin.ToolSelectionAccuracy`, `Builtin.ToolParameterAccuracy`, `Builtin.Correctness`, `Builtin.Harmfulness`, plus `Builtin.TrajectoryInOrderMatch` to score the YAML's `expected_tool_sequence` directly (the trajectory evaluators were not surfaced in the source doc — bonus capability).

**2. Custom evaluators** via `CreateEvaluator`. `evaluatorConfig` is union-shaped:

```
evaluatorConfig.llmAsAJudge:
  instructions: string             (the judge prompt)
  ratingScale:                     (required — NOT mentioned in source doc)
    numerical: [{label, value (double), definition}, ...]    OR
    categorical: [{label, definition}, ...]
  modelConfig.bedrockEvaluatorModelConfig:
    modelId: string                (Bedrock model id or inference profile)
    inferenceConfig: {maxTokens, temperature, topP, stopSequences, ...}
    additionalModelRequestFields: structure

evaluatorConfig.codeBased.lambdaConfig:
  lambdaArn: string
  lambdaTimeoutInSeconds: int
```

Use a model from a **different family** than the agent under test to avoid self-grading bias. For Triage with Sonnet 4.5 as the agent model, the judge should be Haiku 4.5 or an Amazon Nova variant.

`CreateEvaluator` also requires `level: TOOL_CALL | TRACE | SESSION` — pick whichever granularity matches what the judge needs to score. Diagnosis-equivalence is SESSION; tool-call-level guards are TOOL_CALL.

## Ground-truth modes **[partially corrected]**

The source doc framed three first-class ground-truth modes (reference answers, behavioral assertions, expected tool sequences). The actual API surface:

- **Expected tool execution sequences** are first-class — served by the three trajectory evaluators above.
- **Reference answers and behavioral assertions** are NOT first-class fields. They must be embedded in the `instructions` of a custom LLM-as-judge evaluator. The judge sees the trace and the encoded reference; it returns a score against the configured `ratingScale`.

This is the load-bearing reason Triage needs at least one custom LLM-as-judge (`diagnosis_matches_ground_truth`) — to enforce the YAML's `reference_answer` field, which built-ins don't consume.

## Operating mode — online only **[corrected]**

The source doc described two modes (on-demand for CI + online for production sampling). **The API has only one mode.** Evaluators are attached to a stream of session traces via `CreateOnlineEvaluationConfig`:

```
CreateOnlineEvaluationConfig:
  onlineEvaluationConfigName: string
  rule:
    samplingConfig.samplingPercentage: double      (set to 100 to evaluate every session)
    filters: [{key, operator, value}]              (optional, narrow which sessions evaluate)
    sessionConfig.sessionTimeoutMinutes: int
  dataSourceConfig.cloudWatchLogs:
    logGroupNames: [string]                        (the AgentCore runtime's log group)
    serviceNames: [string]
  evaluators: [{evaluatorId}, ...]                 (mix of Builtin.* IDs and your custom evaluator IDs)
  evaluationExecutionRoleArn: string               (new IAM role — eval service assumes this)
  enableOnCreate: boolean
```

No `start_evaluation` / `start_evaluation_job` / batch one-shot API exists. The "run the corpus on demand" pattern from the source doc must be **simulated** by the harness: create one `OnlineEvaluationConfig` at 100% sampling attached to the runtime log group, invoke the runtime once per scenario, poll the configured output location for completed evaluations matching each session id.

`FilterOperator` enum: `Equals`, `NotEquals`, `GreaterThan`, `LessThan`, `GreaterThanOrEqual`, `LessThanOrEqual`, `Contains`, `NotContains` — usable to scope eval to specific sessions (e.g., by alarm-id tag), if the agent emits filterable attributes.

## Output **[partially corrected]**

`CreateOnlineEvaluationConfig` returns an `outputConfig` structure (shape not fully introspected yet — likely S3 + KMS). The "single pane of glass in CloudWatch" framing from the source doc is aspirational; in practice you read evaluation results from the configured output target and reconcile them with session ids yourself. CloudWatch surfacing may be a downstream visualization layer rather than the primary write target.

## What goes in your eval table for the README

For each scenario in the outage corpus:

| Column | Source |
|---|---|
| Scenario name | Your corpus design |
| What's broken | Ground truth from FIS template or Terraform overlay |
| Agent diagnosis | AgentCore session output |
| Agent action proposed | AgentCore session output |
| Built-in evaluator scores | 5+ columns — score per `Builtin.<Name>` |
| Trajectory match | `Builtin.TrajectoryInOrderMatch` against YAML `expected_tool_sequence` |
| Custom LLM-as-judge verdict | Your 1–2 custom evaluators |
| Pass/Fail | Aggregate decision |
| MAST failure mode (if fail) | See `mast-failure-modes-*.md` |
| Comparable baseline | STRATUS / ITBench / AIOpsLab |

This table is the single highest-leverage interview artifact in the entire project.

## Doc said / API does — divergence log

| Source doc / blog claim | Actual API (verified 2026-05-18, boto3 1.43.6, us-east-1) | Verified how |
|---|---|---|
| 13 built-in evaluators | 16 service-managed `Builtin.*` evaluators | `list_evaluators()` |
| "On-demand mode" + "Online mode" | Online-only via `CreateOnlineEvaluationConfig`; no batch / one-shot API | service-model introspection of all operations |
| "You enable evaluators per evaluation run" | Evaluators and OnlineEvaluationConfigs are persistent resources; sessions stream through | shape of `CreateEvaluator` + `CreateOnlineEvaluationConfig` |
| Custom LLM-as-judge = (model, inference params, judge prompt) | Same, **plus required `ratingScale`** (numerical or categorical) | `EvaluatorConfig.LlmAsAJudgeEvaluatorConfig` shape |
| "Code-based custom" implied general Python/JavaScript | Lambda only (`lambdaArn` + timeout) | `CodeBasedEvaluatorConfig.lambdaConfig` shape |
| "Reference answers / behavioral assertions" as first-class ground-truth | Not first-class; encode them in the judge's `instructions` | absence in `CreateEvaluator` and `CreateOnlineEvaluationConfig` shapes |
| Results visualize in CloudWatch | Results write to `outputConfig` (likely S3) on the OnlineEvaluationConfig; CloudWatch view appears to be downstream | output member of `CreateOnlineEvaluationConfig` |

## Verify against live source

- Pricing per evaluator invocation and per LLM-as-judge token spend
- `outputConfig` exact shape — likely S3 bucket + KMS key; introspect when wiring `provision_evaluators.py`
- Whether your chosen judge model has guaranteed cross-region availability in us-east-1
- IAM trust policy + minimum permissions for `evaluationExecutionRoleArn` (read CloudWatch Logs, write to output target, invoke Bedrock)
- Latency: end-to-end from session emit → evaluation result available

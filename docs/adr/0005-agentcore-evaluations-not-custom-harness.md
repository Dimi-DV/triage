# 0005 — Use AgentCore Evaluations natively, not a custom evaluation harness

**Status:** Accepted
**Date:** 2026-05-13
**Deciders:** Dimitrije

## Context

Triage needs a systematic way to score the agent against the outage corpus. The original capstone plan included building a custom Python evaluation harness — load scenarios, invoke the agent, parse outputs, compute scores. That was a defensible choice when this project was first scoped (early May 2026).

On March 31, 2026, AWS released **AgentCore Evaluations** to GA — a managed evaluation framework with **16 built-in evaluators** (correctness, faithfulness, helpfulness, response relevance, conciseness, coherence, instruction following, refusal, harmfulness, stereotyping, tool selection accuracy, tool parameter accuracy, goal success rate, plus three trajectory-match evaluators that score expected tool sequences) and support for custom LLM-as-judge or Lambda-based evaluators. ~~13 built-ins, ground-truth modes including reference answers and behavioral assertions, results visualized in CloudWatch~~ — superseded by 2026-05-18 boto3-introspected reality (see `docs/architecture-references/agentcore-evaluations-2026-03.md`).

The custom-harness path now has a clear competitor: a managed service from the same vendor (AWS) running on the same platform (AgentCore) producing the same kind of results, only better instrumented and more reproducible.

## Decision

Use AgentCore Evaluations natively for Triage's evaluation pipeline. Configure with at least 5 built-in evaluators (goal success rate, tool selection accuracy, tool parameter accuracy, response correctness, safety) plus 1–2 custom LLM-as-judge evaluators ("did the agent ask before destructive action?", "did the diagnosis match ground-truth root cause to within reasonable equivalence?").

Do not build a custom Python evaluation harness.

## Alternatives considered

**Custom Python harness using boto3 + pytest.** Maximum pedagogical value — you understand exactly how the harness works. Rejected because (a) AgentCore Evaluations is the AWS-native pattern, (b) mirroring AWS-published methodology is itself a portfolio talking point, and (c) the differentiator moves up the stack — from "I built a harness" to "I designed the scenario corpus, the failure-mode annotation, and the comparison to published baselines." The latter is a stronger signal.

**Third-party agent eval framework** (e.g., DeepEval, RAGAS). Mature in the LLM eval space but not aligned with AgentCore vocabulary. Rejected for the same vocabulary-alignment reason that drove ADR-0002.

**No eval framework at all — just manual review of agent outputs.** Tempting given the time pressure. Rejected because reproducibility is the differentiator. Manual review of 8–10 scenarios produces no comparison table, no failure-mode distribution, no baseline reference. The eval table is the single highest-leverage interview artifact in the project.

## Consequences

**Positive:**
- The eval table — with built-in evaluator scores, custom LLM-as-judge verdict, MAST failure mode per failed run, and comparison to STRATUS / ITBench / AIOpsLab baselines — becomes the headline artifact in the README
- Single pane of glass: agent traces + eval scores in CloudWatch (AgentCore Observability + Evaluations share the visualization layer)
- A whole sprint day is freed up that would have gone to harness scaffolding — redirected to scenario corpus design and MAST annotation (ADR-0006)
- The eval runs as on-demand mode in CI (regression gate after any prompt/skill/tool change)

**Negative:**
- Less under-the-hood visibility into how scoring works. Mitigation: AgentCore's evaluator definitions are introspectable; the README documents which evaluators are enabled and why.
- Dependency on a March-2026-GA'd service for a piece of the architecture. Acceptable; AgentCore Evaluations is officially GA, not preview.
- **AgentCore Evaluations is online-only (no batch `start_evaluation`).** The synchronous "run the corpus on every change" CI pattern this ADR originally implied has to be simulated by the harness: persistent `OnlineEvaluationConfig` at 100% sampling attached to the runtime log group, harness invokes per scenario and polls the output target for results keyed by session id. Verified 2026-05-18 via boto3 service-model introspection; see `agentcore-evaluations-2026-03.md` for the API divergence log. The free-day claim above is weakened — wiring online eval (IAM execution role + output target + log-group filter) is non-trivial but still less work than a full custom harness.

**Neutral:**
- ~~Online mode is the natural next-iteration extension; v1 ships with on-demand mode only.~~ Inverted by reality: online is the only mode. Future iterations may add a true on-demand orchestration layer in the harness rather than the AWS service.

## References

- Decision doc Section 3.5, Section 11 row 8
- `docs/architecture-references/agentcore-evaluations-2026-03.md`
- AWS announcement: https://aws.amazon.com/blogs/aws/amazon-bedrock-agentcore-adds-quality-evaluations-and-policy-controls-for-deploying-trusted-ai-agents/

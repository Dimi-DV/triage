# 0006 — Annotate eval failures against the MAST taxonomy

**Status:** Accepted
**Date:** 2026-05-13
**Deciders:** Dimitrije

## Context

AgentCore Evaluations (ADR-0005) gives Triage scores per scenario: pass/fail, evaluator dimensions, LLM-as-judge verdicts. What it does *not* give is a **categorical explanation** of *why* the agent failed when it failed. Without categorization, every failure is described in ad-hoc prose, which makes failures uncomparable across scenarios, across models, and against published baselines.

In February 2026, IBM Research and UC Berkeley published the **MAST (Multi-Agent System failure Taxonomy)** on Hugging Face, derived from analyzing thousands of agent traces across ITBench. MAST organizes failure modes hierarchically:

- FM-1.X — Conversation / context failures (e.g., FM-1.4 Loss of Conversation History, FM-1.5 Unaware of Termination Conditions)
- FM-2.X — Reasoning / action failures (e.g., FM-2.6 Reasoning-Action Mismatch)
- FM-3.X — Verification / outcome failures (e.g., FM-3.3 Incorrect Verification)

The MAST team also published an LLM-as-judge classifier that reaches **94% accuracy with 0.88 inter-annotator agreement** — high enough to use for reproducible annotation.

Few comparable agent implementations annotate failures this way. Most just say "the agent failed on this scenario" and move on.

## Decision

For every scenario in Triage's outage corpus where the agent fails, run the trace through a MAST classifier (LLM-as-judge with the published prompt) and record the **primary MAST failure mode**. Aggregate the distribution across all failed scenarios. Include the distribution in the README eval table and compare to published model distributions where relevant.

## Alternatives considered

**Ad-hoc prose descriptions of failures.** What most agent demos do. Rejected because uncomparable: there's no way to say "Triage failed FM-3.3 in 4 of 7 misses, similar to Gemini-3-Flash's failure profile" if failures are described in unique prose each time.

**Custom failure taxonomy.** Could invent one tailored to AIOps incident response specifically. Rejected because (a) inventing a taxonomy is a separate research project, (b) MAST is rigorous (94% classifier accuracy is reproducible), and (c) using a published taxonomy with a citation is more credible than inventing one.

**Skip failure annotation entirely.** Just report pass/fail. Rejected because the failure distribution is a high-value artifact: it turns "the agent failed" into "the agent failed FM-3.3 in 4 of 7 misses," which is actionable and comparable across models and published baselines.

## Consequences

**Positive:**
- The payoff is concrete and actionable: *"The agent failed FM-3.3 in N of M misses; the next iteration would add a Summarizer Agent and an explicit verification step in the lead agent's prompt — the same intervention the IBM/Berkeley paper showed yields up to 53% improvement on ITBench."*
- The MAST column in the eval table differentiates this work from agent demos that only report pass/fail
- Failure analysis stays connected to published research, not invented in isolation
- Reproducible — another evaluator running the same MAST classifier on the same traces would get ~94% agreement

**Negative:**
- The MAST classifier prompt is an external dependency. Mitigation: the prompt is published in the Hugging Face post and stable enough to commit a copy to `evals/`.
- LLM-as-judge token cost for classifying every failure. Mitigation: classifier runs only on failed runs, not the full corpus.

**Neutral:**
- Triage's failure distribution may or may not mirror the published model distributions. Both outcomes are interesting; mirroring validates the taxonomy applies, diverging is interesting in its own right.

## References

- Decision doc Section 3.5, Section 11 row 9
- `docs/architecture-references/mast-failure-modes-ibm-berkeley-2026-02.md`
- Hugging Face post: https://huggingface.co/blog/ibm-research/itbenchandmast

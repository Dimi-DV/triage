# MAST: Multi-Agent System failure Taxonomy

**Source:** "IBM and UC Berkeley Diagnose Why Enterprise Agents Fail Using IT-Bench and MAST," Hugging Face blog, February 18, 2026.
**URL:** https://huggingface.co/blog/ibm-research/itbenchandmast
**Original paper announcement:** December 19, 2025.

## Why this matters for Triage

MAST is the failure-mode taxonomy you use to **classify every failed run** in your eval per the decision doc Section 3.5. Almost no other portfolio project does this. Annotating against a published taxonomy from a current paper with a 94%-accurate classifier signals research literacy and evaluation discipline — the differentiator vs. generic "agent demo" repos in the hiring pool.

Decision-doc cross-references: Section 3.5 (primary), 11 row 9.

## What MAST is

A hierarchical taxonomy of LLM agent failure modes derived from analyzing thousands of agent traces across ITBench scenarios. The IBM/Berkeley team built it specifically to make agent failures *categorizable and comparable* across models, scenarios, and architectures — instead of describing each failure in ad-hoc prose.

The taxonomy has three top-level groups:
- **FM-1.X — Conversation / context failures**
- **FM-2.X — Reasoning / action failures**
- **FM-3.X — Verification / outcome failures**

## The failure modes you most need to know

| Code | Name | What it looks like |
|---|---|---|
| FM-1.4 | Loss of Conversation History | Agent forgets earlier in the session what it learned or decided; contradicts itself across turns |
| FM-1.5 | Unaware of Termination Conditions | Agent doesn't recognize it's done (or has failed terminally); loops, retries, or wanders |
| FM-2.6 | Reasoning-Action Mismatch | Agent's stated plan is correct but the action it takes is different; chain-of-thought says "check logs" then it calls a metrics tool |
| FM-3.3 | Incorrect Verification | Agent claims it fixed/diagnosed something but didn't actually verify the claim against evidence |

There are more modes — the taxonomy is granular. Verify the full list in the source. The four above are the ones most cited in the analysis and most likely to appear in your eval.

## Key findings from the paper analysis (cite-worthy)

- **FM-3.3 Incorrect Verification is the strongest predictor of failure across frontier models.** In Gemini-3-Flash failed traces, FM-3.3 incidence is ~52% higher than in successful traces. If your agent fails on this mode most often, you're in good company — even GPT-4-class models do.
- **FM-2.6 Reasoning-Action Mismatch is endemic.** Present in ~92% of Kimi-K2 failures and ~94% of GPT-OSS-120B failure traces.
- **Average failure modes per trace:** Gemini-3-Flash 2.6, Kimi-K2 4.7, GPT-OSS-120B 5.3. Multiple modes typically co-occur.
- **The MAST LLM-as-judge classifier reaches 94% accuracy with 0.88 inter-annotator agreement** — high enough to use for reproducible annotation.
- **Adding a Summarizer Agent + stricter state machine yields up to 53% performance improvement** on ITBench. Useful pointer for your "next iteration" README section.

## How you'll use it

For every scenario in your outage corpus where the agent fails, run the trace through a MAST classifier (LLM-as-judge with the published prompt) and record the **primary failure mode**. Then aggregate:

- Distribution of failure modes across your 8–10 scenarios
- Whether your distribution mirrors any of the published model distributions
- What design change you'd make to address the most-common mode in your agent

That last point is the interview-grade payoff: "Our agent failed FM-3.3 in 4 of 7 misses. We'd address this in the next iteration by adding a Summarizer Agent and explicit verification step in the lead agent's prompt — the same intervention the IBM/Berkeley paper showed yields up to 53% improvement."

## What's NOT MAST's job

MAST classifies *what kind* of failure occurred. It doesn't explain *why* or prescribe *how to fix*. The "why" comes from your trace inspection; the "how to fix" comes from your engineering judgment. The taxonomy is a vocabulary, not a remediation playbook.

## Verify against live source

- Full taxonomy list (there are more FM-X.Y codes than the four above)
- Current classifier prompt template (the post may evolve)
- Latest paper version on arXiv if cited in your README
- Any updates to the percentage findings as more models are analyzed

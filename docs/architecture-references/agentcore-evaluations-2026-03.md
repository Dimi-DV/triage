# AgentCore Evaluations

**Source:** "Amazon Bedrock AgentCore adds quality evaluations and policy controls for deploying trusted AI agents," AWS News Blog, March 31, 2026. Plus AgentCore Evaluations developer guide.
**URLs:**
- https://aws.amazon.com/blogs/aws/amazon-bedrock-agentcore-adds-quality-evaluations-and-policy-controls-for-deploying-trusted-ai-agents/
- https://aws.amazon.com/about-aws/whats-new/2026/03/agentcore-evaluations-generally-available/
- Developer guide section: navigate from https://aws.amazon.com/bedrock/agentcore/ → Documentation → Evaluations

## Why this matters for Triage

This is the eval framework you use **instead of** building a custom Python eval harness. GA'd March 31, 2026 — not in any LLM training data. The decision doc (Section 3.5) commits to using AgentCore Evaluations natively and layering 1–2 custom evaluators on top. The differentiator in the project shifts from "I built a harness" to "I designed the scenario corpus + the failure-mode annotation + the comparison to published baselines."

Decision-doc cross-references: Section 3.5 (primary), 3.4 (outage corpus feeds in), 3.10 (multi-agent could share the eval harness in future).

## Three evaluator types

**1. Built-in evaluators** (13 ship with the service)

Pre-built quality dimensions you enable per evaluation run. Cited in AWS materials:
- Correctness (factual accuracy)
- Helpfulness
- Tool selection accuracy
- Tool parameter accuracy
- Goal success rate
- Response correctness
- Context relevance
- Safety
- Plus others — verify the full list in live docs before Day 35

**You'll enable at least 5** per the decision doc: goal success rate, tool selection accuracy, tool parameter accuracy, response correctness, safety.

**2. LLM-as-judge (custom)** — you supply the model, inference parameters, and the judge prompt. Use a model from a **different family** than the agent under test (e.g., agent runs Claude, evaluator runs Nova or vice versa) to avoid the model grading its own homework. Decision-doc Section 11 row 22.

**You'll write 1 (or 2):**
- "Did the agent ask before destructive action?"
- "Did the agent's diagnosis match the ground-truth root cause to within reasonable equivalence?"

**3. Code-based (custom)** — Python or JavaScript Lambdas that score the agent's output programmatically. Useful for things measurable by exact match or threshold (latency under X, action sequence exactly matches expected, etc.). Optional in this sprint.

## Ground-truth modes

For your outage corpus, you express ground truth in one or more of these:

- **Reference answers** — what the correct diagnosis should say
- **Behavioral assertions** — session-level goals the agent must achieve
- **Expected tool execution sequences** — the agent must call these tools in this order (or a valid order)

Decision-doc Section 3.4 outage corpus → ground truth → AgentCore Evaluations feeds this.

## Operating modes

**On-demand mode** — run the full corpus on every change to agent prompt, skills, or tools. This is your CI regression gate. Decision doc row 23: "We didn't set out to build an evaluation platform; it's what it took to trust the agent."

**Online mode** — sample live traffic in production, write scores to CloudWatch alongside AgentCore Observability metrics. Out of scope for the 6-day sprint but a natural next-iteration extension.

## Output

Results visualize in CloudWatch alongside AgentCore Observability insights. Single pane of glass — agent traces + eval scores in one view. Decision-doc Section 11 calls this out as part of "Unified monitoring."

## What goes in your eval table for the README

For each scenario in the outage corpus:

| Column | Source |
|---|---|
| Scenario name | Your corpus design |
| What's broken | Ground truth from FIS template or Terraform overlay |
| Agent diagnosis | AgentCore session output |
| Agent action proposed | AgentCore session output |
| Built-in evaluator scores | AgentCore Evaluations (5+ columns) |
| Custom LLM-as-judge verdict | Custom evaluator output |
| Pass/Fail | Aggregate decision |
| MAST failure mode (if fail) | See `mast-failure-modes-*.md` |
| Comparable baseline | STRATUS / ITBench / AIOpsLab |

This table is the single highest-leverage interview artifact in the entire project.

## Verify against live source

- Exact list of all 13 built-in evaluators (the dev guide is the authoritative list)
- Pricing per evaluator invocation and per LLM-as-judge token spend
- Whether your chosen judge model has guaranteed cross-region availability in us-east-1
- Current schema for ground-truth definition files

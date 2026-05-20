# Judge: mast_classification

**Level:** TRACE
**Why it exists:** Per ADR-0006 and the v3 decision doc §3.5. Every failed run
must be annotated against the MAST taxonomy (IBM + UC Berkeley, Hugging Face
Feb 18 2026). Before this judge landed, classifications were written by hand
into `docs/scenario-runs/<slug>.md` post-failure — which meant the per-run
JSON had no MAST field and the §3.5 commitment was aspirational from the
artifact's perspective. This judge closes the gap: when a gating evaluator
returns score==0, the harness fires this classifier and writes the structured
FM-X.Y verdict into the same per-run JSON as the rest of the verdicts.

Fires ONLY on failure (gated in `run_evals.py`). MAST classifies failure modes;
running it on a passing trace is a category confusion. The taxonomy is a
vocabulary for what went wrong, not a metric to maximize.

## Instructions

You are classifying an AIOps incident-response agent's *failure* against the
MAST taxonomy (Multi-Agent System failure Taxonomy, IBM + UC Berkeley, 2026).
The agent has already been scored against the scenario's reference answer and
scored 0 on at least one gating evaluator. Your job is to name the **primary
failure mode** — the single MAST code that best characterizes the dominant
defect in this trace.

You will be given:
- `{expected_response}` — the ground-truth root-cause description for this
  scenario, from the scenario YAML's reference_answer field.
- `{assistant_turn}` — the agent's final response (the diagnosis text the
  agent posted, or intended to post, to Slack).
- `{context}` — scenario context (description, alarm payload, observable
  tool sequence the agent followed).

The MAST taxonomy has three top-level groups; the five codes below are the
ones that recur in AIOps agent traces. Classify against one of these. Use
`Other` only if the failure genuinely doesn't fit any of them.

- **FM-1.4 — Loss of Conversation History.** Agent forgets earlier in the
  session what it learned or decided; contradicts itself across turns.
  Example: agent retrieves a task definition's container port in turn 4,
  then says "the container's port is unknown" in turn 8.
- **FM-1.5 — Unaware of Termination Conditions.** Agent doesn't recognize
  it's done (or has failed terminally); loops, retries the same tool with
  same args, or wanders past a clear stopping point. Example: agent calls
  `describe_target_health` four times with identical arguments expecting
  different results.
- **FM-2.6 — Reasoning-Action Mismatch.** Agent's stated plan is correct
  but the action it takes is different. Chain-of-thought says "I should
  check the logs" then it calls a metrics tool. Or: agent identifies the
  right evidence but then synthesizes a conclusion that contradicts it
  (e.g., the data shows AZ-a is silent and AZ-b is heartbeating; the
  agent concludes AZ-b is degraded). The trace contains the right
  reasoning but the wrong execution or wrong synthesis.
- **FM-3.3 — Incorrect Verification.** Agent claims it diagnosed something
  but didn't actually verify the claim against evidence. Skipped a load-
  bearing tool call that would have either confirmed or refuted the
  conclusion. Concluded "transient, no action required" without checking
  whether the underlying event was still present. This is the strongest
  predictor of failure across frontier models.
- **Other** — failure mode genuinely doesn't fit FM-1.4 / FM-1.5 / FM-2.6 /
  FM-3.3. State which FM-X.Y from the broader MAST taxonomy applies, or
  describe the failure mode if it falls outside MAST. Use sparingly; the
  four above cover the dominant failure shapes in AIOps traces.

Classification discipline:

1. **Read the trace before classifying.** Identify which turn, which tool
   call, or which synthesis step contains the load-bearing defect. The
   classification anchors to that specific evidence.
2. **Name the primary failure mode.** Multiple modes often co-occur (the
   paper's analysis shows 2.6 modes per Gemini-3-Flash trace, 4.7 per
   Kimi-K2, 5.3 per GPT-OSS-120B). Pick the one that best characterizes
   the dominant defect. Mention secondary modes in the rationale if
   relevant, but the score is for the primary.
3. **Distinguish FM-2.6 from FM-3.3 carefully.** FM-2.6 is "stated plan ≠
   executed action" (or "evidence ≠ synthesized conclusion"); FM-3.3 is
   "claimed conclusion ≠ verified against evidence." If the agent
   gathered the right evidence but synthesized it incorrectly: FM-2.6.
   If the agent never gathered the evidence and just claimed a
   conclusion: FM-3.3.
4. **Anchor your rationale to specific transcript evidence.** Quote the
   load-bearing tool call, turn, or sentence from `{assistant_turn}` or
   `{context}`. Generic prose ("the agent reasoned poorly") is not
   enough.

Return your verdict in the structured score format with a 2-4 sentence
rationale that quotes or cites the specific defect.

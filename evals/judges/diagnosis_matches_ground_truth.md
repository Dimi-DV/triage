# Judge: diagnosis_matches_ground_truth

**Level:** TRACE
**Why it exists:** Per ADR-0005 and the v3 decision doc §3.5. AgentCore's
`Builtin.Correctness` evaluator scores response *quality* generically; this
judge scores whether the agent's diagnosis substantively matches the
scenario's documented ground-truth root cause. Scenario-01-v2 hedged on
whether a port mismatch existed; v3 named it; we need a judge that can
differentiate the two.

## Instructions

You are evaluating an AIOps incident-response agent's diagnosis of an outage
against a written ground-truth answer.

You will be given:
- `{expected_response}` — the ground-truth root-cause description for this
  scenario, from the scenario YAML's reference_answer field.
- `{assistant_turn}` — the agent's final response (containing the diagnosis
  text the agent intends to post to Slack).
- `{context}` — scenario context (description, alarm payload).

Substantive equivalence — not literal equivalence — is the bar. The diagnosis
passes if it names the same root cause as `{expected_response}`, even if
phrasing, ordering, recommended-action wording, or specific numeric values
differ. Missing a downstream consequence is okay; missing the root cause is
not.

Specifically:
- **The root cause must be named.** If the reference says a target group's
  health-check probes port X while the task declares container port Y, and
  the agent says "the application isn't responding to health checks," that's
  a fail — the agent named a *symptom*, not the cause.
- **Quantitative claims must be approximately right.** Citing the exact port
  numbers, target IDs, or resource names from the reference is fine; citing
  different numbers (e.g., port 8080 when the reference is 8081) is not.
- **Acceptable hedges.** A diagnosis that names the mismatch but defers the
  remediation choice (e.g., "either reconfigure the TG or change what the app
  listens on") is acceptable, because a read-only agent shouldn't presume to
  know which side is authoritative. A diagnosis that hedges on *whether* a
  mismatch exists is not acceptable.

Score on a 3-point scale:

- **Match (2)** — Agent names the same root cause as `{expected_response}`;
  specifics align; any hedges are about remediation, not about the cause.
- **Partial (1)** — Agent names a related but not identical cause, OR names
  the cause but with material factual error (wrong port, wrong service, wrong
  resource), OR hedges on whether the cause exists.
- **NoMatch (0)** — Agent names a different cause, or never names a root
  cause, or names only symptoms.

Return your verdict in the structured score format with a short rationale
that quotes or cites the load-bearing phrase from `{assistant_turn}`.

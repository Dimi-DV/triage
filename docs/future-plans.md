# Triage — Future Plans

What this doc is: a working list of expansions that *could* land next, with rough effort, dependencies, and the why. Not a commitment, not a deadline tracker. The git log + `docs/agent-md-changelog.md` + the per-scenario eval JSONs are the durable record of what actually ships; this doc is the staging area for what might.

What this doc is not:
- Not a roadmap with dates — see [docs/architecture-references/triage-decision-doc-v3.md] for the load-bearing spec
- Not a CV bullet list — keep it honest, including the things that won't land
- Not a place for in-flight work — that belongs in `~/.claude/plans/` or the active branch

Items are grouped by horizon: **near-term** (single-sprint, mostly self-contained), **mid-term** (multi-week, depends on other things shipping or external signal), **long-term** (structural arcs that change the project shape), and an explicit **not planned** anti-scope so future-me knows what was considered and rejected, and why.

---

## Near-term — high-leverage and self-contained

### N1. CloudTrail MCP tool (operator-action audit)
**Effort:** ~0.5 day. **Depends on:** nothing.

The agent today can diagnose *that* a service was stopped but not *who* stopped it. CloudTrail has `userIdentity.userName`, `eventName: UpdateService`, `requestParameters.desiredCount: 0` for exactly this case. Adding `ecs_api_recent_service_events` (or, more naturally, expanding `logs-api` with a CloudTrail surface as `logs_api_recent_audit_events`) closes the operator-action diagnosis gap surfaced in the Hour 20 "would the agent diagnose a manual stop" thought experiment. IAM bump: `cloudtrail:LookupEvents`. New scenario to validate: "user manually scaled service to 0" — overlay just wraps the symptom; the diagnosis chain is what we're testing.

### N2. Cedar Lambda interceptor (close the spec gap)
**Effort:** ~1 day. **Depends on:** nothing.

`cedar-policies/` has policy text but no enforcement; the decision doc commits to Cedar gating; the IAM-only gating at the Gateway boundary is coarse. Wire a Lambda interceptor via `CreateGateway`'s `interceptorConfigurations` parameter that loads policies from S3, evaluates with `cedar-policy` Python lib, and returns allow/deny. Adds: per-call audit decision log, fine-grained resource-aware policy ("describe only `dev-triage-*` task definitions"), policy-as-code unit tests. Defense in depth — if IAM is misconfigured, Cedar catches it. Detail in v3 spec; see [docs/architecture-references/triage-decision-doc-v3.md].

### N3. Negative-test scenario (verify the eval has teeth)
**Effort:** ~2 hours. **Depends on:** nothing.

Every scenario in the current corpus passes Match (2.0). That's not falsifiable evidence the gating works — it might just mean the rubric is generous. Build one scenario the agent **should** fail at (e.g., agent proposes a write without asking, or hedges past the `mandatory_mentions` gate). Verify the eval actually scores it 0/Fail. Closes the "n=9 all pass" credibility concern in a single test.

### N4. Latency + cost telemetry
**Effort:** ~0.5 day. **Depends on:** nothing.

Currently no measured P50/P95 per scenario or $/incident. Add to the per-run JSON: invocation duration, turn count (already there), per-turn Bedrock token usage (input + output), estimated $ at current Sonnet 4.6 list price. Roll up in `summarize_runs.py`. Required before any "operate at scale" claim. Five extra fields, one estimated-cost helper function.

### N5. Human-SRE blind grading sample
**Effort:** ~2 hours of code + external dependency on someone grading. **Depends on:** finding an SRE.

Pick 20 random runs from `docs/eval-results/runs/`, strip the trajectory and ground truth, present the alarm payload + agent's final Slack post to an SRE who's never seen this project. Have them grade each as "I would act on this / I would ask for more / this is wrong." Compare with the LLM judge's verdicts. Calibrates the lenient-judge concern from Hour 20 with real data. Without this, all the "Match (2.0)" claims have an asterisk.

---

## Mid-term — multi-week arcs

### M1. Corpus expansion — 25-30 scenarios
**Effort:** ~2-3 weeks. **Depends on:** N1 (CloudTrail tool) for some scenarios.

The 9-scenario corpus covers 5 fault families (capacity, network, dependency, security, config-drift). Uncovered shapes worth adding, in priority order:
- DNS resolution failure (overlay; needs no new tool)
- WAF block (overlay; needs WAF MCP tool — fits under `metrics-api` or `ecs-api`)
- Image pull failure (overlay; needs `ecs:DescribeTasks` for task-stop reasons)
- Third-party API timeout (overlay; needs no new tool)
- NACL ephemeral-port block (overlay; needs `ec2:DescribeNetworkAcls`)
- Throttling/rate-limit (overlay; needs no new tool)
- ALB listener rule clash (overlay; needs `elbv2:DescribeRules`)
- Manual operator action stop (overlay; needs N1 CloudTrail)

Discipline: only add scenarios that cover a **new fault family or new tool-surface requirement**. Adding "missing env var v2" inflates n without adding signal. Per rule, ≥1/3 must ship `by_design_none` to keep the generalization claim load-bearing.

### M2. Multi-model strategy
**Effort:** ~1 week. **Depends on:** N4 (cost telemetry to compare $/incident).

Today's single-model dependency (Sonnet 4.6) is a single point of failure for behavior. Options to explore:
- **Fallback chain:** Sonnet 4.6 primary, Opus 4.7 retry on runtime 500 or empty `final_text`
- **Second opinion:** run the same alarm through Sonnet 4.6 + Opus 4.7 in parallel, compare diagnoses, flag disagreements for human review. Costs ~2x but catches model-specific blind spots.
- **Cheap model for triage / strong model for diagnosis:** Haiku to decide *whether* to escalate, Sonnet/Opus only if escalating. Likely big cost reduction.

Pick after N4 lands so the cost numbers are real.

### M3. AgentCore Memory integration
**Effort:** ~1-2 weeks. **Depends on:** spec clarification on episodic-memory shape.

The agent currently treats every incident as a fresh session — no context from prior outages. AgentCore Memory primitive supports session-scoped + cross-session memory, but our runtime doesn't wire it. Use cases:
- "This alarm has fired 5 times this week" — frequency signal in the diagnosis
- "Last time we saw this, the remediation was X" — retrieves prior context
- Risks overfitting to historical patterns; needs careful eval coverage (a memory-aware agent could pass corpus by memorizing rather than reasoning)

### M4. Richer AGENT.md + more runbooks (without overfitting)
**Effort:** continuous; tracked via `docs/agent-md-changelog.md`.

The no-railroading rule (spec §3.11.1) is the discipline boundary: AGENT.md edits must be **general principles** (e.g., "always read task definition for environment-shaped failures"), not scenario-specific ("if alarm name contains 'broken', look at port 8081"). Each candidate edit gets stress-tested against the `by_design_none` scenarios — if it only helps the runbook-shipped scenarios, it's railroading. New runbooks land alongside new scenarios in M1; alarm-specific procedure goes there, not in AGENT.md.

### M5. aws/spans resolution + online evals
**Effort:** ~3-5 days (mostly investigation). **Depends on:** AWS X-Ray Transaction Search enablement OR custom runtime-side OTel export.

Per [`feedback_aws_spans_observability_gap`]: AgentCore Online Evaluations need traces in the reserved `aws/spans` log group, which we can't create directly. Two paths:
- Enable X-Ray Transaction Search → automatically populates `aws/spans` → online evals subscribe
- OR runtime exports OTel to customer-owned log group + custom Lambda subscriber mimics the eval flow

This is the single biggest production-readiness multiplier. Corpus tests miss production drift; online eval at 5% sampling on real alarms accumulates hundreds of evaluated runs/week and gives Match-rate real error bars.

---

## Long-term — structural arcs

### L1. Multi-agent decomposition
**Effort:** several weeks. **Depends on:** stable single-agent baseline.

The current architecture is "single substantive lead agent + one stub subagent" (spec §3.2). Designed for multi-agent expansion. Real subagents to spawn: a `network-investigator` (network/connectivity faults), a `data-plane-investigator` (DB/cache/storage), a `security-investigator` (IAM, secrets, WAF). Lead delegates based on initial signal, aggregates responses. AWS DevOps Agent reference architecture (Molumuri et al., March 2026) does exactly this. Eval framework needs to extend to multi-agent traces — non-trivial.

### L2. Self-improving runbook loop
**Effort:** several weeks. **Depends on:** L1, M3, real production incidents.

When the agent encounters a `by_design_none` scenario and successfully diagnoses, the trajectory could become the *seed* for a new runbook (PR'd to `runbooks/`, reviewed by a human, merged). The agent's own diagnostic chain becomes documentation. Risk: amplifies any bias in how the agent reasons. Needs careful human review gate — auto-merged PRs from the agent are not the goal.

### L3. Action proposal + human-approval workflow
**Effort:** ~1 week. **Depends on:** more write-tool scenarios in M1.

Today the agent is read-only; `asks_before_destructive_action` is mostly vacuous because almost no scenarios have `correct_remediation: <write-action>`. A real production agent needs to *propose* a write (e.g., "rolling restart the service"), get human approval (Slack interactive message? OpsGenie? PagerDuty mobile?), then execute via a write-tool gated by Cedar + audit. The full write-with-approval loop hasn't been tested end-to-end.

### L4. Cross-account + multi-region
**Effort:** several weeks. **Depends on:** stable single-account baseline.

Currently single AWS account, us-east-1. Real SRE work spans accounts (dev/stage/prod) and regions (failover, latency, sovereign data). Cross-account IAM (`sts:AssumeRole` chains), multi-region observability (alarms in eu-west-1 routed to us-east-1 agent? or per-region agents?), regional Bedrock model availability differences — all open questions.

### L5. PagerDuty / Jira / external integrations beyond Slack
**Effort:** ~1 week per integration. **Depends on:** nothing fundamental.

Slack is the only output today. Production SRE workflow usually involves PagerDuty (incident lifecycle), Jira/Linear (post-mortem ticket creation), Confluence (runbook publishing). Each is a new MCP tool under `runbooks-api` (write tools, Cedar-gated, audit-emitting). Low-risk individually; combined they shift the agent from "alarm responder" to "incident-lifecycle participant."

---

## Not planned (anti-scope) — what was considered and rejected, and why

- **Build a custom LLM or fine-tune one for this domain.** Anthropic models on Bedrock cover this need; fine-tuning would lock the project to a specific dataset and lose the model-rotation flexibility of M2.

- **Replace AgentCore with a custom runtime.** AgentCore Runtime + Gateway + Identity + Memory + Observability is the integration layer this project is built around. Self-hosting an equivalent is a separate research project, not an expansion of this one.

- **Expand beyond the four MCP namespaces** (ecs-api / logs-api / metrics-api / runbooks-api). Spec §3.2 + CLAUDE.md rule 5. New capabilities go *inside* an existing namespace. Anything that doesn't fit (e.g., predictive maintenance writing into a time-series store) requires a separate spec discussion, not a namespace expansion.

- **Predictive / preemptive monitoring** ("agent watches metrics, fires runbooks before alarms"). Out of scope for the reactive-incident-response framing. A separate project, possibly worth doing later, but the success criteria are different (precision/recall on prediction, not diagnosis accuracy on real alarms).

- **A web UI / dashboard.** The Slack-posted diagnosis is the UX. Building a webapp would be project-shape creep and add maintenance load with low marginal value vs Slack.

- **Generic "AI agent platform" abstraction layer** ("works with any MCP server / any cloud"). This project is specifically AgentCore + AWS. Abstracting that away dilutes what makes it useful as a reference implementation.

---

## If only one thing lands next

**N2 Cedar Lambda interceptor.** Closes the largest claim-vs-reality gap. One day of focused work converts a paper architectural commitment into a working artifact with policy-as-code testing. The other near-terms are valuable but Cedar is the only one that closes an existing spec promise — everything else is additive.

Distant second: **N1 CloudTrail tool.** Highest practical-diagnosis-capability delta available. Surfaced as a real gap during the Hour 20 thought experiment ("would the agent diagnose a manual operator action?" — no, because there's no audit-trail visibility).

If we had a free week: N2 (Cedar) + N1 (CloudTrail) + N3 (negative-test scenario) + N4 (latency/cost telemetry). That bundle moves Triage from "passes a hand-curated corpus" to "passes a corpus with falsifiable gates, attributed incidents, and measured cost per diagnosis."

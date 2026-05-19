# Triage Project: Architecture, Sprint Plan, and Decision Log

**Version:** v3 (restraint framing + sprint pacing rebuild)
**Status:** committed, May 14, 2026
**Sprint:** Days 31–36 of the 42-day battle plan
**Real-world position at v3:** Day 26 (Week 4 Kubernetes intro). Sprint start lands later than the v2 timeline assumed.
**Owner:** Dimitrije

This document records the decisions for the Triage portfolio project that runs between the end of tool-learning and the start of the job-application sprint. It is the authoritative reference for project scope, architecture, and reasoning. If anything in a future conversation conflicts with this doc, this doc wins until explicitly revised.

v3 is a major revision per the policy. Two structural changes from v2.1: (1) the "designed for multi-agent expansion" framing is removed — the 2026 hiring signal explicitly filters against sprawling multi-agent demos, so the project pitches as a pure single-agent architecture; (2) Claude Code enters the sprint on Day 32 morning instead of Day 33 evening, because real-world benchmarks show 3–4× speedup on the infrastructure-hardening work that occupies Days 32–33, and the freed time is reallocated to agent design (Day 34) where Claude Code's leverage is lowest. (v3.1 amendment 2026-05-19: the stub subagent originally bundled with the single-agent framing is dropped — see §3.10 and §11 row 21.) The full reasoning trail lives in Section 11 (Decision Log).

---

## 1. The project, in one paragraph

A production-style AWS stack with an integrated AIOps agent. The stack is real infrastructure (Multi-AZ NAT, Multi-AZ RDS, real domain with HTTPS via ACM, WAF, CloudWatch agent on instances). The agent is built on **Amazon Bedrock AgentCore** and exposes its AWS observability tools through a custom **MCP server** organized into four canonical namespaces (`ecs-api`, `logs-api`, `metrics-api`, `runbooks-api`). The agent subscribes to CloudWatch alarms, reasons about failures, calls tools to gather evidence, and posts structured diagnoses to Slack. Write actions pass through two gates in series: a Cedar policy at AgentCore Gateway (deterministic) and a Slack approval (human review). Alongside the stack and agent is an **outage corpus** of AWS Fault Injection Service scenarios plus Terraform overlay misconfigurations, evaluated using **AgentCore Evaluations** with failures annotated against the **MAST failure-mode taxonomy**. The repo ships with a designed Claude Code workflow — CLAUDE.md, custom skills, and deterministic hooks — so the engineering substrate itself is part of the portfolio.

The portfolio pitch is that this is a small open-source version of the pattern AWS DevOps Agent and PagerDuty SRE Agent productized in late 2025 / early 2026. We are not competing with those products on capability. We are demonstrating mastery of the platform layer underneath them.

---

## 2. Why this project (market context)

The May 1 job-market analysis in this project established three relevant facts:

- AI-exposed skills are evolving 66% faster than less-exposed ones; professionals with AI expertise earn roughly 56% more on average.
- Entry-level DevOps titles are squeezed hardest by AI displacement. The titles surviving and growing are **AIOps Engineer, Platform Engineer, AI Infrastructure Engineer**.
- Junior DevOps applicants who can demonstrate genuine AI fluency in an infrastructure context are scarce.

The productized landscape reinforces the choice:

- **AWS DevOps Agent** went GA March 31, 2026, with a published reference architecture (Molumuri et al., AWS DevOps Blog).
- **Amazon Bedrock AgentCore** went GA October 13, 2025; **AgentCore Evaluations** went GA March 31, 2026.
- **PagerDuty's full AI agent suite** (SRE, Scribe, Shift, Insights) shipped Fall 2025; Spring 2026 release commits to a fully autonomous responder for well-understood incidents in H2 2026.
- **MCP** was donated to the Linux Foundation in December 2025 and now has first-party servers from PagerDuty, Datadog, Microsoft, AWS, Stripe, Vercel, and others.
- Block built a production triage tool by combining PagerDuty's MCP server with their open-source agent goose — the canonical "build with vendor primitives" proof point this project follows.

A secondary hiring signal worth pointing at: HN "Who is Hiring" posts in 2026 explicitly ask for "Claude Code or Codex daily user with a real workflow, your own skills/hooks/commands." That signal is addressed by Section 3.9 below.

Strategic reading: candidates are roughly nine months behind on this landscape; employers and engineering leadership are not. A portfolio project that mirrors what employers are buying or evaluating signals current literacy in a way other projects cannot.

---

## 3. Architectural decisions and reasoning

### 3.1 AgentCore as the agent platform

Build on Amazon Bedrock AgentCore, not raw Anthropic API. AgentCore is the current AWS-native pattern and is the same platform AWS DevOps Agent runs on. Building on AgentCore gives us:

- Resume vocabulary aligned with what employers in 2026 are evaluating
- Memory, Identity, Gateway, Code Interpreter, Browser, and Observability as managed primitives
- Direct architectural alignment with the productized agents we model against

Tradeoff: less of the raw agent loop is visible. For portfolio purposes, "shipped on AgentCore" beats "implemented the loop from scratch" — same way "deployed on ECS" beats "wrote my own container scheduler" in normal cloud projects.

### 3.2 Custom MCP server with four canonical namespaces

Author a small MCP server that exposes AWS observability operations to the agent. The agent connects through AgentCore Gateway. Tools are organized into four namespaces:

- `metrics-api/*` — CloudWatch metrics queries
- `logs-api/*` — CloudWatch Logs Insights queries
- `ecs-api/*` — ECS task and service inspection (substitutes for `k8s-api/*` in the published AWS reference because the workload is ECS, not EKS)
- `runbooks-api/*` — parse the runbooks committed on Day 30 and surface relevant procedures by alarm type

This namespace organization matches AWS's published multi-agent SRE reference architecture and the `aws-samples/sample-fully-autonomous-incident-response` repo. Same vocabulary the interviewer has seen.

MCP auth uses **AWS IAM (SigV4) at the AgentCore Gateway boundary.** The v2/v3 "OAuth 2.1 via AgentCore Identity" framing didn't match the live `bedrock-agentcore-control` API: `CreateGateway`'s only documented authorizer modes are `AWS_IAM` and `CUSTOM_JWT`, and AgentCore Identity is a credential broker rather than a first-party OAuth issuer (see `[[agentcore-identity-oauth-myth]]` memory for the boto3 introspection trail). Callers (the alarm bridge Lambda, the AgentCore Runtime) sign with their IAM execution roles; the Gateway validates SigV4. Pin the MCP protocol version in the server; flag the upcoming statelessness migration (MCP 2026 roadmap) in the README's "known limitations" section.

### 3.3 Two-layer write-action gating: Cedar at Gateway + Slack approval

Write actions on AWS resources pass through two gates in series:

1. **Cedar policy at AgentCore Gateway** — deterministic. Read-only IAM by default. Write actions allowed only when a Cedar policy evaluates true (example: `restart_ecs_service` allowed only when `environment == "dev"` and `service.task_count > 0`). The LLM cannot prompt-inject around this; the policy is evaluated by Gateway before the tool is invoked.
2. **Slack approval** — human review. Even if Cedar permits, a Slack message proposes the action and waits for acknowledgement before execution.

Every reasoning step and tool invocation also writes to an append-only S3 bucket with Object Lock — the "immutable audit journal" pattern from the AWS DevOps Agent architecture post (Molumuri, Fine, Alioto, Qureshi — AWS DevOps Blog, March 31, 2026).

This is defense in depth and matches the published AWS reference architecture exactly.

### 3.4 Outage corpus: FIS + Terraform overlays + benchmark alignment

The outage corpus is a mix of AWS Fault Injection Service scenarios and Terraform overlay misconfigurations:

- **4 FIS scenarios:** AZ slowdown, EC2 stop, EBS pause-IO, network blackhole between subnets
- **4–6 Terraform overlay scenarios:** target-group port mismatch, IAM permission gap, security-group too restrictive, ECS environment variable missing, ALB listener misconfigured, S3 bucket policy blocking CSS

Cite ITBench v2 (102 scenarios, IBM Research + ETH Zurich) and AIOpsLab (DeathStarBench microservices, NeurIPS 2025) as the methodology baseline in the README. Compare the agent's success rate to published numbers: frontier models alone solve ~11.4% of ITBench SRE; STRATUS achieves 50.0% on ITBench mitigation and 69.2% on AIOpsLab mitigation with GPT-4o.

FIS gives reusable, parameterized faults that demonstrate real chaos-engineering literacy. Benchmark alignment makes the comparison table interview-defensible.

> **Status update 2026-05-19:** 2 overlay scenarios shipped (`target-group-port-mismatch`, `missing-env-var`), both scoring Match (2.0) on the diagnosis judge. The missing-env-var scenario first surfaced MAST FM-3.3 (agent skipped the load-bearing inspection tool) → AGENT.md fix → Match. FIS scenarios are gated on the `logs-api` namespace (chaos faults are diagnosed from logs); namespace landed 2026-05-19 with `logs_api_filter_log_events`, so the first FIS template is unblocked. Outage corpus is the next ship.

### 3.5 Evaluation: AgentCore Evaluations + MAST failure-mode taxonomy

The evaluation harness is **AgentCore Evaluations** (GA March 31, 2026), running primarily on the **on-demand** path: per-scenario, the harness invokes the runtime synchronously, pulls inline-serialized OTel spans from the response, and calls `bedrock-agentcore.Evaluate` once per evaluator. Each verdict commits to a per-run JSON under `docs/eval-results/runs/<scenario>/`.

The 2026-05-19 wired set is **8 evaluators**: 5 AWS-managed built-ins (`Builtin.Correctness`, `Builtin.Faithfulness`, `Builtin.ResponseRelevance`, `Builtin.InstructionFollowing`, `Builtin.GoalSuccessRate`), one trajectory match (`Builtin.TrajectoryInOrderMatch`, scores the YAML's `expected_tool_sequence` field directly), and 2 custom LLM-as-judge evaluators (`diagnosis_matches_ground_truth` and `asks_before_destructive_action`). The custom judges are the **gating** evaluators by design — they encode the scenario writer's assertions; the built-ins are diagnostic signal but don't fail the run alone (so a strict-order trajectory miss doesn't fail an otherwise-correct diagnosis).

> **Execution model — corrected 2026-05-19.** The v3 amendment (2026-05-18) said "AgentCore Evaluations is online-only; on-demand is simulated by polling the output log group." That was wrong. A late boto3 probe surfaced `bedrock-agentcore.Evaluate` on the **runtime** client (not the control plane that was being grepped) — it accepts spans + reference inputs inline and returns scored verdicts synchronously. On-demand is now the primary path; the online `OnlineEvaluationConfig` is retained for future production sampling (still blocked on `aws/spans` emission — see `[[aws-spans-observability-gap]]`). The contract carries two gotchas worth flagging in interview: (1) Evaluate only accepts spans whose `scope.name` ∈ {`strands.telemetry.tracer`, `opentelemetry.instrumentation.langchain`, `openinference.instrumentation.langchain`}, and (2) once the scope is right, the *span shape* still has to match Strands' attribute + event conventions or AgentCore's adapter returns `AgentSpanMappingException` / `ToolSpanMappingException`. Full pinned shape lives in memory `[[agentcore-evaluate-strands-shape]]`. See `docs/architecture-references/agentcore-evaluations-2026-03.md` for the full doc-vs-API divergence log.

For every failed run, annotate against the **MAST taxonomy** (IBM + UC Berkeley, Hugging Face Feb 18, 2026): FM-3.3 Incorrect Verification, FM-2.6 Reasoning-Action Mismatch, FM-1.5 Unaware of Termination Conditions, FM-1.4 Loss of Conversation History, others as applicable. The MAST LLM-as-judge classifier reaches 94% accuracy with 0.88 inter-annotator agreement — reproducible enough to cite. The first empirical annotation in the corpus landed 2026-05-19: scenario 02's initial run scored NoMatch (0.0) on the diagnosis judge, the failure matched the YAML's predicted FM-3.3 hypothesis, and a one-line AGENT.md fix flipped the verdict to Match — the eval loop catching a real regression end-to-end.

The differentiator vs other agent portfolios is not "I built a harness." It is the scenario corpus design plus the named-taxonomy failure annotation plus the comparison to published baselines.

### 3.6 Mirror AWS DevOps Agent's published architecture explicitly

Replicate the architectural pattern documented in Molumuri et al. (AWS DevOps Blog, March 31, 2026), scaled down:

- **Agent Space equivalent:** single cross-account-capable AgentCore Runtime with read-only IAM by default
- **Skill tier 1 (AWS-provided):** AgentCore built-in Code Interpreter and Observability
- **Skill tier 2 (user-defined):** the 3 runbooks written on Day 30, parsed and invokable via `runbooks-api/*`
- **Skill tier 3 (learned):** out of scope for this sprint; document in README as the next iteration
- **Cedar at Gateway:** per Section 3.3
- **Immutable audit:** per Section 3.3

In the README, quote the Molumuri et al. architecture statement and document which elements were replicated, which were scoped out, and why. "Architecturally mirrors AWS DevOps Agent's published reference design" is more specific and verifiable than "inspired by productized agents."

### 3.7 Production-grade infrastructure

The grand-project decision to spend $150–200 on real infrastructure stands. Multi-AZ NAT (one per AZ), Multi-AZ RDS, real domain with ACM certificate and HTTPS end-to-end, WAF with AWS Managed Common Rule Set, CloudWatch agent pushing metrics and logs from instances. This is what makes the project look like a small production service rather than a lab.

### 3.8 Modular design with version pinning

The architecture must accommodate a moving stack. Specifically: model swaps should be configuration changes, not refactors. MCP protocol versions pinned in the server with a documented migration plan for the 2026 spec's statelessness changes. Tool definitions live in the MCP server, not in agent code, so a different agent runtime tomorrow doesn't require rewriting tool logic.

This is itself a portfolio talking point: *"I designed it modularly because I expected the underlying tools to keep moving, and they did."*

### 3.9 Claude Code workflow customization

The engineering substrate is part of the portfolio. The repo ships with a designed Claude Code workflow visible in the `.claude/` directory and in CLAUDE.md at the repo root.

**CLAUDE.md (~2,500 tokens, ~100 lines)** — the project constitution. Boris Cherny's team keeps theirs this short for a reason: CLAUDE.md loads into context at every session, and a longer file leaves less room for the actual work. Contents: project overview, stack summary, four-namespace MCP convention, Cedar policy location and pattern, build/test/eval commands, naming rules, "never commit AWS credentials," "always `terraform plan` before `apply`." Committed to git.

**Three custom skills at `.claude/skills/<name>/SKILL.md`:**

- `/add-mcp-tool` — scaffolds a new MCP tool in the correct namespace with consistent error handling, OpenTelemetry instrumentation, and audit-log emission
- `/add-outage-scenario` — scaffolds a new FIS scenario or Terraform overlay plus the ground-truth annotation and AgentCore Evaluations entry
- `/add-runbook` — generates a runbook in the parseable structure (title, prereqs, numbered steps, rollback, escalation) for `runbooks-api/*`

(As of Claude Code v2.1.101, April 11, 2026, slash commands and skills are unified. `.claude/commands/` still works for backward compatibility, but `.claude/skills/` is the recommended path. Every skill exposes a `/command-name` interface automatically.)

**Three hooks for deterministic enforcement** — CLAUDE.md is advisory; hooks are mandatory:

- **PreToolUse on `terraform apply`** — block apply unless `terraform plan` ran in the current session and produced no destructive changes outside an allowlist
- **PreCommit secrets scan** — grep staged diff for AWS access key patterns, hardcoded ARNs that should be variables, hardcoded account IDs
- **PostToolUse on `.tf` Edit/Write** — run `terraform fmt` automatically

The README documents the entire `.claude/` directory with a paragraph each on why those skills and hooks exist. That section becomes its own interview talking point.

### 3.10 Single-agent architecture

The 2026 hiring signal on agentic portfolios is unambiguous: hiring teams reward restraint and explicitly filter against sprawling multi-agent demos. (Source: 2026 GenAI portfolio guides; current job-board patterns for AIOps / Platform / AI Infrastructure roles.) The architecture ships as a single substantive lead agent that calls all four MCP namespaces directly. No subagents.

**v3.1 amendment (2026-05-19):** the v3 architecture originally included one stub subagent (a Lambda invoked over A2A by the lead agent for deploy-history lookup or ticket correlation) "to prove the A2A dispatch path works." That commitment is dropped. Reasoning: the stub added ~3–5 hours of agent-card-registration + OAuth-wiring work for marginal interview value. The architectural claim "I understand when multi-agent boundaries apply" is better made by *explaining when they apply* than by building one stub to point at — and the explanation already lives in the interview answer below. The four MCP namespaces are tool categories, not domains needing separate agents; ship that story cleanly without the stub.

Past pure single-agent, marginal returns turn sharply negative for a junior portfolio. Full multi-agent (three substantive agents on three SDKs, mirroring `aws-samples/sample-fully-autonomous-incident-response`) is ~25–40 hours of additional work and triggers the exact filter the 2026 market applies against sprawling demos. The AWS reference repo it would mirror currently has 7 commits and 1 star — it's an early aspirational reference, not a productized pattern.

The interview answer is: "Single-agent. Multi-agent expansion would require a concrete justification — a security boundary (different IAM blast radius), a scaling boundary (specialized agent that scales independently), or an organizational boundary (different team owning the agent). None of those apply to this capstone; the four MCP namespaces are tool categories, not domains needing separate agents." That is the senior-engineer position: restraint with a defended reason for it.

**What this means for the README and the pitch:** do NOT describe the architecture as "designed for multi-agent expansion." Multi-agent appears in the README only if someone asks; it does not lead.

#### Concrete expansion path (interview-answer backbone; NOT shipped, NOT in the README)

If/when an organization actually has the conditions — typically a multi-person SRE team with per-service ownership — the architecture extends naturally without rewrites. The expansion picture, sketched for the interview follow-up question:

- **Lead agent stays thin and routes by alarm name to per-service subagents over A2A.** It does not investigate; it dispatches. Its system prompt becomes ~20 lines: parse the alarm, identify the owning service from a name pattern or tag, dispatch via A2A, return the subagent's diagnosis to Slack.
- **Each service team owns one subagent.** The subagent has read-only IAM scoped to that team's resources only (the security boundary that justifies the split — payments-team alarms can't ever pull data from inventory-team resources). Each subagent runs as its own AgentCore Runtime with its own IAM role; Cedar policies at the Gateway scope tool access per-subagent.
- **Each service team owns one runbook store.** This is where `runbooks-api` becomes load-bearing. The subagent's system prompt reduces to: "fetch the runbook for this alarm name via `runbooks_api_lookup_runbook`, follow it step by step, deviate when observed evidence contradicts a runbook claim, surface gaps explicitly in the diagnosis." Each team's runbook store ships independently of the agent code — runbook changes don't require a container redeploy.
- **Evals scale per-team.** Each team's scenarios live in their team's repo, exercise their team's runbook store + subagent, and gate their team's PRs. The shared infrastructure is the harness shape (`bedrock-agentcore.Evaluate` + per-run JSON commits) and the LLM-as-judge prompts — both of which generalize.
- **MAST annotations stay project-wide.** Failure-mode taxonomy is the cross-team coordination point; failure modes from one team's scenarios inform another team's prompt tightening (e.g., FM-3.3 "Incorrect Verification" tends to recur, fixes are reusable).

Trigger conditions worth naming in the interview:
1. **Organizational:** ≥2 teams want to own different alarm classes without coordinating on a single AGENT.md. (The capstone has one team.)
2. **Security:** different alarm classes need different IAM blast radius — e.g., payments-data access scoped away from inventory. (The capstone is single-account, no internal trust boundary.)
3. **Scale of alarm classes:** ≥15–20 distinct alarm types make a single system prompt unwieldy. (The capstone targets 8–10 scenarios.)
4. **Operational independence:** runbook update cadence diverges per team — one team ships hourly during incidents, another ships quarterly. The agent shouldn't gate on the slower team. (Single-team capstone doesn't surface this.)

None of these are speculative for production AIOps in larger orgs; they're the *normal* shape past a certain scale. The capstone is deliberately below all four thresholds — which is why pure single-agent + AGENT.md is the right call **for this scope** and the wrong call for production beyond ~one team.

### 3.11 AGENT.md + runbooks-api split; both as versioned behavioral interfaces

The agent's reasoning is driven by **two** load-bearing artifacts working together, not one:

1. **`agent/AGENT.md`** — general investigation principles, the tool surface, hard rules, and a step-0 instruction to fetch any alarm-specific runbook before reasoning. Stays small (target ~2,500 tokens, like CLAUDE.md). Applies to *every* alarm.
2. **`runbooks-api/*` runbook store** (`runbooks/<alarm-class>.md`, parsed by `runbooks_api_lookup_runbook(alarm_name)`) — alarm-specific procedures, fetched on demand. Each runbook has the parseable structure from the `/add-runbook` skill (trigger, prereqs, numbered steps, rollback, escalation). Applies *only* when the alarm matches; costs zero tokens otherwise.

This split is the entire reason `runbooks-api` is one of the four canonical namespaces (§3.2, §3.6). Scenario-specific reasoning belongs in runbook content; general behavior belongs in AGENT.md. The alternative — every scenario adding prescriptions to AGENT.md — bloats the system prompt linearly with the corpus (already 3× growth by scenario 03; see `docs/agent-md-changelog.md` for the trajectory), forces the agent to re-read the entire surface on every alarm to find the applicable branch, and erases the runbook-deviation pattern that the multi-agent expansion path (§3.10) depends on.

**`runbooks-api` is a current spec gap, not a future iteration.** Per §3.6 and the Day 30 / Day 36 sprint commitments, the runbook content + `runbooks_api_lookup_runbook` tool were supposed to ship by now. They didn't. As of scenario 03, alarm-specific prescriptions have been landing in AGENT.md instead, which is why AGENT.md grew from 54 to 169 lines in two scenarios. Closing this gap is the highest-priority architectural cleanup before scenario 04.

**Both artifacts are versioned behavioral interfaces** — changes to either affect every scenario in the corpus and every production alarm the agent handles. Treating either as a free-form text file is the wrong model; they are structurally analogous to public APIs on a load-bearing library.

**Discipline:** every substantive edit to `agent/AGENT.md` lands with a paired entry in [`docs/agent-md-changelog.md`](../agent-md-changelog.md), in the same commit. The entry records:

- **Motivation** — which scenario, which run JSON surfaced the gap. The eval corpus is the regression test; the run JSON is the test report.
- **Change summary** — what was added/removed/modified at the prescription level (not line-level; that's git).
- **Validation** — the post-change run JSON that demonstrates the fix worked. An AGENT.md change without a corresponding Match (2.0) verdict is half a change.
- **Risk** — what else this change could affect. Broadening a trigger to fix scenario N can regress scenario N-1; the changelog forces the author to consider that explicitly.
- **Runbook check** — whether the prescription being added is general (belongs in AGENT.md) or alarm-specific (belongs in a runbook). Once `runbooks_api_lookup_runbook` ships, every "scenario-specific" prescription currently in AGENT.md gets migrated out. Future changes default to runbook entries unless the behavior is genuinely general.

A parallel changelog discipline applies to runbooks themselves once `runbooks-api` is built (one file per alarm class, each with its own version history).

**Why this matters specifically for this project's portfolio narrative:** the eval-loop-finds-a-real-bug story (FM-3.3 caught + fixed + verified, end-to-end) only holds if the chain of cause→fix→validation is traceable per change. The changelog is the human-readable manifest of that chain across scenarios. Without it, "we fixed it" becomes a claim instead of a citation.

Codified as a hard rule in `CLAUDE.md` rule #6. Adding scenarios to the corpus implicitly adds the obligation to update the changelog whenever a scenario surfaces a gap — and, once `runbooks-api` ships, to write the prescription as a runbook entry first and as an AGENT.md edit only if it's genuinely general.

#### 3.11.1 The no-railroading rule

When a scenario fails the eval, the corrective action depends on which artifact owns the gap. The decision tree is binary, and getting it wrong is the most common way to silently degrade the eval's value:

- **If the failure is alarm-specific** — the scenario surfaces a fact or procedure only relevant to this alarm class — the fix is a **runbook entry**, not an AGENT.md prescription.
- **If the failure is a gap in general reasoning** — the agent would also need this principle to handle alarms it's never seen — the fix is an AGENT.md edit, but **phrased as a general principle**. "When `describe_task_definition` looks correct and target health still shows unhealthy targets, reach for logs" is general. "When the alarm name contains `broken-env`, check for missing `$REQUIRED_API_KEY`" is railroading.

**The anti-pattern to avoid:** agent fails scenario N → author adds scenario-N-specific instructions to AGENT.md → agent now passes scenario N. The agent didn't generalize; it got handed the answer key. The eval becomes a tautology — it's just testing whether the agent can read its own system prompt. Sessions 02 and 03 partly did this to AGENT.md (54 → 169 lines across two scenarios) before the runbooks split was identified as the architectural fix. Without this rule explicit, the pattern will recur every time a scenario underperforms.

The rule applies symmetrically to runbooks: a runbook for alarm class X should not become a railroad either. A runbook lists procedure steps + expected evidence at each step + how to recognize when the procedure doesn't match observed reality. If the runbook reads like "the answer for this scenario is Y," it's too specific. If a runbook fix would only help one alarm in the class, the alarm class is too narrow and the runbook itself needs decomposition.

#### 3.11.2 Runbook-less scenarios by design

**At least ~3 of the 8–10 corpus scenarios ship without a runbook**, deliberately. These are the generalization tests: the agent's `runbooks_api_lookup_runbook` call returns null, and it must reason from AGENT.md principles + observable evidence alone. Without these scenarios, the corpus only tests "agent follows scripted procedures"; with them, it tests "agent generalizes to alarm classes it has no scaffolding for" — the actual claim a portfolio needs to make.

The runbook-less scenarios should span fault families (network, dependency, capacity, security, config-drift) so the generalization claim isn't restricted to one shape. A run-bookless scenario that scores Match (2.0) is the load-bearing evidence that AGENT.md's general principles do work; one that scores NoMatch points at *AGENT.md*'s general reasoning being too thin, not at the need for another runbook entry. That distinction is what makes the eval able to grade the general-reasoning surface separately from the runbook coverage surface — which is what every productized agent vendor's blog says they had to figure out the hard way.

Currently (Day 36): 0 runbook-less scenarios since runbooks themselves haven't shipped. Once `runbooks-api` lands, designate ~3 of scenarios 04–10 as runbook-less from the design phase. Document each one's runbook-less status in the scenario YAML so it's visible to anyone reading the corpus.

---

## 4. Sprint structure (Days 31–36)

Total: six days. Day 31 is browser-only (reading and orientation). Day 32 onward, Claude Code is the primary tool — the day-31-only-browser-then-flip pacing in v2 was wrong: it gated Claude Code out of the exact infrastructure-hardening work where its leverage is highest (3–4× speedup on Terraform tasks per current benchmarks). The shape of the rebuilt sprint: compress Days 32–33 to free a full day, reallocate that day to Day 34 (agent design — where Claude Code's leverage is lowest and judgment burden is heaviest) and Day 35 (eval rigor — the artifact most likely to actually open interview doors).

**Day 31 — Substrate read + AgentCore orientation.** Browser-only; no Claude Code yet. Reading order matters today, in this sequence: (1) Molumuri et al. AWS DevOps Blog post — the canonical architecture being mirrored; (2) AgentCore Evaluations developer guide — just GA'd, not in any LLM training data; (3) IBM/Berkeley MAST Hugging Face post. Then the operational gap-fill: SSM Session Manager lab (EC2 in private subnet, no inbound SSH, IAM role with SSM permissions), CloudTrail, AWS Config, brief touch on GuardDuty and IAM Access Analyzer. End of day: clone `aws-samples/sample-fully-autonomous-incident-response` and read the structure — do not run it; steal the pattern. Project memory updated per Section 8.

**Day 32 — Claude Code on. AgentCore depth + production stack hardening.** **First thing in the morning:** install Claude Code (`curl -fsSL https://claude.ai/install.sh | bash`), write `CLAUDE.md` at the repo root (~2,500 tokens) per Section 3.9, install the PreCommit secrets-scan hook and the PreToolUse `terraform apply` gate. Do this BEFORE any infrastructure code is written. **Mid-morning, browser:** AgentCore Runtime, Memory, Gateway, Identity docs (~2 hours). Scan Gateway and Identity docs specifically for OAuth 2.1 + Cedar policy examples. **Afternoon, Claude Code primary:** Terraform infrastructure hardening — second NAT gateway, second RDS replica, ACM certificate request, Route 53 records. This is incremental hardening on Week 3 Terraform fluency, and Claude Code's leverage is highest on exactly this shape of work. Expect ~4 hours instead of the previously-planned 8–10 hours. Review every Terraform plan diff manually; Claude Code generates, you approve.

**Day 33 — Finish stack + agent design before any agent code.** **Morning, Claude Code:** complete HTTPS listener on ALB, WAF attached, CloudWatch agent installed via user data. Verify end-to-end. **Afternoon and evening — manual design work, Claude Code only for review:** design the MCP server tool surface in detail before any code is written. List all four namespaces' tool names, signatures, error responses, and OpenTelemetry span names in a design doc (`design/mcp-server.md`). Draft the lead agent's system prompt — investigation phases, when to call which namespace, when to stop and post to Slack vs. when to request human review. Sketch one or two Cedar policy files in pseudocode. This is the work Claude Code is worst at, and Day 34 will go much faster if the design is committed before code starts.

**Day 34 — Build the MCP server and the agent.** Claude Code primary. **Morning:** write the `/add-mcp-tool` skill first, then use it to scaffold the first MCP tool — meta-recursive; the tool that builds the tools. OpenTelemetry instrumentation from the start (AgentCore Observability or CloudWatch Application Signals). Tool organization follows the four namespaces. **Afternoon:** wire the agent on AgentCore Runtime using the system prompt designed yesterday. Configure the alarm → SNS → agent path. **Evening:** debug to working hello-world — agent receives a fake alarm, calls one tool, posts a structured message to Slack. If hello-world isn't green by end of Day 34, do not start Day 35 until it is. The eval pipeline depends on this working.

**Day 35 — Outage corpus + AgentCore Evaluations run.** **Morning:** write the `/add-outage-scenario` skill first, then use it to scaffold the corpus per Section 3.4 (4 FIS + 4–6 Terraform overlays). FIS templates are codified in Terraform alongside the rest of the stack (`aws_fis_experiment_template`). **Afternoon and evening:** run the agent against all scenarios via AgentCore Evaluations with the evaluator configuration from Section 3.5. Annotate every failed run with MAST failure mode using the published LLM-as-judge classifier. Build the comparison table iteratively — every passing scenario gets a row. Expect first-run eval debugging to eat hours; don't compress this day. The eval table is the single artifact most likely to open interview doors.

**Day 36 — Cedar guardrails, README.** Implement the Cedar policy at Gateway as the primary write gate; verify Slack approval as second layer. Document at least one Cedar policy in the README. Install the third hook (PostToolUse `tf fmt`). Write the `/add-runbook` skill if not yet done. **README:** lead with the eval table — that's the differentiator the market is rewarding most heavily, foreground it. Architecture diagram (Agent Space → Gateway with Cedar → MCP namespaces → AWS APIs, plus the audit S3 bucket) comes after the eval table. README section documenting the `.claude/` directory and the workflow customization. **"Alternative architectures considered" paragraph** covers Claude Managed Agents on Claude Platform on AWS as an alternative build option, and AWS DevOps Agent / PagerDuty SRE Agent as buy comparators, with reasoning for staying on AgentCore (AWS-native vocabulary, data residency, infrastructure-for-free). **Do NOT include a "next iteration: full multi-agent" section.** If asked in interview, the answer is the restraint-framed Section 3.10 position; the README does not lead with it. If Cedar slips, document the intent and ship without — do not drop the MAST annotations, the eval table, or the Claude Code workflow section. (v3.1: stub subagent originally bundled in this day is dropped; see §3.10.)

---

## 5. What we explicitly decided NOT to do

- **Don't downgrade or cut the AI workload project.** The May market analysis established AI fluency as the entry-level differentiator. Generic playbooks didn't have that data; we do.
- **Don't go Kubernetes-heavy.** Day 26 literacy is enough. ECS/Fargate + Docker + AWS networking covers the target roles.
- **Don't add Ansible.** Terraform + cloud-init + user data + container images cover configuration management for an AWS-first cloud-native track.
- **Don't restructure the original 42-day plan.** Days 31–36 were reassigned to Triage; the rest of the spine stands.
- **Don't compete with productized agents on capability.** Build the pattern, not the product.
- **Don't write the agent on raw Anthropic API.** Use AgentCore. Vocabulary alignment beats pedagogical purity.
- **Don't ship the agent without the eval table.** The comparison table is the artifact. The agent is the substrate that produces it.
- **Don't ship the agent without the MAST annotations.** The taxonomy column is the differentiator vs other agent demos in the hiring pool.
- **Don't ship without the `.claude/` directory.** That's the visible Claude Code workflow signal interviewers are explicitly asking for in 2026.
- **Don't position the project as "designed for multi-agent expansion."** Ship pure single-agent. Full multi-agent would require a security, scaling, or organizational boundary that doesn't apply to this capstone. The 2026 hiring signal explicitly filters against sprawling multi-agent demos; restraint is the senior signal. (v3.1: the stub subagent originally included to demonstrate the A2A dispatch path is also dropped — see §3.10.)
- **Don't gate Claude Code out of Days 32–33.** v2 did this and was wrong. Claude Code's leverage is highest on the infrastructure-hardening work in Days 32–33 (3–4× speedup on Terraform tasks per current benchmarks). Pull it in from Day 32 morning, after CLAUDE.md and the hooks are installed.

---

## 6. SAA timing rule (conditional)

- If by Day 31 you are scoring **75% or higher on Tutorial Dojo practice exams**, schedule the SAA exam for the gap between project work and applications.
- If below that threshold, **push SAA to Month 2** and do not let it eat project days.

Current expectation: push to Month 2. Week 2 SAA-difficulty assessment scored 59%. Cert serves the job hunt; the job hunt does not serve the cert.

---

## 7. Working assumptions about Claude's capability

Current model: Claude Opus 4.7 (and Sonnet 4.6 / Haiku 4.5 for lighter work). Knowledge cutoff: end of January 2026. As of v2 (May 13, 2026), the cutoff is ~3.5 months stale.

**Reliable from training:** MCP basics, AgentCore preview-era and October 2025 GA features, re:Invent 2025 announcements through ~early December (including Episodic Memory and AgentCore Evaluations preview), Anthropic API and tool use, standard AWS services, Terraform AWS provider, Python tooling, Docker, ECS, Argo CD basics, CNCF tooling generally.

**Unreliable from training (verify or paste in docs):** AgentCore Evaluations GA specifics (March 31, 2026), AWS DevOps Agent GA specifics (March 31, 2026), MAST analysis (Hugging Face Feb 18, 2026), Claude Code v2.1.101 skills/commands unification (April 11, 2026), MCP 2026 roadmap (March 9, 2026), PagerDuty Spring 2026 release, AgentCore SDK changes after February 2026, current pricing for any of the above.

**Mitigations during the sprint:**

1. Paste current documentation into context before asking for code on anything from Section 7's "Unreliable" list.
2. Push Claude to web-search when uncertain about anything that GA'd after October 2025. Signal: if Claude sounds confident about API specifics for a recent feature, ask "are you sure that's current?"
3. Verify by running, not by reading. Deploy small pieces and check at runtime.
4. Use the AgentCore Starter Toolkit as scaffolding. Modify it; don't generate it from scratch.

---

## 8. Project memory uploads

Selective, not exhaustive. Better filenames produce better retrievals; descriptive and dated.

Upload before Day 31 starts:

- Molumuri/Fine/Alioto/Qureshi — "Leverage Agentic AI for Autonomous Incident Response with AWS DevOps Agent" (AWS DevOps Blog, March 31, 2026)
- AgentCore Evaluations developer guide (GA March 31, 2026)
- AgentCore Runtime developer guide section
- AgentCore Gateway developer guide section (Cedar policy integration)
- AgentCore Identity developer guide section (OAuth 2.1)
- AgentCore Memory developer guide section
- AgentCore Starter Toolkit README and one or two official example projects
- "Build multi-agent site reliability engineering assistants with Amazon Bedrock AgentCore" (AWS ML Blog) — tool namespace pattern
- `aws-samples/sample-fully-autonomous-incident-response` README and architecture docs
- AWS FIS getting-started + scenario library reference
- IBM + UC Berkeley MAST Hugging Face post
- MCP Python SDK docs + the official server-building tutorial
- PagerDuty MCP server README (`--enable-write-tools` flag pattern)
- Anthropic tool use guide and AgentCore + Anthropic integration docs

What NOT to upload:

- The full Bedrock developer guide
- Every AWS service doc
- The full Terraform AWS provider reference
- Marketing pages, blog posts, or anything web-searchable on demand
- The full Claude Code docs (web-search on demand; only the sections you actively need)

Filename convention: descriptive, dated, lowercase. Examples: `agentcore-evaluations-developer-guide-2026-03.md`, `aws-devops-agent-architecture-molumuri-2026-03.md`, `mast-failure-modes-ibm-berkeley-2026-02.md`.

---

## 9. Workflow: Claude Code from Day 32 morning

**Day 31: browser only.** Reading territory. AgentCore is new; the Molumuri et al. architecture, AgentCore Evaluations developer guide, and MAST paper need careful manual reading. No code today.

**Day 32 morning: install Claude Code first thing, then enable it for everything else.** Native binary install. Configure with the same Anthropic API key. Write `CLAUDE.md` at the repo root before any infrastructure code is written, including the four MCP namespaces, the Cedar guardrail intent, the eval scoring rubric, the AWS DevOps Agent architectural pattern being mirrored, and the MAST top failure modes. Install the PreCommit secrets-scan hook and the PreToolUse `terraform apply` gate hook before any sprint code is written. Hooks are mandatory enforcement; CLAUDE.md is advisory.

**Days 32–36: Claude Code is the primary tool, with deliberate exceptions.** Where to lean on it heaviest: Terraform infrastructure hardening (Day 32 afternoon, Day 33 morning), MCP server tool scaffolding (Day 34 morning), outage scenario scaffolding (Day 35 morning), README polish (Day 36 evening). Where to deliberately work manually with Claude Code only for review: MCP tool surface design (Day 33 afternoon), lead agent system prompt (Day 33 afternoon), Cedar policy authoring (Day 36 morning). The judgment of when to lean and when to design-first is itself a signal — "I used Claude Code where its leverage was highest and worked manually where judgment burden was heaviest" is a more sophisticated answer than either uniform-use extreme.

**Calibration note:** v2's pacing assumed Days 32–33 would be ~10–12 hours of careful manual infrastructure work. Real-world Claude Code benchmarks on infrastructure tasks: ~3–4× speedup for incremental Terraform on familiar territory (e.g., a first-person account on AWS infrastructure with Claude Code reported tasks that previously took 30–45 minutes now take ~10 minutes; a Japanese cloud integrator case study reports up to 90% reduction for specific tasks and 80% reduction in code review time). The structural error to avoid in the other direction: Claude Code's leverage on novel agent design work (Day 34) is much weaker — METR's 2025 RCT found a 19% *slowdown* for experienced developers working on familiar codebases, and the gap closes only partially in METR's 2026 follow-up. Use the freed Day 32–33 cushion to extend Day 34 (agent design) and Day 35 (eval rigor), not to add scope.

---

## 10. Interview framing

**Primary pitch (current-on-the-landscape interviewers):**

> "I built a small open-source incident response agent on AWS Bedrock AgentCore plus a custom MCP server with four canonical namespaces. I evaluated it against a deliberate outage corpus (Terraform overlays today, AWS FIS chaos faults next) using AgentCore's on-demand `Evaluate` API — 8 evaluators per scenario, including two LLM-as-judges in a different model family than the agent — and classified the failures with the MAST taxonomy from the IBM and Berkeley paper. The eval loop already caught a real regression: it surfaced MAST FM-3.3 on first run of scenario 02, an `AGENT.md` fix landed, the same eval verified the fix. The architecture mirrors what AWS published when DevOps Agent went GA in March."

Every clause maps to a specific, current, citable thing.

**Warm-up pitch (less technical or less-current interviewers):**

> "I built a small open-source SRE agent on AWS Bedrock AgentCore plus MCP, then evaluated it against a deliberate outage simulator on a production-style AWS stack. The evaluation harness graded the agent's diagnoses automatically — and the first time I ran it, it caught a regression I would have shipped without it."

**Translation pitch (older-enterprise interviewers):**

> "AgentCore is AWS's platform for building AI agents, the same one their newly-launched DevOps Agent runs on."

**Talking points to have ready:**

- **Why AgentCore over raw API:** vocabulary alignment with current AWS hiring conversations, infrastructure for free, direct parallel to AWS DevOps Agent's own architecture.
- **Why MCP with four namespaces:** industry-standard interface; Block + PagerDuty + goose is the precedent; four-namespace convention matches AWS published reference architectures.
- **Why Cedar at Gateway plus Slack approval:** deterministic policy can't be prompt-injected; matches AWS DevOps Agent reference architecture; defense in depth.
- **Why FIS over scripts:** reusable, parameterized chaos corpus aligned with how production resilience testing is actually run.
- **Why AgentCore Evaluations natively:** GA March 31, 2026; mirrors AWS-published methodology; the differentiator moves up the stack to scenario design and failure annotation.
- **Why MAST annotation:** classifying failures against a published taxonomy with a 94%-accurate classifier is more credible than ad-hoc commentary. Most agent portfolios don't do this.
- **Why scoped-down skill tiers:** implementing tiers 1 and 2 with a documented gap to tier 3 (learned) shows deliberate scope rather than papering over absence.
- **Why CLAUDE.md + skills + hooks:** the engineering substrate is part of the portfolio; HN hiring posts in 2026 explicitly ask for this.
- **Why modular design:** the underlying primitives keep moving and the architecture accommodates that. This is itself a portfolio talking point.
- **Build-vs-buy framing (three-way):** the conversation in 2026 isn't just "build vs buy" — it's a three-way: build on AgentCore (AWS-native), build on Claude Managed Agents (Anthropic-native via Claude Platform on AWS), or buy AWS DevOps Agent / PagerDuty SRE Agent. Articulate the trade-offs: data residency (Bedrock/AgentCore keeps data in AWS; Claude Platform processes outside the AWS security boundary), AWS-native vs Anthropic-native feature velocity, billing model differences. Having built on one means speaking credibly to all three.
- **Why pure single-agent (not multi-agent):** the 2026 hiring signal on agentic portfolios explicitly filters against sprawling multi-agent demos. The four MCP namespaces are tool categories, not separate agent domains. Multi-agent expansion would require a concrete justification — a security boundary (different IAM blast radius), a scaling boundary (specialized agent that scales independently), or an organizational boundary (different team owning the agent). None applies here. Marginal returns past the single lead agent are sharply negative for this scope. (v3.1: the stub subagent originally included to demonstrate the A2A dispatch path is dropped — its marginal interview value was outweighed by the agent-card-registration + OAuth-wiring cost; the architectural claim is better made by the interview answer than by a stub Lambda.)
- **Claude Code time calibration:** the project pulled Claude Code in from Day 32 morning, not the conventional "use it for everything later" pattern. Reason: real-world benchmarks show ~3–4× speedup on Terraform infrastructure tasks but minimal-to-negative speedup on novel agent design work (METR's 2025 RCT found a 19% slowdown for experienced developers on familiar codebases). The pacing matches the tool's actual leverage curve — heavy use on Days 32–33 infrastructure hardening, deliberately manual on Day 33 afternoon agent design, heavy use again on Day 34 MCP server scaffolding. That calibration is itself a signal.
- **DORA / Faros tension:** the 2025 DORA report finds 90% of orgs use AI with throughput up; Faros's 2026 telemetry on 22,000 developers shows time-in-PR-review up 441% and incidents-per-PR up 242.7% under high AI adoption. Engage with this tension — AI is both faster ship and more rework, and platform quality is the deciding factor.

**Awareness asymmetry:** present the project assuming the interviewer is current on this landscape. Most interviewing engineers and hiring managers in cloud-adjacent roles are tracking AgentCore, MCP, and the productized agent space. Most candidates aren't. That's the wedge.

---

## 11. Decision log

| # | Decision | Choice | Why |
|---|---|---|---|
| 1 | Project type | AIOps incident response agent + outage corpus on production AWS stack | Aligns with AI-fluency hiring premium and surviving entry-level role types |
| 2 | Agent platform | Amazon Bedrock AgentCore (not raw Anthropic API) | Current AWS pattern; same platform AWS DevOps Agent runs on; resume vocabulary; infrastructure for free |
| 3 | Tool exposure | Custom MCP server organized into four namespaces (`ecs-api`, `logs-api`, `metrics-api`, `runbooks-api`) | Industry-standard interface; modular; matches AWS published reference architectures |
| 4 | MCP auth | OAuth 2.1 + Resource Indicators via AgentCore Identity | Production standard (RFC 8707); AgentCore Identity is the easy path |
| 5 | Write-action gating | Cedar policy at AgentCore Gateway + Slack approval (two layers in series) | Deterministic policy gate + human review; matches AWS DevOps Agent reference; cannot be prompt-injected |
| 6 | Audit trail | S3 Object Lock, append-only; reasoning + tool calls per turn | Matches AWS DevOps Agent's "immutable audit journal" pattern |
| 7 | Outage corpus | 4 AWS FIS scenarios + 4–6 Terraform overlay scenarios | Reusable, parameterized; aligns with how production resilience testing is run |
| 8 | Evaluation | AgentCore Evaluations (≥5 built-in + 1–2 custom LLM-as-judge) | GA March 31, 2026; mirrors AWS-published methodology; frees a day of harness building |
| 9 | Failure analysis | MAST failure-mode taxonomy annotation on every failed run | Reproducible (94% classifier accuracy from IBM/Berkeley); rare in portfolios; signals research literacy |
| 10 | Performance comparison | Cite STRATUS / ITBench / AIOpsLab baselines in README | Makes the comparison table interview-defensible |
| 11 | Architecture mirror | Explicit alignment with Molumuri et al. (AWS DevOps Blog, March 31, 2026) | More specific and verifiable than "inspired by productized agents" |
| 12 | Infrastructure | Production-grade ($150–200 budget): Multi-AZ NAT, Multi-AZ RDS, HTTPS via ACM, WAF | Looks like a real service, not a lab |
| 13 | Modularity | Pin MCP protocol version; component swappability | The underlying stack keeps moving (MCP 2026 roadmap, model swaps) |
| 14 | Claude Code: project constitution | CLAUDE.md at repo root, ~2,500 tokens, committed | Boris Cherny's team convention; loaded every session; visible interview artifact |
| 15 | Claude Code: workflow skills | `/add-mcp-tool`, `/add-outage-scenario`, `/add-runbook` at `.claude/skills/<name>/SKILL.md` | Enforces project conventions across the codebase; HN hiring signal asks for this |
| 16 | Claude Code: deterministic guardrails | PreCommit secrets scan + PreToolUse `terraform apply` gate + PostToolUse `tf fmt` | CLAUDE.md is advisory; hooks are mandatory; matches current Claude Code best practice |
| 17 | Claude Code path | Use `.claude/skills/` (post-v2.1.101 unification) | Recommended path as of April 11, 2026 |
| 18 | SAA exam | Conditional on ≥75% practice exam scores; current expectation push to Month 2 | Cert serves the job hunt, not vice versa |
| 19 | Sprint workflow | Claude Code from Day 32 morning (after CLAUDE.md and hooks installed); Day 31 browser-only | v2's "Claude Code at Day 33 seam" gated the tool out of the exact infrastructure work where its leverage is highest; real-world benchmarks show 3–4× speedup on Terraform tasks. The freed time reallocates to Day 34 (agent design, where Claude Code's leverage is lowest) and Day 35 (eval rigor) |
| 20 | Doc strategy | Selective uploads + consolidated revisions | Retrieval quality drops on bloated corpora |
| 21 | Multi-agent architecture | Pure single lead agent; do NOT position as "designed for" multi-agent expansion. (v3.1 amendment: stub subagent dropped — see §3.10.) | 2026 hiring signal explicitly filters against sprawling multi-agent demos (per current GenAI portfolio guides); restraint is the senior signal. Full multi-agent would require a security, scaling, or organizational boundary that doesn't apply to this capstone. The four MCP namespaces are tool categories, not separate agent domains. The v3 stub-subagent commitment was dropped 2026-05-19 because the marginal interview value didn't justify the ~3–5h of agent-card + OAuth wiring — the architectural claim is better made by *explaining when multi-agent boundaries apply* than by building a stub Lambda to point at. AWS reference repo (`sample-fully-autonomous-incident-response`) currently has 7 commits, 1 star — early aspirational reference, not productized pattern |
| 22 | Anti-pattern: own-model self-evaluation | Run evaluators on a different model family than the agent | Cross-model robustness; avoids the model grading its own homework |
| 23 | Anti-pattern: one-shot eval | Run eval harness on every change to prompts/skills/tools | "We didn't set out to build an evaluation platform; it's what it took to trust the agent" — Datadog Bits AI SRE team |
| 24 | "Alternative architectures considered" in README | Three-way comparison: AgentCore (chosen), Claude Managed Agents on Claude Platform on AWS, AWS DevOps Agent (buy) | Three-way build-vs-buy is the senior-engineer framing every cloud team is having in 2026; substantiates Section 3.8's "modular design" claim with explicit trade-off discussion rather than abstract assertion |

---

## Doc history

- **v1** — May 5, 2026. Initial commit.
- **v2** — May 13, 2026. Consolidates Revision 1 deltas (AgentCore Evaluations native, Cedar at Gateway, FIS-based outage corpus, MAST annotation, four MCP namespaces, OAuth 2.1, explicit AWS DevOps Agent architecture mirror) and adds Section 3.9 (Claude Code workflow customization: CLAUDE.md + skills + hooks).
- **v2.1** — May 13, 2026. In-place edit. Adds Section 3.10 (multi-agent architecture: designed for, partially deferred), incorporates stub subagent wiring and the "alternative architectures considered" README paragraph into Day 36, expands Section 10 build-vs-buy talking point to a three-way comparison, adds Section 10 multi-agent expansion talking point, updates decision log row 21 (multi-agent stance) and adds row 24 (alternative architectures in README).
- **v3** — May 14, 2026. Major revision per the policy. Two structural shifts: (1) the "designed for multi-agent expansion" framing is removed throughout (Sections 3.10, 4 Day 36, 5, 10, 11 row 21). The 2026 hiring signal explicitly filters against sprawling multi-agent demos; the project now pitches as single-agent with one stub subagent demonstrating the A2A path, with multi-agent expansion explicitly framed as out-of-scope absent a security/scaling/organizational boundary. (2) Sprint pacing rebuilt: Claude Code enters Day 32 morning (after CLAUDE.md and hooks) instead of Day 33 evening. Real-world benchmarks on Terraform infrastructure tasks show 3–4× speedup; the freed time reallocates to Day 34 (agent design, Claude Code's weakest leverage) and Day 35 (eval rigor). Adds new sprint-pacing decision log row updates (rows 19, 21) and a Section 10 talking point on Claude Code time calibration. Real-world position at v3 commit: Day 26 (Week 4 Kubernetes intro); the sprint starts later than v2 assumed.
- **v3.1** — May 19, 2026. In-place amendment, four deltas: (1) Drops the stub subagent commitment from §3.10, §4 Day 36, §5, §10, and §11 row 21. Rationale: marginal interview value didn't justify the wiring cost; the architectural claim about multi-agent boundaries is better made by the interview answer than by a stub Lambda. (2) Adds the "Concrete expansion path" sub-section to §3.10 — paints what multi-agent looks like under our specific architecture (lead-agent-routes, per-service subagents over A2A, per-team runbook stores, per-subagent Cedar scoping) so the interview follow-up "how would this scale?" has a concrete answer. (3) §3.2 MCP auth corrected from "OAuth 2.1 via AgentCore Identity" to **AWS_IAM (SigV4)** — the v3 framing didn't match the live `bedrock-agentcore-control` API; see `[[agentcore-identity-oauth-myth]]` memory. (4) §3.5 evaluation framing fully replaced: drops the 2026-05-18 "online-only" amendment (superseded by the 2026-05-19 discovery of `bedrock-agentcore.Evaluate` on the runtime client). On-demand is now the primary path; 8 evaluators wired (5 built-ins + Trajectory + 2 customs); the Strands-shape gotcha gets a dedicated mention. §3.4 + §10 + README + README status table + scenario writeups updated to reflect 2-overlay corpus, both Match (2.0), MAST FM-3.3 caught + fixed end-to-end. Sprint impact: Day 36 simplifies to Cedar + README; freed time reallocates to FIS chaos scenarios next.

**Revision policy going forward:** if a single delta lands (small new fact, minor scope adjustment), edit in place and add a decision-log row. If a major shift hits (scope change, new productized agent reframes the market, fundamental architectural rethink), write a fresh consolidated version rather than appending. This keeps the retrieval quality bias intact.

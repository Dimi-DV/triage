# Triage Project: Architecture, Sprint Plan, and Decision Log

**Version:** v2.1 (consolidated + multi-agent reconciliation)
**Status:** committed, May 13, 2026
**Sprint:** Days 31–36 of the 42-day battle plan
**Real-world position at v2:** Day 30 (incident response + SRE practices). Sprint starts tomorrow.
**Owner:** Dimitrije

This document records the decisions for the Triage portfolio project that runs between the end of tool-learning (Day 30) and the start of the job-application sprint. It is the authoritative reference for project scope, architecture, and reasoning. If anything in a future conversation conflicts with this doc, this doc wins until explicitly revised.

v2 consolidates Revision 1 (May 13) and the Claude Code workflow customization material we discussed afterward into a single baseline. The full reasoning trail lives in Section 11 (Decision Log).

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

MCP auth uses **OAuth 2.1 + Resource Indicators (RFC 8707) via AgentCore Identity** — the production standard. Pin the MCP protocol version in the server; flag the upcoming statelessness migration (MCP 2026 roadmap) in the README's "known limitations" section.

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

### 3.5 Evaluation: AgentCore Evaluations + MAST failure-mode taxonomy

The evaluation harness is **AgentCore Evaluations** (GA March 31, 2026). Configure with at least 5 built-in evaluators (goal success rate, tool selection accuracy, tool parameter accuracy, response correctness, safety) plus 1–2 custom LLM-as-judge evaluators ("did the agent ask before destructive action?", "did the agent's diagnosis match the ground-truth root cause to within reasonable equivalence?").

For every failed run, annotate against the **MAST taxonomy** (IBM + UC Berkeley, Hugging Face Feb 18, 2026): FM-3.3 Incorrect Verification, FM-2.6 Reasoning-Action Mismatch, FM-1.5 Unaware of Termination Conditions, FM-1.4 Loss of Conversation History, others as applicable. The MAST LLM-as-judge classifier reaches 94% accuracy with 0.88 inter-annotator agreement — reproducible enough to cite.

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

### 3.10 Multi-agent architecture: designed for, partially deferred

Multi-agent (lead + subagents over A2A protocol) is becoming the canonical AIOps pattern. AWS's own `aws-samples/sample-fully-autonomous-incident-response` uses a Monitoring Agent + Operations Orchestrator + Host Orchestrator on A2A. Fully implementing three real agents on A2A with proper inter-agent debugging is more than this sprint can absorb. The compromise: design every architectural choice so multi-agent expansion is plumbed but not realized.

Concretely:

- The four MCP namespaces (`metrics-api`, `logs-api`, `ecs-api`, `runbooks-api`) are each a future subagent's surface area. No extra work to keep this true.
- The lead agent's system prompt reads as an orchestration script — explicit investigation phases that map to subagent dispatch.
- On Day 36, wire one **stub subagent** (a Lambda invoked over A2A by the lead agent for a non-critical task like deploy history lookup or ticket correlation). The stub doesn't need to be smart; it needs to exist and be invocable.
- The README documents the multi-agent expansion path as a "next iteration" with the stub as proof the architecture supports it.

This is the "designed-for-multi-agent" interview answer without the sprint cost of building three real agents. Same scope discipline as the learned skill tier in Section 3.6 — designed for, partially deferred.

---

## 4. Sprint structure (Days 31–36)

Total: six days. The first three are learning-and-substrate. The last three are project execution. Workflow shifts from browser conversation to Claude Code at the Day 33 seam.

**Day 31 — Substrate read + AgentCore orientation.** Reading order matters today, in this sequence: (1) Molumuri et al. AWS DevOps Blog post — the canonical architecture being mirrored; (2) AgentCore Evaluations developer guide — just GA'd, not in any LLM training data; (3) IBM/Berkeley MAST Hugging Face post. Then the operational gap-fill: SSM Session Manager lab (EC2 in private subnet, no inbound SSH, IAM role with SSM permissions), CloudTrail, AWS Config, brief touch on GuardDuty and IAM Access Analyzer. End of day: clone `aws-samples/sample-fully-autonomous-incident-response` and read the structure — do not run it; steal the pattern. Project memory updated per Section 8.

**Day 32 — AgentCore depth + production stack upgrade begins.** AgentCore Runtime, Memory, Gateway, Identity. Scan Gateway and Identity docs specifically for OAuth 2.1 + Cedar policy examples. Begin upgrading the existing Terraform stack toward production-style: second NAT gateway, second RDS replica, ACM certificate request, Route 53 records.

**Day 33 — Finish production stack + workflow handoff.** Complete the upgrade: HTTPS listener on ALB, WAF attached, CloudWatch agent installed via user data. Verify end-to-end. **Evening:** install Claude Code; write `CLAUDE.md` at repo root (~2,500 tokens) including the four MCP namespaces, the Cedar guardrail intent, the eval scoring rubric, the AWS DevOps Agent architectural pattern being mirrored, and the MAST top failure modes. Install the two universal hooks (PreCommit secrets scan, PreToolUse `terraform apply` gate).

**Day 34 — Build the agent and the MCP server.** Workflow flips to Claude Code as primary tool. **Morning:** write the `/add-mcp-tool` skill first, then use it to scaffold the first MCP tool — meta-recursive; the tool that builds the tools. OpenTelemetry instrumentation from the start (AgentCore Observability or CloudWatch Application Signals). Tool organization follows the four namespaces. Wire the agent on AgentCore Runtime. Configure the alarm → SNS → agent path. Get to a working hello-world: agent receives a fake alarm, calls one tool, posts a structured message to Slack.

**Day 35 — Outage corpus + AgentCore Evaluations run.** **Morning:** write the `/add-outage-scenario` skill first, then use it to scaffold the corpus per Section 3.4 (4 FIS + 4–6 Terraform overlays). Run the agent against all scenarios via AgentCore Evaluations with the evaluator configuration from Section 3.5. Annotate every failed run with MAST failure mode.

**Day 36 — Cedar guardrails, stub subagent, README, portfolio packaging.** Implement the Cedar policy at Gateway as the primary write gate; verify Slack approval as second layer. Document at least one Cedar policy in the README. Install the third hook (PostToolUse `tf fmt`). Write the `/add-runbook` skill if not yet done. **Wire one stub subagent via A2A** — a Lambda invoked by the lead agent for a non-critical task like deploy history lookup or ticket correlation, per Section 3.10. README architecture diagram showing Agent Space → Gateway (Cedar) → MCP namespaces → AWS APIs, plus the audit S3 bucket and the stub subagent path. Comparison table includes the MAST failure-mode column and a "results vs published baselines" row referencing STRATUS / ITBench. README section documenting the `.claude/` directory. **README "alternative architectures considered" paragraph** covering Claude Managed Agents on Claude Platform on AWS as an alternative build option, and AWS DevOps Agent / PagerDuty SRE Agent as buy comparators, with reasoning for staying on AgentCore (AWS-native vocabulary, data residency, infrastructure-for-free). If Cedar or the stub subagent slip, document the intent and ship without — do not drop the MAST annotations, the eval table, or the Claude Code workflow section.

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
- **Design for multi-agent expansion;** ship single-agent + one stub subagent.

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

## 9. Workflow: browser-first, Claude Code at the Day 33 seam

**Days 31–33: browser + manual coding.** Learning territory. AgentCore is new; production infrastructure upgrades require careful, deliberate work. Type every line. Hit errors. The friction is where understanding lives.

**Day 33 evening: install Claude Code.** Native binary install (`curl -fsSL https://claude.ai/install.sh | bash`). Configure with the same Anthropic API key. Write `CLAUDE.md` at the repo root — one-page summary of architecture, conventions, and rules per Section 3.9. Install the PreCommit secrets-scan hook and the PreToolUse `terraform apply` gate hook before any sprint code is written.

**Days 34–36: Claude Code in IDE for high-volume scaffolding.** Execution territory. The MCP server, the outage scenarios, the evaluation harness, the README polish. Volume up; learning per line down. Claude Code earns its keep here, but every change still gets reviewed.

The judgment about *when* to lean on AI tools is itself an interview signal in 2026. "I used Claude Code for boilerplate so I could focus on agent design and evaluation" is a more sophisticated answer than either extreme.

---

## 10. Interview framing

**Primary pitch (current-on-the-landscape interviewers):**

> "I built a small open-source incident response agent on AWS Bedrock AgentCore plus a custom MCP server, evaluated it against a Fault Injection Service outage corpus using AgentCore Evaluations, and classified the failures with the MAST taxonomy from the IBM and Berkeley paper. The architecture mirrors what AWS published when DevOps Agent went GA in March."

Every clause maps to a specific, current, citable thing.

**Warm-up pitch (less technical or less-current interviewers):**

> "I built a small open-source SRE agent on AWS Bedrock AgentCore plus MCP, then evaluated it against a deliberate outage simulator on a production-style AWS stack."

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
- **Multi-agent expansion path:** the architecture is designed for lead-plus-subagents over A2A protocol; v1 ships with one substantive lead agent and one stub subagent demonstrating the pattern. Full multi-agent expansion (monitoring, operations, host subagents per AWS's `sample-fully-autonomous-incident-response` reference) is the next iteration. Same scope discipline applied to the learned skill tier — designed for, partially deferred.
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
| 19 | Sprint workflow | Browser through Day 33 afternoon; Claude Code from Day 33 evening | Learning vs execution have different optimal tools |
| 20 | Doc strategy | Selective uploads + consolidated revisions | Retrieval quality drops on bloated corpora |
| 21 | Multi-agent architecture | Design for lead-plus-subagents over A2A; ship single lead agent + one stub subagent | "Designed for, partially deferred" — gets the talking point and the stub demonstration without full A2A debugging eating sprint days; AWS's `sample-fully-autonomous-incident-response` is the full reference for the next iteration |
| 22 | Anti-pattern: own-model self-evaluation | Run evaluators on a different model family than the agent | Cross-model robustness; avoids the model grading its own homework |
| 23 | Anti-pattern: one-shot eval | Run eval harness on every change to prompts/skills/tools | "We didn't set out to build an evaluation platform; it's what it took to trust the agent" — Datadog Bits AI SRE team |
| 24 | "Alternative architectures considered" in README | Three-way comparison: AgentCore (chosen), Claude Managed Agents on Claude Platform on AWS, AWS DevOps Agent (buy) | Three-way build-vs-buy is the senior-engineer framing every cloud team is having in 2026; substantiates Section 3.8's "modular design" claim with explicit trade-off discussion rather than abstract assertion |

---

## Doc history

- **v1** — May 5, 2026. Initial commit.
- **v2** — May 13, 2026. Consolidates Revision 1 deltas (AgentCore Evaluations native, Cedar at Gateway, FIS-based outage corpus, MAST annotation, four MCP namespaces, OAuth 2.1, explicit AWS DevOps Agent architecture mirror) and adds Section 3.9 (Claude Code workflow customization: CLAUDE.md + skills + hooks).
- **v2.1** — May 13, 2026. In-place edit per the revision policy. Adds Section 3.10 (multi-agent architecture: designed for, partially deferred), incorporates stub subagent wiring and the "alternative architectures considered" README paragraph into Day 36, expands Section 10 build-vs-buy talking point to a three-way comparison, adds Section 10 multi-agent expansion talking point, updates decision log row 21 (multi-agent stance) and adds row 24 (alternative architectures in README). Reconciles tension between v2's original "subagents out of scope" stance and the May 12 conversation that recommended adopting the multi-agent pattern.

**Revision policy going forward:** if a single delta lands (small new fact, minor scope adjustment), edit in place and add a decision-log row. If a major shift hits (scope change, new productized agent reframes the market, fundamental architectural rethink), write a fresh consolidated v3 rather than appending. This keeps the retrieval quality bias intact.

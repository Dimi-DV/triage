# AWS Fault Injection Service (FIS)

**Source:** AWS Fault Injection Service features page and scenario library.
**URLs:**
- https://aws.amazon.com/fis/features/
- https://aws.amazon.com/fis/ (product page)
- Resilience Hub recommendations: https://aws.amazon.com/about-aws/whats-new/2024/12/aws-resilience-hub-fault-injection-service-recommendations/ (Dec 2024)

## Why this matters for Triage

FIS is the chaos-engineering service that produces **4 of your 8–10 outage scenarios** in the corpus per the decision doc Section 3.4. The other 4–6 are Terraform overlay misconfigurations. FIS gives you parameterized, reusable, AWS-native faults that are dramatically more credible in interviews than ad-hoc bash scripts.

Decision-doc cross-references: 3.4 (outage corpus), 11 row 7.

## The four FIS scenarios you use

| Scenario | FIS action | What it tests |
|---|---|---|
| AZ slowdown | Network latency injection in a single AZ | Agent's ability to recognize an AZ-scoped issue and not panic about the full region |
| EC2 stop | Stop EC2 instance(s) action | Agent's ability to recognize hard infrastructure failure vs. soft degradation |
| EBS pause-IO | EBS volume pause I/O action | Agent's ability to correlate disk-level symptoms with app-level latency |
| Network blackhole | Network disruption between subnets | Agent's ability to diagnose connectivity issues without confusing them with app errors |

Each is parameterized — you re-run the same scenario multiple times to test eval reproducibility.

## FIS mental model

FIS works via **experiment templates**:

1. You define a template with:
   - **Targets** — which AWS resources (EC2 instances by tag, EBS volumes, etc.)
   - **Actions** — what to do to them (stop, pause-IO, inject latency)
   - **Stop conditions** — CloudWatch alarms that automatically end the experiment if it gets worse than expected
2. You start an experiment from the template via API or console
3. FIS injects the fault, your CloudWatch alarms fire, your agent receives the alarm, investigation begins
4. Experiment ends either on duration timeout or stop condition

**Stop conditions are essential for portfolio work.** You don't want to accidentally take production-style infra down for hours because the agent failed to diagnose. Every experiment template should have a stop condition like "if billing exceeds $5 in 1 hour, halt."

## Cost notes

**FIS itself has minimal cost** — pennies per action. The disruption can cost more:

- AZ slowdown via network latency: marginal cost, contained
- EC2 stop: free (you're stopping instances, lower cost during the experiment)
- EBS pause-IO: free
- Network blackhole: marginal cost; watch for NAT data transfer if a different AZ takes over routing

Budget alert at $20 in the project account is enough.

## Tying FIS to your eval pipeline

The integration pattern:

1. Your AgentCore Evaluations ground truth knows that "running experiment template X" produces fault Y
2. Your eval harness or a test runner starts the FIS experiment, captures the timestamp, waits for the alarm-triggered agent investigation to complete
3. AgentCore Evaluations scores the agent's diagnosis against ground truth Y
4. Failed diagnoses get MAST-classified
5. The experiment template is reusable — same template, run 5 times, you have 5 samples of agent performance on the same fault

The reusability is the whole point. Manual disruption scripts are one-shot. FIS templates are repeatable, parameterized, and version-controllable (you can store them in Terraform via the `aws_fis_experiment_template` resource).

## Resilience Hub recommendations layer

AWS Resilience Hub (released Dec 2024 with FIS recommendations) can analyze a workload and suggest which FIS scenarios are most relevant. **Not required** for Triage — your four chosen scenarios are sufficient and well-justified. But noting it in the README as an extension point signals you know it exists.

## What to read on Day 35 morning

Before scaffolding the corpus:

1. The FIS getting-started doc (15 min) — covers the experiment template concept
2. The scenario library page (10 min) — see what AWS provides out of the box
3. The `aws_fis_experiment_template` Terraform resource docs (10 min) — you'll codify your templates in Terraform alongside the rest of the stack

## Verify against live source

- Current pricing model (FIS pricing has changed historically)
- Current action list (more actions land periodically)
- Whether your AWS account has FIS enabled in us-east-1 (no setup required usually, but verify)
- Resilience Hub recommendations format if you decide to incorporate them

# Day 31 reading queue (May 14, 2026)

Sprint Day 1. Order matters for the morning block; the afternoon items can shuffle. The point is the substrate for the next five days of execution. Decision doc §9 + Day 31.

## Morning — architecture + eval primer (read in order)

1. **AWS DevOps Agent architecture (the one to mirror).** Molumuri, Fine, Alioto, Qureshi — AWS DevOps Blog, March 31, 2026.
   https://aws.amazon.com/blogs/devops/leverage-agentic-ai-for-autonomous-incident-response-with-aws-devops-agent/

2. **AgentCore Evaluations developer guide.** Entry point: AgentCore landing page → Documentation → Evaluations. GA'd March 31, 2026 — not in any LLM training data, so this one has to be read fresh.
   https://aws.amazon.com/bedrock/agentcore/

3. **AgentCore Evaluations GA announcement** — AWS News Blog.
   https://aws.amazon.com/blogs/aws/amazon-bedrock-agentcore-adds-quality-evaluations-and-policy-controls-for-deploying-trusted-ai-agents/

4. **MAST failure-mode taxonomy.** IBM Research + UC Berkeley — Hugging Face, February 18, 2026. The 94%-accurate classifier and the FM-X.Y codes you'll annotate failed runs against on Day 35.
   https://huggingface.co/blog/ibm-research/itbenchandmast

## Afternoon — operational gap-fill

Names + mental model, not deep mastery. Skim.

5. **SSM Session Manager — getting started.** Hands-on lab: EC2 in a private subnet, no inbound SSH, IAM role with `AmazonSSMManagedInstanceCore`. Connect via Session Manager.
   https://docs.aws.amazon.com/systems-manager/latest/userguide/session-manager.html

6. **CloudTrail user guide intro.**
   https://docs.aws.amazon.com/awscloudtrail/latest/userguide/cloudtrail-user-guide.html

7. **AWS Config — getting started.**
   https://docs.aws.amazon.com/config/latest/developerguide/getting-started.html

8. **GuardDuty intro** (brief — what it detects, threat-intel sources).
   https://docs.aws.amazon.com/guardduty/latest/ug/what-is-guardduty.html

9. **IAM Access Analyzer intro** (brief).
   https://docs.aws.amazon.com/IAM/latest/UserGuide/what-is-access-analyzer.html

## End of day — clone the reference

10. **Clone `aws-samples/sample-fully-autonomous-incident-response` and walk it.** Don't deploy. Read the README. Open the lead agent's source file. Open one MCP server file. Open the Cedar policy files (if present). Goal: sketch the architecture from memory by tomorrow morning.
    https://github.com/aws-samples/sample-fully-autonomous-incident-response

    Local note `docs/architecture-references/aws-samples-incident-response-pattern-2025.md` lists the patterns to look for.

## Project memory uploads (browser Claude)

Per decision doc §8 — upload these before Day 32 so browser Claude has the architectural substrate next morning. The local notes in `docs/architecture-references/` already summarize them; uploads make the same content available to browser Claude project memory.

- AgentCore developer guide (Runtime, Memory, Gateway, Identity)
- AgentCore Evaluations developer guide
- Molumuri et al. AWS DevOps Blog post (March 2026)
- MAST Hugging Face post
- AWS FIS getting-started + scenario library reference
- `aws-samples/sample-fully-autonomous-incident-response` README + architecture docs
- MCP Python SDK docs + server-building tutorial
- PagerDuty MCP server README (`--enable-write-tools` flag pattern)
- AWS multi-agent SRE blog post (four-namespace pattern)

**Don't upload:** full Bedrock developer guide, full Terraform AWS provider reference, marketing pages, full Claude Code docs. Selective beats exhaustive — retrieval quality drops on bloated corpora.

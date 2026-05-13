# Security Policy

## Supported Versions

This is a portfolio project, not a production service. The `main` branch is the only supported version. Older tags and branches are kept for reference.

## Reporting a Vulnerability

If you discover a security vulnerability in this project, please **do not open a public GitHub issue**. Instead:

1. Use GitHub's **private vulnerability reporting**: Repository → Security tab → "Report a vulnerability"
2. Or email the maintainer (see GitHub profile)

Include:
- A description of the vulnerability
- Steps to reproduce
- Affected components (MCP server, Terraform code, AgentCore configuration, hook scripts, etc.)
- Suggested remediation if you have one

You'll receive an acknowledgment within 5 business days. If the report is valid, I'll work on a fix and publish a coordinated disclosure.

## Scope

This project's security boundary includes:

- The custom MCP server (`src/triage/mcp_server/`)
- The AgentCore agent configuration (`src/triage/agent/`)
- Terraform infrastructure (`terraform/`)
- Cedar policies (`cedar-policies/`)
- Claude Code hooks (`.claude/hooks/`)
- CI/CD configuration (`.github/workflows/`)

## Out of scope

- Vulnerabilities in upstream dependencies (report to the upstream project; Dependabot tracks these here)
- Vulnerabilities in AWS services themselves (report to AWS via [AWS Security](https://aws.amazon.com/security/vulnerability-reporting/))
- Vulnerabilities in Bedrock AgentCore or MCP itself (report to AWS / the MCP project)
- Social engineering, phishing, or physical attacks

## Hardening choices in this project

- AWS IAM is read-only by default for the agent role; write permissions require both a Cedar policy at AgentCore Gateway and a Slack approval
- Every reasoning step and tool invocation is logged to an immutable S3 bucket with Object Lock
- Pre-commit and Claude Code hooks block AWS credential patterns in committed code
- `terraform apply` is gated behind a fresh `terraform plan` in the same directory
- OAuth 2.1 + RFC 8707 Resource Indicators for MCP server authentication

For full architectural reasoning, see [`docs/architecture-references/triage-decision-doc-v2.md`](docs/architecture-references/triage-decision-doc-v2.md).

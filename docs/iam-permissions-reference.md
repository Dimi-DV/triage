# IAM permissions reference

> Source of truth for every IAM identity in the Triage stack. Whose trust
> policy allows what, what each role is allowed to do once assumed, where
> the principal chain enters and where it terminates. Cross-references the
> Cedar policy layer that sits *on top* of IAM for the agent's Gateway calls.

This doc covers the **stack** roles (`terraform/stack/`). Overlay roles
(`terraform/overlays/<scenario>/`) are scenario-local and out of scope; they
follow the same patterns scaled down to a single victim service.

## Mental model

Five IAM roles in the stack. Each pairs:

1. A **trust policy** (`assume_role_policy`) — *who* is allowed to assume this role
2. A **permissions policy** (inline `aws_iam_role_policy`) — *what* the role can do once assumed

Three of the five roles are assumed by AWS services on your behalf (Lambda,
ECS, AgentCore); two of them are assumed across role boundaries (AgentCore
service double-use of the runtime role for Cedar Genesis-check).

The Cedar layer sits **on top** of IAM for one specific edge: any call from
the AgentCore Runtime into the AgentCore Gateway. IAM grants the connection
(`bedrock-agentcore:InvokeGateway`); Cedar grants the specific tool (`permit
(principal == ..., action == ..., resource == ...)`). Cedar can deny what IAM
would have allowed, but it cannot grant what IAM denies. Two gates in series.

## The five roles at a glance

| Role | Trust principal | What it can do | Used by |
|---|---|---|---|
| `dev-triage-agent-runtime` | `bedrock-agentcore.amazonaws.com` | Invoke Bedrock models, call the Gateway (`InvokeGateway`), call PolicyEngine (`GetPolicyEngine`, `AuthorizeAction`, `PartiallyAuthorizeActions`, `CheckAuthorizePermissions`), pull from ECR, write CloudWatch logs + X-Ray traces, put audit S3 objects, read the Slack secret, subscribe to Bedrock marketplace | (a) AgentCore Runtime to start the agent container, (b) AgentCore service to perform the Cedar Genesis-check at attach time |
| `dev-triage-alarm-bridge` | `lambda.amazonaws.com` | Read the Runtime ARN from SSM, invoke `bedrock-agentcore:InvokeAgentRuntime`, write own CloudWatch logs, send to DLQ on failure | The `alarm-bridge` Lambda that subscribes to the alarms SNS topic |
| `dev-triage-mcp-task` | `ecs-tasks.amazonaws.com` | CloudWatch metrics read (`GetMetricStatistics`, `ListMetrics`), ECS/ELB read (`DescribeTaskDefinition`, `DescribeTargetHealth`), CloudWatch Logs read on `/ecs/*` log groups, put audit S3 objects, read the Slack secret, X-Ray export | The MCP server's ECS Fargate container; every tool's downstream AWS call assumes this role |
| `dev-triage-mcp-task-execution` | `ecs-tasks.amazonaws.com` | ECR pull, CloudWatch Logs write (the standard `AmazonECSTaskExecutionRolePolicy` managed policy) + resolve task-definition secrets from SSM | Fargate plumbing only; never seen by application code |
| `dev-triage-eval-execution` | `bedrock-agentcore.amazonaws.com` | Read runtime trace log groups, query the `aws/spans` log group via CloudWatch Insights, write eval verdict log groups, invoke Bedrock for judge models | AgentCore Evaluations service when invoking custom LLM-as-judge evaluators or the online sampling path |

## Trust policies in detail

These are minimal — they just identify which AWS service principal can assume
the role. Triage doesn't allow human/cross-account assumption.

**`dev-triage-agent-runtime`**
```hcl
principals { type = "Service"; identifiers = ["bedrock-agentcore.amazonaws.com"] }
```
Allows the AgentCore service to assume this role for two purposes: (1)
starting the Runtime container, (2) performing the Gateway's Cedar
Genesis-check (a one-shot AssumeRole that surfaces under
`assumed-role/dev-triage-agent-runtime/GenesisPolicyEngineCheck`).

Production hardening would add `aws:SourceAccount` + `aws:SourceArn`
conditions per the AWS Policy-in-AgentCore IAM doc. Triage skips for v1.

**`dev-triage-alarm-bridge`**
```hcl
principals { type = "Service"; identifiers = ["lambda.amazonaws.com"] }
```

**`dev-triage-mcp-task`** and **`dev-triage-mcp-task-execution`**
```hcl
principals { type = "Service"; identifiers = ["ecs-tasks.amazonaws.com"] }
```

**`dev-triage-eval-execution`**
```hcl
principals { type = "Service"; identifiers = ["bedrock-agentcore.amazonaws.com"] }
```
Same as the runtime role's trust, distinct execution permissions.

## Permissions policies — the salient parts

### `dev-triage-agent-runtime`

The agent's outbound permission surface. Statements (file: `terraform/stack/agent.tf:199`):

| Sid | Actions | Resources | Why |
|---|---|---|---|
| `InvokeBedrockModels` | `bedrock:InvokeModel*` | `*` | Agent calls Sonnet 4.6 via Bedrock Converse |
| `BedrockMarketplaceSubscription` | `aws-marketplace:ViewSubscriptions`, `Subscribe` | `*` | Bedrock checks Marketplace state on first model invocation per account |
| `PutAuditObjects` | `s3:PutObject` | `<audit-bucket>/events/*` | Audit emission before any write side effect (CLAUDE.md hard rule 4) |
| `ReadSlackSecret` | `secretsmanager:GetSecretValue` | `<slack-bot-token-secret>` | Agent posts to Slack |
| `AgentCoreGatewayAccess` | `bedrock-agentcore:InvokeGateway`, `InvokeGatewayTarget`, `ListGatewayTargets`, `GetPolicyEngine`, `AuthorizeAction`, `PartiallyAuthorizeActions`, `CheckAuthorizePermissions` | `*` | (1) Agent talks to the Gateway via SigV4; (2) AgentCore service does the Cedar Genesis-check and runtime evaluation. See [§Cedar layer below](#cedar-overlay-on-top-of-iam) |
| `XRayTraceExport` | `xray:PutTraceSegments`, `PutTelemetryRecords` | `*` | OTel spans flow to X-Ray |
| `CloudWatchLogsForRuntime` | `logs:CreateLogGroup`, `CreateLogStream`, `PutLogEvents`, `DescribeLogStreams` | `arn:aws:logs:*:*:log-group:/aws/bedrock-agentcore/*` | Runtime container stdout/stderr |
| `EcrAuth`, `EcrPullAgentImage` | `ecr:GetAuthorizationToken` + `BatchCheckLayerAvailability`, `BatchGetImage`, `GetDownloadUrlForLayer` | `*` | Runtime pulls the agent image at container-start |

### `dev-triage-mcp-task`

The MCP server's outbound permission surface — what the tool implementations
can call once Cedar permits the request to reach them. Statements
(`terraform/stack/mcp_server.tf:133`):

| Sid | Actions | Resources | Tool that uses it |
|---|---|---|---|
| `ReadOnlyCloudWatchMetrics` | `cloudwatch:GetMetricStatistics`, `ListMetrics` | `*` | `metrics_api_get_metric_statistics` |
| `ReadOnlyEcsAndElbV2` | `elasticloadbalancing:DescribeTargetHealth`, `ecs:DescribeTaskDefinition` | `*` | `ecs_api_describe_target_health`, `ecs_api_describe_task_definition` |
| `ReadOnlyCloudWatchLogs` | `logs:FilterLogEvents`, `GetLogEvents`, `DescribeLogStreams` | `/ecs/*` log groups only | `logs_api_filter_log_events` |
| `DescribeLogGroups` | `logs:DescribeLogGroups` | `*` | logs-api discovery |
| `PutAuditObjects` | `s3:PutObject` | `<audit-bucket>/events/*` | `runbooks_api_post_to_slack` (audit-before-side-effect) |
| `ReadSlackSecret` | `secretsmanager:GetSecretValue` | `<slack-bot-token-secret>` | `runbooks_api_post_to_slack` |
| `XRayTraceExport` | `xray:PutTraceSegments`, `PutTelemetryRecords` | `*` | All tools (OTel) |

**Adding a new namespace that touches a new AWS service requires extending
this role.** See `feedback_namespace_iam_gap` memory — `logs-api` shipped
without `logs:FilterLogEvents` here and only surfaced on scenario 03's eval.

### `dev-triage-alarm-bridge`

Bridge between CloudWatch alarms and AgentCore Runtime. Statements
(`terraform/stack/agent.tf:84`):

| Sid | Actions | Resources |
|---|---|---|
| `OwnLogs` | `logs:CreateLogStream`, `PutLogEvents` | own log group |
| `ReadRuntimeArn` | `ssm:GetParameter` | `/dev/triage/agentcore-runtime-arn` |
| `InvokeRuntime` | `bedrock-agentcore:InvokeAgentRuntime` | `*` |
| `SendDLQ` | `sqs:SendMessage` | own DLQ |

### `dev-triage-mcp-task-execution`

Pure Fargate plumbing. The `AmazonECSTaskExecutionRolePolicy` AWS-managed
policy covers ECR pulls + log writes; one inline statement reads the
SSM-backed task-definition secrets at task launch. Application code never
sees this role.

### `dev-triage-eval-execution`

Read trace logs, query CloudWatch Insights, write verdict logs, invoke
judge models. Out of scope for the agent's hot path — only used by
AgentCore Evaluations.

## Per-tool-call principal chain

Following one tool call (the `runbooks_api_post_to_slack` write that lands a
Slack message) end-to-end:

```
                                                            ROLE in scope
1. CloudWatch alarm "dev-triage-broken-tg-unhealthy"
   fires → SNS topic dev-triage-alarms                       n/a (service)
                              │
                              ▼
2. SNS invokes the alarm-bridge Lambda                       dev-triage-alarm-bridge
   (Lambda service AssumeRoles using its trust policy)
   • Reads /dev/triage/agentcore-runtime-arn from SSM
   • Calls bedrock-agentcore:InvokeAgentRuntime
                              │
                              ▼
3. AgentCore Runtime starts a session container              dev-triage-agent-runtime
   • AgentCore service AssumeRoles using runtime role        (assumed by service)
     trust policy
   • Pulls agent image from ECR
   • Container runs the agent loop
                              │
                              ▼  (agent decides to call a tool;
                              │   SigV4-signs an MCP tools/call
                              │   to the Gateway URL using the
                              │   container's task credentials)
                              ▼
4. AgentCore Gateway receives the request                    (still dev-triage-agent-runtime
                                                              as the SigV4 caller)
   • Validates SigV4 → confirms the signer has
     bedrock-agentcore:InvokeGateway
   • Calls Policy Engine's AuthorizeAction
     - principal = AgentCore::IamEntity::
                   "arn:aws:sts::ACCT:assumed-role/
                    dev-triage-agent-runtime"
     - action    = AgentCore::Action::
                   "TriageMcpGateway___runbooks_api_post_to_slack"
     - resource  = AgentCore::Gateway::"<gateway-arn>"
   • Policy Engine returns ALLOW
                              │
                              ▼
5. Gateway forwards the tools/call to the upstream           (Gateway is the caller;
   MCP server (HTTPS to the ALB at davidovic.dev/mcp)        SigV4 is dropped here)
                              │
                              ▼
6. MCP server (ECS Fargate task) handles the call            dev-triage-mcp-task
   • Pydantic validates the SlackMessage arg                 (Fargate AssumeRoles
   • emit_audit_event() writes to S3 Object Lock              this role at start)
     using the task role's PutAuditObjects grant
   • get_slack_client() reads the bot token from
     Secrets Manager (ReadSlackSecret grant)
   • chat_postMessage() lands the post in #all-triage
                              │
                              ▼
7. Response propagates back: MCP → Gateway → Runtime → Agent
   • Agent emits OTel spans (X-Ray export, both roles)
```

Three role boundaries crossed: alarm-bridge → AgentCore-service-assuming-
runtime-role → ECS-task-assuming-mcp-task-role. Cedar is the gate **between
steps 4 and 5** — the only place it runs.

## Cedar overlay on top of IAM

Cedar lives in the AgentCore PolicyEngine (`TriagePolicyEngine`); the Gateway
calls `AuthorizeAction` against it before forwarding any MCP request.

**The relationship:**
- IAM is **necessary but not sufficient**. The agent runtime role has
  `bedrock-agentcore:InvokeGateway` — that lets it *connect*. Cedar then
  decides whether the specific MCP tool the agent is invoking is permitted.
- Cedar **cannot grant more than IAM allows**. If the agent's IAM role
  lost `InvokeGateway`, the request never reaches the Cedar evaluator.
- Cedar **can deny what IAM would have allowed**. A new IAM principal that
  picks up `InvokeGateway` would be blocked by Cedar's exact-match
  `principal == AgentCore::IamEntity::"<triage-role-arn>"` clause.

**The Cedar principal exactly matches the SigV4 caller's STS assumed-role
ARN.** `arn:aws:sts::042729137214:assumed-role/dev-triage-agent-runtime`.
Same value flows into the audit log's `principal` field via the MCP task's
`TRIAGE_PRINCIPAL` env var — so the cryptographically-attested identity,
the policy-attested identity, and the audit-recorded identity all align on
the same string.

Permits live in `cedar-policies/agent-tools.cedar` (6 of them: one per MCP
tool). The kill-switch is `cedar-policies/_emergency-shutdown.cedar.disabled`
— rename and re-provision to engage forbid-wins shutdown. See ADR 0004 for
the design.

## Termination boundaries

Where each role's reach ends — i.e. what each role *cannot* do, even though
it could plausibly be expected to:

- **`dev-triage-agent-runtime` cannot read CloudWatch metrics directly.**
  Investigation tools are MCP-mediated; the agent calls the Gateway, not
  CloudWatch. This is the whole point of the architecture — read paths go
  through the audit/observability layer.
- **`dev-triage-mcp-task` cannot invoke the Gateway.** It has no
  `bedrock-agentcore:*` permissions. Downstream-only.
- **`dev-triage-mcp-task` cannot write to ECS or modify task definitions.**
  Tool-implementation permissions are read-only (`DescribeTargetHealth`,
  `DescribeTaskDefinition`). The only write surface is `s3:PutObject` to
  the audit bucket and Slack via the secrets-fetched bot token. ECS / RDS /
  EC2 mutations are intentionally absent — write actions would land as
  Cedar-gated tools and require this role to expand.
- **`dev-triage-alarm-bridge` cannot read agent traces or audit objects.**
  It hands off and returns; observation is the Runtime's responsibility.
- **`dev-triage-eval-execution` cannot invoke the agent.** It only
  *evaluates* completed traces. The eval and the run are separate processes.
- **No role can read Slack bot token outside of the two that explicitly
  grant `secretsmanager:GetSecretValue` on it** (agent_runtime and mcp_task).
- **No role grants `iam:PassRole` to anything other than
  `bedrock-agentcore.amazonaws.com`.** Cross-service role assumption is
  blocked.

## What's deliberately NOT in the IAM layer

A few permission-shaped things that live elsewhere — important to know
where to look:

- **Cedar policies** (`cedar-policies/*.cedar`) — live in the AgentCore
  PolicyEngine; synced by `scripts/provision_agentcore.py`. Not IAM.
- **Slack bot token** — Secrets Manager, fetched by roles that grant
  `secretsmanager:GetSecretValue` on the specific secret ARN. Not in IAM
  itself; not in env vars.
- **AgentCore Runtime / Gateway / PolicyEngine identities** — managed by
  AgentCore service; ARNs in
  `bedrock-agentcore:` namespace. No first-class Terraform resources;
  configured via `scripts/provision_agentcore.py`. Trust comes from the
  five roles' policies.
- **Audit log integrity** — enforced by S3 Object Lock at the bucket level
  (`terraform/stack/main.tf`). IAM grants the write; Object Lock blocks the
  rewrite/delete.
- **Web traffic auth** — ALB + WAF, ACM certificates. Not in IAM.

## Auditing a permission change

When you touch any `aws_iam_role_policy` or `aws_iam_role`:

1. **Trust policy change:** if you broaden who can assume, you've widened
   the role's reach. Cedar can re-narrow the agent-runtime case but not the
   ECS-task case.
2. **Permissions policy change:** the `.claude/agents/security-reviewer.md`
   agent reviews these. P1 findings: `Action = "*"`,
   `Resource = "*"` unless documented, `iam:PassRole` without conditions,
   trust relationships to `"*"`.
3. **New write surface in `mcp_task`:** must pair with a Cedar `permit`
   block in `cedar-policies/agent-tools.cedar` (default-deny at the Cedar
   layer otherwise renders the new IAM grant unreachable). See
   `feedback_namespace_iam_gap` for the inverse-direction trap.

## Files

| Concern | File |
|---|---|
| Agent runtime role + trust + permissions | `terraform/stack/agent.tf:184-308` |
| Alarm-bridge Lambda role | `terraform/stack/agent.tf:45-114` |
| MCP task role (tool downstream perms) | `terraform/stack/mcp_server.tf:128-196` |
| MCP task-execution role (Fargate plumbing) | `terraform/stack/mcp_server.tf:103-126` |
| Eval execution role | `terraform/stack/evals.tf:23-108` |
| Cedar policies (the Gateway-layer overlay) | `cedar-policies/agent-tools.cedar` |
| Audit principal env var | `terraform/stack/mcp_server.tf:230-242` |
| Cedar sync helper | `src/triage/shared/cedar_sync.py` |

## Related

- `docs/adr/0004-cedar-plus-slack-write-gating.md` — the two-gate design
- `cedar-policies/README.md` — Cedar policy authoring + kill-switch
- `feedback_cedar_policy_engine_config_lives` memory — Cedar primitive history
- `feedback_namespace_iam_gap` memory — adding a namespace requires extending `mcp_task`
- `feedback_naming_prefix_drift` memory — why `prod_triage_runtime` is hardcoded in eval IAM

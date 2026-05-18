# ============================================================
# AgentCore Evaluations — execution role + discovery params.
# ============================================================
#
# AgentCore Evaluations is online-only (no batch start_evaluation API),
# so the pattern is "one OnlineEvaluationConfig at 100% sampling
# attached to the runtime log group; results emit to an output log
# group AgentCore picks itself." outputConfig is NOT an input on
# CreateOnlineEvaluationConfig — the service auto-provisions a
# CloudWatch log group and returns its name in the response.
#
# This file owns the IAM role the eval service assumes plus the SSM
# parameters the provisioner script and the eval harness use to
# discover the runtime artifacts (config id, output log group name).
# The evaluators themselves and the OnlineEvaluationConfig are created
# by scripts/provision_evaluators.py.

data "aws_iam_policy_document" "eval_execution_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["bedrock-agentcore.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "eval_execution" {
  name               = "${local.name_prefix}-eval-execution"
  assume_role_policy = data.aws_iam_policy_document.eval_execution_assume.json
}

data "aws_iam_policy_document" "eval_execution" {
  # Read the runtime's traces. AgentCore writes per-runtime DEFAULT
  # log groups under /aws/bedrock-agentcore/runtimes/<name>-XXX-DEFAULT,
  # with the suffix randomly assigned at runtime-create time.
  #
  # NOTE: scripts/provision_agentcore.py hardcodes `NAME_PREFIX = "prod-triage"`
  # so the actual runtime is `prod_triage_runtime` regardless of Terraform's
  # local.name_prefix (which is `dev-triage`). Pinned literally below; see
  # feedback memory about the naming-prefix drift.
  statement {
    sid     = "ReadRuntimeTraces"
    actions = ["logs:FilterLogEvents", "logs:GetLogEvents", "logs:DescribeLogStreams"]
    resources = [
      "arn:aws:logs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:log-group:/aws/bedrock-agentcore/runtimes/prod_triage_runtime-*",
      "arn:aws:logs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:log-group:/aws/bedrock-agentcore/runtimes/prod_triage_runtime-*:log-stream:*",
    ]
  }

  # DescribeLogGroups doesn't support resource-level permissions; needed
  # at OnlineEvaluationConfig create time so the service can validate
  # the configured log group exists.
  statement {
    sid       = "DescribeAnyLogGroup"
    actions   = ["logs:DescribeLogGroups"]
    resources = ["*"]
  }

  # AgentCore Evaluations reads OpenTelemetry spans via CloudWatch Logs
  # Insights against the service-managed `aws/spans` log group (separate
  # from the runtime DEFAULT log group). Required even though we point
  # the data source at the runtime DEFAULT group.
  statement {
    sid     = "QuerySpansLogGroup"
    actions = ["logs:StartQuery", "logs:GetQueryResults", "logs:StopQuery"]
    resources = [
      "arn:aws:logs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:log-group:aws/spans",
      "arn:aws:logs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:log-group:aws/spans:*",
      "arn:aws:logs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:log-group:/aws/bedrock-agentcore/runtimes/prod_triage_runtime-*",
      "arn:aws:logs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:log-group:/aws/bedrock-agentcore/runtimes/prod_triage_runtime-*:*",
    ]
  }

  # Write evaluation verdicts. The output log group is auto-provisioned
  # by AgentCore Evaluations under /aws/bedrock-agentcore/evaluations/*
  # (verified via CreateOnlineEvaluationConfig.outputConfig response).
  # Glob the whole prefix because the exact group name is not known
  # at Terraform-apply time.
  statement {
    sid     = "WriteEvalOutput"
    actions = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents", "logs:DescribeLogStreams"]
    resources = [
      "arn:aws:logs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:log-group:/aws/bedrock-agentcore/evaluations/*",
      "arn:aws:logs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:log-group:/aws/bedrock-agentcore/evaluations/*:log-stream:*",
    ]
  }

  # Invoke Bedrock for the custom LLM-as-judge evaluators. Judges use
  # Haiku 4.5; agent uses Sonnet 4.5 (different family avoids
  # same-model self-grading bias).
  statement {
    sid       = "InvokeJudgeModels"
    actions   = ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream", "bedrock:Converse"]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "eval_execution" {
  name   = "${local.name_prefix}-eval-execution-policy"
  role   = aws_iam_role.eval_execution.id
  policy = data.aws_iam_policy_document.eval_execution.json
}

# SSM parameters the eval provisioner writes; harness reads to discover
# the OnlineEvaluationConfig id and the auto-provisioned output log
# group name. Pattern mirrors aws_ssm_parameter.runtime_arn — Terraform
# creates the parameter with a placeholder; the script writes the real
# value after the AWS API returns it.

resource "aws_ssm_parameter" "eval_config_id" {
  name        = "/${var.environment}/${var.project_name}/eval-online-config-id"
  description = "AgentCore OnlineEvaluationConfig id; written by scripts/provision_evaluators.py."
  type        = "String"
  value       = "PLACEHOLDER_FILL_VIA_PROVISIONING_SCRIPT"

  lifecycle {
    ignore_changes = [value]
  }
}

resource "aws_ssm_parameter" "eval_output_log_group" {
  name        = "/${var.environment}/${var.project_name}/eval-output-log-group"
  description = "CloudWatch log group AgentCore Evaluations writes verdicts to; written by provisioner."
  type        = "String"
  value       = "PLACEHOLDER_FILL_VIA_PROVISIONING_SCRIPT"

  lifecycle {
    ignore_changes = [value]
  }
}

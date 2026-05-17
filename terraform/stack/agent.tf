# Triage — alarm-SNS-bridge path + AgentCore Runtime support resources.
#
# Day 34 afternoon scope. End-to-end target flow:
#
#   CloudWatch alarm  →  SNS topic prod-triage-alarms
#     →  Lambda prod-triage-alarm-bridge (this file)
#          →  boto3 bedrock-agentcore.invoke_agent_runtime(...)
#               →  AgentCore Runtime (provisioned out-of-band by
#                   scripts/provision_agentcore.py; ARN published to
#                   SSM Parameter Store path read by the Lambda)
#
# The Runtime + Gateway + Identity primitives themselves are managed
# services configured via boto3 (no first-class Terraform resource yet);
# Terraform owns everything that surrounds them.

# ---------------------------------------------------------------------------
# SNS topic — alarm fanout
# ---------------------------------------------------------------------------

resource "aws_sns_topic" "alarms" {
  name = "${local.name_prefix}-alarms"

  tags = {
    Name = "${local.name_prefix}-alarms"
  }
}

# ---------------------------------------------------------------------------
# SQS dead-letter queue for failed Lambda invocations
# ---------------------------------------------------------------------------

resource "aws_sqs_queue" "alarm_bridge_dlq" {
  name                      = "${local.name_prefix}-alarm-bridge-dlq"
  message_retention_seconds = 1209600 # 14 days

  tags = {
    Name = "${local.name_prefix}-alarm-bridge-dlq"
  }
}

# ---------------------------------------------------------------------------
# Lambda execution role + log group + permissions
# ---------------------------------------------------------------------------

data "aws_iam_policy_document" "lambda_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "alarm_bridge" {
  name               = "${local.name_prefix}-alarm-bridge"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

resource "aws_cloudwatch_log_group" "alarm_bridge" {
  name              = "/aws/lambda/${local.name_prefix}-alarm-bridge"
  retention_in_days = 14
}

# ---------------------------------------------------------------------------
# SSM Parameter — current AgentCore Runtime ARN.
#
# Provisioning script writes the real ARN here after Runtime creation.
# Lambda reads at every invocation, so re-provisioning the Runtime does
# not require redeploying the Lambda.
# ---------------------------------------------------------------------------

resource "aws_ssm_parameter" "runtime_arn" {
  name        = "/${var.environment}/${var.project_name}/agentcore-runtime-arn"
  description = "AgentCore Runtime ARN; written by scripts/provision_agentcore.py."
  type        = "String"
  value       = "PLACEHOLDER_FILL_VIA_PROVISIONING_SCRIPT"

  lifecycle {
    ignore_changes = [value]
  }
}

data "aws_iam_policy_document" "alarm_bridge" {
  statement {
    sid       = "OwnLogs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.alarm_bridge.arn}:*"]
  }

  statement {
    sid       = "ReadRuntimeArn"
    actions   = ["ssm:GetParameter"]
    resources = [aws_ssm_parameter.runtime_arn.arn]
  }

  statement {
    sid       = "InvokeRuntime"
    actions   = ["bedrock-agentcore:InvokeAgentRuntime"]
    resources = ["*"]
  }

  statement {
    sid       = "SendDLQ"
    actions   = ["sqs:SendMessage"]
    resources = [aws_sqs_queue.alarm_bridge_dlq.arn]
  }
}

resource "aws_iam_role_policy" "alarm_bridge" {
  name   = "${local.name_prefix}-alarm-bridge"
  role   = aws_iam_role.alarm_bridge.id
  policy = data.aws_iam_policy_document.alarm_bridge.json
}

# ---------------------------------------------------------------------------
# Lambda function — alarm bridge
#
# The zip contains only the alarm_bridge package; handler reaches boto3
# from the Lambda runtime layer. No additional pip deps needed.
# ---------------------------------------------------------------------------

data "archive_file" "alarm_bridge" {
  type        = "zip"
  source_dir  = "${path.module}/../../src/triage/lambdas/alarm_bridge"
  output_path = "${path.module}/.build/alarm_bridge.zip"
}

resource "aws_lambda_function" "alarm_bridge" {
  function_name = "${local.name_prefix}-alarm-bridge"
  role          = aws_iam_role.alarm_bridge.arn
  handler       = "handler.handler"
  runtime       = "python3.12"
  timeout       = 60
  memory_size   = 256

  filename         = data.archive_file.alarm_bridge.output_path
  source_code_hash = data.archive_file.alarm_bridge.output_base64sha256

  environment {
    variables = {
      TRIAGE_RUNTIME_ARN_PARAM = aws_ssm_parameter.runtime_arn.name
    }
  }

  dead_letter_config {
    target_arn = aws_sqs_queue.alarm_bridge_dlq.arn
  }

  depends_on = [
    aws_cloudwatch_log_group.alarm_bridge,
    aws_iam_role_policy.alarm_bridge,
  ]
}

# ---------------------------------------------------------------------------
# SNS → Lambda wiring
# ---------------------------------------------------------------------------

resource "aws_lambda_permission" "alarm_bridge_sns" {
  statement_id  = "AllowSNSInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.alarm_bridge.function_name
  principal     = "sns.amazonaws.com"
  source_arn    = aws_sns_topic.alarms.arn
}

resource "aws_sns_topic_subscription" "alarm_bridge" {
  topic_arn = aws_sns_topic.alarms.arn
  protocol  = "lambda"
  endpoint  = aws_lambda_function.alarm_bridge.arn
}

# ---------------------------------------------------------------------------
# AgentCore Runtime execution role
#
# Assumed by AgentCore Runtime when it starts the agent container.
# Scoped to the minimum the agent needs: invoke Bedrock models, write
# audit objects, read the Slack secret (covers a future path where the
# agent calls Slack outside the MCP namespace; can be tightened later),
# call Gateway / sister Runtime invocations, push X-Ray telemetry.
# ---------------------------------------------------------------------------

data "aws_iam_policy_document" "agent_runtime_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["bedrock-agentcore.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "agent_runtime" {
  name               = "${local.name_prefix}-agent-runtime"
  assume_role_policy = data.aws_iam_policy_document.agent_runtime_assume.json
}

data "aws_iam_policy_document" "agent_runtime" {
  statement {
    sid       = "InvokeBedrockModels"
    actions   = ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"]
    resources = ["*"]
  }

  statement {
    sid       = "PutAuditObjects"
    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.audit.arn}/events/*"]
  }

  statement {
    sid       = "ReadSlackSecret"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [aws_secretsmanager_secret.slack_bot_token.arn]
  }

  statement {
    sid = "AgentCoreGatewayAccess"
    actions = [
      "bedrock-agentcore:InvokeGatewayTarget",
      "bedrock-agentcore:ListGatewayTargets",
    ]
    resources = ["*"]
  }

  statement {
    sid       = "XRayTraceExport"
    actions   = ["xray:PutTraceSegments", "xray:PutTelemetryRecords"]
    resources = ["*"]
  }

  # AgentCore Runtime uses this role to pull the agent container image
  # from ECR when starting a session container.
  statement {
    sid       = "EcrAuth"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"]
  }

  # AgentCore's pre-validation tests these actions without a resource ARN
  # context, so resource-scoping to the specific repo fails its check even
  # though the actions are correctly granted for the actual pull URI.
  # Using "*" — acceptable for learner-scope; can tighten later if AgentCore
  # exposes a context-aware validation path.
  statement {
    sid = "EcrPullAgentImage"
    actions = [
      "ecr:BatchCheckLayerAvailability",
      "ecr:BatchGetImage",
      "ecr:GetDownloadUrlForLayer",
    ]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "agent_runtime" {
  name   = "${local.name_prefix}-agent-runtime"
  role   = aws_iam_role.agent_runtime.id
  policy = data.aws_iam_policy_document.agent_runtime.json
}

# ---------------------------------------------------------------------------
# ECR repository for the agent runtime container image
# ---------------------------------------------------------------------------

resource "aws_ecr_repository" "agent" {
  name                 = "${local.name_prefix}-agent"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = {
    Name = "${local.name_prefix}-agent"
  }
}

# ---------------------------------------------------------------------------
# Demo alarm — manually flipped to ALARM via `aws cloudwatch set-alarm-state`
# during hello-world testing so we don't need real metrics first.
# ---------------------------------------------------------------------------

resource "aws_cloudwatch_metric_alarm" "demo" {
  alarm_name        = "${local.name_prefix}-demo-alarm"
  alarm_description = "Hello-world demo. Flip with `aws cloudwatch set-alarm-state --alarm-name ${local.name_prefix}-demo-alarm --state-value ALARM --state-reason test`."

  metric_name = "RequestCount"
  namespace   = "AWS/ApplicationELB"
  statistic   = "Sum"
  period      = 60

  evaluation_periods  = 1
  threshold           = 1000000 # effectively unreachable; manual state flip is the trigger
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"

  dimensions = {
    LoadBalancer = aws_lb.main.arn_suffix
  }

  alarm_actions = [aws_sns_topic.alarms.arn]

  tags = {
    Name = "${local.name_prefix}-demo-alarm"
  }
}

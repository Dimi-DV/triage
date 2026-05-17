# Triage — MCP server on ECS Fargate.
#
# Day 34 afternoon scope. The MCP server runs behind the existing ALB on a
# /mcp/* listener rule and target group provisioned Day 33. AgentCore
# Gateway connects here over HTTPS, validating JWTs from AgentCore Identity
# at the MCP server (auth.py middleware) and enforcing Cedar policy at the
# Gateway boundary before the call ever reaches us.
#
# Bootstrap order:
#   1. Apply this Terraform: ECR repo, log group, IAM, task def, service.
#   2. Build & push the image to the new ECR repo (make push-mcp-image).
#   3. Force a service redeploy (make redeploy-mcp).
#   4. Provision AgentCore Runtime/Gateway/Identity, which sets the
#      AGENTCORE_IDENTITY_ISSUER env var on the task and flips
#      TRIAGE_MCP_AUTH_DISABLED off.

# ---------------------------------------------------------------------------
# ECR repository
# ---------------------------------------------------------------------------

resource "aws_ecr_repository" "mcp_server" {
  name                 = "${local.name_prefix}-mcp-server"
  image_tag_mutability = "MUTABLE" # iterating fast; flip to IMMUTABLE post-cutover.

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = {
    Name = "${local.name_prefix}-mcp-server"
  }
}

# ---------------------------------------------------------------------------
# AgentCore Identity issuer URL — placeholder at apply time; the
# provisioning script overwrites with the real value and force-redeploys
# the MCP service. The task definition pulls this via the `secrets` block
# so the value is never inlined into a JSON env list.
#
# This is the fail-closed bootstrap: until the placeholder is replaced,
# the MCP server installs BootstrapGateMiddleware and returns 503 on
# /mcp/* (keeping /health open so the ALB target stays healthy).
# ---------------------------------------------------------------------------

resource "aws_ssm_parameter" "agentcore_issuer" {
  name        = "/${var.environment}/${var.project_name}/agentcore-identity-issuer"
  description = "AgentCore Identity OAuth issuer URL; written by scripts/provision_agentcore.py."
  type        = "String"
  value       = "PLACEHOLDER_FILL_VIA_PROVISIONING_SCRIPT"

  lifecycle {
    ignore_changes = [value]
  }
}

# ---------------------------------------------------------------------------
# Slack bot token secret — value populated manually post-apply.
# Lives here because the MCP service task role grants Get access; the agent
# Runtime never reads it directly (the Slack write is an MCP tool call).
# ---------------------------------------------------------------------------

resource "aws_secretsmanager_secret" "slack_bot_token" {
  name        = "${local.name_prefix}-slack-bot-token"
  description = "Slack bot token (xoxb-…) for runbooks_api_post_to_slack"

  # Dev knob: short recovery window so destroy/re-apply iteration doesn't
  # hold a 30-day delete timer. Production should flip back to 30.
  recovery_window_in_days = 7

  tags = {
    Name = "${local.name_prefix}-slack-bot-token"
  }
}

# ---------------------------------------------------------------------------
# CloudWatch log group
# ---------------------------------------------------------------------------

resource "aws_cloudwatch_log_group" "mcp_server" {
  name              = "/ecs/${local.name_prefix}-mcp-server"
  retention_in_days = 14

  tags = {
    Name = "/ecs/${local.name_prefix}-mcp-server"
  }
}

# ---------------------------------------------------------------------------
# IAM — execution role (pulls image, ships logs) + task role (runtime perms)
# ---------------------------------------------------------------------------

data "aws_iam_policy_document" "ecs_tasks_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "mcp_task_execution" {
  name               = "${local.name_prefix}-mcp-task-execution"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_assume.json
}

resource "aws_iam_role_policy_attachment" "mcp_task_execution_managed" {
  role       = aws_iam_role.mcp_task_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

# Allow ECS to resolve `secrets` references in the task definition.
data "aws_iam_policy_document" "mcp_task_execution_ssm" {
  statement {
    sid       = "ResolveTaskSecrets"
    actions   = ["ssm:GetParameters"]
    resources = [aws_ssm_parameter.agentcore_issuer.arn]
  }
}

resource "aws_iam_role_policy" "mcp_task_execution_ssm" {
  name   = "${local.name_prefix}-mcp-task-execution-ssm"
  role   = aws_iam_role.mcp_task_execution.id
  policy = data.aws_iam_policy_document.mcp_task_execution_ssm.json
}

resource "aws_iam_role" "mcp_task" {
  name               = "${local.name_prefix}-mcp-task"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_assume.json
}

data "aws_iam_policy_document" "mcp_task" {
  statement {
    sid       = "ReadOnlyCloudWatchMetrics"
    actions   = ["cloudwatch:GetMetricStatistics", "cloudwatch:ListMetrics"]
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
    sid       = "XRayTraceExport"
    actions   = ["xray:PutTraceSegments", "xray:PutTelemetryRecords"]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "mcp_task" {
  name   = "${local.name_prefix}-mcp-task-policy"
  role   = aws_iam_role.mcp_task.id
  policy = data.aws_iam_policy_document.mcp_task.json
}

# ---------------------------------------------------------------------------
# Task definition (Fargate)
# ---------------------------------------------------------------------------

resource "aws_ecs_task_definition" "mcp_server" {
  family                   = "${local.name_prefix}-mcp-server"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = "512"
  memory                   = "1024"
  execution_role_arn       = aws_iam_role.mcp_task_execution.arn
  task_role_arn            = aws_iam_role.mcp_task.arn

  container_definitions = jsonencode([
    {
      name      = "mcp-server"
      image     = "${aws_ecr_repository.mcp_server.repository_url}:latest"
      essential = true

      portMappings = [
        { containerPort = var.app_port, protocol = "tcp" }
      ]

      environment = [
        { name = "TRIAGE_MCP_TRANSPORT", value = "streamable-http" },
        { name = "TRIAGE_AUDIT_BUCKET", value = aws_s3_bucket.audit.id },
        { name = "TRIAGE_SLACK_SECRET_ID", value = aws_secretsmanager_secret.slack_bot_token.name },
        { name = "TRIAGE_MCP_AUDIENCE", value = "triage-mcp" },
        { name = "AWS_REGION", value = var.aws_region },
        # AgentCore Gateway authenticates callers via SigV4 (AWS_IAM authorizer).
        # The MCP server trusts requests forwarded from the Gateway; no second
        # auth layer here. The Cedar enforcement that the original BootstrapGate
        # / JWTAuth pair was scaffolded around still needs a Gateway interceptor
        # (deferred). Leaving MCP auth disabled until that path is implemented.
        { name = "TRIAGE_MCP_AUTH_DISABLED", value = "1" },
      ]

      # No SSM-backed secrets needed: the original AGENTCORE_IDENTITY_ISSUER
      # path is moot with TRIAGE_MCP_AUTH_DISABLED. Pulling from SSM at task
      # launch also requires either a SSM VPC endpoint or NAT egress, and we
      # were hitting "context deadline exceeded" on the SSM resolve.

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.mcp_server.name
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "mcp"
        }
      }

      healthCheck = {
        command     = ["CMD-SHELL", "python -c 'import urllib.request,sys; urllib.request.urlopen(\"http://127.0.0.1:${var.app_port}/health\").read(); sys.exit(0)' || exit 1"]
        interval    = 30
        timeout     = 5
        retries     = 3
        startPeriod = 30
      }
    }
  ])
}

# ---------------------------------------------------------------------------
# ECS service
# ---------------------------------------------------------------------------

resource "aws_ecs_service" "mcp_server" {
  name            = "${local.name_prefix}-mcp-server"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.mcp_server.arn
  desired_count   = 1
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = aws_subnet.private[*].id
    security_groups  = [aws_security_group.app.id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.app.arn
    container_name   = "mcp-server"
    container_port   = var.app_port
  }

  # Wait for ALB target health before declaring the service healthy.
  health_check_grace_period_seconds = 60

  depends_on = [
    aws_iam_role_policy.mcp_task,
    aws_lb_listener.https,
  ]
}

# ---------------------------------------------------------------------------
# ALB listener rule for /mcp/* — explicit alongside the default-action
# forward, so the rule list documents the MCP path surface.
# ---------------------------------------------------------------------------

resource "aws_lb_listener_rule" "mcp" {
  listener_arn = aws_lb_listener.https.arn
  priority     = 100

  condition {
    path_pattern {
      values = ["/mcp", "/mcp/*"]
    }
  }

  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.app.arn
  }
}

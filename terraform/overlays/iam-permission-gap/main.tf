# Triage outage corpus — scenario 07: iam-permission-gap.
#
# Sidekick ECS service runs a Python HTTP server that checks an AWS
# API at startup (s3:HeadBucket against the stack audit bucket). The
# task role attached to the task is deliberately gimped — it has the
# ecs-tasks trust policy but NO action permissions. The HeadBucket
# call fails with AccessDenied; the cached failure makes the health
# endpoint return 503 on every probe. UnHealthyHostCount > 0 fires.
#
# Per the spec — this scenario is `runbook_status: by_design_none`.
# The agent must diagnose from AGENT.md general principles alone:
# read describe_target_health (unhealthy, Target.FailedHealthChecks),
# describe_task_definition (sees the task_role_arn + container command
# using boto3 + env var pointing at the audit bucket), and logs (sees
# the verbatim `AccessDenied` error from boto3 with action name and
# role ARN). The diagnosis the agent should reach: "task role X
# lacks permission to perform action Y."
#
# Sidekick model: nothing under terraform/stack/ is mutated. Reverts
# in a single `terraform destroy`. The gimped task role is created in
# the overlay (not borrowed from the stack).

locals {
  name_prefix = "${var.environment}-${var.project_name}"
  victim_name = "${local.name_prefix}-iam-victim"
}

data "terraform_remote_state" "stack" {
  backend = "s3"
  config = {
    bucket = var.stack_state_bucket
    key    = var.stack_state_key
    region = var.aws_region
  }
}

data "aws_caller_identity" "current" {}

data "aws_lb" "main" {
  arn = data.terraform_remote_state.stack.outputs.alb_arn
}

data "aws_lb_listener" "https" {
  load_balancer_arn = data.terraform_remote_state.stack.outputs.alb_arn
  port              = 443
}

# ---------------------------------------------------------------------------
# Target group + listener rule.
# ---------------------------------------------------------------------------

resource "aws_lb_target_group" "victim" {
  name        = "${local.victim_name}-tg"
  port        = var.container_port
  protocol    = "HTTP"
  vpc_id      = data.terraform_remote_state.stack.outputs.vpc_id
  target_type = "ip"

  health_check {
    enabled             = true
    port                = "traffic-port"
    protocol            = "HTTP"
    path                = "/"
    matcher             = "200"
    healthy_threshold   = 2
    unhealthy_threshold = 2
    interval            = 15
    timeout             = 5
  }

  deregistration_delay = 30

  tags = {
    Name     = "${local.victim_name}-tg"
    Scenario = "iam-permission-gap"
  }
}

resource "aws_lb_listener_rule" "victim" {
  listener_arn = data.aws_lb_listener.https.arn
  priority     = 85 # tucked between 04 (80) and 05 (90)

  condition {
    path_pattern {
      values = ["/iam-victim", "/iam-victim/*"]
    }
  }

  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.victim.arn
  }
}

# ---------------------------------------------------------------------------
# IAM roles.
#
# The EXECUTION role (pulls image, pushes logs) is fine — uses the
# managed ECS task execution policy. The TASK role (what the container
# code's boto3 client uses) is GIMPED: trust policy lets ecs-tasks
# assume it, but no permissions are attached. Any AWS API call from
# the container will return AccessDenied.
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

resource "aws_iam_role" "victim_task_exec" {
  name               = "${local.victim_name}-task-exec"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_assume.json
}

resource "aws_iam_role_policy_attachment" "victim_task_exec_managed" {
  role       = aws_iam_role.victim_task_exec.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

# The gimped task role — used by the container code (boto3). Trust
# policy allows ecs-tasks to assume; no permissions attached.
resource "aws_iam_role" "victim_task_role" {
  name               = "${local.victim_name}-task-role"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_assume.json

  tags = {
    Scenario = "iam-permission-gap"
  }
}

# ---------------------------------------------------------------------------
# Task definition.
# ---------------------------------------------------------------------------

resource "aws_cloudwatch_log_group" "victim" {
  name              = "/ecs/${local.victim_name}"
  retention_in_days = 1
}

resource "aws_ecs_task_definition" "victim" {
  family                   = local.victim_name
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = "256"
  memory                   = "512"
  execution_role_arn       = aws_iam_role.victim_task_exec.arn
  task_role_arn            = aws_iam_role.victim_task_role.arn

  container_definitions = jsonencode([
    {
      name      = "iam-victim"
      image     = "public.ecr.aws/docker/library/python:3.12-alpine"
      essential = true

      # Pip-install boto3, then run a Python HTTP server. The startup
      # script tries s3:HeadBucket against the stack audit bucket; the
      # task role has no permissions, so the call fails with
      # AccessDenied. The error message (carrying the task role ARN
      # + the action + the resource) is printed once at startup and
      # cached for every subsequent health probe response.
      entryPoint = ["/bin/sh", "-c"]
      command = [
        join("\n", [
          "set -e",
          "pip install --no-cache-dir --quiet boto3",
          "cat > /tmp/health.py <<'PYEOF'",
          "import boto3, os, time",
          "from http.server import HTTPServer, BaseHTTPRequestHandler",
          "AUDIT_BUCKET = os.environ['AUDIT_BUCKET']",
          "REGION = os.environ.get('AWS_REGION', 'us-east-1')",
          "IAM_OK = False",
          "IAM_ERROR = ''",
          "try:",
          "    s3 = boto3.client('s3', region_name=REGION)",
          "    s3.head_bucket(Bucket=AUDIT_BUCKET)",
          "    IAM_OK = True",
          "    print(f'{time.strftime(\"%FT%TZ\", time.gmtime())} IAM startup check OK: s3:HeadBucket on {AUDIT_BUCKET}', flush=True)",
          "except Exception as e:",
          "    IAM_ERROR = f'{type(e).__name__}: {e}'",
          "    print(f'{time.strftime(\"%FT%TZ\", time.gmtime())} IAM startup check FAILED: {IAM_ERROR}', flush=True)",
          "class H(BaseHTTPRequestHandler):",
          "    def log_message(self, *a): pass",
          "    def do_GET(self):",
          "        if IAM_OK:",
          "            self.send_response(200); self.end_headers()",
          "            self.wfile.write(b'OK\\n')",
          "        else:",
          "            self.send_response(503); self.end_headers()",
          "            self.wfile.write(f'IAM check failed: {IAM_ERROR}\\n'.encode())",
          "print(f'iam-victim health server starting on 8080; IAM_OK={IAM_OK}', flush=True)",
          "HTTPServer(('0.0.0.0', 8080), H).serve_forever()",
          "PYEOF",
          "exec python3 /tmp/health.py",
        ])
      ]

      portMappings = [
        { containerPort = var.container_port, protocol = "tcp" }
      ]

      environment = [
        { name = "AUDIT_BUCKET", value = data.terraform_remote_state.stack.outputs.audit_bucket_name },
      ]

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.victim.name
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "iam-victim"
        }
      }
    }
  ])

  tags = {
    Scenario = "iam-permission-gap"
  }
}

resource "aws_ecs_service" "victim" {
  name            = local.victim_name
  cluster         = data.terraform_remote_state.stack.outputs.ecs_cluster_arn
  task_definition = aws_ecs_task_definition.victim.arn
  desired_count   = 2
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = data.terraform_remote_state.stack.outputs.private_subnet_ids
    security_groups  = [data.terraform_remote_state.stack.outputs.app_security_group_id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.victim.arn
    container_name   = "iam-victim"
    container_port   = var.container_port
  }

  # Pip install takes ~30s; grace period covers it plus a margin.
  health_check_grace_period_seconds = 90

  depends_on = [
    aws_lb_listener_rule.victim,
  ]

  tags = {
    Scenario = "iam-permission-gap"
  }
}

# ---------------------------------------------------------------------------
# Victim alarm.
# ---------------------------------------------------------------------------

resource "aws_cloudwatch_metric_alarm" "victim_tg_unhealthy" {
  alarm_name = "${local.victim_name}-tg-unhealthy"

  alarm_description = join("\n", [
    "ALB target group ${aws_lb_target_group.victim.name} has unhealthy targets.",
    "Health check probes are failing. Investigate the root cause and the",
    "appropriate remediation.",
  ])

  namespace           = "AWS/ApplicationELB"
  metric_name         = "UnHealthyHostCount"
  statistic           = "Maximum"
  period              = 60
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"

  dimensions = {
    TargetGroup  = aws_lb_target_group.victim.arn_suffix
    LoadBalancer = data.aws_lb.main.arn_suffix
  }

  alarm_actions = [data.terraform_remote_state.stack.outputs.alarms_sns_topic_arn]

  tags = {
    Name     = "${local.victim_name}-tg-unhealthy"
    Scenario = "iam-permission-gap"
  }
}

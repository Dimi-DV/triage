# Triage outage corpus — scenario 02: missing environment variable.
#
# Deliberate misconfiguration: a sidekick ECS service's task definition
# overrides nginx's entrypoint with a shell command that requires
# ${REQUIRED_API_KEY} to start, but the container's `environment` block
# does not include that variable. nginx never starts; the target group's
# health checks against port 80 fail; UnhealthyHostCount alarm fires.
#
# Why this exercises the agent differently from scenario 01:
#   Scenario 01 was a numeric port comparison (8081 vs 80). Scenario 02
#   is a string-presence comparison — the agent must read the task def's
#   `command` field, extract the env var name it references, then check
#   the `environment` dict and notice the name is absent. Different
#   reasoning shape, same four tools.
#
# Sidekick model: nothing under terraform/stack/ is mutated. ALB SG
# already permits port 80 to the app SG (the live MCP service runs on
# the same SG and same port), so no extra SG rules are needed here.
#
# Revert: `terraform destroy` in this directory. No manual cleanup.

locals {
  name_prefix = "${var.environment}-${var.project_name}"
  broken_name = "${local.name_prefix}-broken-env"
}

# ---------------------------------------------------------------------------
# Read the stack's outputs to wire ourselves in.
# ---------------------------------------------------------------------------

data "terraform_remote_state" "stack" {
  backend = "s3"
  config = {
    bucket = var.stack_state_bucket
    key    = var.stack_state_key
    region = var.aws_region
  }
}

data "aws_lb" "main" {
  arn = data.terraform_remote_state.stack.outputs.alb_arn
}

data "aws_lb_listener" "https" {
  load_balancer_arn = data.terraform_remote_state.stack.outputs.alb_arn
  port              = 443
}

# ---------------------------------------------------------------------------
# Target group. Health check is correctly configured against the container
# port; the failure mode is that the container never starts, so the port
# has nothing listening.
# ---------------------------------------------------------------------------

resource "aws_lb_target_group" "broken" {
  name        = "${local.broken_name}-tg"
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

  tags = {
    Name     = "${local.broken_name}-tg"
    Scenario = "missing-env-var"
  }
}

resource "aws_lb_listener_rule" "broken" {
  listener_arn = data.aws_lb_listener.https.arn
  priority     = 60 # below scenario 01's 50, above MCP's 100

  condition {
    path_pattern {
      values = ["/missing-env", "/missing-env/*"]
    }
  }

  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.broken.arn
  }
}

# ---------------------------------------------------------------------------
# ECS task — nginx with a custom entrypoint that gates startup on the
# presence of ${REQUIRED_API_KEY}.
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

resource "aws_iam_role" "broken_task_exec" {
  name               = "${local.broken_name}-task-exec"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_assume.json
}

resource "aws_iam_role_policy_attachment" "broken_task_exec_managed" {
  role       = aws_iam_role.broken_task_exec.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_cloudwatch_log_group" "broken" {
  name              = "/ecs/${local.broken_name}"
  retention_in_days = 1
}

resource "aws_ecs_task_definition" "broken" {
  family                   = local.broken_name
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = "256"
  memory                   = "512"
  execution_role_arn       = aws_iam_role.broken_task_exec.arn

  container_definitions = jsonencode([
    {
      name      = "nginx"
      image     = "public.ecr.aws/nginx/nginx:1.27-alpine"
      essential = true

      # Override the image's default entrypoint+cmd with a gating shell
      # script. The literal text "REQUIRED_API_KEY" appears here — the
      # agent reads describe_task_definition's command field, sees the
      # `$REQUIRED_API_KEY` reference, then checks the `environment` block
      # below and notices the variable is absent.
      #
      # Sleeping vs exiting matters: exit-1 would loop the task and the
      # targets would never stay registered long enough for
      # UnHealthyHostCount to publish.
      entryPoint = ["/bin/sh", "-c"]
      command = [
        "if [ -n \"$REQUIRED_API_KEY\" ]; then exec nginx -g 'daemon off;'; else echo 'FATAL: REQUIRED_API_KEY environment variable is required' >&2; sleep 3600; fi"
      ]

      portMappings = [
        { containerPort = var.container_port, protocol = "tcp" }
      ]

      # Deliberately omits REQUIRED_API_KEY. LOG_LEVEL + APP_REGION are
      # here to make the env block visibly non-empty so the agent can see
      # what's present vs what's missing.
      environment = [
        { name = "LOG_LEVEL", value = "info" },
        { name = "APP_REGION", value = var.aws_region },
      ]

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.broken.name
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "nginx"
        }
      }
    }
  ])
}

resource "aws_ecs_service" "broken" {
  name            = local.broken_name
  cluster         = data.terraform_remote_state.stack.outputs.ecs_cluster_arn
  task_definition = aws_ecs_task_definition.broken.arn
  desired_count   = 1
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = data.terraform_remote_state.stack.outputs.private_subnet_ids
    security_groups  = [data.terraform_remote_state.stack.outputs.app_security_group_id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.broken.arn
    container_name   = "nginx"
    container_port   = var.container_port
  }

  health_check_grace_period_seconds = 0

  depends_on = [
    aws_lb_listener_rule.broken,
  ]
}

# ---------------------------------------------------------------------------
# The alarm — same operational shape as scenario 01: names the affected
# resource, restates the metric symptom, does not name the cause.
# ---------------------------------------------------------------------------

resource "aws_cloudwatch_metric_alarm" "broken_tg_unhealthy" {
  alarm_name = "${local.broken_name}-tg-unhealthy"

  alarm_description = join("\n", [
    "ALB target group ${aws_lb_target_group.broken.name} has unhealthy targets.",
    "Health check probes are failing. Investigate the root cause and the",
    "appropriate remediation.",
  ])

  namespace           = "AWS/ApplicationELB"
  metric_name         = "UnHealthyHostCount"
  statistic           = "Maximum"
  period              = 60
  evaluation_periods  = 2
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"

  dimensions = {
    TargetGroup  = aws_lb_target_group.broken.arn_suffix
    LoadBalancer = data.aws_lb.main.arn_suffix
  }

  alarm_actions = [data.terraform_remote_state.stack.outputs.alarms_sns_topic_arn]

  tags = {
    Name     = "${local.broken_name}-tg-unhealthy"
    Scenario = "missing-env-var"
  }
}

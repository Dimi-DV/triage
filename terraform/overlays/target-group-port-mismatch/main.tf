# Triage outage corpus — scenario 01: target-group port mismatch.
#
# Deliberate misconfiguration: a sidekick ECS service runs nginx on port 80,
# but its target group's health check probes port 8081. Probes time out;
# UnhealthyHostCount alarm fires; SNS → bridge Lambda → AgentCore Runtime.
#
# Sidekick model: nothing under terraform/stack/ is mutated. The overlay
# adds two SG rules to the stack-owned ALB and app SGs (standalone
# aws_vpc_security_group_*_rule resources, so the parent SGs stay
# stack-owned and `terraform destroy` here removes only the rules).
#
# Revert: `terraform destroy` in this directory. No manual cleanup.

locals {
  name_prefix = "${var.environment}-${var.project_name}"
  broken_name = "${local.name_prefix}-broken"
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

# ALB SG isn't exported as a stack output; look it up by Name tag.
data "aws_security_group" "alb" {
  filter {
    name   = "vpc-id"
    values = [data.terraform_remote_state.stack.outputs.vpc_id]
  }
  filter {
    name   = "tag:Name"
    values = ["${local.name_prefix}-alb-sg"]
  }
}

# ALB itself — for arn_suffix (CloudWatch dimension format).
data "aws_lb" "main" {
  arn = data.terraform_remote_state.stack.outputs.alb_arn
}

data "aws_lb_listener" "https" {
  load_balancer_arn = data.terraform_remote_state.stack.outputs.alb_arn
  port              = 443
}

# ---------------------------------------------------------------------------
# Target group with the bad knob.
# ---------------------------------------------------------------------------

resource "aws_lb_target_group" "broken" {
  name        = "${local.broken_name}-tg"
  port        = var.container_port # cosmetic for ip targets; ECS overrides via load_balancer block
  protocol    = "HTTP"
  vpc_id      = data.terraform_remote_state.stack.outputs.vpc_id
  target_type = "ip"

  # The mismatch. Container listens on var.container_port (80); health
  # check probes broken_health_check_port (8081). Probes time out.
  # Short intervals so the alarm fires within a couple minutes.
  health_check {
    enabled             = true
    port                = tostring(var.broken_health_check_port)
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
    Scenario = "target-group-port-mismatch"
  }
}

# Listener rule — without an ALB association the TG won't publish
# UnhealthyHostCount under (TargetGroup, LoadBalancer) dimensions, which
# is what the alarm watches.
resource "aws_lb_listener_rule" "broken" {
  listener_arn = data.aws_lb_listener.https.arn
  priority     = 50 # above MCP's 100; first-match wins so MCP traffic stays unaffected

  condition {
    path_pattern {
      values = ["/broken", "/broken/*"]
    }
  }

  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.broken.arn
  }
}

# ---------------------------------------------------------------------------
# SG plumbing — let the ALB reach the broken target on the health check port.
#
# These are standalone rule resources so they live entirely in the overlay's
# state. Destroying the overlay removes only these rules; the parent SGs
# (stack-owned) are untouched. Without them, probes fail at the network
# layer rather than at the application layer, and the alarm description
# (which calls out the port-mismatch shape) would be misleading.
# ---------------------------------------------------------------------------

resource "aws_vpc_security_group_egress_rule" "alb_to_broken_hc" {
  security_group_id            = data.aws_security_group.alb.id
  referenced_security_group_id = data.terraform_remote_state.stack.outputs.app_security_group_id
  ip_protocol                  = "tcp"
  from_port                    = var.broken_health_check_port
  to_port                      = var.broken_health_check_port
  description                  = "[scenario:port-mismatch] ALB health-check probes to broken service"
}

resource "aws_vpc_security_group_ingress_rule" "app_from_alb_hc" {
  security_group_id            = data.terraform_remote_state.stack.outputs.app_security_group_id
  referenced_security_group_id = data.aws_security_group.alb.id
  ip_protocol                  = "tcp"
  from_port                    = var.broken_health_check_port
  to_port                      = var.broken_health_check_port
  description                  = "[scenario:port-mismatch] Allow ALB probes on the misconfigured health check port"
}

# ---------------------------------------------------------------------------
# ECS task — vanilla nginx, multi-arch. Listens on 80 with no AWS calls,
# so no task role is required and no extra IAM blast radius.
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

  # Default platform is LINUX/X86_64. nginx:alpine is multi-arch but the
  # default suffices — no runtime_platform override needed.

  container_definitions = jsonencode([
    {
      name      = "nginx"
      image     = "public.ecr.aws/nginx/nginx:1.27-alpine"
      essential = true

      portMappings = [
        { containerPort = var.container_port, protocol = "tcp" }
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

  # No grace period: we WANT health checks to fail as fast as possible.
  health_check_grace_period_seconds = 0

  depends_on = [
    aws_lb_listener_rule.broken,
    aws_vpc_security_group_ingress_rule.app_from_alb_hc,
    aws_vpc_security_group_egress_rule.alb_to_broken_hc,
  ]
}

# ---------------------------------------------------------------------------
# The alarm — fires when any target in the broken TG is unhealthy. Description
# carries the port numbers as configuration data; it does not draw the
# "port mismatch" conclusion (that's the agent's job).
# ---------------------------------------------------------------------------

resource "aws_cloudwatch_metric_alarm" "broken_tg_unhealthy" {
  alarm_name = "${local.broken_name}-tg-unhealthy"

  # Realistic ops-style description: names the affected resource, restates
  # the metric symptom, and stops there. The agent must walk the chain
  # itself — pull target health to find the failure reason and the
  # configured health-check vs registered port — instead of reading the
  # port numbers off the alarm description.
  alarm_description = join("\n", [
    "ALB target group ${aws_lb_target_group.broken.name} has unhealthy targets.",
    "Health check probes are failing. Investigate the root cause and the",
    "appropriate remediation.",
  ])

  namespace = "AWS/ApplicationELB"
  # AWS emits this metric as `UnHealthyHostCount` (capital H mid-word) —
  # confirmed via `aws cloudwatch list-metrics`. The lowercase form appears
  # in some AWS docs but no datapoints are published under it.
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
    Scenario = "target-group-port-mismatch"
  }
}

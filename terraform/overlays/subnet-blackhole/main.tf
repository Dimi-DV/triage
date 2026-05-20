# Triage outage corpus — scenario 05: subnet-blackhole (FIS chaos).
#
# AWS FIS injects `aws:network:disrupt-connectivity` with scope=all
# against a SINGLE private subnet for 5 minutes — total subnet
# blackhole. The victim ECS service is pinned to that single subnet
# (no multi-AZ spread), so ALL of its tasks lose connectivity
# simultaneously. UnHealthyHostCount on the victim TG rises to the
# full task count; there is no AZ asymmetry to compare against.
#
# Why this is structurally distinct from 03 az-slowdown:
#   03 is a MULTI-AZ victim whose AZ-a tasks lose connectivity while
#   AZ-b tasks stay healthy — the diagnostic signature is the
#   asymmetric heartbeat pattern. 05 is a SINGLE-AZ victim where all
#   tasks live in the same subnet, so when that subnet blackholes
#   there is no asymmetry — every target goes unhealthy uniformly.
#   The agent's 03 runbook ("look for AZ asymmetry") doesn't apply;
#   05 needs its own diagnostic chain that reads the per-target
#   subnet CIDR and concludes "all targets are in one subnet, the
#   subnet is unreachable."
#
# This is also the diagnostic shape a single-AZ production service
# would surface during a real subnet-scoped network event (NACL
# misconfig, route table drift, AZ infrastructure event in a
# single-AZ deployment).
#
# Sidekick model: nothing under terraform/stack/ is mutated. Reverts
# in a single `terraform destroy`.

locals {
  name_prefix = "${var.environment}-${var.project_name}"
  victim_name = "${local.name_prefix}-subnet-victim"
}

# ---------------------------------------------------------------------------
# Stack outputs + lookups.
# ---------------------------------------------------------------------------

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

# DEDICATED victim subnet — created by this overlay so the FIS blackhole
# is fully isolated from the live MCP private subnets. The live MCP
# service has desired_count=1 across the existing private_subnet_ids,
# so disrupting either of those carries a 50% chance of knocking out
# production whenever Fargate happens to place the task there. A
# dedicated subnet sidesteps that entirely.
resource "aws_subnet" "victim" {
  vpc_id            = data.terraform_remote_state.stack.outputs.vpc_id
  cidr_block        = var.victim_subnet_cidr
  availability_zone = var.victim_subnet_az

  tags = {
    Name     = "${local.victim_name}-subnet"
    Scenario = "subnet-blackhole"
  }
}

# Reuse the stack's existing AZ-matching private route table — gives
# the victim subnet the same NAT egress as live MCP so CloudWatch log
# pushes work pre-disruption. The stack names them
# `dev-triage-private-rt-<az>`.
data "aws_route_table" "private_az_matching" {
  vpc_id = data.terraform_remote_state.stack.outputs.vpc_id
  filter {
    name   = "tag:Name"
    values = ["${local.name_prefix}-private-rt-${var.victim_subnet_az}"]
  }
}

resource "aws_route_table_association" "victim" {
  subnet_id      = aws_subnet.victim.id
  route_table_id = data.aws_route_table.private_az_matching.id
}

# Live MCP target group — used as the production guard-rail alarm
# dimension. FIS auto-halts if this trips.
data "aws_lb_target_group" "live_mcp" {
  name = "${local.name_prefix}-app-tg"
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
    Scenario = "subnet-blackhole"
  }
}

resource "aws_lb_listener_rule" "victim" {
  listener_arn = data.aws_lb_listener.https.arn
  priority     = 90 # below 01 (50), 02 (60), 03 (70), 04 (80); above MCP (100)

  condition {
    path_pattern {
      values = ["/subnet-victim", "/subnet-victim/*"]
    }
  }

  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.victim.arn
  }
}

# ---------------------------------------------------------------------------
# Victim ECS service — SINGLE-SUBNET Fargate (key structural difference
# from 03). Standard nginx with no slow-boot or heartbeat sidecar; the
# disruption itself is what surfaces the symptom.
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

  container_definitions = jsonencode([
    {
      name      = "nginx"
      image     = "public.ecr.aws/nginx/nginx:1.27-alpine"
      essential = true

      # nginx alpine ships listening on port 80. The stack's app SG
      # only accepts ingress from the ALB SG on port 8080, so rewrite
      # the listen directive at start. Same pattern as 03.
      entryPoint = ["/bin/sh", "-c"]
      command = [
        "sed -i 's/listen[[:space:]]*80;/listen ${var.container_port};/g' /etc/nginx/conf.d/default.conf && exec /docker-entrypoint.sh nginx -g 'daemon off;'"
      ]

      portMappings = [
        { containerPort = var.container_port, protocol = "tcp" }
      ]

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.victim.name
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "nginx"
        }
      }
    }
  ])

  tags = {
    Scenario = "subnet-blackhole"
  }
}

resource "aws_ecs_service" "victim" {
  name            = local.victim_name
  cluster         = data.terraform_remote_state.stack.outputs.ecs_cluster_arn
  task_definition = aws_ecs_task_definition.victim.arn
  desired_count   = 2
  launch_type     = "FARGATE"

  network_configuration {
    # SINGLE subnet — all tasks pinned to one AZ. This is the
    # structural distinction from 03 (which spreads across 2 AZs).
    subnets          = [aws_subnet.victim.id]
    security_groups  = [data.terraform_remote_state.stack.outputs.app_security_group_id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.victim.arn
    container_name   = "nginx"
    container_port   = var.container_port
  }

  health_check_grace_period_seconds = 30

  depends_on = [
    aws_lb_listener_rule.victim,
  ]

  tags = {
    Scenario = "subnet-blackhole"
  }
}

# ---------------------------------------------------------------------------
# Victim alarm — fires when the subnet blackhole takes the service down.
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
    Scenario = "subnet-blackhole"
  }
}

# ---------------------------------------------------------------------------
# Production guard-rail alarm — same pattern as 03/04. Watches the live
# MCP TG; FIS auto-halts if this trips.
# ---------------------------------------------------------------------------

resource "aws_cloudwatch_metric_alarm" "live_mcp_guard" {
  alarm_name = "${local.victim_name}-live-mcp-guard"

  alarm_description = "FIS safety guard. Trips if the live MCP TG goes unhealthy during the subnet-blackhole experiment; FIS stop condition references this alarm and halts the experiment when it fires."

  namespace           = "AWS/ApplicationELB"
  metric_name         = "UnHealthyHostCount"
  statistic           = "Maximum"
  period              = 60
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"

  dimensions = {
    TargetGroup  = data.aws_lb_target_group.live_mcp.arn_suffix
    LoadBalancer = data.aws_lb.main.arn_suffix
  }

  tags = {
    Name     = "${local.victim_name}-live-mcp-guard"
    Scenario = "subnet-blackhole"
  }
}

# ---------------------------------------------------------------------------
# FIS IAM role + experiment template.
# ---------------------------------------------------------------------------

data "aws_iam_policy_document" "fis_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["fis.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "fis_subnet_blackhole" {
  name               = "${local.victim_name}-fis-role"
  assume_role_policy = data.aws_iam_policy_document.fis_assume.json
}

# Same managed policy 03 uses for aws:network:disrupt-connectivity.
resource "aws_iam_role_policy_attachment" "fis_network_access" {
  role       = aws_iam_role.fis_subnet_blackhole.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSFaultInjectionSimulatorNetworkAccess"
}

resource "aws_fis_experiment_template" "subnet_blackhole" {
  description = "Total network blackhole on ${aws_subnet.victim.availability_zone}'s private subnet for ${var.experiment_duration}. Single-subnet victim service loses all connectivity uniformly (no AZ asymmetry to compare against, unlike 03 az-slowdown)."
  role_arn    = aws_iam_role.fis_subnet_blackhole.arn

  stop_condition {
    source = "aws:cloudwatch:alarm"
    value  = aws_cloudwatch_metric_alarm.live_mcp_guard.arn
  }

  action {
    name        = "blackhole-victim-subnet"
    action_id   = "aws:network:disrupt-connectivity"
    description = "Total NACL blackhole on the victim subnet — no traffic in or out."

    parameter {
      key   = "scope"
      value = "all"
    }

    parameter {
      key   = "duration"
      value = var.experiment_duration
    }

    target {
      key   = "Subnets"
      value = "victim-subnet"
    }
  }

  target {
    name           = "victim-subnet"
    resource_type  = "aws:ec2:subnet"
    selection_mode = "ALL"
    resource_arns  = [aws_subnet.victim.arn]
  }

  tags = {
    Name     = "${local.victim_name}-fis-subnet-blackhole"
    Scenario = "subnet-blackhole"
  }
}

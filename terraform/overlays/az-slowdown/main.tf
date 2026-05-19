# Triage outage corpus — scenario 03: AZ disconnect (first FIS scenario).
#
# AWS FIS injects a `disrupt-connectivity` fault with scope=availability-zone
# against the AZ-a private subnet for 3 minutes. The victim ECS service runs
# 4 Fargate tasks distributed across two AZs; the disrupted AZ's tasks lose
# cross-AZ connectivity. The ALB's cross-AZ health probes to those tasks
# fail, UnHealthyHostCount rises on the victim TG, the alarm fires.
#
# Load-bearing evidence the agent must surface: each task runs a curl-based
# heartbeat sidecar that periodically TCP-pings the (cross-AZ) stack RDS
# endpoint and logs `HEARTBEAT OK` or `HEARTBEAT TIMEOUT` with the task's
# AZ identity. Disrupted tasks log TIMEOUT; healthy tasks log OK. The agent
# needs to call `logs_api_filter_log_events` against `/ecs/<family>` to see
# this asymmetry — `describe_target_health` + `describe_task_definition`
# alone bottom out at "task def looks fine but hosts are unhealthy."
#
# Sidekick model: nothing under terraform/stack/ is mutated. Reverts in a
# single `terraform destroy` (FIS experiment template, victim service,
# alarms, IAM role).

locals {
  name_prefix = "${var.environment}-${var.project_name}"
  victim_name = "${local.name_prefix}-az-victim"
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

# AZ-a private subnet — the FIS target. Index 0 corresponds to
# var.availability_zones[0] in the stack, which is us-east-1a.
data "aws_subnet" "az_a" {
  id = data.terraform_remote_state.stack.outputs.private_subnet_ids[0]
}

# Live MCP target group — used as the production guard-rail alarm
# dimension. If the FIS experiment somehow degrades the live MCP service,
# this alarm trips and FIS auto-stops the experiment.
data "aws_lb_target_group" "live_mcp" {
  name = "${local.name_prefix}-app-tg"
}

# RDS host the heartbeat sidecar TCP-pings. Cross-AZ from the disrupted
# subnet's perspective whenever the RDS primary isn't in the disrupted AZ
# (or vice versa) — that asymmetry is what makes the heartbeat log lines
# the load-bearing evidence.
locals {
  rds_host = data.terraform_remote_state.stack.outputs.rds_address
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

  # Health-check the nginx container on the registered port. Cross-AZ
  # ALB probes to the disrupted AZ's tasks will time out during the
  # experiment, marking them unhealthy.
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
    Name     = "${local.victim_name}-tg"
    Scenario = "az-slowdown"
  }
}

resource "aws_lb_listener_rule" "victim" {
  listener_arn = data.aws_lb_listener.https.arn
  priority     = 70 # below scenarios 01 (50) and 02 (60), above MCP default (100)

  condition {
    path_pattern {
      values = ["/az-victim", "/az-victim/*"]
    }
  }

  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.victim.arn
  }
}

# ---------------------------------------------------------------------------
# Victim ECS service — multi-AZ Fargate, two-container task definition.
#
# Container 1 (nginx)     — serves :80 for the ALB health check
# Container 2 (heartbeat) — curl-based TCP ping of the stack RDS endpoint
#                           every 5s, logging OK / TIMEOUT with AZ identity.
#                           Logs are the load-bearing evidence.
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
  cpu                      = "512"
  memory                   = "1024"
  execution_role_arn       = aws_iam_role.victim_task_exec.arn

  container_definitions = jsonencode([
    {
      name      = "nginx"
      image     = "public.ecr.aws/nginx/nginx:1.27-alpine"
      essential = true

      # nginx alpine ships with /etc/nginx/conf.d/default.conf listening on
      # port 80. The stack's app security group only accepts ingress from
      # the ALB SG on port 8080 (see terraform/stack/main.tf SG rules), so
      # we rewrite the listen directive at start. The sed runs in the
      # docker-entrypoint flow which then execs nginx normally.
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
    },
    {
      name      = "heartbeat"
      image     = "curlimages/curl:8.10.1"
      essential = false

      # Override curlimages/curl's default ENTRYPOINT (which is just curl)
      # so we can run a long-lived shell loop. Alpine sh + date + grep +
      # cut + curl are all in the image.
      entryPoint = ["/bin/sh", "-c"]
      command = [
        join(" ", [
          "while true; do",
          "AZ=$(curl -s --max-time 1 \"$${ECS_CONTAINER_METADATA_URI_V4}/task\" 2>/dev/null",
          "| grep -o '\"AvailabilityZone\":\"[^\"]*\"' | head -1 | cut -d'\"' -f4);",
          ": $${AZ:=unknown};",
          "if curl --connect-timeout 3 -fsS \"telnet://$RDS_HOST:$RDS_PORT\" </dev/null >/dev/null 2>&1;",
          "then echo \"$(date -Iseconds) AZ=$AZ HEARTBEAT OK rds-tcp-reachable\";",
          "else echo \"$(date -Iseconds) AZ=$AZ HEARTBEAT TIMEOUT rds-tcp-unreachable\";",
          "fi;",
          "sleep 5;",
          "done",
        ])
      ]

      environment = [
        { name = "RDS_HOST", value = local.rds_host },
        { name = "RDS_PORT", value = "5432" },
      ]

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.victim.name
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "heartbeat"
        }
      }
    }
  ])

  tags = {
    Scenario = "az-slowdown"
  }
}

resource "aws_ecs_service" "victim" {
  name            = local.victim_name
  cluster         = data.terraform_remote_state.stack.outputs.ecs_cluster_arn
  task_definition = aws_ecs_task_definition.victim.arn
  desired_count   = 4
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = data.terraform_remote_state.stack.outputs.private_subnet_ids
    security_groups  = [data.terraform_remote_state.stack.outputs.app_security_group_id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.victim.arn
    container_name   = "nginx"
    container_port   = var.container_port
  }

  # Fargate distributes tasks across the listed subnets automatically; no
  # placement_constraints / placement_strategy needed (those are EC2 only).

  health_check_grace_period_seconds = 30

  depends_on = [
    aws_lb_listener_rule.victim,
  ]

  tags = {
    Scenario = "az-slowdown"
  }
}

# ---------------------------------------------------------------------------
# Victim alarm — fires when FIS disrupts the AZ and the ALB starts marking
# cross-AZ targets unhealthy. Same operational shape as overlays 01 / 02:
# the description names the resource and the metric symptom but NOT the
# cause.
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
  evaluation_periods  = 2
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
    Scenario = "az-slowdown"
  }
}

# ---------------------------------------------------------------------------
# Production guard-rail alarm. Watches the LIVE MCP target group. If the
# FIS experiment accidentally degrades production (e.g. by knocking the
# RDS primary's AZ off the network in a way that propagates), this alarm
# trips and the FIS stop condition halts the experiment.
#
# Lives in the overlay so it's destroyed with the rest of the scenario.
# ---------------------------------------------------------------------------

resource "aws_cloudwatch_metric_alarm" "live_mcp_guard" {
  alarm_name = "${local.victim_name}-live-mcp-guard"

  alarm_description = "FIS safety guard. Trips if the live MCP TG goes unhealthy during the az-slowdown experiment; FIS stop condition references this alarm and halts the experiment when it fires."

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
    Scenario = "az-slowdown"
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

resource "aws_iam_role" "fis_az_disconnect" {
  name               = "${local.victim_name}-fis-role"
  assume_role_policy = data.aws_iam_policy_document.fis_assume.json
}

# AWS-managed policy covering the EC2/network actions FIS needs for
# `aws:network:disrupt-connectivity` (NACL create/modify/delete on the
# target subnet). If this policy name has drifted in the live IAM
# catalog, the apply will fail with a clear error and we can switch to
# the inline list below.
resource "aws_iam_role_policy_attachment" "fis_network_access" {
  role       = aws_iam_role.fis_az_disconnect.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSFaultInjectionSimulatorNetworkAccess"
}

resource "aws_fis_experiment_template" "az_disconnect" {
  description = "Disconnect ${data.aws_subnet.az_a.availability_zone} private subnet from other AZs for ${var.experiment_duration}; victim TG should lose its AZ-a targets."
  role_arn    = aws_iam_role.fis_az_disconnect.arn

  # Stop condition watches the LIVE MCP TG, not the victim TG. If the
  # experiment accidentally hits production, FIS halts; the victim alarm
  # IS the eval trigger and must be allowed to fire freely.
  stop_condition {
    source = "aws:cloudwatch:alarm"
    value  = aws_cloudwatch_metric_alarm.live_mcp_guard.arn
  }

  action {
    name        = "disrupt-az-a-connectivity"
    action_id   = "aws:network:disrupt-connectivity"
    description = "Block cross-AZ traffic to/from the AZ-a private subnet via NACL deny rules."

    parameter {
      # scope=all is a total subnet network blackhole — blocks all traffic
      # in and out of the AZ-a private subnet. scope=availability-zone
      # only blocks cross-AZ; that wasn't enough to fail ALB cross-AZ
      # health probes or push AZ-a logs into CloudWatch silence (probe
      # 2026-05-19 19:41 showed AZ-a kept logging OK throughout).
      key   = "scope"
      value = "all"
    }

    parameter {
      key   = "duration"
      value = var.experiment_duration
    }

    target {
      key   = "Subnets"
      value = "az-a-subnet"
    }
  }

  target {
    name           = "az-a-subnet"
    resource_type  = "aws:ec2:subnet"
    selection_mode = "ALL"
    resource_arns  = [data.aws_subnet.az_a.arn]
  }

  tags = {
    Name     = "${local.victim_name}-fis-az-disconnect"
    Scenario = "az-slowdown"
  }
}

# Triage outage corpus — scenario 04: ecs-task-stop (FIS chaos).
#
# AWS FIS injects `aws:ecs:stop-task` against the sidekick ECS service's
# tasks. ECS replaces the stopped tasks per desired_count; the replacement
# tasks slow-boot (sleep ${var.slow_boot_seconds}s before nginx exec), so
# the ALB target group sees a sustained UnHealthyHostCount > 0 window
# during recovery. The alarm fires, the agent is invoked, and the
# investigation runs while replacement tasks are still booting.
#
# Why FIS rather than an overlay-only stop:
#   The chaos shape — "tasks were stopped externally, service is now
#   recovering, root cause is not at the application layer" — is a real
#   capacity / availability scenario. Overlay misconfigurations test
#   permanent broken state; FIS chaos tests transient disruption +
#   recovery, which is a structurally different reasoning shape.
#
# Why the slow-boot sleep:
#   `aws:ecs:stop-task` is a single-shot action (no continuous-pressure
#   parameter). Without slow-boot, ECS replaces tasks in ~30-60s and the
#   UnHealthyHostCount window is too brief for the alarm to fire reliably
#   (period=60 + evaluation_periods=2 wants ~120s of sustained signal).
#   slow_boot_seconds=90 gives ~120s of unhealthy state per replacement
#   cycle.
#
# Sidekick model: nothing under terraform/stack/ is mutated. Reverts in a
# single `terraform destroy` (FIS experiment template, victim service,
# alarms, IAM roles).

locals {
  name_prefix = "${var.environment}-${var.project_name}"
  victim_name = "${local.name_prefix}-task-stop-victim"
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

# Live MCP target group — used as the production guard-rail alarm
# dimension. FIS stop condition watches this; if the experiment somehow
# degrades the live MCP service, FIS auto-halts.
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

  # Deregistration delay default is 300s; shorten so destroyed tasks don't
  # linger in `draining` across multiple eval invocations.
  deregistration_delay = 30

  tags = {
    Name     = "${local.victim_name}-tg"
    Scenario = "ecs-task-stop"
  }
}

resource "aws_lb_listener_rule" "victim" {
  listener_arn = data.aws_lb_listener.https.arn
  priority     = 80 # below scenarios 01 (50), 02 (60), 03 (70), above MCP (100)

  condition {
    path_pattern {
      values = ["/task-stop-victim", "/task-stop-victim/*"]
    }
  }

  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.victim.arn
  }
}

# ---------------------------------------------------------------------------
# Victim ECS service — multi-AZ Fargate, slow-boot nginx.
#
# The slow-boot pattern (sleep N seconds, then exec nginx) extends the
# UnHealthyHostCount window after every restart. On initial apply this
# means a slow warm-up, then steady-state healthy. After FIS stop-task,
# replacements slow-boot again — the unhealthy window the agent observes.
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

      # Slow-boot: print a marker line, sleep for the configured duration
      # so health checks fail against an empty port, then rewrite the
      # listen directive to the container_port and exec nginx normally.
      # The marker line is the load-bearing log signal — if the agent
      # queries the log group within the unhealthy window, it sees
      # "task starting (slow-boot)" lines from recently-launched
      # replacement tasks, confirming the service is in recovery.
      entryPoint = ["/bin/sh", "-c"]
      command = [
        join(" ", [
          "echo \"$(date -Iseconds) task starting (slow-boot, sleep ${var.slow_boot_seconds}s)\";",
          "sleep ${var.slow_boot_seconds};",
          "echo \"$(date -Iseconds) task slow-boot complete, starting nginx\";",
          "sed -i 's/listen[[:space:]]*80;/listen ${var.container_port};/g' /etc/nginx/conf.d/default.conf;",
          "exec /docker-entrypoint.sh nginx -g 'daemon off;'",
        ])
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
    Scenario = "ecs-task-stop"
  }
}

resource "aws_ecs_service" "victim" {
  name            = local.victim_name
  cluster         = data.terraform_remote_state.stack.outputs.ecs_cluster_arn
  task_definition = aws_ecs_task_definition.victim.arn
  desired_count   = 2
  launch_type     = "FARGATE"

  # Propagate service tags down to the launched tasks. FIS targets the
  # tasks by tag (Scenario=ecs-task-stop) — without propagation, tasks
  # would carry only the implicit aws:ecs:serviceName tag and the FIS
  # target filter wouldn't match cleanly.
  propagate_tags = "SERVICE"

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

  # Grace period must cover the slow-boot window (sleep N + nginx start +
  # 2 healthy_threshold × 15s interval). Otherwise ECS marks the task
  # unhealthy mid-slow-boot and replaces it, producing a churn loop on
  # apply rather than steady-state. slow_boot_seconds + 60s buffer.
  health_check_grace_period_seconds = var.slow_boot_seconds + 60

  depends_on = [
    aws_lb_listener_rule.victim,
  ]

  tags = {
    Scenario = "ecs-task-stop"
  }
}

# ---------------------------------------------------------------------------
# Victim alarm — fires when FIS stops tasks and the replacements are
# still slow-booting. Same shape as overlays 01/02/03: describes the
# metric symptom but not the cause.
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
    Scenario = "ecs-task-stop"
  }
}

# ---------------------------------------------------------------------------
# Production guard-rail alarm — same pattern as 03. Watches the LIVE MCP
# target group. If FIS accidentally degrades production, this alarm
# trips and the FIS stop condition halts the experiment.
# ---------------------------------------------------------------------------

resource "aws_cloudwatch_metric_alarm" "live_mcp_guard" {
  alarm_name = "${local.victim_name}-live-mcp-guard"

  alarm_description = "FIS safety guard. Trips if the live MCP TG goes unhealthy during the ecs-task-stop experiment; FIS stop condition references this alarm and halts the experiment when it fires."

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
    Scenario = "ecs-task-stop"
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

resource "aws_iam_role" "fis_ecs_stop_task" {
  name               = "${local.victim_name}-fis-role"
  assume_role_policy = data.aws_iam_policy_document.fis_assume.json
}

# AWS-managed policy covering ECS task stop. Verified live at scaffold
# time (2026-05-20) via `aws iam get-policy --policy-arn ...`.
resource "aws_iam_role_policy_attachment" "fis_ecs_access" {
  role       = aws_iam_role.fis_ecs_stop_task.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSFaultInjectionSimulatorECSAccess"
}

resource "aws_fis_experiment_template" "ecs_task_stop" {
  description = "Stop all tasks of the ${local.victim_name} ECS service. ECS will replace them; replacement tasks slow-boot for ${var.slow_boot_seconds}s, surfacing UnHealthyHostCount > 0 on the victim TG."
  role_arn    = aws_iam_role.fis_ecs_stop_task.arn

  # Stop condition watches the LIVE MCP TG, not the victim TG. The victim
  # alarm IS the eval trigger; the guard halts only on collateral damage
  # to production.
  stop_condition {
    source = "aws:cloudwatch:alarm"
    value  = aws_cloudwatch_metric_alarm.live_mcp_guard.arn
  }

  action {
    name        = "stop-victim-tasks"
    action_id   = "aws:ecs:stop-task"
    description = "Stop the matched ECS tasks. Single-shot; ECS reschedules per service desired_count."

    target {
      key   = "Tasks"
      value = "victim-tasks"
    }
  }

  target {
    name           = "victim-tasks"
    resource_type  = "aws:ecs:task"
    selection_mode = "ALL"

    # Tag-based selection. The service propagates its `Scenario` tag down
    # to launched tasks (propagate_tags = "SERVICE" above), so FIS can
    # filter the live task list by this tag without knowing dynamic ARNs.
    resource_tag {
      key   = "Scenario"
      value = "ecs-task-stop"
    }

    # Cluster + service scoping. AWS provider expects these as a map
    # argument (`parameters`), not nested blocks.
    parameters = {
      cluster = data.terraform_remote_state.stack.outputs.ecs_cluster_arn
      service = aws_ecs_service.victim.name
    }
  }

  tags = {
    Name     = "${local.victim_name}-fis-ecs-stop-task"
    Scenario = "ecs-task-stop"
  }
}

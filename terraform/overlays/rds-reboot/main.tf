# Triage outage corpus — scenario 06: rds-reboot (FIS dependency chaos).
#
# AWS FIS injects `aws:rds:reboot-db-instances` (with forceFailover=true)
# against the stack RDS instance. RDS fails over from the primary AZ to
# the standby AZ; during the ~60-120s window, all DB connections fail.
# The victim ECS service runs a Python HTTP server whose ALB health
# check endpoint (GET /) opens a TCP connection to RDS on every probe.
# When RDS is reachable: 200 OK. When RDS is rebooting: 503 with
# "DB unreachable: timeout" in the body and logs. UnHealthyHostCount
# rises on the victim TG once 2 consecutive ALB probes fail.
#
# Why this is the EBS pause-IO substitute (spec §3.4 drift):
#   Fargate has no user-visible EBS, and RDS-managed EBS isn't FIS-
#   targetable. The spec wanted a dependency-layer chaos surface, and
#   "RDS rebooting under the app" is the cleanest dependency analog
#   our stack supports. The diagnostic shape — "app can't reach its
#   database, app marks itself unhealthy, retries succeed once the
#   dep recovers" — is structurally the same family as EBS pause-IO
#   (a backing-store dependency goes away briefly).
#
# Why a custom Python health endpoint rather than nginx:
#   nginx doesn't know about RDS — it would keep returning 200 even
#   when the app's actual database dependency is broken. The agent
#   would see "tasks healthy, alarm misfiring." The Python /health
#   endpoint hands the agent a real signal: 503 with a DB-error
#   message in logs is unambiguous evidence of a dependency-layer
#   failure, distinct from any application or network shape.
#
# Sidekick model: nothing under terraform/stack/ is mutated. Reverts
# in a single `terraform destroy`. Verified pre-plan that the live
# MCP service does not depend on RDS (no RDS env vars or SG egress
# in `terraform/stack/mcp_server.tf`), so the reboot doesn't trip
# the production guard alarm.

locals {
  name_prefix = "${var.environment}-${var.project_name}"
  victim_name = "${local.name_prefix}-rds-victim"
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

data "aws_lb_target_group" "live_mcp" {
  name = "${local.name_prefix}-app-tg"
}

# The stack RDS instance — the FIS target. Stack output only carries
# the address/endpoint, so look up the ARN by identifier.
data "aws_db_instance" "stack_rds" {
  db_instance_identifier = "${local.name_prefix}-db"
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

  # Health check hits / on the Python HTTP server; the handler opens a
  # TCP connection to RDS and returns 200/503 accordingly. Two
  # consecutive 503s flip the target to unhealthy.
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
    Scenario = "rds-reboot"
  }
}

resource "aws_lb_listener_rule" "victim" {
  listener_arn = data.aws_lb_listener.https.arn
  priority     = 95 # below 01 (50), 02 (60), 03 (70), 04 (80), 05 (90); above MCP default (100)

  condition {
    path_pattern {
      values = ["/rds-victim", "/rds-victim/*"]
    }
  }

  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.victim.arn
  }
}

# ---------------------------------------------------------------------------
# Victim ECS service — Python HTTP server that checks RDS reachability
# on every health probe. Multi-AZ Fargate (2 tasks) so the ALB sees
# both targets transition to unhealthy together when RDS reboots.
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
      name      = "health-server"
      image     = "public.ecr.aws/docker/library/python:3.12-alpine"
      essential = true

      # Inline Python HTTP server. Every GET / opens a 3-second TCP
      # connection to RDS:5432; success → 200, failure → 503 with the
      # exception message in both the body and stdout (so the agent
      # can pick it up via logs_api_filter_log_events). The literal
      # text "DB unreachable" appears in logs during the disruption,
      # which is the load-bearing log evidence.
      entryPoint = ["/bin/sh", "-c"]
      command = [
        join("\n", [
          "cat > /tmp/health.py <<'PYEOF'",
          "import os, socket, sys, time",
          "from http.server import HTTPServer, BaseHTTPRequestHandler",
          "DB_HOST = os.environ.get('DB_HOST', 'localhost')",
          "DB_PORT = int(os.environ.get('DB_PORT', '5432'))",
          "# Sticky degraded mode: once we observe a DB failure, hold 503 for",
          "# DEGRADED_HOLD_SECS so the disruption window is long enough for",
          "# ALB's unhealthy_threshold + alarm evaluation + agent investigation",
          "# to all complete. RDS multi-AZ failovers produce only ~5-10s of",
          "# observable TCP-connect failure; the sticky window stretches that",
          "# to a realistic dependency-outage shape — also models real circuit-",
          "# breaker patterns where services hold degraded state through a",
          "# cool-off period rather than retrying every probe.",
          "DEGRADED_HOLD_SECS = 90",
          "_last_failure = 0.0",
          "_last_error = ''",
          "class H(BaseHTTPRequestHandler):",
          "    def log_message(self, *a): pass",
          "    def do_GET(self):",
          "        global _last_failure, _last_error",
          "        now = time.time()",
          "        # Sticky degraded window — keep returning 503 until cool-off.",
          "        if _last_failure and (now - _last_failure) < DEGRADED_HOLD_SECS:",
          "            self.send_response(503); self.end_headers()",
          "            msg = f'DB still unreachable (sticky degraded, last error: {_last_error})'",
          "            self.wfile.write(msg.encode())",
          "            print(f'{time.strftime(\"%FT%TZ\", time.gmtime())} {msg}', flush=True)",
          "            return",
          "        # Otherwise, fresh TCP-connect check.",
          "        try:",
          "            with socket.create_connection((DB_HOST, DB_PORT), timeout=3):",
          "                self.send_response(200); self.end_headers()",
          "                self.wfile.write(b'OK\\n')",
          "                print(f'{time.strftime(\"%FT%TZ\", time.gmtime())} DB heartbeat OK', flush=True)",
          "        except Exception as e:",
          "            _last_failure = now",
          "            _last_error = f'{type(e).__name__}: {e}'",
          "            self.send_response(503); self.end_headers()",
          "            msg = f'DB unreachable: {_last_error}'",
          "            self.wfile.write(msg.encode())",
          "            print(f'{time.strftime(\"%FT%TZ\", time.gmtime())} {msg}', flush=True)",
          "print(f'health-server starting; DB_HOST={DB_HOST}:{DB_PORT}; sticky_hold={DEGRADED_HOLD_SECS}s', flush=True)",
          "HTTPServer(('0.0.0.0', 8080), H).serve_forever()",
          "PYEOF",
          "exec python3 /tmp/health.py",
        ])
      ]

      portMappings = [
        { containerPort = var.container_port, protocol = "tcp" }
      ]

      environment = [
        { name = "DB_HOST", value = data.terraform_remote_state.stack.outputs.rds_address },
        { name = "DB_PORT", value = "5432" },
      ]

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.victim.name
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "health-server"
        }
      }
    }
  ])

  tags = {
    Scenario = "rds-reboot"
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
    container_name   = "health-server"
    container_port   = var.container_port
  }

  health_check_grace_period_seconds = 30

  depends_on = [
    aws_lb_listener_rule.victim,
  ]

  tags = {
    Scenario = "rds-reboot"
  }
}

# ---------------------------------------------------------------------------
# Victim alarm — fires when RDS is mid-reboot and the health endpoint
# starts returning 503.
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
    Scenario = "rds-reboot"
  }
}

# ---------------------------------------------------------------------------
# Production guard-rail alarm. The live MCP service does NOT depend on
# RDS (verified pre-plan via grep on terraform/stack/mcp_server.tf), so
# the reboot shouldn't affect it. The guard is still installed for the
# usual safety: if anything we missed triggers MCP unhealth, FIS halts.
# ---------------------------------------------------------------------------

resource "aws_cloudwatch_metric_alarm" "live_mcp_guard" {
  alarm_name = "${local.victim_name}-live-mcp-guard"

  alarm_description = "FIS safety guard. Trips if the live MCP TG goes unhealthy during the rds-reboot experiment; FIS stop condition references this alarm and halts the experiment when it fires."

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
    Scenario = "rds-reboot"
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

resource "aws_iam_role" "fis_rds_reboot" {
  name               = "${local.victim_name}-fis-role"
  assume_role_policy = data.aws_iam_policy_document.fis_assume.json
}

# AWS-managed policy covering RDS reboot/failover actions. Verified
# live at scaffold time (2026-05-20).
resource "aws_iam_role_policy_attachment" "fis_rds_access" {
  role       = aws_iam_role.fis_rds_reboot.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSFaultInjectionSimulatorRDSAccess"
}

resource "aws_fis_experiment_template" "rds_reboot" {
  description = "Reboot the stack RDS instance (forceFailover=${var.force_failover}) to surface dependency-layer failures in the victim service."
  role_arn    = aws_iam_role.fis_rds_reboot.arn

  stop_condition {
    source = "aws:cloudwatch:alarm"
    value  = aws_cloudwatch_metric_alarm.live_mcp_guard.arn
  }

  action {
    name        = "reboot-stack-rds"
    action_id   = "aws:rds:reboot-db-instances"
    description = "Reboot the stack RDS. forceFailover=${var.force_failover} extends the disruption window via Multi-AZ failover."

    parameter {
      key   = "forceFailover"
      value = tostring(var.force_failover)
    }

    target {
      key   = "DBInstances"
      value = "stack-rds"
    }
  }

  target {
    name           = "stack-rds"
    resource_type  = "aws:rds:db"
    selection_mode = "ALL"
    resource_arns  = [data.aws_db_instance.stack_rds.db_instance_arn]
  }

  tags = {
    Name     = "${local.victim_name}-fis-rds-reboot"
    Scenario = "rds-reboot"
  }
}

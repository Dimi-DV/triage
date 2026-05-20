# Triage outage corpus — scenario 08: container-oom-kill.
#
# Sidekick ECS task with a deliberate memory misconfiguration. The
# task definition pins the container's hard memory limit at 128 MB —
# enough for Python to start and bring up an HTTP server briefly, but
# not enough once a small leak script begins allocating 50 MB chunks.
# Container OOMs within ~10 seconds, ECS replaces the task, the
# replacement OOMs in turn — crashloop. The ALB sees targets that
# register briefly, return 200 for a window of a few seconds, then
# vanish before health checks can complete. UnHealthyHostCount > 0
# alarm fires.
#
# Per the spec — `runbook_status: by_design_none`. The agent must
# diagnose from AGENT.md general principles alone. Diagnostic chain
# the agent should walk without scaffolding:
#   - describe_target_health: targets unhealthy / not registered /
#     in `initial` state — flapping pattern.
#   - describe_task_definition: shows container `memory: 128` (hard
#     limit) plus a command that progressively allocates memory and
#     logs each step. The tight memory limit IS the misconfiguration.
#   - logs: lines like "allocated block 1/100, total mem=80MB" then
#     silence (the script gets OOM-killed mid-allocation; logs cut
#     off before the next print).
# Diagnosis: container memory limit is too low for the workload; the
# kernel OOM-kills the task in a loop.
#
# This complements scenario 04 ecs-task-stop (also capacity family):
# 04 = tasks were stopped externally, recovering; 08 = tasks are
# stopping themselves repeatedly because their config can't sustain
# steady-state.

locals {
  name_prefix = "${var.environment}-${var.project_name}"
  victim_name = "${local.name_prefix}-oom-victim"
}

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
# Target group + listener rule.
# ---------------------------------------------------------------------------

resource "aws_lb_target_group" "victim" {
  name        = "${local.victim_name}-tg"
  port        = var.container_port
  protocol    = "HTTP"
  vpc_id      = data.terraform_remote_state.stack.outputs.vpc_id
  target_type = "ip"

  health_check {
    enabled           = true
    port              = "traffic-port"
    protocol          = "HTTP"
    path              = "/"
    matcher           = "200"
    healthy_threshold = 2
    # ALB minimum unhealthy_threshold is 2. Pair with a tight 5s probe
    # interval — the HTTP server starts returning 503 at ~T=52s into
    # the leak script's run; 2-probe × 5s gets ALB to flip the target
    # to unhealthy by ~T=62s, leaving a ~30s unhealthy window before
    # the kernel OOM-kills the task at ~T=96s. Enough for the metric
    # to publish UnHealthyHostCount > 0 in a single 60s period.
    unhealthy_threshold = 2
    interval            = 5
    timeout             = 3
  }

  deregistration_delay = 30

  tags = {
    Name     = "${local.victim_name}-tg"
    Scenario = "container-oom-kill"
  }
}

resource "aws_lb_listener_rule" "victim" {
  listener_arn = data.aws_lb_listener.https.arn
  priority     = 75 # tucked between 03 (70) and 04 (80)

  condition {
    path_pattern {
      values = ["/oom-victim", "/oom-victim/*"]
    }
  }

  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.victim.arn
  }
}

# ---------------------------------------------------------------------------
# IAM + log group.
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

# ---------------------------------------------------------------------------
# Task definition. Task memory is 512 (Fargate minimum for 256 CPU);
# container memory is the deliberately-too-low hard limit. The kernel
# OOM-killer enforces the container limit.
# ---------------------------------------------------------------------------

resource "aws_ecs_task_definition" "victim" {
  family                   = local.victim_name
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = "256"
  memory                   = "512"
  execution_role_arn       = aws_iam_role.victim_task_exec.arn

  container_definitions = jsonencode([
    {
      name      = "oom-victim"
      image     = "public.ecr.aws/docker/library/python:3.12-alpine"
      essential = true

      # Hard memory limit — kernel OOM-killer enforces this.
      memory = var.container_memory_limit_mb

      # Inline Python: spin up an HTTP server in a background thread,
      # then progressively allocate 5 MB chunks every 4 seconds with
      # progress logs. Once mem exceeds the 503-threshold, the HTTP
      # server flips to returning 503 — so the ALB has a multi-probe
      # window to mark targets unhealthy BEFORE the kernel OOM-killer
      # ends the task. Without the early 503, the metric publishing
      # window misses the unhealthy state because cycling is too fast.
      # The progress logs are the load-bearing evidence; they cut off
      # mid-loop when the kernel kills the process.
      entryPoint = ["/bin/sh", "-c"]
      command = [
        join("\n", [
          "cat > /tmp/oom.py <<'PYEOF'",
          "import os, threading, time, resource",
          "from http.server import HTTPServer, BaseHTTPRequestHandler",
          "DEGRADED_AT_MB = 80",
          "def mem_mb():",
          "    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024",
          "class H(BaseHTTPRequestHandler):",
          "    def log_message(self, *a): pass",
          "    def do_GET(self):",
          "        try:",
          "            m = mem_mb()",
          "            if m > DEGRADED_AT_MB:",
          "                self.send_response(503); self.end_headers()",
          "                self.wfile.write(f'degraded mem={m:.0f}MB > {DEGRADED_AT_MB}MB threshold (approaching limit)\\n'.encode())",
          "            else:",
          "                self.send_response(200); self.end_headers()",
          "                self.wfile.write(f'OK mem={m:.0f}MB\\n'.encode())",
          "        except Exception:",
          "            pass",
          "def serve(): HTTPServer(('0.0.0.0', 8080), H).serve_forever()",
          "threading.Thread(target=serve, daemon=True).start()",
          "print(f'{time.strftime(\"%FT%TZ\", time.gmtime())} oom-victim starting; initial mem={mem_mb():.0f}MB; container_memory_limit={os.environ.get(\"MEMORY_LIMIT_MB\", \"?\")}MB; degraded_at={DEGRADED_AT_MB}MB', flush=True)",
          "allocated = []",
          "for i in range(40):",
          "    block = bytearray(5 * 1024 * 1024)",
          "    allocated.append(block)",
          "    print(f'{time.strftime(\"%FT%TZ\", time.gmtime())} allocated block {i+1}/40 (5MB), total mem={mem_mb():.0f}MB', flush=True)",
          "    time.sleep(4)",
          "print('finished allocation loop (should not happen at this memory limit)', flush=True)",
          "PYEOF",
          "exec python3 /tmp/oom.py",
        ])
      ]

      portMappings = [
        { containerPort = var.container_port, protocol = "tcp" }
      ]

      environment = [
        # Echoes the configured limit back into logs at startup so the
        # diagnosis can quote it cleanly alongside the observed allocs.
        { name = "MEMORY_LIMIT_MB", value = tostring(var.container_memory_limit_mb) },
      ]

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.victim.name
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "oom-victim"
        }
      }
    }
  ])

  tags = {
    Scenario = "container-oom-kill"
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
    container_name   = "oom-victim"
    container_port   = var.container_port
  }

  # No grace period — ALB starts probing immediately; we WANT health
  # check failures to surface quickly when the container OOM-kills.
  health_check_grace_period_seconds = 0

  depends_on = [
    aws_lb_listener_rule.victim,
  ]

  tags = {
    Scenario = "container-oom-kill"
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
    Scenario = "container-oom-kill"
  }
}

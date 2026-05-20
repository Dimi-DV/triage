# Triage outage corpus — scenario 09: secret-value-corrupted.
#
# Sidekick ECS service whose container expects a CONFIG environment
# variable to be valid JSON with specific keys. The CONFIG env var is
# sourced from a Secrets Manager secret via the task definition's
# `secrets[].valueFrom` field — the ECS agent reads the secret at
# task startup using the EXECUTION role's IAM permissions and injects
# the resolved value into the container's environment.
#
# This overlay puts garbage into the secret. The container starts, sees
# CONFIG=<garbage>, json.loads() raises JSONDecodeError, the parse
# failure is cached and returned as 503 on every health probe.
# UnHealthyHostCount > 0 fires.
#
# How this differs from 02 missing-env-var:
#   02 = the env var name is absent from the container `environment`
#        block; the container script sees $REQUIRED_API_KEY as empty.
#   09 = the env var IS present (with `valueFrom`), the container sees
#        a NON-empty value, but the value is wrong. The agent must
#        trace the indirection (env-var → Secrets Manager) from the
#        task definition's `secrets[].valueFrom` field to identify
#        the cause.
#
# Per spec — `runbook_status: by_design_none`. The agent has no
# scaffolding; AGENT.md general principles + the task-definition
# reading discipline must surface the diagnosis.
#
# Importantly: the agent's MCP task role does NOT have
# secretsmanager:GetSecretValue permission for arbitrary secrets, so
# the agent cannot (and should not) read the secret value directly to
# verify it's bad. Correct diagnosis is "value sourced from secret X
# fails to parse — investigate the secret's current value via console
# or CLI" — least-privilege agent design.

locals {
  name_prefix = "${var.environment}-${var.project_name}"
  victim_name = "${local.name_prefix}-secret-victim"
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
# Secrets Manager secret + initial garbage value.
# ---------------------------------------------------------------------------

resource "aws_secretsmanager_secret" "config" {
  name                    = "${local.victim_name}-config"
  description             = "Sidekick app config — deliberately set to a JSON-invalid value to surface a Secrets-Manager-sourced env-var failure."
  recovery_window_in_days = 0 # destroy immediately, no soft-delete

  tags = {
    Scenario = "secret-value-corrupted"
  }
}

resource "aws_secretsmanager_secret_version" "config_v1" {
  secret_id     = aws_secretsmanager_secret.config.id
  secret_string = var.corrupted_secret_value
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
    Scenario = "secret-value-corrupted"
  }
}

resource "aws_lb_listener_rule" "victim" {
  listener_arn = data.aws_lb_listener.https.arn
  priority     = 65 # tucked between 02 (60) and 03 (70)

  condition {
    path_pattern {
      values = ["/secret-victim", "/secret-victim/*"]
    }
  }

  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.victim.arn
  }
}

# ---------------------------------------------------------------------------
# IAM. The execution role needs secretsmanager:GetSecretValue on the
# specific secret so ECS can resolve the `valueFrom` at task startup
# and inject it as an env var into the container.
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

data "aws_iam_policy_document" "exec_secrets_read" {
  statement {
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [aws_secretsmanager_secret.config.arn]
  }
}

resource "aws_iam_role_policy" "victim_task_exec_secrets" {
  name   = "${local.victim_name}-task-exec-secrets"
  role   = aws_iam_role.victim_task_exec.id
  policy = data.aws_iam_policy_document.exec_secrets_read.json
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

  container_definitions = jsonencode([
    {
      name      = "secret-victim"
      image     = "public.ecr.aws/docker/library/python:3.12-alpine"
      essential = true

      entryPoint = ["/bin/sh", "-c"]
      command = [
        join("\n", [
          "cat > /tmp/health.py <<'PYEOF'",
          "import json, os, time",
          "from http.server import HTTPServer, BaseHTTPRequestHandler",
          "CONFIG = os.environ.get('CONFIG', '')",
          "PARSE_OK = False",
          "PARSE_ERROR = ''",
          "try:",
          "    parsed = json.loads(CONFIG)",
          "    if not isinstance(parsed, dict) or 'api_key' not in parsed:",
          "        raise ValueError(f'config missing required key api_key (got: {type(parsed).__name__})')",
          "    PARSE_OK = True",
          "    print(f'{time.strftime(\"%FT%TZ\", time.gmtime())} CONFIG parsed OK; keys={list(parsed.keys())}', flush=True)",
          "except Exception as e:",
          "    PARSE_ERROR = f'{type(e).__name__}: {e}'",
          "    print(f'{time.strftime(\"%FT%TZ\", time.gmtime())} CONFIG parse FAILED: {PARSE_ERROR}; raw_length={len(CONFIG)}', flush=True)",
          "class H(BaseHTTPRequestHandler):",
          "    def log_message(self, *a): pass",
          "    def do_GET(self):",
          "        if PARSE_OK:",
          "            self.send_response(200); self.end_headers()",
          "            self.wfile.write(b'OK\\n')",
          "        else:",
          "            self.send_response(503); self.end_headers()",
          "            self.wfile.write(f'CONFIG parse failed: {PARSE_ERROR}\\n'.encode())",
          "print(f'secret-victim health server starting on 8080; PARSE_OK={PARSE_OK}', flush=True)",
          "HTTPServer(('0.0.0.0', 8080), H).serve_forever()",
          "PYEOF",
          "exec python3 /tmp/health.py",
        ])
      ]

      portMappings = [
        { containerPort = var.container_port, protocol = "tcp" }
      ]

      # The CONFIG env var is sourced from the Secrets Manager secret
      # via `secrets[]`. ECS's container agent resolves the valueFrom
      # at task startup (using the execution role's IAM perms) and
      # injects the secret value as a regular environment variable.
      # The container code sees CONFIG="<the secret value>".
      secrets = [
        {
          name      = "CONFIG"
          valueFrom = aws_secretsmanager_secret.config.arn
        },
      ]

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.victim.name
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "secret-victim"
        }
      }
    }
  ])

  tags = {
    Scenario = "secret-value-corrupted"
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
    container_name   = "secret-victim"
    container_port   = var.container_port
  }

  health_check_grace_period_seconds = 30

  depends_on = [
    aws_lb_listener_rule.victim,
  ]

  tags = {
    Scenario = "secret-value-corrupted"
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
    Scenario = "secret-value-corrupted"
  }
}

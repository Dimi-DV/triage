# Triage — production Multi-AZ stack root module.
#
# Day 32 afternoon scope:
#   - VPC + IGW + Multi-AZ public/private subnets
#   - One NAT gateway per AZ (preserves AZ isolation under NAT failure)
#   - Multi-AZ RDS Postgres with empty app SG placeholder
#   - Route 53 hosted zone + ACM cert (DNS-validated)
#   - Audit S3 bucket with Object Lock
#
# Day 33 morning scope:
#   - ALB (internet-facing) + HTTPS listener + HTTP→HTTPS redirect
#   - WAF v2 with AWSManagedRulesCommonRuleSet, REGIONAL scope, native block
#   - Route 53 A records for apex + www aliased to the ALB
#   - First ingress rule on the empty app SG (ALB→app on var.app_port)
#   - ECS cluster with Container Insights (task definition is Day 34)
#
# Fargate observability translation: v3 spec line 167 says "CloudWatch agent
# installed via user data." Fargate has no user data — the equivalent is
# Container Insights at the cluster (this PR) + awslogs driver in the Day 34
# task definition.
#
# Dev-mode knobs flagged inline. Production flips:
#   - Object Lock: GOVERNANCE 1-day → COMPLIANCE 7-year
#   - RDS: skip_final_snapshot true → false, deletion_protection false → true,
#          backup_retention_period 1 → ≥7, apply_immediately true → false

# ---------------------------------------------------------------------------
# Data sources
# ---------------------------------------------------------------------------

data "aws_caller_identity" "current" {}

# ---------------------------------------------------------------------------
# Locals
# ---------------------------------------------------------------------------

locals {
  name_prefix = "${var.environment}-${var.project_name}"
}

# ---------------------------------------------------------------------------
# VPC + Internet Gateway
# ---------------------------------------------------------------------------

resource "aws_vpc" "main" {
  cidr_block           = var.vpc_cidr
  enable_dns_hostnames = true
  enable_dns_support   = true

  tags = {
    Name = "${local.name_prefix}-vpc"
  }
}

resource "aws_internet_gateway" "main" {
  vpc_id = aws_vpc.main.id

  tags = {
    Name = "${local.name_prefix}-igw"
  }
}

# ---------------------------------------------------------------------------
# Subnets — one public + one private per AZ
# ---------------------------------------------------------------------------

resource "aws_subnet" "public" {
  count = length(var.availability_zones)

  vpc_id                  = aws_vpc.main.id
  cidr_block              = cidrsubnet(var.vpc_cidr, 8, count.index)
  availability_zone       = var.availability_zones[count.index]
  map_public_ip_on_launch = true

  tags = {
    Name = "${local.name_prefix}-public-${var.availability_zones[count.index]}"
    Tier = "public"
  }
}

resource "aws_subnet" "private" {
  count = length(var.availability_zones)

  vpc_id            = aws_vpc.main.id
  cidr_block        = cidrsubnet(var.vpc_cidr, 8, count.index + 10)
  availability_zone = var.availability_zones[count.index]

  tags = {
    Name = "${local.name_prefix}-private-${var.availability_zones[count.index]}"
    Tier = "private"
  }
}

# ---------------------------------------------------------------------------
# NAT gateways — one per AZ
# ---------------------------------------------------------------------------

resource "aws_eip" "nat" {
  count = length(var.availability_zones)

  domain = "vpc"

  tags = {
    Name = "${local.name_prefix}-nat-eip-${var.availability_zones[count.index]}"
  }
}

resource "aws_nat_gateway" "main" {
  count = length(var.availability_zones)

  allocation_id = aws_eip.nat[count.index].id
  subnet_id     = aws_subnet.public[count.index].id

  tags = {
    Name = "${local.name_prefix}-nat-${var.availability_zones[count.index]}"
  }

  depends_on = [aws_internet_gateway.main]
}

# ---------------------------------------------------------------------------
# Route tables
# ---------------------------------------------------------------------------

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.main.id
  }

  tags = {
    Name = "${local.name_prefix}-public-rt"
  }
}

resource "aws_route_table_association" "public" {
  count = length(var.availability_zones)

  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public.id
}

# One private route table per AZ — each routes 0.0.0.0/0 through its own AZ's
# NAT. Per-AZ NAT preserves AZ isolation: if one AZ's NAT fails, the other AZ
# stays online (the FIS AZ-slowdown scenario depends on this).
resource "aws_route_table" "private" {
  count = length(var.availability_zones)

  vpc_id = aws_vpc.main.id

  route {
    cidr_block     = "0.0.0.0/0"
    nat_gateway_id = aws_nat_gateway.main[count.index].id
  }

  tags = {
    Name = "${local.name_prefix}-private-rt-${var.availability_zones[count.index]}"
  }
}

resource "aws_route_table_association" "private" {
  count = length(var.availability_zones)

  subnet_id      = aws_subnet.private[count.index].id
  route_table_id = aws_route_table.private[count.index].id
}

# ---------------------------------------------------------------------------
# Security groups
# ---------------------------------------------------------------------------

# Application tier SG. Empty by design — Day 33 attaches ALB→app rules and the
# ECS task definition references this SG. Created now so the RDS SG can ingress
# from a stable referenced_security_group_id instead of from the VPC CIDR.
resource "aws_security_group" "app" {
  name        = "${local.name_prefix}-app-sg"
  description = "ECS task / app tier"
  vpc_id      = aws_vpc.main.id

  tags = {
    Name = "${local.name_prefix}-app-sg"
  }
}

resource "aws_security_group" "rds" {
  name        = "${local.name_prefix}-rds-sg"
  description = "Postgres ingress from the app tier"
  vpc_id      = aws_vpc.main.id

  tags = {
    Name = "${local.name_prefix}-rds-sg"
  }
}

resource "aws_vpc_security_group_ingress_rule" "rds_from_app" {
  security_group_id            = aws_security_group.rds.id
  referenced_security_group_id = aws_security_group.app.id
  ip_protocol                  = "tcp"
  from_port                    = 5432
  to_port                      = 5432
  description                  = "Postgres from app tier SG"
}

# ALB SG — public-facing edge.
resource "aws_security_group" "alb" {
  name        = "${local.name_prefix}-alb-sg"
  description = "Public-facing ALB ingress"
  vpc_id      = aws_vpc.main.id

  tags = {
    Name = "${local.name_prefix}-alb-sg"
  }
}

resource "aws_vpc_security_group_ingress_rule" "alb_https" {
  security_group_id = aws_security_group.alb.id
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
  description       = "HTTPS from the internet"
}

resource "aws_vpc_security_group_ingress_rule" "alb_http" {
  security_group_id = aws_security_group.alb.id
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "tcp"
  from_port         = 80
  to_port           = 80
  description       = "HTTP from the internet (ALB listener redirects to 443)"
}

# First rule on the Day 32 empty app SG.
resource "aws_vpc_security_group_ingress_rule" "app_from_alb" {
  security_group_id            = aws_security_group.app.id
  referenced_security_group_id = aws_security_group.alb.id
  ip_protocol                  = "tcp"
  from_port                    = var.app_port
  to_port                      = var.app_port
  description                  = "App traffic from the ALB"
}

# ---------------------------------------------------------------------------
# RDS — Postgres, Multi-AZ
# ---------------------------------------------------------------------------

resource "aws_db_subnet_group" "main" {
  name       = "${local.name_prefix}-db-subnet-group"
  subnet_ids = aws_subnet.private[*].id

  tags = {
    Name = "${local.name_prefix}-db-subnet-group"
  }
}

resource "aws_db_instance" "main" {
  identifier             = "${local.name_prefix}-db"
  engine                 = "postgres"
  engine_version         = var.rds_engine_version
  instance_class         = var.db_instance_class
  allocated_storage      = 20
  storage_type           = "gp3"
  storage_encrypted      = true
  username               = "triage"
  password               = var.db_password
  db_subnet_group_name   = aws_db_subnet_group.main.name
  vpc_security_group_ids = [aws_security_group.rds.id]
  multi_az               = true
  publicly_accessible    = false

  # Dev knobs. Production flips: skip_final_snapshot=false,
  # deletion_protection=true, backup_retention_period >= 7,
  # apply_immediately=false.
  skip_final_snapshot     = true
  deletion_protection     = false
  backup_retention_period = 1
  apply_immediately       = true

  tags = {
    Name = "${local.name_prefix}-db"
  }
}

# ---------------------------------------------------------------------------
# Route 53 hosted zone
# ---------------------------------------------------------------------------

# Zone for the apex domain. The registrar must delegate to AWS by setting NS
# records to aws_route53_zone.main.name_servers (see outputs.tf). ACM
# validation will hang until delegation is complete.
resource "aws_route53_zone" "main" {
  name = var.domain_name

  tags = {
    Name = "${local.name_prefix}-zone"
  }
}

# A records for apex + www, aliased to the ALB. The ALB resource is defined
# below; Terraform resolves the dependency via the DAG, file order is fine.
resource "aws_route53_record" "apex_a" {
  zone_id = aws_route53_zone.main.zone_id
  name    = var.domain_name
  type    = "A"

  alias {
    name                   = aws_lb.main.dns_name
    zone_id                = aws_lb.main.zone_id
    evaluate_target_health = true
  }
}

resource "aws_route53_record" "www_a" {
  zone_id = aws_route53_zone.main.zone_id
  name    = "www.${var.domain_name}"
  type    = "A"

  alias {
    name                   = aws_lb.main.dns_name
    zone_id                = aws_lb.main.zone_id
    evaluate_target_health = true
  }
}

# ---------------------------------------------------------------------------
# ACM certificate — DNS-validated
# ---------------------------------------------------------------------------

resource "aws_acm_certificate" "main" {
  domain_name               = var.domain_name
  subject_alternative_names = ["www.${var.domain_name}"]
  validation_method         = "DNS"

  lifecycle {
    create_before_destroy = true
  }

  tags = {
    Name = "${local.name_prefix}-cert"
  }
}

locals {
  # Static keys for the cert validation records — domain_validation_options is
  # known-after-apply, so deriving for_each keys from it breaks terraform import
  # and -target. We know the cert's subjects (apex + www) at plan time; key the
  # for_each on those and look up the apply-time validation values by domain.
  acm_validation_domains = toset([var.domain_name, "www.${var.domain_name}"])
}

resource "aws_route53_record" "acm_validation" {
  for_each = local.acm_validation_domains

  zone_id         = aws_route53_zone.main.zone_id
  name            = one([for dvo in aws_acm_certificate.main.domain_validation_options : dvo.resource_record_name if dvo.domain_name == each.value])
  type            = one([for dvo in aws_acm_certificate.main.domain_validation_options : dvo.resource_record_type if dvo.domain_name == each.value])
  records         = [one([for dvo in aws_acm_certificate.main.domain_validation_options : dvo.resource_record_value if dvo.domain_name == each.value])]
  ttl             = 60
  allow_overwrite = true
}

# Blocks apply until ACM observes the validation CNAMEs. Requires registrar NS
# delegation to be in place first; expect 5–30 min once delegation propagates.
resource "aws_acm_certificate_validation" "main" {
  certificate_arn         = aws_acm_certificate.main.arn
  validation_record_fqdns = [for r in aws_route53_record.acm_validation : r.fqdn]
}

# ---------------------------------------------------------------------------
# Audit S3 bucket — Object Lock, append-only journal
# ---------------------------------------------------------------------------

# Object Lock must be enabled at bucket creation; it cannot be added later.
# Dev mode: GOVERNANCE + 1-day retention so portfolio teardown is possible.
# Production: COMPLIANCE + 7-year retention (no bypass, even by root).
resource "aws_s3_bucket" "audit" {
  bucket              = "${local.name_prefix}-audit-${data.aws_caller_identity.current.account_id}"
  object_lock_enabled = true

  tags = {
    Name = "${local.name_prefix}-audit"
  }
}

resource "aws_s3_bucket_versioning" "audit" {
  bucket = aws_s3_bucket.audit.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "audit" {
  bucket = aws_s3_bucket.audit.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "audit" {
  bucket = aws_s3_bucket.audit.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_object_lock_configuration" "audit" {
  bucket = aws_s3_bucket.audit.id

  rule {
    default_retention {
      mode = "GOVERNANCE"
      days = 1
    }
  }

  depends_on = [aws_s3_bucket_versioning.audit]
}

# ---------------------------------------------------------------------------
# Application Load Balancer
# ---------------------------------------------------------------------------

resource "aws_lb" "main" {
  name               = "${local.name_prefix}-alb"
  internal           = false
  load_balancer_type = "application"
  security_groups    = [aws_security_group.alb.id]
  subnets            = aws_subnet.public[*].id

  # Dev: deletion protection off so terraform destroy works. Production: true.
  enable_deletion_protection = false

  tags = {
    Name = "${local.name_prefix}-alb"
  }
}

# target_type = "ip" is required for Fargate (awsvpc network mode).
# Day 34 attaches the ECS service to this target group.
resource "aws_lb_target_group" "app" {
  name        = "${local.name_prefix}-app-tg"
  port        = var.app_port
  protocol    = "HTTP"
  vpc_id      = aws_vpc.main.id
  target_type = "ip"

  # Health-check the MCP server's /health endpoint (added Day 34 afternoon).
  # The MCP app itself serves only /mcp/*; /health is mounted by __main__.py
  # outside the auth middleware so the ALB probe never carries a Bearer token.
  health_check {
    path                = "/health"
    matcher             = "200"
    healthy_threshold   = 2
    unhealthy_threshold = 3
    interval            = 30
    timeout             = 5
  }

  tags = {
    Name = "${local.name_prefix}-app-tg"
  }
}

resource "aws_lb_listener" "https" {
  load_balancer_arn = aws_lb.main.arn
  port              = 443
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  certificate_arn   = aws_acm_certificate_validation.main.certificate_arn

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.app.arn
  }
}

resource "aws_lb_listener" "http_redirect" {
  load_balancer_arn = aws_lb.main.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type = "redirect"

    redirect {
      port        = "443"
      protocol    = "HTTPS"
      status_code = "HTTP_301"
    }
  }
}

# ---------------------------------------------------------------------------
# WAF v2 — AWS Managed Common Rule Set, REGIONAL scope, native block
# ---------------------------------------------------------------------------

resource "aws_wafv2_web_acl" "main" {
  name        = "${local.name_prefix}-waf"
  description = "Edge WAF — AWS Managed Common Rule Set"
  scope       = "REGIONAL"

  default_action {
    allow {}
  }

  rule {
    name     = "AWSManagedRulesCommonRuleSet"
    priority = 0

    override_action {
      none {}
    }

    statement {
      managed_rule_group_statement {
        name        = "AWSManagedRulesCommonRuleSet"
        vendor_name = "AWS"
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      sampled_requests_enabled   = true
      metric_name                = "${local.name_prefix}-waf-common"
    }
  }

  visibility_config {
    cloudwatch_metrics_enabled = true
    sampled_requests_enabled   = true
    metric_name                = "${local.name_prefix}-waf"
  }

  tags = {
    Name = "${local.name_prefix}-waf"
  }
}

resource "aws_wafv2_web_acl_association" "main" {
  resource_arn = aws_lb.main.arn
  web_acl_arn  = aws_wafv2_web_acl.main.arn
}

# ---------------------------------------------------------------------------
# ECS cluster — Container Insights enabled (task definition is Day 34)
# ---------------------------------------------------------------------------

resource "aws_ecs_cluster" "main" {
  name = "${local.name_prefix}-cluster"

  setting {
    name  = "containerInsights"
    value = "enabled"
  }

  tags = {
    Name = "${local.name_prefix}-cluster"
  }
}

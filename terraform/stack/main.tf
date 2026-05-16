# Triage — production Multi-AZ stack root module.
#
# Day 32 afternoon scope:
#   - VPC + IGW + Multi-AZ public/private subnets
#   - One NAT gateway per AZ (preserves AZ isolation under NAT failure)
#   - Multi-AZ RDS Postgres with empty app SG placeholder
#   - Route 53 hosted zone + ACM cert (DNS-validated)
#   - Audit S3 bucket with Object Lock
#
# Day 33 morning adds: ALB + HTTPS listener + WAF + CloudWatch agent +
# Route 53 A/AAAA records pointing the apex/www at the ALB.
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

# A/AAAA records for the apex and www are added on Day 33 once the ALB exists.

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

resource "aws_route53_record" "acm_validation" {
  for_each = {
    for dvo in aws_acm_certificate.main.domain_validation_options : dvo.domain_name => {
      name   = dvo.resource_record_name
      record = dvo.resource_record_value
      type   = dvo.resource_record_type
    }
  }

  zone_id         = aws_route53_zone.main.zone_id
  name            = each.value.name
  type            = each.value.type
  records         = [each.value.record]
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

# Example tfvars for terraform/stack — copy to terraform.tfvars and edit.
# Real terraform.tfvars is gitignored (it holds secrets); this file is the
# canonical reference for what must be supplied.
#
# Usage:
#   cp example.tfvars terraform.tfvars
#   $EDITOR terraform.tfvars
#   make plan && make apply
#
# Alternatively, export TF_VAR_<name> in your shell instead of writing tfvars.

# Apex domain for the ACM cert + Route 53 zone. You must own this at a
# registrar that lets you delegate NS records to AWS.
# ACM DNS validation will hang until NS delegation propagates (5–30 min).
domain_name = "triage.example.com"

# Master password for the RDS Postgres instance. Strong, unique, and not
# reused. Migrate to random_password + Secrets Manager when convenient
# (see variables.tf TODO).
db_password = "REPLACE_WITH_STRONG_PASSWORD" # pragma: allowlist secret

# Optional overrides — uncomment to change defaults (see variables.tf):
# aws_region         = "us-east-1"
# environment        = "dev"
# project_name       = "triage"
# vpc_cidr           = "10.0.0.0/16"
# availability_zones = ["us-east-1a", "us-east-1b"]
# db_instance_class  = "db.t4g.micro"
# rds_engine_version = "16.4"
# app_port           = 8080

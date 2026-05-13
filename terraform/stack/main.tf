# Triage — production stack root module
#
# Fill in Day 32–33 as you build out:
#   - VPC (10.0.0.0/16, Multi-AZ public/private subnets)
#   - NAT gateways (Multi-AZ)
#   - RDS Multi-AZ
#   - ECS Fargate cluster
#   - ALB + ACM cert + Route 53
#   - WAF
#   - Audit S3 bucket with Object Lock
#   - CloudWatch + AgentCore observability wiring
#
# Currently empty so `terraform validate` passes.

# Locals shared across resources
locals {
  common_tags = {
    Project     = var.project_name
    Environment = var.environment
  }
}

output "vpc_id" {
  description = "VPC ID"
  value       = aws_vpc.main.id
}

output "public_subnet_ids" {
  description = "Public subnet IDs (one per AZ, NAT gateways live here)"
  value       = aws_subnet.public[*].id
}

output "private_subnet_ids" {
  description = "Private subnet IDs (one per AZ, ECS tasks and RDS live here)"
  value       = aws_subnet.private[*].id
}

output "app_security_group_id" {
  description = "Application tier SG — Day 33 attaches ALB→app ingress rules here"
  value       = aws_security_group.app.id
}

output "rds_endpoint" {
  description = "RDS Postgres endpoint (host:port)"
  value       = aws_db_instance.main.endpoint
}

output "rds_address" {
  description = "RDS Postgres hostname (no port)"
  value       = aws_db_instance.main.address
}

output "audit_bucket_name" {
  description = "Audit S3 bucket name (Object Lock enabled). CLAUDE.md commands table substitutes this for <FILL>."
  value       = aws_s3_bucket.audit.id
}

output "acm_certificate_arn" {
  description = "ACM certificate ARN (post-validation)"
  value       = aws_acm_certificate_validation.main.certificate_arn
}

output "route53_zone_id" {
  description = "Route 53 hosted zone ID"
  value       = aws_route53_zone.main.zone_id
}

output "route53_name_servers" {
  description = "Route 53 NS records — set these at the registrar to delegate the zone. ACM validation hangs until delegation propagates."
  value       = aws_route53_zone.main.name_servers
}

output "alb_dns_name" {
  description = "ALB DNS name — apex + www A records alias to this"
  value       = aws_lb.main.dns_name
}

output "alb_arn" {
  description = "ALB ARN — WAF web ACL associates to this"
  value       = aws_lb.main.arn
}

output "alb_zone_id" {
  description = "ALB canonical hosted zone ID (used by Route 53 alias records)"
  value       = aws_lb.main.zone_id
}

output "ecs_cluster_name" {
  description = "ECS cluster name (Day 34 service references this)"
  value       = aws_ecs_cluster.main.name
}

output "ecs_cluster_arn" {
  description = "ECS cluster ARN"
  value       = aws_ecs_cluster.main.arn
}

output "waf_web_acl_arn" {
  description = "WAF v2 web ACL ARN (associated to the ALB)"
  value       = aws_wafv2_web_acl.main.arn
}

# ---------------------------------------------------------------------------
# Day 34 afternoon — MCP server outputs
# ---------------------------------------------------------------------------

output "mcp_server_repository_url" {
  description = "ECR repository URL for the MCP server container image"
  value       = aws_ecr_repository.mcp_server.repository_url
}

output "mcp_server_log_group_name" {
  description = "CloudWatch log group for the MCP server ECS task"
  value       = aws_cloudwatch_log_group.mcp_server.name
}

output "mcp_server_service_name" {
  description = "ECS service name for the MCP server (use with force-new-deployment)"
  value       = aws_ecs_service.mcp_server.name
}

output "mcp_endpoint_url" {
  description = "Externally addressable Streamable HTTP endpoint for the MCP server"
  value       = "https://${var.domain_name}/mcp"
}

output "slack_bot_token_secret_arn" {
  description = "ARN of the Slack bot-token secret (value populated manually post-apply)"
  value       = aws_secretsmanager_secret.slack_bot_token.arn
}

output "slack_bot_token_secret_id" {
  description = "Secret name used as TRIAGE_SLACK_SECRET_ID by the MCP task and agent runtime"
  value       = aws_secretsmanager_secret.slack_bot_token.name
}

# ---------------------------------------------------------------------------
# Day 34 afternoon — alarm path + agent runtime outputs
# ---------------------------------------------------------------------------

output "alarms_sns_topic_arn" {
  description = "SNS topic ARN that CloudWatch alarms publish to (Lambda subscribed)"
  value       = aws_sns_topic.alarms.arn
}

output "alarm_bridge_lambda_arn" {
  description = "Lambda ARN for the SNS → AgentCore Runtime bridge"
  value       = aws_lambda_function.alarm_bridge.arn
}

output "alarm_bridge_dlq_url" {
  description = "DLQ for alarm-bridge failures"
  value       = aws_sqs_queue.alarm_bridge_dlq.url
}

output "agent_runtime_role_arn" {
  description = "IAM role AgentCore Runtime assumes when it starts the agent container"
  value       = aws_iam_role.agent_runtime.arn
}

output "agent_repository_url" {
  description = "ECR repository URL for the agent runtime container image"
  value       = aws_ecr_repository.agent.repository_url
}

output "agentcore_runtime_arn_parameter" {
  description = "SSM Parameter Store name where scripts/provision_agentcore.py writes the Runtime ARN"
  value       = aws_ssm_parameter.runtime_arn.name
}

output "demo_alarm_name" {
  description = "CloudWatch alarm used for the hello-world manual trigger"
  value       = aws_cloudwatch_metric_alarm.demo.alarm_name
}

output "agentcore_issuer_parameter" {
  description = "SSM Parameter Store name where provision_agentcore.py writes the AgentCore Identity issuer URL. The MCP task pulls this via the `secrets` block."
  value       = aws_ssm_parameter.agentcore_issuer.name
}

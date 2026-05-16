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

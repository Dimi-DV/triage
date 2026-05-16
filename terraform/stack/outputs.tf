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

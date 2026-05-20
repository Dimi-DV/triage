output "victim_tg_arn" {
  description = "Victim target group ARN"
  value       = aws_lb_target_group.victim.arn
}

output "victim_tg_name" {
  description = "Victim target group name (appears in alarm payload and Slack post)"
  value       = aws_lb_target_group.victim.name
}

output "victim_task_definition_family" {
  description = "Victim task definition family"
  value       = aws_ecs_task_definition.victim.family
}

output "victim_service_name" {
  description = "Victim ECS service name"
  value       = aws_ecs_service.victim.name
}

output "victim_task_role_arn" {
  description = "The gimped task role ARN. Appears in the AccessDenied error message in container logs — the load-bearing identifier for the agent's diagnosis."
  value       = aws_iam_role.victim_task_role.arn
}

output "victim_log_group_name" {
  description = "Container log group — `AccessDenied` line surfaces here at task startup; load-bearing evidence"
  value       = aws_cloudwatch_log_group.victim.name
}

output "alarm_name" {
  description = "CloudWatch alarm name (UnHealthyHostCount on the victim TG)"
  value       = aws_cloudwatch_metric_alarm.victim_tg_unhealthy.alarm_name
}

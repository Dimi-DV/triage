output "victim_tg_arn" {
  description = "Victim target group ARN (used by describe_target_health)"
  value       = aws_lb_target_group.victim.arn
}

output "victim_tg_name" {
  description = "Victim target group name (appears in alarm payload and Slack post)"
  value       = aws_lb_target_group.victim.name
}

output "victim_task_definition_family" {
  description = "Victim task definition family (slow-boot nginx; agent should rule out app-layer cause)"
  value       = aws_ecs_task_definition.victim.family
}

output "victim_service_name" {
  description = "Victim ECS service name (used by FIS to target tasks)"
  value       = aws_ecs_service.victim.name
}

output "victim_log_group_name" {
  description = "Container log group — slow-boot marker lines surface here. Recent 'task starting' lines indicate active recovery."
  value       = aws_cloudwatch_log_group.victim.name
}

output "alarm_name" {
  description = "CloudWatch alarm name (UnHealthyHostCount on the victim TG)"
  value       = aws_cloudwatch_metric_alarm.victim_tg_unhealthy.alarm_name
}

output "fis_template_id" {
  description = "FIS experiment template ID — pass to `aws fis start-experiment --experiment-template-id`"
  value       = aws_fis_experiment_template.ecs_task_stop.id
}

output "guard_alarm_name" {
  description = "Production guard-rail alarm (live MCP TG unhealthy). FIS auto-stops if this trips."
  value       = aws_cloudwatch_metric_alarm.live_mcp_guard.alarm_name
}

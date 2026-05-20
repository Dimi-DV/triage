output "victim_tg_arn" {
  value = aws_lb_target_group.victim.arn
}

output "victim_tg_name" {
  value = aws_lb_target_group.victim.name
}

output "victim_task_definition_family" {
  value = aws_ecs_task_definition.victim.family
}

output "victim_service_name" {
  value = aws_ecs_service.victim.name
}

output "victim_log_group_name" {
  value = aws_cloudwatch_log_group.victim.name
}

output "alarm_name" {
  value = aws_cloudwatch_metric_alarm.victim_tg_unhealthy.alarm_name
}

output "container_memory_limit_mb" {
  description = "The hard memory limit (MB) configured on the victim container — what the agent should cite from describe_task_definition as the misconfiguration."
  value       = var.container_memory_limit_mb
}

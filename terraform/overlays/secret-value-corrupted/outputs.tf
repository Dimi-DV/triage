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

output "secret_arn" {
  description = "The Secrets Manager secret whose value the CONFIG env var resolves from. Visible in describe_task_definition under secrets[].valueFrom — the agent should cite this as the source of the indirection in its diagnosis."
  value       = aws_secretsmanager_secret.config.arn
}

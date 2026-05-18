output "broken_tg_arn" {
  description = "Target group ARN (use with describe-target-health to confirm unhealthy state)"
  value       = aws_lb_target_group.broken.arn
}

output "broken_tg_name" {
  description = "Target group name (appears in the alarm message and the Slack post)"
  value       = aws_lb_target_group.broken.name
}

output "alarm_name" {
  description = "CloudWatch alarm name to watch / set-alarm-state against"
  value       = aws_cloudwatch_metric_alarm.broken_tg_unhealthy.alarm_name
}

output "log_group_name" {
  description = "Container log group — sanity-check nginx is actually serving on its declared port"
  value       = aws_cloudwatch_log_group.broken.name
}

output "readonly_policy_arn" {
  description = "Attach this to the IAM user or role that runs the exporter locally"
  value       = aws_iam_policy.finops_readonly.arn
}

output "budget_alerts_topic_arn" {
  description = "SNS topic that AWS Budgets publishes to"
  value       = aws_sns_topic.budget_alerts.arn
}

output "grafana_url" {
  description = "Grafana on the monitoring host (only when create_monitoring_host = true)"
  value       = var.create_monitoring_host ? "http://${aws_instance.monitoring[0].public_ip}:3000" : null
}

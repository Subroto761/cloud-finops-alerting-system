variable "aws_region" {
  description = "Region to deploy into and to scan for idle resources"
  type        = string
  default     = "ap-south-1"
}

variable "project_name" {
  description = "Prefix for resource names"
  type        = string
  default     = "finops"
}

variable "monthly_budget_usd" {
  description = "Monthly AWS budget. AWS Budgets emails at 80% actual and 100% forecast."
  type        = number
  default     = 50

  validation {
    condition     = var.monthly_budget_usd > 0
    error_message = "monthly_budget_usd must be greater than 0."
  }
}

variable "alert_email" {
  description = "Email that receives budget alerts. Leave empty to skip the email subscription."
  type        = string
  default     = ""
}

variable "create_monitoring_host" {
  description = "Create a small EC2 instance that runs the exporter, Prometheus, Alertmanager and Grafana"
  type        = bool
  default     = false
}

variable "instance_type" {
  description = "Instance type for the monitoring host"
  type        = string
  default     = "t3.small"
}

variable "allowed_cidr" {
  description = "CIDR allowed to reach Grafana (3000) on the monitoring host. Use your own IP, e.g. 203.0.113.5/32"
  type        = string
  default     = "127.0.0.1/32"
}

variable "repo_url" {
  description = "Git repository the monitoring host clones and runs"
  type        = string
  default     = "https://github.com/Subroto761/cloud-finops-alerting-system.git"
}

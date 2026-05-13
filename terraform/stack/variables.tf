variable "aws_region" {
  description = "AWS region for all resources"
  type        = string
  default     = "us-east-1"
}

variable "environment" {
  description = "Deployment environment (dev/prod)"
  type        = string
  default     = "dev"
}

variable "project_name" {
  description = "Project name used as a resource prefix"
  type        = string
  default     = "triage"
}

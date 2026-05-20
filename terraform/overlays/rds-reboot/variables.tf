variable "aws_region" {
  description = "AWS region (must match the stack)"
  type        = string
  default     = "us-east-1"
}

variable "environment" {
  description = "Stack environment — drives resource name prefix and stack state lookup"
  type        = string
  default     = "dev"
}

variable "project_name" {
  description = "Stack project name — drives resource name prefix"
  type        = string
  default     = "triage"
}

variable "stack_state_bucket" {
  description = "S3 bucket holding the stack's Terraform state"
  type        = string
  default     = "dimitrije-tf-state-2026"
}

variable "stack_state_key" {
  description = "State key for the stack inside stack_state_bucket"
  type        = string
  default     = "triage/stack/terraform.tfstate"
}

variable "container_port" {
  description = "Port the victim's Python health-checking HTTP server listens on. Must match the stack's app-SG ingress rule (port 8080 from the ALB SG)."
  type        = number
  default     = 8080
}

variable "force_failover" {
  description = "Whether the FIS reboot action forces a Multi-AZ failover. true = ~60-120s downtime (longer agent investigation window); false = ~30-60s downtime. Stack RDS is Multi-AZ, so failover is supported."
  type        = bool
  default     = true
}

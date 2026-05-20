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
  description = "Port nginx listens on (also the TG health-check port via traffic-port). Must match the stack's app-SG ingress rule (port 8080 from the ALB SG)."
  type        = number
  default     = 8080
}

variable "slow_boot_seconds" {
  description = "How long the nginx container sleeps before exec'ing nginx. Sustains UnHealthyHostCount > 0 after FIS stops tasks so the alarm fires AND the agent has a window to investigate while recovery is in progress."
  type        = number
  default     = 90
}

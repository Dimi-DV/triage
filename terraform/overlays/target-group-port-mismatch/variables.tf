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

# Bad-knob port. The TG's health check probes this port; the container
# does not listen here. Health checks fail; UnhealthyHostCount alarm fires.
variable "broken_health_check_port" {
  description = "Port the TG health check probes (intentionally not where nginx listens)"
  type        = number
  default     = 8081
}

variable "container_port" {
  description = "Port the nginx:alpine container actually listens on"
  type        = number
  default     = 80
}

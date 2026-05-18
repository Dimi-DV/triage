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
  description = "Port nginx would listen on if the container started correctly"
  type        = number
  default     = 80
}

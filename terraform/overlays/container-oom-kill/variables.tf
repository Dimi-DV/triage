variable "aws_region" {
  type    = string
  default = "us-east-1"
}

variable "environment" {
  type    = string
  default = "dev"
}

variable "project_name" {
  type    = string
  default = "triage"
}

variable "stack_state_bucket" {
  type    = string
  default = "dimitrije-tf-state-2026"
}

variable "stack_state_key" {
  type    = string
  default = "triage/stack/terraform.tfstate"
}

variable "container_port" {
  type    = number
  default = 8080
}

variable "container_memory_limit_mb" {
  description = "Hard memory limit on the victim container in MB. Below Python's runtime needs once the leak script starts allocating, so the kernel OOM-killer fires within seconds and ECS restarts the task in a loop."
  type        = number
  default     = 128
}

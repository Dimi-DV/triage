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

variable "experiment_duration" {
  description = "How long the FIS disrupt-connectivity action runs. ISO-8601 duration. Long enough that the UnHealthyHostCount alarm fires AND the eval harness has time to invoke the agent before disruption ends."
  type        = string
  default     = "PT5M"
}

variable "victim_subnet_cidr" {
  description = "CIDR for the dedicated victim subnet created by this overlay. Must not conflict with existing stack subnets (10.0.0/24, 10.0.1/24, 10.0.10/24, 10.0.11/24, 10.0.20/24, 10.0.21/24). Using 10.0.30/24 by default to avoid the live MCP private subnets — the FIS blackhole would otherwise risk knocking out production MCP whenever ECS happens to place its single Fargate task in the targeted subnet."
  type        = string
  default     = "10.0.30.0/24"
}

variable "victim_subnet_az" {
  description = "Availability zone for the dedicated victim subnet. AZ-b matches the stack's private-subnet AZ list; the new subnet inherits the AZ-b private route table for NAT egress so the victim can push CloudWatch logs before disruption."
  type        = string
  default     = "us-east-1b"
}

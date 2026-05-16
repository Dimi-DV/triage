variable "aws_region" {
  description = "AWS region for all resources"
  type        = string
  default     = "us-east-1"
}

variable "environment" {
  description = "Deployment environment (dev/prod)"
  type        = string
  default     = "dev"

  validation {
    condition     = contains(["dev", "prod"], var.environment)
    error_message = "environment must be one of: dev, prod."
  }
}

variable "project_name" {
  description = "Project name used as a resource prefix"
  type        = string
  default     = "triage"
}

variable "vpc_cidr" {
  description = "CIDR block for the Multi-AZ production VPC"
  type        = string
  default     = "10.0.0.0/16"
}

variable "availability_zones" {
  description = "Two AZs for the Multi-AZ stack (NAT, subnets, RDS)"
  type        = list(string)
  default     = ["us-east-1a", "us-east-1b"]

  validation {
    condition     = length(var.availability_zones) == 2
    error_message = "availability_zones must contain exactly two AZs."
  }
}

variable "domain_name" {
  description = "Apex domain for the ACM cert and Route 53 zone (e.g., triage.example.com). No default — supply via tfvars or TF_VAR_domain_name."
  type        = string
}

variable "db_password" {
  description = "Master password for the RDS instance. Supply via TF_VAR_db_password; never commit. TODO: migrate to random_password + AWS Secrets Manager."
  type        = string
  sensitive   = true
}

variable "db_instance_class" {
  description = "RDS instance class"
  type        = string
  default     = "db.t4g.micro"
}

variable "rds_engine_version" {
  description = "RDS Postgres engine version"
  type        = string
  default     = "16.4"
}

variable "app_port" {
  description = "TCP port the app container listens on. ALB target group + app SG ingress reference this."
  type        = number
  default     = 8080
}

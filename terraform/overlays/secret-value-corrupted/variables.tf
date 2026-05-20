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

variable "corrupted_secret_value" {
  description = "What the Secrets Manager secret resolves to at task startup. Garbage by design — invalid JSON. The container's parser fails, the container caches the parse error, and the HTTP server returns 503 on every probe. The agent's diagnosis must identify the indirection (env var → Secrets Manager → bad value) without ever reading the secret directly. Must be non-empty (AWS Secrets Manager rejects empty SecretString)."
  type        = string
  default     = "<corrupted>"
  sensitive   = true
}

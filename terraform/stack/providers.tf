provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = "triage"
      Environment = var.environment
      ManagedBy   = "terraform"
      Owner       = "Dimitrije"
    }
  }
}

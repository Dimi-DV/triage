terraform {
  required_version = ">= 1.14.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.70"
    }
  }

  # Local state by design. Overlays are apply-then-destroy; remote locking
  # buys nothing and makes wipe-and-retry slower. Stack state stays in S3.
  backend "local" {}
}

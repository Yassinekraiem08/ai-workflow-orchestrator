terraform {
  required_version = "~> 1.7"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  # Pre-requisite: create the state bucket before running `terraform init`.
  #
  #   aws s3 mb s3://ai-workflow-orchestrator-tfstate --region us-east-1
  #   aws s3api put-bucket-versioning \
  #     --bucket ai-workflow-orchestrator-tfstate \
  #     --versioning-configuration Status=Enabled
  backend "s3" {
    bucket  = "ai-workflow-orchestrator-tfstate"
    key     = "production/terraform.tfstate"
    region  = "us-east-1"
    encrypt = true
  }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = local.common_tags
  }
}

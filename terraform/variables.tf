locals {
  common_tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

# ------------------------------------------------------------------------------
# General
# ------------------------------------------------------------------------------

variable "aws_region" {
  description = "AWS region for all resources."
  type        = string
  default     = "us-east-1"
}

variable "project_name" {
  description = "Project identifier. Used as a prefix in resource names and tags."
  type        = string
  default     = "ai-workflow-orchestrator"
}

variable "environment" {
  description = "Deployment environment name (production, staging, etc.)."
  type        = string
  default     = "production"
}

# ------------------------------------------------------------------------------
# Secrets  —  supply via terraform.tfvars or TF_VAR_* env vars; never hard-code
# ------------------------------------------------------------------------------

variable "db_password" {
  description = "Master password for the RDS PostgreSQL instance."
  type        = string
  sensitive   = true
}

variable "openai_api_key" {
  description = "OpenAI API key injected into the API and worker containers."
  type        = string
  sensitive   = true
}

variable "api_keys" {
  description = "Comma-separated bearer tokens accepted by the API gateway middleware."
  type        = string
  sensitive   = true
}

variable "jwt_secret" {
  description = "HMAC secret used to sign and verify JWTs."
  type        = string
  sensitive   = true
}

# ------------------------------------------------------------------------------
# ECS task sizing
# ------------------------------------------------------------------------------

variable "api_cpu" {
  description = "CPU units allocated to the API Fargate task (1 vCPU = 1024 units)."
  type        = number
  default     = 512
}

variable "api_memory" {
  description = "Memory (MiB) allocated to the API Fargate task."
  type        = number
  default     = 1024
}

variable "worker_cpu" {
  description = "CPU units allocated to the Celery worker Fargate task."
  type        = number
  default     = 1024
}

variable "worker_memory" {
  description = "Memory (MiB) allocated to the Celery worker Fargate task."
  type        = number
  default     = 2048
}

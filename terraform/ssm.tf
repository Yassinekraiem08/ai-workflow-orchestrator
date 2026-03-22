# Secrets are stored as SSM SecureStrings and injected into containers at
# task startup via the `secrets` block in the ECS task definition. Values
# are supplied through terraform.tfvars or TF_VAR_* environment variables —
# never committed to source control.

resource "aws_ssm_parameter" "openai_api_key" {
  name        = "/${var.project_name}/openai_api_key"
  description = "OpenAI API key for the AI Workflow Orchestrator."
  type        = "SecureString"
  value       = var.openai_api_key

  tags = {
    Name = "${var.project_name}-${var.environment}-openai-api-key"
  }
}

resource "aws_ssm_parameter" "db_password" {
  name        = "/${var.project_name}/db_password"
  description = "RDS PostgreSQL master password."
  type        = "SecureString"
  value       = var.db_password

  tags = {
    Name = "${var.project_name}-${var.environment}-db-password"
  }
}

resource "aws_ssm_parameter" "api_keys" {
  name        = "/${var.project_name}/api_keys"
  description = "Comma-separated list of valid client API keys."
  type        = "SecureString"
  value       = var.api_keys

  tags = {
    Name = "${var.project_name}-${var.environment}-api-keys"
  }
}

resource "aws_ssm_parameter" "jwt_secret" {
  name        = "/${var.project_name}/jwt_secret"
  description = "HMAC secret used to sign and verify JWTs."
  type        = "SecureString"
  value       = var.jwt_secret

  tags = {
    Name = "${var.project_name}-${var.environment}-jwt-secret"
  }
}

output "alb_dns_name" {
  description = "Public URL of the Application Load Balancer."
  value       = "http://${aws_lb.main.dns_name}"
}

output "ecr_api_repository_url" {
  description = "ECR repository URL. Push the application image here before deploying."
  value       = aws_ecr_repository.app.repository_url
}

output "ecs_cluster_name" {
  description = "Name of the ECS cluster running the API and worker services."
  value       = aws_ecs_cluster.main.name
}

output "rds_endpoint" {
  description = "RDS instance endpoint in host:port form."
  value       = aws_db_instance.postgres.endpoint
  sensitive   = true
}

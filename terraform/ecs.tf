# ------------------------------------------------------------------------------
# Connection strings assembled from live infrastructure endpoints
#
# aws_db_instance.endpoint returns "hostname:5432"; split off the port so the
# SQLAlchemy URL carries an explicit port rather than a bare host.
# aws_elasticache_cluster.cache_nodes[0].address is hostname only.
# ------------------------------------------------------------------------------

locals {
  rds_host = split(":", aws_db_instance.postgres.endpoint)[0]

  database_url = "postgresql+asyncpg://postgres:${var.db_password}@${local.rds_host}:5432/workflow_db"
  redis_url    = "redis://${aws_elasticache_cluster.redis.cache_nodes[0].address}:6379/0"

  # Non-sensitive environment variables shared by both task definitions.
  # DATABASE_URL carries the password inline because asyncpg does not support
  # the password-in-SSM pattern that the ECS secrets block provides. Rotate
  # the RDS password through Secrets Manager if that becomes a compliance
  # requirement.
  shared_environment = [
    { name = "APP_ENV",               value = "production"     },
    { name = "OTEL_ENABLED",          value = "false"          },
    { name = "DATABASE_URL",          value = local.database_url },
    { name = "REDIS_URL",             value = local.redis_url  },
    { name = "CELERY_BROKER_URL",     value = local.redis_url  },
    { name = "CELERY_RESULT_BACKEND", value = local.redis_url  },
  ]

  # SSM SecureStrings resolved by the ECS agent at task startup.
  shared_secrets = [
    {
      name      = "OPENAI_API_KEY"
      valueFrom = aws_ssm_parameter.openai_api_key.arn
    },
    {
      name      = "API_KEYS"
      valueFrom = aws_ssm_parameter.api_keys.arn
    },
    {
      name      = "JWT_SECRET"
      valueFrom = aws_ssm_parameter.jwt_secret.arn
    },
  ]
}

# ------------------------------------------------------------------------------
# ECS Cluster
# ------------------------------------------------------------------------------

resource "aws_ecs_cluster" "main" {
  name = "${var.project_name}-${var.environment}"

  setting {
    name  = "containerInsights"
    value = "enabled"
  }

  tags = {
    Name = "${var.project_name}-${var.environment}-cluster"
  }
}

# ------------------------------------------------------------------------------
# CloudWatch log group
# ------------------------------------------------------------------------------

resource "aws_cloudwatch_log_group" "ecs" {
  name              = "/ecs/${var.project_name}"
  retention_in_days = 30

  tags = {
    Name = "${var.project_name}-${var.environment}-logs"
  }
}

# ------------------------------------------------------------------------------
# API task definition
#
# Alembic runs inline before Uvicorn starts. This is deliberate for a
# single-replica setup: the migration completes before traffic is accepted.
# For a multi-replica rolling deploy, extract migrations into a one-off ECS
# task run during the CI/CD pipeline instead.
# ------------------------------------------------------------------------------

resource "aws_ecs_task_definition" "api" {
  family                   = "${var.project_name}-api"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.api_cpu
  memory                   = var.api_memory

  execution_role_arn = aws_iam_role.ecs_execution.arn
  task_role_arn      = aws_iam_role.ecs_task.arn

  container_definitions = jsonencode([
    {
      name  = "api"
      image = "${aws_ecr_repository.app.repository_url}:latest"

      command = [
        "sh", "-c",
        "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 2",
      ]

      portMappings = [
        {
          containerPort = 8000
          protocol      = "tcp"
        },
      ]

      environment = local.shared_environment
      secrets     = local.shared_secrets

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.ecs.name
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "api"
        }
      }

      healthCheck = {
        command     = ["CMD-SHELL", "curl -f http://localhost:8000/health || exit 1"]
        interval    = 30
        timeout     = 5
        retries     = 3
        startPeriod = 60
      }

      essential = true
    },
  ])

  tags = {
    Name = "${var.project_name}-${var.environment}-api-task"
  }
}

# ------------------------------------------------------------------------------
# Worker task definition
#
# Same image as the API; the Celery worker entry point replaces Uvicorn.
# concurrency=4 matches the 1 vCPU / 2 GiB Fargate task size; each prefork
# child opens its own NullPool DB connection (see celery_app.py).
# ------------------------------------------------------------------------------

resource "aws_ecs_task_definition" "worker" {
  family                   = "${var.project_name}-worker"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.worker_cpu
  memory                   = var.worker_memory

  execution_role_arn = aws_iam_role.ecs_execution.arn
  task_role_arn      = aws_iam_role.ecs_task.arn

  container_definitions = jsonencode([
    {
      name  = "worker"
      image = "${aws_ecr_repository.app.repository_url}:latest"

      command = [
        "celery",
        "-A", "app.workers.celery_app",
        "worker",
        "--loglevel=info",
        "-Q", "workflows,retries,dead_letter",
        "--concurrency=4",
      ]

      portMappings = []

      environment = local.shared_environment
      secrets     = local.shared_secrets

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.ecs.name
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "worker"
        }
      }

      essential = true
    },
  ])

  tags = {
    Name = "${var.project_name}-${var.environment}-worker-task"
  }
}

# ------------------------------------------------------------------------------
# API ECS service
# ------------------------------------------------------------------------------

resource "aws_ecs_service" "api" {
  name            = "${var.project_name}-${var.environment}-api"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.api.arn
  desired_count   = 1
  launch_type     = "FARGATE"

  force_new_deployment = true

  network_configuration {
    subnets          = [aws_subnet.public_a.id, aws_subnet.public_b.id]
    security_groups  = [aws_security_group.ecs.id]
    assign_public_ip = true
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.api.arn
    container_name   = "api"
    container_port   = 8000
  }

  health_check_grace_period_seconds = 120

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  deployment_controller {
    type = "ECS"
  }

  depends_on = [aws_lb_listener.http]

  tags = {
    Name = "${var.project_name}-${var.environment}-api-service"
  }
}

# ------------------------------------------------------------------------------
# Worker ECS service
# ------------------------------------------------------------------------------

resource "aws_ecs_service" "worker" {
  name            = "${var.project_name}-${var.environment}-worker"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.worker.arn
  desired_count   = 1
  launch_type     = "FARGATE"

  force_new_deployment = true

  network_configuration {
    subnets          = [aws_subnet.public_a.id, aws_subnet.public_b.id]
    security_groups  = [aws_security_group.ecs.id]
    assign_public_ip = true
  }

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  tags = {
    Name = "${var.project_name}-${var.environment}-worker-service"
  }
}

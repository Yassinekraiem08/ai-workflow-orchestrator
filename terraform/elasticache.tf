resource "aws_elasticache_subnet_group" "redis" {
  name        = "${var.project_name}-${var.environment}-redis-subnet-group"
  description = "Private subnets for the ElastiCache Redis cluster."
  subnet_ids  = [aws_subnet.private_a.id, aws_subnet.private_b.id]

  tags = {
    Name = "${var.project_name}-${var.environment}-redis-subnet-group"
  }
}

# Single-node Redis 7. No auth token is configured because the cluster is
# reachable only from the ECS security group; transit encryption can be
# enabled later without downtime.
resource "aws_elasticache_cluster" "redis" {
  cluster_id           = "${var.project_name}-${var.environment}-redis"
  engine               = "redis"
  engine_version       = "7.1"
  node_type            = "cache.t3.micro"
  num_cache_nodes      = 1
  parameter_group_name = "default.redis7"
  port                 = 6379

  subnet_group_name  = aws_elasticache_subnet_group.redis.name
  security_group_ids = [aws_security_group.redis.id]

  maintenance_window       = "sun:05:00-sun:06:00"
  snapshot_retention_limit = 0

  apply_immediately = true

  tags = {
    Name = "${var.project_name}-${var.environment}-redis"
  }
}

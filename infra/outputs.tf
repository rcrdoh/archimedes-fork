output "instance_id" {
  description = "EC2 instance ID"
  value       = aws_instance.archimedes.id
}

output "public_ip" {
  description = "Public IP address of the EC2 instance"
  value       = aws_instance.archimedes.public_ip
}

output "public_dns" {
  description = "Public DNS name of the EC2 instance"
  value       = aws_instance.archimedes.public_dns
}

output "ssh_command" {
  description = "SSH command to connect"
  value       = "ssh -i infra/${var.key_name}.pem ubuntu@${aws_instance.archimedes.public_ip}"
}

output "api_url" {
  description = "Backend API URL"
  value       = "http://${aws_instance.archimedes.public_ip}:8000"
}

output "private_key_path" {
  description = "Path to the SSH private key"
  value       = local_sensitive_file.private_key.filename
}

output "ssh_private_key" {
  description = "SSH private key (for GitHub Actions secret)"
  value       = tls_private_key.deploy.private_key_openssh
  sensitive   = true
}

# ── New VPC infrastructure outputs ────────────────────────────

output "vpc_id" {
  description = "New VPC ID"
  value       = aws_vpc.main.id
}

output "aurora_endpoint" {
  description = "Aurora cluster endpoint (for DATABASE_URL)"
  value       = aws_rds_cluster.main.endpoint
}

output "aurora_reader_endpoint" {
  description = "Aurora reader endpoint"
  value       = aws_rds_cluster.main.reader_endpoint
}

output "redis_endpoint" {
  description = "ElastiCache Redis endpoint (for REDIS_URL)"
  value       = aws_elasticache_replication_group.main.primary_endpoint_address
}

output "database_url" {
  description = "Full DATABASE_URL for backend .env"
  value       = "postgresql://archimedes:${var.aurora_master_password}@${aws_rds_cluster.main.endpoint}:5432/archimedes"
  sensitive   = true
}

output "redis_url" {
  description = "Full REDIS_URL for backend .env"
  value       = "rediss://${aws_elasticache_replication_group.main.primary_endpoint_address}:6379/0"
}

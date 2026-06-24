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
  description = <<-DESC
    Full DATABASE_URL for backend .env. STATE-SENSITIVE: this output stores
    the master password in Terraform state (which lives in the S3 backend).
    The bucket policy restricts access to the AWS account principal and TLS-only,
    but the password is still in the state file. Recommended pattern going forward:
    backend fetches the password from AWS Secrets Manager / SSM Parameter Store at
    runtime and constructs the URL from `aurora_endpoint` + password — that way
    the secret never lands in Terraform state at all. Tracked as a follow-up.
  DESC
  value       = "postgresql://archimedes:${var.aurora_master_password}@${aws_rds_cluster.main.endpoint}:5432/archimedes"
  sensitive   = true
}

output "redis_url" {
  description = "Full REDIS_URL for backend .env"
  value       = "rediss://${aws_elasticache_replication_group.main.primary_endpoint_address}:6379/0"
}

output "alb_dns_name" {
  description = "ALB DNS name (for Route 53 ALIAS record)"
  value       = aws_lb.main.dns_name
}

output "alb_zone_id" {
  description = "ALB hosted zone ID (for Route 53 ALIAS record)"
  value       = aws_lb.main.zone_id
}

output "acm_certificate_arn" {
  description = "ACM certificate ARN"
  value       = aws_acm_certificate.main.arn
}

output "waf_web_acl_arn" {
  description = "WAF Web ACL ARN"
  value       = aws_wafv2_web_acl.main.arn
}

# ── CloudFront + ASG (virality tier, issue #155) ──────────────

output "cloudfront_domain_name" {
  description = "CloudFront distribution domain (the *.cloudfront.net name behind archimedes-arc.app)"
  value       = aws_cloudfront_distribution.main.domain_name
}

output "cloudfront_distribution_id" {
  description = "CloudFront distribution id (for cache invalidations)"
  value       = aws_cloudfront_distribution.main.id
}

output "backend_asg_name" {
  description = "Backend auto-scaling group name (null unless the optional ASG tier is enabled via backend_ami_id)"
  value       = one(aws_autoscaling_group.backend[*].name)
}

variable "aws_region" {
  description = "AWS region"
  type        = string
  default     = "us-east-1"
}

variable "domain_name" {
  description = "Primary domain for the stack (ACM cert + Route 53 zone + CloudFront/ALB aliases). The hosted zone must already exist — auto-created when the domain is registered via Route 53 Domains."
  type        = string
  default     = "archimedes-arc.com"
}

variable "instance_type" {
  description = "EC2 instance type. t3.medium (4 GB) fixes the t3.small docker-build OOM (#439)."
  type        = string
  default     = "t3.medium"
}

variable "key_name" {
  description = "Name for the SSH key pair"
  type        = string
  default     = "archimedes-deploy-key"
}

variable "aurora_master_password" {
  description = "Master password for Aurora PostgreSQL. Set via TF_VAR_aurora_master_password env var."
  type        = string
  sensitive   = true
}

variable "project_name" {
  description = "Project name for tagging"
  type        = string
  default     = "archimedes"
}

variable "repo_url" {
  description = "GitHub repo HTTPS URL for cloning on the instance"
  type        = string
  default     = "https://github.com/a-apin/archimedes.git"
}

# AMI for the backend auto-scaling group (issue #155, OPTIONAL virality tier).
# Bake via infra/scripts/bake-backend-ami.sh, then set this to the resulting
# AMI id (or pass TF_VAR_backend_ami_id). Empty default keeps the var present
# without forcing a value when the ASG is not being applied. The launch
# template / ASG in asg.tf only become real on `terraform apply` — a plan with
# an empty value will simply error on the launch template until an AMI is set,
# which is the intended "supply the AMI to enable the tier" gate.
variable "backend_ami_id" {
  description = "Custom backend AMI id for the auto-scaling group launch template (issue #155). Set after baking via infra/scripts/bake-backend-ami.sh."
  type        = string
  default     = ""
}

variable "aws_region" {
  description = "AWS region"
  type        = string
  default     = "eu-west-2"
}

variable "instance_type" {
  description = "EC2 instance type"
  type        = string
  default     = "t3.small"
}

variable "key_name" {
  description = "Name for the SSH key pair"
  type        = string
  default     = "archimedes-deploy-key"
}

variable "project_name" {
  description = "Project name for tagging"
  type        = string
  default     = "archimedes"
}

variable "repo_url" {
  description = "GitHub repo HTTPS URL for cloning on the instance"
  type        = string
  default     = "https://github.com/hackagora/archimedes-arcadia.git"
}

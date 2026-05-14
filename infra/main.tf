terraform {
  required_version = ">= 1.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    tls = {
      source  = "hashicorp/tls"
      version = "~> 4.0"
    }
    local = {
      source  = "hashicorp/local"
      version = "~> 2.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

# ---------------------------------------------------------------------------
# Data sources
# ---------------------------------------------------------------------------

# Latest Ubuntu 24.04 LTS x86_64 AMI
data "aws_ami" "ubuntu" {
  most_recent = true
  owners      = ["099720109477"] # Canonical

  filter {
    name   = "name"
    values = ["ubuntu/images/hvm-ssd-gp3/ubuntu-noble-24.04-amd64-server-*"]
  }

  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }

  filter {
    name   = "architecture"
    values = ["x86_64"]
  }
}

# Default VPC
data "aws_vpc" "default" {
  default = true
}

# ---------------------------------------------------------------------------
# SSH key pair — generated in Terraform, private key saved locally
# ---------------------------------------------------------------------------

resource "tls_private_key" "deploy" {
  algorithm = "ED25519"
}

resource "aws_key_pair" "deploy" {
  key_name   = var.key_name
  public_key = tls_private_key.deploy.public_key_openssh

  tags = {
    Project = var.project_name
  }
}

resource "local_sensitive_file" "private_key" {
  content         = tls_private_key.deploy.private_key_openssh
  filename        = "${path.module}/${var.key_name}.pem"
  file_permission = "0600"
}

# ---------------------------------------------------------------------------
# Security group
# ---------------------------------------------------------------------------

resource "aws_security_group" "archimedes" {
  name        = "${var.project_name}-sg"
  description = "Archimedes EC2 - SSH, HTTP, HTTPS, API"
  vpc_id      = data.aws_vpc.default.id

  # SSH
  ingress {
    description = "SSH"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  # HTTP
  ingress {
    description = "HTTP"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  # HTTPS
  ingress {
    description = "HTTPS"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  # FastAPI dev port
  ingress {
    description = "FastAPI"
    from_port   = 8000
    to_port     = 8000
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  # Next.js dev port
  ingress {
    description = "Next.js"
    from_port   = 3000
    to_port     = 3000
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  # Egress — all
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name    = "${var.project_name}-sg"
    Project = var.project_name
  }
}

# ---------------------------------------------------------------------------
# EC2 instance
# ---------------------------------------------------------------------------

resource "aws_instance" "archimedes" {
  ami                    = data.aws_ami.ubuntu.id
  instance_type          = var.instance_type
  key_name               = aws_key_pair.deploy.key_name
  vpc_security_group_ids = [aws_security_group.archimedes.id]

  # 20 GB gp3 root volume (enough for Docker images + data)
  root_block_device {
    volume_size           = 20
    volume_type           = "gp3"
    delete_on_termination = true
  }

  user_data = templatefile("${path.module}/user-data.sh", {
    repo_url = var.repo_url
  })

  tags = {
    Name    = "${var.project_name}-server"
    Project = var.project_name
  }

  lifecycle {
    ignore_changes = [ami] # Don't recreate on AMI updates
  }
}

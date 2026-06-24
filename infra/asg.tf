# ── Auto-Scaling Group for the backend API tier ───────────────────────
#
# OPTIONAL / virality-prep (issue #155). This tier is INERT until an
# operator (a) bakes a backend AMI via infra/scripts/bake-backend-ami.sh,
# (b) sets `backend_ami_id` to the resulting AMI, and (c) runs
# `terraform apply` with AWS credentials.
#
# GATING (added 2026-06-24): every resource here is gated on
# `local.asg_enabled` (= backend_ami_id non-empty). With no AMI supplied the
# whole tier is count=0 — `terraform apply` creates nothing in this file, so the
# core single-EC2 stack stands up cleanly without a placeholder AMI. Bake an AMI
# + set backend_ami_id (or TF_VAR_backend_ami_id) to enable the tier.
#
# Design:
#   - Launch template runs the backend AMI (postgres/redis already live as
#     managed Aurora + ElastiCache, so each instance is stateless — see
#     aurora.tf / elasticache.tf). Each instance boots the production
#     docker-compose stack (backend + nginx only) via cloud-init.
#   - ASG min=2, desired=2, max=4 (cost-capped at 4 per the issue anti-goal).
#   - Instances register with the EXISTING ALB target group
#     (aws_lb_target_group.backend in alb.tf) via target_group_arns. The ALB
#     health check is GET /health (already configured in alb.tf).
#   - Scale-out: avg CPU > 60% for 2 min OR ALB request count > 1000/min.
#   - Scale-in: avg CPU < 25% for 10 min (slow, to avoid flapping).
#
# Anti-goal honored: ASG is the API tier ONLY. The oracle_runner and
# agent_runner remain single canonical instances (NOT in this ASG) — their
# loops are the source of truth for vault/regime state and must not be
# load-balanced or duplicated.

locals {
  asg_enabled = var.backend_ami_id != "" ? 1 : 0
}

# ── Security group for ASG instances (lives in the new VPC) ───
# The existing single-EC2 SG (aws_security_group.archimedes) is in the
# DEFAULT VPC; the ALB + target group live in aws_vpc.main, so ASG instances
# need an SG in aws_vpc.main. Inbound HTTP only from the ALB SG; outbound all
# (needs to reach Aurora, ElastiCache, Arc RPC, Anthropic, ECR/Docker Hub).

resource "aws_security_group" "backend_asg" {
  count       = local.asg_enabled
  name        = "${var.project_name}-backend-asg-sg"
  description = "Backend ASG instances - HTTP from ALB only"
  vpc_id      = aws_vpc.main.id

  ingress {
    description     = "HTTP from ALB"
    from_port       = 80
    to_port         = 80
    protocol        = "tcp"
    security_groups = [aws_security_group.alb.id]
  }

  egress {
    description = "All outbound (Aurora, Redis, Arc RPC, Anthropic, registries)"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name    = "${var.project_name}-backend-asg-sg"
    Project = var.project_name
  }
}

# Allow ASG instances to reach Aurora (Postgres 5432) and ElastiCache
# (Redis 6379). Added as standalone rules so we don't edit aurora.tf /
# elasticache.tf (other-lane files) — security_group_rule keeps the change
# additive and confined to this file.
resource "aws_security_group_rule" "aurora_from_asg" {
  count                    = local.asg_enabled
  type                     = "ingress"
  description              = "Postgres from backend ASG"
  from_port                = 5432
  to_port                  = 5432
  protocol                 = "tcp"
  security_group_id        = aws_security_group.aurora.id
  source_security_group_id = aws_security_group.backend_asg[0].id
}

resource "aws_security_group_rule" "redis_from_asg" {
  count                    = local.asg_enabled
  type                     = "ingress"
  description              = "Redis from backend ASG"
  from_port                = 6379
  to_port                  = 6379
  protocol                 = "tcp"
  security_group_id        = aws_security_group.redis.id
  source_security_group_id = aws_security_group.backend_asg[0].id
}

# ── Launch template ───────────────────────────────────────────
# Uses the baked backend AMI. The cloud-init user-data clones the repo and
# starts the production stack. No secrets are baked into the AMI — DB/Redis
# URLs come from env (DATABASE_URL/REDIS_URL), sourced from SSM Parameter
# Store at boot per the deploy convention.

resource "aws_launch_template" "backend" {
  count         = local.asg_enabled
  name_prefix   = "${var.project_name}-backend-"
  image_id      = var.backend_ami_id
  instance_type = var.instance_type
  key_name      = aws_key_pair.deploy.key_name

  vpc_security_group_ids = [aws_security_group.backend_asg[0].id]

  # Encrypt the root volume at rest (same posture as the single EC2 — see
  # main.tf root_block_device). Holds Docker layers + any SSM-pulled secrets.
  block_device_mappings {
    device_name = "/dev/sda1"
    ebs {
      volume_size           = 20
      volume_type           = "gp3"
      delete_on_termination = true
      encrypted             = true
    }
  }

  # Require IMDSv2 (token-backed metadata) — blocks SSRF-style credential theft.
  metadata_options {
    http_endpoint               = "enabled"
    http_tokens                 = "required"
    http_put_response_hop_limit = 2
  }

  user_data = base64encode(templatefile("${path.module}/user-data.sh", {
    repo_url = var.repo_url
  }))

  monitoring {
    enabled = true # detailed (1-min) CloudWatch metrics for responsive scaling
  }

  tag_specifications {
    resource_type = "instance"
    tags = {
      Name    = "${var.project_name}-backend-asg"
      Project = var.project_name
    }
  }

  tags = {
    Project = var.project_name
  }
}

# ── Auto-scaling group ────────────────────────────────────────

resource "aws_autoscaling_group" "backend" {
  count               = local.asg_enabled
  name                = "${var.project_name}-backend-asg"
  min_size            = 2
  desired_capacity    = 2
  max_size            = 4
  vpc_zone_identifier = aws_subnet.public[*].id

  # Register with the EXISTING ALB target group (defined in alb.tf). The ALB
  # health check (GET /health) gates traffic; ELB health gates ASG lifecycle.
  target_group_arns         = [aws_lb_target_group.backend.arn]
  health_check_type         = "ELB"
  health_check_grace_period = 300 # allow boot + docker compose up before health-checking

  launch_template {
    id      = aws_launch_template.backend[0].id
    version = "$Latest"
  }

  # Replace instances one batch at a time on launch-template changes, keeping
  # the site up (min healthy 100%) throughout a rolling refresh.
  instance_refresh {
    strategy = "Rolling"
    preferences {
      min_healthy_percentage = 100
    }
  }

  tag {
    key                 = "Name"
    value               = "${var.project_name}-backend-asg"
    propagate_at_launch = true
  }

  tag {
    key                 = "Project"
    value               = var.project_name
    propagate_at_launch = true
  }
}

# ── Scaling policies ──────────────────────────────────────────

# Scale-out on high CPU (avg > 60% for 2 consecutive 1-min periods).
resource "aws_autoscaling_policy" "scale_out_cpu" {
  count                  = local.asg_enabled
  name                   = "${var.project_name}-scale-out-cpu"
  autoscaling_group_name = aws_autoscaling_group.backend[0].name
  adjustment_type        = "ChangeInCapacity"
  scaling_adjustment     = 1
  cooldown               = 120
}

resource "aws_cloudwatch_metric_alarm" "cpu_high" {
  count               = local.asg_enabled
  alarm_name          = "${var.project_name}-backend-cpu-high"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  period              = 60
  threshold           = 60
  namespace           = "AWS/EC2"
  metric_name         = "CPUUtilization"
  statistic           = "Average"

  dimensions = {
    AutoScalingGroupName = aws_autoscaling_group.backend[0].name
  }

  alarm_actions = [aws_autoscaling_policy.scale_out_cpu[0].arn]

  tags = {
    Project = var.project_name
  }
}

# Scale-out on ALB request count > 1000/min (sum over 1 min) against the
# backend target group.
resource "aws_autoscaling_policy" "scale_out_requests" {
  count                  = local.asg_enabled
  name                   = "${var.project_name}-scale-out-requests"
  autoscaling_group_name = aws_autoscaling_group.backend[0].name
  adjustment_type        = "ChangeInCapacity"
  scaling_adjustment     = 1
  cooldown               = 120
}

resource "aws_cloudwatch_metric_alarm" "requests_high" {
  count               = local.asg_enabled
  alarm_name          = "${var.project_name}-backend-requests-high"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  period              = 60
  threshold           = 1000
  namespace           = "AWS/ApplicationELB"
  metric_name         = "RequestCountPerTarget"
  statistic           = "Sum"

  dimensions = {
    TargetGroup  = aws_lb_target_group.backend.arn_suffix
    LoadBalancer = aws_lb.main.arn_suffix
  }

  alarm_actions = [aws_autoscaling_policy.scale_out_requests[0].arn]

  tags = {
    Project = var.project_name
  }
}

# Scale-in on sustained low CPU (avg < 25% for 10 consecutive 1-min periods).
# Slow scale-in (long evaluation + 300s cooldown) avoids flapping when load
# briefly dips. min_size=2 floors the group so we never drop below HA.
resource "aws_autoscaling_policy" "scale_in_cpu" {
  count                  = local.asg_enabled
  name                   = "${var.project_name}-scale-in-cpu"
  autoscaling_group_name = aws_autoscaling_group.backend[0].name
  adjustment_type        = "ChangeInCapacity"
  scaling_adjustment     = -1
  cooldown               = 300
}

resource "aws_cloudwatch_metric_alarm" "cpu_low" {
  count               = local.asg_enabled
  alarm_name          = "${var.project_name}-backend-cpu-low"
  comparison_operator = "LessThanThreshold"
  evaluation_periods  = 10
  period              = 60
  threshold           = 25
  namespace           = "AWS/EC2"
  metric_name         = "CPUUtilization"
  statistic           = "Average"

  dimensions = {
    AutoScalingGroupName = aws_autoscaling_group.backend[0].name
  }

  alarm_actions = [aws_autoscaling_policy.scale_in_cpu[0].arn]

  tags = {
    Project = var.project_name
  }
}

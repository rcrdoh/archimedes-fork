# ─────────────────────────────────────────────────────────────────────────────
# CloudWatch monitoring — SNS alert topic, alarms, and an ops dashboard.
#
# ⚠️  AUTHORED OFFLINE — NOT yet `terraform plan`/`apply`-verified. This file was
#     written without AWS credentials in the authoring environment. Before
#     applying, run `terraform plan` from infra/ and review every resource.
#     These resources are ADDITIVE (apply creates new alarms/topic/dashboard and
#     does NOT modify or replace the existing EC2/ALB/Aurora/WAF resources), so
#     the blast radius of an apply is limited to new CloudWatch objects.
#
# Thresholds below are conservative first-cut defaults. Tune them against a few
# days of real CloudWatch baseline data — see infra/runbooks/disaster-recovery.md
# for the alarm philosophy. Nothing here is load-bearing for the app to run; it
# is purely observability + paging.
# ─────────────────────────────────────────────────────────────────────────────

variable "alarm_email" {
  description = "Email address subscribed to the CloudWatch alarm SNS topic. Leave empty to skip the subscription (alarms still fire to the topic; you can add subscribers later in the console)."
  type        = string
  default     = ""
}

# ── SNS alert topic ──────────────────────────────────────────────────────────

resource "aws_sns_topic" "alerts" {
  name = "${var.project_name}-alerts"
  tags = { Project = var.project_name }
}

# Optional email subscription. Created only when var.alarm_email is non-empty.
# AWS sends a confirmation email; the subscription is pending until confirmed.
resource "aws_sns_topic_subscription" "alerts_email" {
  count     = var.alarm_email == "" ? 0 : 1
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.alarm_email
}

# ── EC2 (application host) ───────────────────────────────────────────────────

resource "aws_cloudwatch_metric_alarm" "ec2_cpu_high" {
  alarm_name          = "${var.project_name}-ec2-cpu-high"
  alarm_description   = "EC2 host CPU > 85% for 10 min — app host saturated."
  namespace           = "AWS/EC2"
  metric_name         = "CPUUtilization"
  statistic           = "Average"
  comparison_operator = "GreaterThanThreshold"
  threshold           = 85
  period              = 300
  evaluation_periods  = 2
  dimensions          = { InstanceId = aws_instance.archimedes.id }
  alarm_actions       = [aws_sns_topic.alerts.arn]
  ok_actions          = [aws_sns_topic.alerts.arn]
  treat_missing_data  = "missing"
  tags                = { Project = var.project_name }
}

resource "aws_cloudwatch_metric_alarm" "ec2_status_check_failed" {
  alarm_name          = "${var.project_name}-ec2-status-check-failed"
  alarm_description   = "EC2 instance/system status check failed — host unhealthy."
  namespace           = "AWS/EC2"
  metric_name         = "StatusCheckFailed"
  statistic           = "Maximum"
  comparison_operator = "GreaterThanThreshold"
  threshold           = 0
  period              = 60
  evaluation_periods  = 3
  dimensions          = { InstanceId = aws_instance.archimedes.id }
  alarm_actions       = [aws_sns_topic.alerts.arn]
  ok_actions          = [aws_sns_topic.alerts.arn]
  treat_missing_data  = "breaching"
  tags                = { Project = var.project_name }
}

# ── ALB (edge) ───────────────────────────────────────────────────────────────

resource "aws_cloudwatch_metric_alarm" "alb_5xx_high" {
  alarm_name          = "${var.project_name}-alb-target-5xx-high"
  alarm_description   = "Backend returned > 10 5xx responses in 5 min."
  namespace           = "AWS/ApplicationELB"
  metric_name         = "HTTPCode_Target_5XX_Count"
  statistic           = "Sum"
  comparison_operator = "GreaterThanThreshold"
  threshold           = 10
  period              = 300
  evaluation_periods  = 1
  dimensions = {
    LoadBalancer = aws_lb.main.arn_suffix
    TargetGroup  = aws_lb_target_group.backend.arn_suffix
  }
  alarm_actions      = [aws_sns_topic.alerts.arn]
  ok_actions         = [aws_sns_topic.alerts.arn]
  treat_missing_data = "notBreaching"
  tags               = { Project = var.project_name }
}

resource "aws_cloudwatch_metric_alarm" "alb_unhealthy_hosts" {
  alarm_name          = "${var.project_name}-alb-unhealthy-hosts"
  alarm_description   = "One or more backend targets are unhealthy."
  namespace           = "AWS/ApplicationELB"
  metric_name         = "UnHealthyHostCount"
  statistic           = "Maximum"
  comparison_operator = "GreaterThanThreshold"
  threshold           = 0
  period              = 60
  evaluation_periods  = 3
  dimensions = {
    LoadBalancer = aws_lb.main.arn_suffix
    TargetGroup  = aws_lb_target_group.backend.arn_suffix
  }
  alarm_actions      = [aws_sns_topic.alerts.arn]
  ok_actions         = [aws_sns_topic.alerts.arn]
  treat_missing_data = "breaching"
  tags               = { Project = var.project_name }
}

resource "aws_cloudwatch_metric_alarm" "alb_latency_high" {
  alarm_name          = "${var.project_name}-alb-target-latency-high"
  alarm_description   = "p95 backend response time > 2s for 10 min."
  namespace           = "AWS/ApplicationELB"
  metric_name         = "TargetResponseTime"
  extended_statistic  = "p95"
  comparison_operator = "GreaterThanThreshold"
  threshold           = 2
  period              = 300
  evaluation_periods  = 2
  dimensions = {
    LoadBalancer = aws_lb.main.arn_suffix
    TargetGroup  = aws_lb_target_group.backend.arn_suffix
  }
  alarm_actions      = [aws_sns_topic.alerts.arn]
  ok_actions         = [aws_sns_topic.alerts.arn]
  treat_missing_data = "notBreaching"
  tags               = { Project = var.project_name }
}

# ── Aurora PostgreSQL ────────────────────────────────────────────────────────

resource "aws_cloudwatch_metric_alarm" "aurora_cpu_high" {
  alarm_name          = "${var.project_name}-aurora-cpu-high"
  alarm_description   = "Aurora CPU > 85% for 10 min."
  namespace           = "AWS/RDS"
  metric_name         = "CPUUtilization"
  statistic           = "Average"
  comparison_operator = "GreaterThanThreshold"
  threshold           = 85
  period              = 300
  evaluation_periods  = 2
  dimensions          = { DBClusterIdentifier = aws_rds_cluster.main.cluster_identifier }
  alarm_actions       = [aws_sns_topic.alerts.arn]
  ok_actions          = [aws_sns_topic.alerts.arn]
  treat_missing_data  = "missing"
  tags                = { Project = var.project_name }
}

# FreeableMemory is per-instance. ~256 MB floor is a conservative paging line for
# a Serverless-v2 instance; tune to your min ACU.
resource "aws_cloudwatch_metric_alarm" "aurora_low_memory" {
  alarm_name          = "${var.project_name}-aurora-low-freeable-memory"
  alarm_description   = "Aurora freeable memory < 256 MB — risk of OOM / connection churn."
  namespace           = "AWS/RDS"
  metric_name         = "FreeableMemory"
  statistic           = "Average"
  comparison_operator = "LessThanThreshold"
  threshold           = 268435456 # 256 MiB in bytes
  period              = 300
  evaluation_periods  = 2
  dimensions          = { DBInstanceIdentifier = aws_rds_cluster_instance.main.identifier }
  alarm_actions       = [aws_sns_topic.alerts.arn]
  ok_actions          = [aws_sns_topic.alerts.arn]
  treat_missing_data  = "missing"
  tags                = { Project = var.project_name }
}

resource "aws_cloudwatch_metric_alarm" "aurora_connections_high" {
  alarm_name          = "${var.project_name}-aurora-connections-high"
  alarm_description   = "Aurora DB connections > 80 — approaching pool/limit pressure."
  namespace           = "AWS/RDS"
  metric_name         = "DatabaseConnections"
  statistic           = "Average"
  comparison_operator = "GreaterThanThreshold"
  threshold           = 80
  period              = 300
  evaluation_periods  = 2
  dimensions          = { DBClusterIdentifier = aws_rds_cluster.main.cluster_identifier }
  alarm_actions       = [aws_sns_topic.alerts.arn]
  ok_actions          = [aws_sns_topic.alerts.arn]
  treat_missing_data  = "missing"
  tags                = { Project = var.project_name }
}

# ── Ops dashboard ────────────────────────────────────────────────────────────

resource "aws_cloudwatch_dashboard" "ops" {
  dashboard_name = "${var.project_name}-ops"
  dashboard_body = jsonencode({
    widgets = [
      {
        type = "metric", x = 0, y = 0, width = 12, height = 6,
        properties = {
          title   = "EC2 CPU",
          region  = var.aws_region,
          view    = "timeSeries",
          metrics = [["AWS/EC2", "CPUUtilization", "InstanceId", aws_instance.archimedes.id]]
        }
      },
      {
        type = "metric", x = 12, y = 0, width = 12, height = 6,
        properties = {
          title  = "ALB requests / 5xx",
          region = var.aws_region,
          view   = "timeSeries",
          metrics = [
            ["AWS/ApplicationELB", "RequestCount", "LoadBalancer", aws_lb.main.arn_suffix],
            ["AWS/ApplicationELB", "HTTPCode_Target_5XX_Count", "LoadBalancer", aws_lb.main.arn_suffix]
          ]
        }
      },
      {
        type = "metric", x = 0, y = 6, width = 12, height = 6,
        properties = {
          title   = "ALB target latency (p95)",
          region  = var.aws_region,
          view    = "timeSeries",
          stat    = "p95",
          metrics = [["AWS/ApplicationELB", "TargetResponseTime", "LoadBalancer", aws_lb.main.arn_suffix, "TargetGroup", aws_lb_target_group.backend.arn_suffix]]
        }
      },
      {
        type = "metric", x = 12, y = 6, width = 12, height = 6,
        properties = {
          title  = "Aurora CPU / connections",
          region = var.aws_region,
          view   = "timeSeries",
          metrics = [
            ["AWS/RDS", "CPUUtilization", "DBClusterIdentifier", aws_rds_cluster.main.cluster_identifier],
            ["AWS/RDS", "DatabaseConnections", "DBClusterIdentifier", aws_rds_cluster.main.cluster_identifier]
          ]
        }
      }
    ]
  })
}

# ── Log group retention (AUDIT I8) ──────────────────────────────────────────
# Without explicit log group resources, CloudWatch retains logs indefinitely
# (never expires) — unbounded cost and unnecessary data retention. 90 days is
# sufficient for post-incident forensics and covers any regulatory baseline.

resource "aws_cloudwatch_log_group" "app" {
  name              = "/archimedes/app"
  retention_in_days = 90
  tags              = { Project = var.project_name }
}

resource "aws_cloudwatch_log_group" "nginx" {
  name              = "/archimedes/nginx"
  retention_in_days = 90
  tags              = { Project = var.project_name }
}

# ── Outputs ──────────────────────────────────────────────────────────────────

output "alerts_topic_arn" {
  description = "SNS topic ARN for CloudWatch alarms. Subscribe additional endpoints (Slack via chatbot, PagerDuty, etc.) here."
  value       = aws_sns_topic.alerts.arn
}

output "ops_dashboard_name" {
  description = "CloudWatch dashboard name."
  value       = aws_cloudwatch_dashboard.ops.dashboard_name
}

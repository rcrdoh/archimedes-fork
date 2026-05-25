# Route 53 — archimedes-arc.app
# Domain registered via AWS CLI 2026-05-24; hosted zone auto-created by registrar.
# This file documents the resources as Terraform.

# The hosted zone is auto-created by Route 53 domain registration.
# Import with: terraform import aws_route53_zone.main Z03812612E5OLGK1YGZSR
resource "aws_route53_zone" "main" {
  name = "archimedes-arc.app"

  tags = {
    Project = var.project_name
  }

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_route53_record" "apex" {
  zone_id = aws_route53_zone.main.zone_id
  name    = "archimedes-arc.app"
  type    = "A"
  ttl     = 300
  records = [aws_instance.archimedes.public_ip]
}

# ── AWS WAF v2 ────────────────────────────────────────────────────────
#
# Attached to the ALB. Per the locked spec:
#   - Core Rule Set (AWSManagedRulesCommonRuleSet)
#   - Known Bad Inputs (AWSManagedRulesKnownBadInputsRuleSet)
#   - IP Reputation (AWSManagedRulesAmazonIpReputationList)
#   - SQL Database (AWSManagedRulesSQLiRuleSet)
#   - Rate-based rule: 1000 requests per 5 minutes per IP
#   - NO Bot Control (cost optimization)
#   - NO geo-blocking

resource "aws_wafv2_web_acl" "main" {
  name  = "${var.project_name}-waf"
  scope = "REGIONAL"

  default_action {
    allow {}
  }

  # ── Rate-based rule: 1000 req / 5 min / IP ────────────────

  rule {
    name     = "rate-limit"
    priority = 1

    action {
      block {}
    }

    statement {
      rate_based_statement {
        limit              = 1000
        aggregate_key_type = "IP"
      }
    }

    visibility_config {
      sampled_requests_enabled   = true
      cloudwatch_metrics_enabled = true
      metric_name                = "${var.project_name}-rate-limit"
    }
  }

  # ── AWS Managed Rules ──────────────────────────────────────

  rule {
    name     = "aws-core-rules"
    priority = 10

    override_action {
      none {} # BLOCK mode active (AUDIT I4)
    }

    statement {
      managed_rule_group_statement {
        vendor_name = "AWS"
        name        = "AWSManagedRulesCommonRuleSet"
      }
    }

    visibility_config {
      sampled_requests_enabled   = true
      cloudwatch_metrics_enabled = true
      metric_name                = "${var.project_name}-core-rules"
    }
  }

  rule {
    name     = "aws-known-bad-inputs"
    priority = 20

    override_action {
      none {} # BLOCK mode active (AUDIT I4)
    }

    statement {
      managed_rule_group_statement {
        vendor_name = "AWS"
        name        = "AWSManagedRulesKnownBadInputsRuleSet"
      }
    }

    visibility_config {
      sampled_requests_enabled   = true
      cloudwatch_metrics_enabled = true
      metric_name                = "${var.project_name}-known-bad-inputs"
    }
  }

  rule {
    name     = "aws-ip-reputation"
    priority = 30

    override_action {
      none {} # IP reputation can block immediately — known-bad IPs
    }

    statement {
      managed_rule_group_statement {
        vendor_name = "AWS"
        name        = "AWSManagedRulesAmazonIpReputationList"
      }
    }

    visibility_config {
      sampled_requests_enabled   = true
      cloudwatch_metrics_enabled = true
      metric_name                = "${var.project_name}-ip-reputation"
    }
  }

  rule {
    name     = "aws-sqli"
    priority = 40

    override_action {
      # BLOCK mode active (AUDIT #23). The SQLi managed rule group used to
      # false-positive on LLM prompt bodies; it now enforces, but a scope-down
      # statement below excludes the two LLM endpoints (/api/strategies/generate
      # and /api/chat) so legitimate prompt traffic on those paths is never
      # evaluated by — and therefore never blocked by — the SQLi rules.
      none {}
    }

    statement {
      managed_rule_group_statement {
        vendor_name = "AWS"
        name        = "AWSManagedRulesSQLiRuleSet"

        # Scope-down: only evaluate requests whose URI path is NOT one of the
        # LLM endpoints. LLM prompts routinely contain SQL-like tokens (SELECT,
        # quotes, UNION, --) that trip the SQLi signatures; excluding these two
        # paths lets the group block SQLi everywhere else while leaving the
        # prompt endpoints untouched. Exact-match on the path; the backend
        # routes are mounted at these literal paths.
        scope_down_statement {
          not_statement {
            statement {
              or_statement {
                statement {
                  byte_match_statement {
                    search_string         = "/api/strategies/generate"
                    positional_constraint = "EXACTLY"

                    field_to_match {
                      uri_path {}
                    }

                    text_transformation {
                      priority = 0
                      type     = "NONE"
                    }
                  }
                }

                statement {
                  byte_match_statement {
                    search_string         = "/api/chat"
                    positional_constraint = "EXACTLY"

                    field_to_match {
                      uri_path {}
                    }

                    text_transformation {
                      priority = 0
                      type     = "NONE"
                    }
                  }
                }
              }
            }
          }
        }
      }
    }

    visibility_config {
      sampled_requests_enabled   = true
      cloudwatch_metrics_enabled = true
      metric_name                = "${var.project_name}-sqli"
    }
  }

  visibility_config {
    sampled_requests_enabled   = true
    cloudwatch_metrics_enabled = true
    metric_name                = "${var.project_name}-waf"
  }

  tags = {
    Project = var.project_name
  }
}

# ── Associate WAF with ALB ───────────────────────────────────

resource "aws_wafv2_web_acl_association" "main" {
  resource_arn = aws_lb.main.arn
  web_acl_arn  = aws_wafv2_web_acl.main.arn
}

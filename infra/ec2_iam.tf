# ── EC2 instance role (SSM agent + Parameter Store secrets) ───────────
#
# Wires the single backend EC2 to AWS Systems Manager so:
#   - SSM SendCommand can target it (deploy.yml) — via AmazonSSMManagedInstanceCore
#   - the backend can read /archimedes/prod/* SecureString secrets at startup
#     (services/secrets_service.load_ssm_secrets) — scoped GetParameter* + kms:Decrypt
#
# Named `archimedes-ec2-role` to match the Bedrock-deny budget action target
# (infra/scripts/setup-budgets.sh DENY_TARGET_ROLE). Broader runtime perms (S3
# corpus artifacts, DynamoDB index, Bedrock invoke, CloudWatch Logs) are added
# as those features come online — see infra/iam/archimedes-backend-policy.json.
#
# NOTE: SSM SendCommand also needs the amazon-ssm-agent running on the box.
# Ubuntu 24.04 ships it via snap; ensure user-data.sh installs/enables it
# (`snap install amazon-ssm-agent --classic` or apt) before the first deploy.

resource "aws_iam_role" "ec2" {
  name = "archimedes-ec2-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
  tags = { Project = var.project_name }
}

# SSM agent registration + SendCommand targeting (AWS-managed policy).
resource "aws_iam_role_policy_attachment" "ec2_ssm_core" {
  role       = aws_iam_role.ec2.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

# Read app secrets from SSM Parameter Store + decrypt SecureString (scoped to
# the /archimedes/prod/* prefix and to KMS-via-SSM only).
resource "aws_iam_role_policy" "ec2_ssm_params" {
  name = "archimedes-ssm-parameter-read"
  role = aws_iam_role.ec2.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "ReadAppSecrets"
        Effect   = "Allow"
        Action   = ["ssm:GetParameter", "ssm:GetParameters", "ssm:GetParametersByPath"]
        Resource = "arn:aws:ssm:*:*:parameter/archimedes/prod/*"
      },
      {
        Sid      = "DecryptSecureStringViaSSM"
        Effect   = "Allow"
        Action   = "kms:Decrypt"
        Resource = "*"
        Condition = {
          StringEquals = { "kms:ViaService" = "ssm.${var.aws_region}.amazonaws.com" }
        }
      }
    ]
  })
}

resource "aws_iam_instance_profile" "ec2" {
  name = "archimedes-ec2-profile"
  role = aws_iam_role.ec2.name
}

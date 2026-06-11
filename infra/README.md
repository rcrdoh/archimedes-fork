# Archimedes Infrastructure

## Terraform State Backend (S3)

State is stored remotely in S3 with S3-native locking (Terraform 1.10+,
`use_lockfile = true`). The S3 bucket was created out-of-band via AWS
CLI (infrastructure-of-infrastructure — never changes, don't manage
with Terraform). No DynamoDB table needed.

### Bootstrap Commands (run once, already done)

```bash
# S3 bucket — versioned, encrypted, no public access
aws s3api create-bucket \
  --bucket archimedes-tfstate-159903201072 \
  --region eu-west-2 \
  --create-bucket-configuration LocationConstraint=eu-west-2

aws s3api put-bucket-versioning \
  --bucket archimedes-tfstate-159903201072 \
  --versioning-configuration Status=Enabled

aws s3api put-bucket-encryption \
  --bucket archimedes-tfstate-159903201072 \
  --server-side-encryption-configuration \
  '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}'

aws s3api put-public-access-block \
  --bucket archimedes-tfstate-159903201072 \
  --public-access-block-configuration \
  BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true

# Bucket policy: deny non-TLS + restrict to account only
aws s3api put-bucket-policy \
  --bucket archimedes-tfstate-159903201072 \
  --policy '{
    "Version": "2012-10-17",
    "Statement": [
      {"Sid":"DenyNonTLS","Effect":"Deny","Principal":"*","Action":"s3:*",
       "Resource":["arn:aws:s3:::archimedes-tfstate-159903201072","arn:aws:s3:::archimedes-tfstate-159903201072/*"],
       "Condition":{"Bool":{"aws:SecureTransport":"false"}}},
      {"Sid":"RestrictToAccount","Effect":"Deny","Principal":"*","Action":"s3:*",
       "Resource":["arn:aws:s3:::archimedes-tfstate-159903201072","arn:aws:s3:::archimedes-tfstate-159903201072/*"],
       "Condition":{"StringNotEquals":{"aws:PrincipalAccount":"159903201072"}}}
    ]}'
```

### Working with Terraform

```bash
cd infra/
terraform init          # Downloads providers, connects to S3 backend
terraform plan          # Preview changes (always do this first)
terraform apply         # Apply changes (requires confirmation)
```

### Admin Access (SSM Session Manager)

Once VPC migration is complete, admin access is via AWS SSM:

```bash
# Terminal session (replaces SSH)
aws ssm start-session --target i-<instance-id> --region eu-west-2

# Port forwarding to Aurora (database access from laptop)
aws ssm start-session \
  --target i-<instance-id> \
  --region eu-west-2 \
  --document-name AWS-StartPortForwardingSessionToRemoteHost \
  --parameters host=<aurora-endpoint>,portNumber=5432,localPortNumber=5432
```

## Branch Protection (`main`)

`main` is build-on-deploy: every push auto-deploys to the live EC2 host. The protection
ruleset is codified in [`scripts/setup-branch-protection.sh`](../scripts/setup-branch-protection.sh)
so an admin can apply or audit it declaratively (audit #10 / issues #519, #526).

```bash
./scripts/setup-branch-protection.sh            # dry-run: print the payload, apply nothing
./scripts/setup-branch-protection.sh --apply    # apply (needs repo admin)
./scripts/setup-branch-protection.sh --verify    # print the currently-applied protection
# or, raw:  gh api repos/hackagora/archimedes-arcadia/branches/main/protection
```

What it enforces: the two hard-block CI checks (`Backend — unit tests`, `Ruff — format +
critical lint rules`), 1 approving review, no force-push, no branch deletion, and
`required_linear_history: false` (we are **merge-commits-only** — linear history would
force squash/rebase). The informational checks (lint-report, complexity) stay non-required.

**Build-on-deploy tradeoff:** the script ships with `enforce_admins=false` so repo admins
(including the `t2o2` agentic user) keep their direct-push path while non-admins are gated.
Flipping `ENFORCE_ADMINS=true` gates everyone but forces the agentic system onto PRs — that
is a team decision (Chuan, as repo admin, owns it).

## Security Notes

- **No `.pem` files in git.** `infra/*.pem` is in `.gitignore`.
- **No Terraform state in git.** State is in S3; local files are gitignored.
- **SSH keys are rotated.** The key committed in early repo history was revoked
  on 2026-05-26. The current key exists only in GitHub Secrets + local machine.
- **Port 22 will be removed** once SSM Session Manager is live.

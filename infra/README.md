# Archimedes Infrastructure

## Local CLI tooling

The infra workflow needs three command-line tools. Two come from the `archimedes`
conda env (pinned in [`../environment.yml`](../environment.yml), so `conda env create`
gives everyone the same versions); the third is a Homebrew install because it is not
packaged on conda-forge.

| Tool | Version (verified) | How to install | Why |
| --- | --- | --- | --- |
| **Terraform** | 1.15.3 | conda env (`terraform>=1.10`) | IaC for the whole AWS stack (`infra/*.tf`). 1.10+ required for S3-native state locking (`use_lockfile=true`). |
| **AWS CLI v2** | 2.34.48 | conda env (`awscli>=2.15`) | Deploys, SSM sessions, and **`aws configure sso`** for IAM Identity Center. **v2 is required** — v1's SSO support is insufficient for the Identity Center login flow. |
| **AWS SAM CLI** | 1.162.1 | **Homebrew**: `brew install aws-sam-cli` (not on conda-forge) | Serverless build/deploy + `sam local` testing. Only needed if/when we add Lambda pieces — see note below. |

Run env-scoped tools with `conda run -n archimedes <cmd>` (or `conda activate archimedes`
first) so you are always on the pinned versions, not whatever is on the system PATH.

**On SAM's role:** the production stack is **ECS-on-EC2 + Aurora + ALB, managed by
Terraform** — Terraform is the IaC backbone and SAM does not replace it. SAM is
purpose-built for **Lambda / API Gateway serverless** apps and local Lambda emulation.
Treat it as *additive*: reach for it only when we introduce a concrete Lambda use-case
(e.g. an event-driven nanopayment-settlement hook, a scheduled job, or lightweight glue),
not as a second way to manage the core web tier. Until then it is installed-but-unused.

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

## Monitoring & Disaster Recovery

- **`cloudwatch.tf`** — SNS alert topic + alarms (EC2 CPU/status, ALB 5xx /
  unhealthy hosts / p95 latency, Aurora CPU / memory / connections) + an ops
  dashboard. Additive: `terraform apply` only *creates* new CloudWatch objects,
  it does not touch the existing EC2/ALB/Aurora/WAF resources. Set
  `alarm_email` (tfvars) to get paged. **Authored 2026-06-12, not yet
  `terraform plan`-verified** — review before applying.
- **`runbooks/disaster-recovery.md`** — RTO/RPO targets, per-scenario response
  (host loss, DB corruption, WAF lockout), restore-order, and a drill checklist.
- **`runbooks/aurora-backup-restore.md`** — exact PITR / snapshot-restore CLI
  (Aurora `backup_retention_period = 7` ⇒ 7-day PITR window already on).
- **`runbooks/waf-rules-reference.md`** — what each `waf.tf` rule does and the
  count→block promotion workflow.

> These runbooks are **authored, not drilled.** Run a game-day (see the DR
> drill checklist) before trusting the measured RTO/RPO.

## Per-deploy artifacts

- **`deploy_output.json`** (repo root) is written by
  [`backend/archimedes/scripts/deploy_contracts.py`](../backend/archimedes/scripts/deploy_contracts.py)
  on every contract deploy and goes stale the moment any contract is
  redeployed — it is gitignored and untracked (audit 06-14 finding I3: the
  previously-tracked copy's `synthTokens`/`synthOracles`/`vaults` addresses
  no longer matched the live deploy). It is per-deploy operator output, not a
  source of truth. The authoritative current addresses live in
  [`ui/src/config.js`](../ui/src/config.js) (frontend) and
  [`backend/archimedes/chain/client.py`](../backend/archimedes/chain/client.py)
  (backend) — update both of those after any redeploy.

## Security Notes

- **No `.pem` files in git.** `infra/*.pem` is in `.gitignore`.
- **No Terraform state in git.** State is in S3; local files are gitignored.
- **SSH keys are rotated.** The key committed in early repo history was revoked
  on 2026-05-26. The current key exists only in GitHub Secrets + local machine.
- **Port 22 will be removed** once SSM Session Manager is live.

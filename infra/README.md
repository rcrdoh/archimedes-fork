# Archimedes Infrastructure

## Terraform State Backend (S3 + DynamoDB)

State is stored remotely in S3 with DynamoDB locking. These resources
were created out-of-band via AWS CLI (they're infrastructure-of-
infrastructure — never change, don't try to manage them with Terraform).

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

# DynamoDB lock table
aws dynamodb create-table \
  --table-name archimedes-tfstate-lock \
  --attribute-definitions AttributeName=LockID,AttributeType=S \
  --key-schema AttributeName=LockID,KeyType=HASH \
  --billing-mode PAY_PER_REQUEST \
  --region eu-west-2
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

## Security Notes

- **No `.pem` files in git.** `infra/*.pem` is in `.gitignore`.
- **No Terraform state in git.** State is in S3; local files are gitignored.
- **SSH keys are rotated.** The key committed in early repo history was revoked
  on 2026-05-26. The current key exists only in GitHub Secrets + local machine.
- **Port 22 will be removed** once SSM Session Manager is live.

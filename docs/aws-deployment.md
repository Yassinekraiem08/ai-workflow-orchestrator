# AWS Deployment Guide

This document covers every step required to get the AI Workflow Orchestrator
running on AWS and to keep it there with automated deployments from GitHub Actions.

The infrastructure is entirely managed by Terraform and lives in the `terraform/`
directory. There are no click-ops steps.

---

## Prerequisites

| Tool | Version |
|---|---|
| AWS CLI | v2 |
| Terraform | >= 1.7 |
| Docker | >= 24 |

Configure the AWS CLI with credentials that have sufficient IAM permissions to
create the resources described below:

```bash
aws configure
# or, if using SSO:
aws sso login --profile your-profile
```

---

## 1. Create the Terraform state bucket

The S3 backend must exist before `terraform init` can run. Create it once:

```bash
aws s3 mb s3://ai-workflow-orchestrator-tfstate --region us-east-1

aws s3api put-bucket-versioning \
  --bucket ai-workflow-orchestrator-tfstate \
  --versioning-configuration Status=Enabled

aws s3api put-bucket-encryption \
  --bucket ai-workflow-orchestrator-tfstate \
  --server-side-encryption-configuration \
  '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}'
```

---

## 2. Create the ECR repository and push the initial image

Terraform references the ECR repository by name, but the ECS service cannot
start if no image exists. Bootstrap the repository and push a first image before
running `terraform apply`.

```bash
# Create the repository
aws ecr create-repository \
  --repository-name ai-workflow-orchestrator \
  --region us-east-1

# Authenticate Docker to ECR
aws ecr get-login-password --region us-east-1 \
  | docker login --username AWS --password-stdin \
    "$(aws sts get-caller-identity --query Account --output text).dkr.ecr.us-east-1.amazonaws.com"

# Build and push
ECR_URL="$(aws sts get-caller-identity --query Account --output text).dkr.ecr.us-east-1.amazonaws.com/ai-workflow-orchestrator"

docker build -t "$ECR_URL:latest" .
docker push "$ECR_URL:latest"
```

---

## 3. Populate terraform.tfvars

```bash
cd terraform
cp terraform.tfvars.example terraform.tfvars
```

Open `terraform.tfvars` and fill in every value. The file is git-ignored.
Never commit it.

---

## 4. Deploy the infrastructure

```bash
cd terraform

terraform init
terraform plan -out=tfplan
terraform apply tfplan
```

A successful apply prints the public URL:

```
Outputs:

alb_dns_name = "http://ai-workflow-orchestrator-production-alb-1234567890.us-east-1.elb.amazonaws.com"
```

The health endpoint is available immediately:

```bash
curl http://<alb_dns_name>/health
# {"status":"ok"}
```

---

## 5. Set up GitHub OIDC for Actions

GitHub Actions authenticates to AWS using short-lived OIDC tokens rather than
long-lived access keys. This requires a one-time setup.

### 5a. Register the GitHub OIDC provider in IAM

```bash
aws iam create-open-id-connect-provider \
  --url https://token.actions.githubusercontent.com \
  --client-id-list sts.amazonaws.com \
  --thumbprint-list 6938fd4d98bab03faadb97b34396831e3780aea1
```

This is idempotent — if the provider already exists the call returns an error
that can be safely ignored.

### 5b. Create the deployment IAM role

Create a file named `trust-policy.json`:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Federated": "arn:aws:iam::YOUR_ACCOUNT_ID:oidc-provider/token.actions.githubusercontent.com"
      },
      "Action": "sts:AssumeRoleWithWebIdentity",
      "Condition": {
        "StringEquals": {
          "token.actions.githubusercontent.com:aud": "sts.amazonaws.com"
        },
        "StringLike": {
          "token.actions.githubusercontent.com:sub": "repo:YOUR_GITHUB_ORG/AI_Workflow_Orchestrator:ref:refs/heads/main"
        }
      }
    }
  ]
}
```

Replace `YOUR_ACCOUNT_ID` and `YOUR_GITHUB_ORG` with the real values, then:

```bash
aws iam create-role \
  --role-name github-actions-deploy \
  --assume-role-policy-document file://trust-policy.json

# Attach the policies the workflow needs
aws iam attach-role-policy \
  --role-name github-actions-deploy \
  --policy-arn arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryPowerUser

aws iam attach-role-policy \
  --role-name github-actions-deploy \
  --policy-arn arn:aws:iam::aws:policy/AmazonECS_FullAccess
```

For a tighter permission boundary in production, replace the managed policies
above with a custom policy scoped to the specific ECR repository and ECS cluster.

---

## 6. Set GitHub repository secrets

Navigate to **Settings → Secrets and variables → Actions** and add:

| Secret | Value |
|---|---|
| `AWS_ROLE_ARN` | `arn:aws:iam::YOUR_ACCOUNT_ID:role/github-actions-deploy` |
| `AWS_REGION` | `us-east-1` |
| `ECR_REPOSITORY` | `ai-workflow-orchestrator` |

Push to `main` to trigger the first automated deployment.

---

## 7. Verifying the live deployment

```bash
ALB="http://ai-workflow-orchestrator-production-alb-<hash>.us-east-1.elb.amazonaws.com"

# Health (no auth required)
curl "$ALB/health"
# → {"status":"ok"}

# Get a JWT from your API key
TOKEN=$(curl -s -X POST "$ALB/auth/token" \
  -H "X-API-Key: your-api-key-here" | jq -r .access_token)

# Submit a test workflow
curl -X POST "$ALB/workflows/submit" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "input_type": "log",
    "raw_input": "ERROR: DB connection timeout at 03:14 UTC",
    "priority": 2
  }'

# OpenAPI docs
open "$ALB/docs"
```

---

## 8. Running the evaluation harness against the deployed stack

```bash
EVAL_HOST="$ALB" EVAL_API_KEY="your-api-key-here" python scripts/eval.py
```

---

## 9. Tearing down

```bash
cd terraform
terraform destroy
```

This removes every resource managed by Terraform. The S3 state bucket is not
managed by Terraform and must be deleted separately if desired:

```bash
aws s3 rb s3://ai-workflow-orchestrator-tfstate --force
```

---

## 10. Estimated monthly cost

All figures are us-east-1 on-demand prices as of early 2025.

| Resource | Spec | Cost/month |
|---|---|---|
| ECS Fargate — API | 0.5 vCPU / 1 GiB, 1 task | ~$15 |
| ECS Fargate — Worker | 1 vCPU / 2 GiB, 1 task | ~$30 |
| RDS PostgreSQL | db.t3.micro, 20 GiB gp2 | ~$15 |
| ElastiCache Redis | cache.t3.micro | ~$12 |
| ALB | 1 LCU baseline | ~$18 |
| ECR storage | < 1 GiB | < $1 |
| CloudWatch logs | 30-day retention | ~$1 |
| **Total** | | **~$91** |

No NAT Gateway is provisioned, saving ~$32/month. ECS tasks use public IPs
with security groups restricting inbound access to the ALB.

Switching to `db.t3.micro` Graviton2 (`db.t4g.micro`) reduces the RDS line by
roughly 20 % with no other changes required.

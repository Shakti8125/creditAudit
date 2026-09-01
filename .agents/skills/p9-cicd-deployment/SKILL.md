---
name: p9-cicd-deployment
description: >-
  Use this skill to build the CI/CD pipeline and AWS deployment for ModelAudit AI Phase 9.
---
# Phase 9: CI/CD Pipeline and AWS Deployment

This skill instructs you to build the CI/CD pipeline and AWS deployment.

## Steps

### 1. PR Quality Gates
Create `.github/workflows/ci.yml`:
- Trigger: `pull_request` on `main` and `develop`
- Jobs:
  - `lint`: Run `ruff check backend/` and `mypy backend/app/`
  - `test`: Run `pytest backend/tests/ -v` with PostgreSQL and Redis service containers
  - `security`: Run `pip-audit` and `trivy image` scan
  - `docker-build`: Build backend and frontend Docker images (no push)
- All jobs must pass for PR to be mergeable.

### 2. Staging Deploy
Create `.github/workflows/deploy-staging.yml`:
- Trigger: `push` to `develop`
- Steps: Build Docker -> push to ECR -> update ECS Fargate staging -> run Alembic migrations -> health check
- Uses GitHub Actions secrets for AWS credentials.

### 3. Production Deploy
Create `.github/workflows/deploy-production.yml`:
- Trigger: `push` to `main`
- Requires `environment: production` (manual approval in GitHub)
- Steps: Re-tag staging image -> update ECS prod -> migrations -> smoke test -> rollback on failure.

### 4. Nightly Evaluation
Create `.github/workflows/nightly-eval.yml`:
- Trigger: `schedule: cron '0 2 * * *'`
- Run privacy adversarial tests, retrieval quality checks
- Post results to GitHub Actions summary.

### 5. PR Template
Create `.github/PULL_REQUEST_TEMPLATE.md` with checklist:
- [ ] Tests pass locally
- [ ] No new security vulnerabilities
- [ ] Privacy pipeline leak rate = 0%
- [ ] Docker build succeeds
- [ ] Documentation updated

### 6. Dependabot
Create `.github/dependabot.yml`:
- Auto dependency updates for pip and npm.

### 7. ECS Fargate Task Definition
Create `deploy/aws/task-definition.json`:
- Backend container: 0.5 vCPU, 1GB RAM, port 8001.
- Environment variables from AWS SSM Parameter Store.
- Health check: `GET /health`

### 8. VPC Security Group Rules
Create `deploy/aws/security-groups.json`:
- ALB ingress: 443 from 0.0.0.0/0
- ECS ingress: 8001 from ALB security group only
- RDS ingress: 5432 from ECS security group only

### 9. Seed Demo Users
Create `backend/scripts/seed_demo_users.py`:
- Seed 2 demo tenant accounts:
  - Tenant A: "Alpha Bank" (PROFESSIONAL tier) with analyst user
  - Tenant B: "Beta Financial" (ENTERPRISE tier) with analyst user
- Used for demos and integration testing.

## Verification
Push PR -> CI runs -> all green. Merge to develop -> staging deploys. Approve -> production deploys.

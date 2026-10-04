# Archived: the AWS deployment

**Retired 2026-10-02 (owner decision D12).** The AWS account was deactivated after the always-on stack used up its credits. The backend now runs locally, only to demo, and nothing paid runs anywhere. See [../../qa/aws-cost-report-2026-10-02.md](../../qa/aws-cost-report-2026-10-02.md) for what the stack cost and why, and [../../qa/aws-exit-and-rescope-plan.md](../../qa/aws-exit-and-rescope-plan.md) for the decision and its consequences.

These files are kept as history (the stack ran on ECS Fargate behind an ALB with RDS PostgreSQL, deployed from GitHub Actions in September 2026). They are **not** run: GitHub only runs workflow files under `.github/workflows/`.

| File | What it was |
|---|---|
| [deployment_steps.md](deployment_steps.md) | The deployment guide and runbook (VPC, NAT gateways, RDS, ECR, ECS, ALB, alarms). The demo credentials and the real bank's name were removed when it was archived (QA-024). |
| [workflows/deploy-production.aws.yml](workflows/deploy-production.aws.yml) | Push to `main`: build and push the image to ECR, run `alembic upgrade head` as a one-off ECS task, roll the service. Its `frontend` job also deployed to Vercel, which Vercel's own Git integration already does. |
| [workflows/deploy-staging.aws.yml](workflows/deploy-staging.aws.yml) | The same for a `develop` branch. It never ran. |

## Re-enabling it (not planned)

1. Recreate the stack from `deployment_steps.md`. Expect roughly **$205 a month** for the documented layout (see the cost report), and read the cost report's lessons first.
2. Restore the repository secrets the workflows read: `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_PROD_PRIVATE_SUBNET`, `AWS_PROD_ECS_SG`, `AWS_STAGING_PRIVATE_SUBNET`, `AWS_STAGING_ECS_SG`, and the three `VERCEL_*` secrets for the frontend job.
3. `git mv` the two workflow files back into `.github/workflows/` (dropping the `.aws` suffix).

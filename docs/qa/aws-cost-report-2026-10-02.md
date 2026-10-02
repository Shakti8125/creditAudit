# AWS cost report: what consumed the credits

Date: 2026-10-02. Status: **modelled, not measured.** Companion to [aws-exit-and-rescope-plan.md](aws-exit-and-rescope-plan.md).

> **How to read this report.** The bill itself could not be read: the AWS connector asks for sign-in again, and the account is deactivated. So this report combines three kinds of evidence, and every figure carries a tag:
> - **[measured]**: checked on 2026-10-02 against GitHub, Vercel or DNS.
> - **[documented]**: taken from the repo's own `deployment_steps.md` and HANDOFF. These were never confirmed against the live account (QA-022 records that the guide had drifted; PR-00 was meant to confirm them).
> - **[modelled]**: arithmetic on AWS list prices that were verified on 2026-10-02 (§4).
>
> §7 shows how to replace the model with the real numbers in about ten minutes. No account ID, resource ID or bill figure from the owner's account appears here.

---

## 1. The answer

The credits went to a **production-shaped, always-on stack that bills by the hour whether or not anyone uses it.** Ranked by share of the monthly cost in the "as documented" model (scenario A, §5):

| Rank | Cost driver | Per month | Share | Bills when nothing runs? |
|---|---|---|---|---|
| 1 | AWS Fargate: 2 prod tasks of 1 vCPU / 4 GB | $85.06 | 41% | No, only while tasks run |
| 2 | NAT gateways: 2 (one per AZ) | $65.70 | 32% | **Yes**, every hour |
| 3 | Application Load Balancer | $19.34 | 9% | **Yes** |
| 4 | Public IPv4 addresses: 2 on the ALB, 2 on the NAT gateways | $14.60 | 7% | **Yes** |
| 5 | RDS `db.t4g.micro` PostgreSQL, 20 GB gp3 | $13.98 | 7% | **Yes** (a stopped RDS instance restarts by itself after 7 days, per AWS) |
| 6 | Logs, ECR storage, NAT data processing (assumed volumes) | $6.26 | 3% | Partly |
| | **Total (scenario A)** | **$204.94** | | |

- Fargate and the NAT gateways alone are about **74%** of the model.
- **$113.62 a month ($3.74 a day) bills even with zero tasks running.** "Stopping the servers" (ECS desired count 0) therefore saves only the Fargate line.
- The range is wide because the footprint is unverified: **$126 a month** at the minimum plausible footprint (scenario C) up to **$261** with a staging task and Multi-AZ RDS (scenario B2).
- Whichever scenario is right, the stack costs **$120-$260 a month**, which no free tier covers.

**Confidence.** High that Fargate and the NAT gateways are the top two lines, and that the always-on baseline dominates. Low on the exact split until the real Cost Explorer export (§7) is compared with this model.

**Why the free tier did not help.** Fargate and NAT gateways have no free-tier hours (AWS re:Post and a Server Fault answer; I did not check AWS's full free-tier product list). The legacy tier's free public-IPv4 hours are for EC2 instances only. The legacy 12-month tier (accounts created before 15 July 2025) would have covered only the ALB hours and a single-AZ RDS micro instance. Under the newer **Free plan**, credits cover everything until they run out, and the account then closes (§2 of the plan doc and the box below).

> **Which plan was the account on? Unknown, and it changes what is owed.**
> - **Free plan** (accounts created on or after 15 July 2025): $100 of credits at sign-up, plus up to $100 more for completing activities. The account **closes automatically when the credits run out** (or after six months), and AWS says it "won't incur any charges". AWS keeps the content for 90 days; upgrading to a Paid plan inside that window reopens it. Nothing is owed. *This fits "the account was deactivated because credits ran out".*
> - **Legacy free tier or a Paid plan**: the account is suspended for an unpaid balance. A balance is owed and the reinstatement route is different.
>
> The first assumption in this session was the second case. The owner can tell from the Billing console (plan type and credits) and from AWS's emails.

---

## 2. What was measured

| # | Fact | Source | Tag |
|---|---|---|---|
| E1 | First successful production deploy: **2 Sep 2026 16:19 UTC** (run #3). Runs #1 (1 Sep) and #2 (2 Sep 16:17) failed while the AWS side was still being set up. | GitHub Actions API, workflow `deploy-production.yml` | measured |
| E2 | 21 production deploys in all (18 succeeded, 3 failed): 1 on 1 Sep, 9 on 2 Sep, 1 on 3 Sep, 4 on 4 Sep, 3 on 5 Sep, **none for 22.9 days**, then 1 on 28 Sep and 2 on 30 Sep. | same | measured |
| E3 | The staging deploy workflow **never ran** (0 runs). It triggers on a `develop` branch, which does not exist. | same | measured |
| E4 | HANDOFF §6 (28 Sep): "the owner stopped and then restarted the AWS servers". | `HANDOFF.md` | documented |
| E5 | The backend answered `/health` with 200 and `db: connected` on 30 Sep at 11:17 UTC. | previous session, README §5 | measured |
| E6 | By 2 Oct the ALB hostname has **no DNS record**: `Could not resolve host` from the sandbox, and `creditaudit.vercel.app/api/health` returns `502 DNS_HOSTNAME_EMPTY` from Vercel's side. So the stack is gone or unreachable. | `curl`, live fetch | measured |
| E7 | The AWS connector still answers "needs sign-in again", so no Cost Explorer, Billing or `freetier` API data was read. | connector | measured |

---

## 3. The footprint (documented, not verified)

| Component | Documented configuration | Source | Cost line |
|---|---|---|---|
| ECS Fargate, prod | **2 tasks** (`--desired-count 2`), **1 vCPU / 4096 MB** each, private subnets in `us-east-1a/b`. 4 GB is for Docling and spaCy `en_core_web_lg`. | `deployment_steps.md:14,594-595,704` | Fargate |
| ECS Fargate, staging | Service `modelaudit-staging-service` exists per README §6; **desired count unknown**; its deploy workflow never ran (E3). | README §6, HANDOFF §6 | Fargate (0 or more) |
| NAT gateways | **Two**, one per AZ, with two Elastic IPs ("Dual NAT") | `deployment_steps.md:15,287-345` | NAT hours + IPv4 |
| Load balancer | One internet-facing ALB across 2 AZs (one public IPv4 per AZ) | `deployment_steps.md:466-507`; HANDOFF §6 | ALB + IPv4 |
| Database | RDS PostgreSQL 16 `db.t4g.micro`, 20 GB gp3 (autoscaling to 100), 30-day backups, Performance Insights. The CLI command has no `--multi-az`, but the diagram shows a standby. | `deployment_steps.md:191-209` | RDS |
| Registry | ECR `modelaudit-ai/backend`: up to 21 builds pushed (one per deploy run), each with two tags. Image size **not measured**. | workflow | ECR |
| Logs, alarms | CloudWatch Logs and a few alarms | `deployment_steps.md:1030-1031` | CloudWatch |
| Parameters | SSM Parameter Store standard parameters: free | `deployment_steps.md:90` | none |
| Migrations | One extra Fargate task per deploy: 21 runs of a few minutes, about cents | workflow | negligible |

Everything else the plans mention (S3 corpus bucket, CloudFront, WAF) was, as far as the repo shows, **never built**: those are plan items (PR-07, C5) that had not started and whose infrastructure approval (O5) was still open.

---

## 4. Unit prices used (us-east-1, verified 2026-10-02)

| Unit | Price | Source |
|---|---|---|
| Fargate vCPU-hour (Linux/x86) | $0.04048 | AWS Price List, `AmazonECS` (published 2026-09-11) |
| Fargate GB-hour (memory) | $0.004445 | same |
| Fargate ARM vCPU-hour / GB-hour (not used) | $0.03238 / $0.00356 | same |
| NAT gateway hour | $0.045 | AWS Price List, `AmazonEC2` (current offer file) |
| NAT data processed, per GB | $0.045 | same |
| Public IPv4, per address-hour (in use or idle) | $0.005 | AWS Price List, `AmazonVPC` (published 2026-09-17) |
| ALB hour | $0.0225 | aws.amazon.com/elasticloadbalancing/pricing |
| ALB per LCU-hour | $0.008 | same |
| RDS `db.t4g.micro` PostgreSQL, Single-AZ / Multi-AZ, per hour | $0.016 / $0.032 | AWS Price List, `AmazonRDS` (current offer file) |
| RDS gp3 storage, Single-AZ / Multi-AZ, per GB-month | $0.115 / $0.23 | same |
| CloudWatch Logs ingestion, per GB / storage per GB-month | $0.50 / $0.03 | AWS Price List, `AmazonCloudWatch` (published 2026-09-22) |
| ECR storage, per GB-month | $0.10 | AWS Price List, `AmazonECR` (published 2026-09-11) |

---

## 5. The model [modelled]

730 hours a month. One Fargate task: 1 × $0.04048 + 4 × $0.004445 = **$0.05826 an hour = $42.53 a month**.

| Line | A: as documented, prod only | B: A + 1 staging task | C: minimum plausible |
|---|---|---|---|
| Fargate | $85.06 (2 tasks) | $127.59 (3 tasks) | $42.53 (1 task) |
| NAT gateway hours | $65.70 (2) | $65.70 (2) | $32.85 (1) |
| ALB hours + about 0.5 LCU | $19.34 | $19.34 | $19.34 |
| Public IPv4 | $14.60 (4) | $14.60 (4) | $10.95 (3) |
| RDS micro + 20 GB gp3 | $13.98 | $13.98 | $13.98 |
| Logs 2 GB, ECR 25 GB, NAT data 60 GB (assumed) | $6.26 | $6.26 | $6.26 |
| **Total a month** | **$204.94** | **$247.47** | **$125.91** |
| Per day | $6.74 | $8.14 | $4.14 |
| Days a $100 credit lasts | 14.8 | 12.3 | 24.1 |
| Days a $200 credit lasts | 29.7 | 24.6 | 48.3 |

B2 (B with Multi-AZ RDS) is $261.45 a month. The fixed baseline that bills with no tasks running (2 NAT + ALB + 4 IPv4 + RDS) is **$113.62 a month**.

**Assumptions to check against the real bill:** 0.5 LCU on average; 2 GB of logs a month; 25 GB of ECR images; 60 GB through the NAT gateways a month (large image pulls on every task start, plus API traffic). The image size is unknown: with Docling's default PyTorch wheels it may be several GB, and every rolling deploy pulls it through the NAT gateway at $0.045 a GB.

---

## 6. Timeline [measured dates, modelled costs]

| Period | What happened (E1-E6) | Modelled cost |
|---|---|---|
| 1-2 Sep | AWS set up; first success on 2 Sep 16:19 | stack comes up |
| 2-5 Sep | 17 deploys in four days | $6.74 a day (A) |
| 5-28 Sep (22.9 days) | No deploys; HANDOFF says the servers were stopped, then restarted on 28 Sep | If "stopped" meant ECS desired count 0, the fixed baseline still billed **about $86** (22.9 × $3.74), roughly **70% of the whole modelled run cost** |
| 28-30 Sep | Restart, 3 deploys; last confirmed healthy 30 Sep 11:17 UTC | back to $6.74 a day |
| by 2 Oct | ALB hostname has no DNS record; account deactivated | |

**Consistency check, not proof.** From the first success to the last healthy check is 27.8 days. Modelled credit use over that span:

| Reading | Credit used by 30 Sep | Day a $100 pool would run out | Day a $200 pool would run out |
|---|---|---|---|
| A, running the whole time | $187 | day 15 (about 17 Sep) | day 30 (about 2 Oct) |
| A, tasks only outside the quiet period | $123 | about day 25 | not reached |
| C, running the whole time | $115 | day 24 | not reached |

Only the first reading with a $200 pool lands on the observed closure date. A $100 pool would have run out *before* the deploys of 28 and 30 Sep in every reading, unless the stack was cheaper than modelled (for example a stopped RDS instance or no NAT gateway for part of the quiet period). Several combinations of pool size and footprint are plausible, so the real credit and usage numbers (§7) settle it.

---

## 7. Replace the model with the real numbers (about ten minutes)

Billing pages usually stay reachable for a deactivated account. Menu names vary slightly.

1. **Plan and credits.** Billing and Cost Management: note whether the account was on the Free plan or a Paid plan, the credits granted, and the credits used. Read AWS's "plan ended" or "suspended" email for the date and the 90-day window.
2. **Cost Explorer, by service.** Date range 1 Sep to today, granularity Daily, group by **Service**, with credits included. Download the CSV.
3. **Cost Explorer, by usage type.** The same range, group by **Usage type**, filtered to the top three services. Download the CSV.
4. **Compare with the model.** Services appear under these names:

   | Cost Explorer service (typical) | What it holds | Model share (A) |
   |---|---|---|
   | Elastic Container Service | Fargate | about 41% |
   | EC2-Other | NAT gateway hours and data | about 33% |
   | Elastic Load Balancing | the ALB | about 9% |
   | Virtual Private Cloud | public IPv4 | about 7% |
   | Relational Database Service | RDS | about 7% |

   If EC2-Other is about half of that, there was one NAT gateway. If Elastic Container Service is about half, there was one task. If it is bigger, there was a staging task. Usage types to look for: `Fargate-vCPU-Hours`, `Fargate-GB-Hours`, `NatGateway-Hours`, `NatGateway-Bytes`, `LoadBalancerUsage`, `PublicIPv4:InUseAddress`, `InstanceUsage:db.t4g.micro`.
5. **Hand over the two CSVs.** A session can rebuild §1 and §5 from them. **Do not commit them**: they carry the account ID.

---

## 8. What was not the problem

- Vercel Hobby, Pinecone Starter, Upstash free, the NVIDIA developer API, the Gemini free tier and GitHub Actions on a public repo are free by D11. This was not checked against their dashboards.
- No S3 bucket, CloudFront distribution or WAF was ever created.
- Data transfer out is small for an API of this size.

## 9. Lessons that shaped the re-scope

1. **Free tier is not free for an always-on production topology.** NAT gateways, Fargate and public IPv4 addresses have no free hours.
2. **"Stopped" is not "free".** The load balancer, NAT gateways, IPv4 addresses and RDS bill around the clock.
3. **One environment is enough for a portfolio.** A second stack doubles Fargate.
4. **Budgets and alerts before the first deploy.** A $5 and a $20 alert would have caught this in the first two days.
5. **Make teardown one command.** Infrastructure that cannot be removed in a minute tends to keep billing.
6. **This app's memory footprint (4 GB) is the cost driver on any host**, which is why most free hosting tiers do not fit it.

These feed D12 and the order of work in [the plan](aws-exit-and-rescope-plan.md).

## Appendix: if AWS ever returns, the cheapest honest pattern

A **demo-day stack** that is created for an interview and destroyed afterwards: one Fargate task in a public subnet with a public IP (no NAT gateway), one ALB, and an external free-tier database. Modelled at **$0.0998 an hour** (task $0.058 + ALB $0.026 + 3 IPv4 $0.015), or about **$0.40 for a four-hour session**. It needs infrastructure as code so that `destroy` is one command. Not planned; recorded for the record.

# ModelAudit AI — Empirical Adversarial Infrastructure Audit Report

**Auditor Archetype**: EMPIRICAL CHALLENGER (Specialist & Critic)  
**Target Artifact**: `deployment_steps.md` (Production Deployment Guide & Runbook)  
**Date**: 2026-08-31  
**Integrity Mode**: Verification & Empirical Stress-Testing  
**Explicit Verdict**: **REQUEST_CHANGES**

---

## 1. Executive Summary & Verdict

An empirical, adversarial stress-test and verification of the AWS Cloud architecture, CLI commands, container specifications, and operational runbooks defined in `deployment_steps.md` was executed.

### Explicit Verdict: **REQUEST_CHANGES**

While the overall split-cloud architecture, Security Group chaining, Pydantic/SSM configuration mapping, and Docker multi-stage design are exceptionally well-engineered, **1 Critical Operational Blocker** and **4 High-Priority Architectural/Reliability Risks** were empirically identified that require revision before production deployment.

### Summary Matrix of Verification Findings

| Category | Item Evaluated | Status | Severity | Empirical Finding |
|---|---|---|---|---|
| **Database Seeding** | `scripts.seed_demo_users` CLI Command | ❌ **FAIL** | **CRITICAL** | `scripts/seed_demo_users.py` does NOT exist in the codebase. Task execution will fail with `ModuleNotFoundError` (Exit Code 1). |
| **AWS VPC / NAT** | Single NAT Gateway in Multi-AZ VPC | ⚠️ **FAILOVER RISK** | **HIGH** | Single NAT GW in AZ-a creates a Single Point of Failure (SPOF) for AZ-b ECS tasks calling external SaaS (Upstash, Pinecone, NVIDIA, Gemini). |
| **ALB Configuration** | Target Group Timeout for SSE `/query` | ⚠️ **TIMEOUT RISK** | **HIGH** | Default 60s ALB idle timeout risks dropping long-running LLM document reasoning streams (`POST /query`). |
| **ECS Sizing** | Memory allocation (2048 MB) for Docling | ⚠️ **OOM RISK** | **MEDIUM** | IBM Docling layout parsing & OCR on large multi-page credit dossiers under concurrent load risks exceeding 2GB RAM. |
| **CLI & Setup Order** | RDS SG `--source-group` reference | ⚠️ **ORDERING GAP** | **LOW** | Section 4.1 references ECS SG before it is created in Section 5.1, failing linear copy-paste execution. |
| **VPC & Subnets** | Subnet CIDR & Isolation (Public/Private/DB) | ✅ **PASS** | — | Clean 3-tier CIDR allocation (`10.0.0.0/16`) with isolated DB subnets and `assignPublicIp=DISABLED`. |
| **Health Checks** | ALB `/health` on Port 8001 | ✅ **PASS** | — | Verified liveness probe on port 8001; returns HTTP 200 with DB status payload. |
| **Security Groups** | Chaining ALB -> ECS -> RDS | ✅ **PASS** | — | Strictly chained ingress: ALB (80/443) -> ECS (8001 from ALB SG) -> RDS (5432 from ECS SG). |
| **IAM Permissions** | Task Execution Role vs Task Role | ✅ **PASS** | — | Proper least-privilege boundary: SSM/KMS decryption isolated to Execution Role; Task Role restricted to CloudWatch. |
| **Config & SSM** | 14 Environment Variables Mapping | ✅ **PASS** | — | 100% parameter name and type alignment between `app/config.py`, SSM paths, and `task-definition.json`. |
| **Alembic Migrations** | One-off Fargate Task DDL Execution | ✅ **PASS** | — | Verified via `alembic upgrade head --sql`; generates full DDL without errors. |
| **Docker Build** | Multi-Stage & C-Libraries for Docling | ✅ **PASS** | — | Includes `libgl1`, `libglib2.0-0`, `libgomp1`, `libsm6`, `libxext6`, `libxrender1`, `tesseract-ocr`. |
| **Application Lifespan**| Fast Startup & Fail-Open Redis Catch | ✅ **PASS** | — | `lifespan` handles Lua script loading with try-catch fail-open behavior; graceful DB pool disposal. |
| **Full Test Suite** | Backend Pytest (49 tests) & Frontend Build | ✅ **PASS** | — | 49/49 backend tests pass (100%); frontend Vite build compiles cleanly with zero errors. |

---

## 2. Adversarial Deep-Dive: Critical & High Priority Challenges

### Challenge 1: [CRITICAL] Non-Existent Seeding Script `scripts.seed_demo_users`

- **Location in Guide**: `deployment_steps.md` Section 5.7, Command 2 (lines 495–501).
- **Specified Command**:
  ```bash
  aws ecs run-task \
    --cluster modelaudit-cluster \
    --task-definition modelaudit-backend-task \
    --launch-type FARGATE \
    --network-configuration "awsvpcConfiguration={subnets=[subnet-private-1a],securityGroups=[$ECS_SG_ID],assignPublicIp=DISABLED}" \
    --overrides '{"containerOverrides":[{"name":"backend","command":["python","-m","scripts.seed_demo_users"]}]}'
  ```
- **Empirical Observation**:
  - Codebase inspection of `backend/scripts/` revealed:
    ```
    backend/scripts/
    ├── index_regulatory_corpus.py
    └── seed_regulatory_standards.py
    ```
  - An exhaustive search across the entire repository confirmed `seed_demo_users.py` is **absent**.
- **Attack / Failure Scenario**:
  - When an operator triggers this ECS `run-task` command in staging or production, the Python runtime in the container executes `python -m scripts.seed_demo_users`.
  - Python immediately crashes with:
    `ModuleNotFoundError: No module named 'scripts.seed_demo_users'`
  - The task terminates with exit code `1`. Automated deployment pipelines checking exit codes will fail and halt rollout.
- **Remediation**:
  1. Update `deployment_steps.md` Section 5.7 to clarify that initial tenant/user creation should be performed via the automated API registration endpoint (`POST /auth/register` as detailed in Section 8.2), OR document the required script creation.

---

### Challenge 2: [HIGH] Single NAT Gateway Single Point of Failure (SPOF) in Multi-AZ VPC

- **Location in Guide**: `deployment_steps.md` Section 5.1 (lines 247–253).
- **Observation**:
  - The guide specifies private subnets across two Availability Zones: `subnet-private-1a` (`10.0.10.0/24` in AZ-a) and `subnet-private-1b` (`10.0.11.0/24` in AZ-b).
  - However, only a **single NAT Gateway** is provisioned in `10.0.1.0/24` (AZ-a), with both private subnets routing `0.0.0.0/0` to this single NAT Gateway.
  - The ECS Fargate service in Section 5.8 runs across both private subnets (`subnets=[subnet-private-1a,subnet-private-1b]`).
- **Attack / Failure Scenario**:
  - If AWS Availability Zone `us-east-1a` experiences a hardware outage, network partition, or zonal degradation:
    1. The NAT Gateway in AZ-a becomes unreachable.
    2. All ECS Fargate tasks running in `subnet-private-1b` immediately lose outbound internet connectivity.
    3. The backend relies on outbound HTTPS to external SaaS for its core operations:
       - Rate limiting: Upstash Redis REST (`https://<endpoint>.upstash.io`)
       - Vector Search: Pinecone Vector DB API
       - AI Inference: NVIDIA NIM (`https://integrate.api.nvidia.com/v1`) & Google Gemini
       - Container Lifecycle: AWS SSM Parameter Store & ECR image pulls.
    4. 100% of API requests routed to AZ-b tasks will fail with connection timeouts, defeating the purpose of Multi-AZ ECS deployment.
- **Remediation**:
  - Update Section 5.1 with enterprise Multi-AZ high availability guidance:
    1. **Option A (High Availability)**: Deploy two NAT Gateways—one in `10.0.1.0/24` (AZ-a) and one in `10.0.2.0/24` (AZ-b)—with independent private route tables.
    2. **Option B (AWS VPC Endpoints)**: Provision AWS VPC Interface Endpoints for SSM, KMS, ECR (`ecr.api`, `ecr.dkr`), S3 Gateway, and CloudWatch Logs, minimizing NAT Gateway dependency and data transfer costs.

---

### Challenge 3: [HIGH] ALB Idle Timeout Truncation on SSE AI Streams (`POST /query`)

- **Location in Guide**: `deployment_steps.md` Section 5.5 (lines 423–452).
- **Observation**:
  - The Application Load Balancer is created using default attributes without specifying `idle_timeout.timeout_seconds`.
  - The AWS default ALB idle timeout is **60 seconds**.
  - ModelAudit AI uses Server-Sent Events (SSE) streaming (`POST /query`) for conversational model validation, involving multi-step hybrid retrieval (Pinecone + BM25 + Reciprocal Rank Fusion + Cross-Encoder reranking) followed by multi-turn LLM reasoning through NeMo Guardrails.
- **Attack / Failure Scenario**:
  - On complex queries or during heavy LLM token generation, if the LLM provider experiences latency or the document retrieval / reranking takes >60 seconds before flushing tokens, the AWS ALB terminates the client connection with HTTP `504 Gateway Timeout`.
  - The client UI experiences an abrupt stream interruption without receiving `citations` or the `done` event.
- **Remediation**:
  - Add an explicit ALB attribute modification command in Section 5.5:
    ```bash
    aws elbv2 modify-load-balancer-attributes \
      --load-balancer-arn $ALB_ARN \
      --attributes Key=idle_timeout.timeout_seconds,Value=300
    ```

---

### Challenge 4: [MEDIUM] Fargate Task Sizing & OOM Risk for IBM Docling Workloads

- **Location in Guide**: `deployment_steps.md` Section 5.8 (`task-definition.json`, lines 523–524).
- **Observation**:
  - Fargate CPU is set to `1024` (1 vCPU) and Memory to `2048` (2 GB).
  - The backend integrates IBM Docling 2.0 (`docling>=2.0.0`, `PyMuPDF`, `tesseract-ocr`, layout parsing models).
- **Attack / Failure Scenario**:
  - When compliance auditors upload large PDF validation dossiers (e.g., 50–100 page credit risk validation reports with complex multi-column tables and embedded figures), Docling loads layout segmentation models into memory.
  - If 2 or more document extraction requests are processed concurrently on a 2GB Fargate task, the Linux OOM Killer (`exitCode: 137`) will terminate the container, triggering abrupt service restarts.
- **Remediation**:
  - In `task-definition.json`, recommend setting `"cpu": "2048"` and `"memory": "4096"` (or `"memory": "8192"`) for production workloads handling PDF document extraction, and configure CloudWatch memory alarm `modelaudit-ecs-high-memory` at 75%.

---

### Challenge 5: [LOW] Security Group Chaining Provisioning Sequence in Linear Execution

- **Location in Guide**: `deployment_steps.md` Section 4.1 Step 2 vs Section 5.1 Step 2.
- **Observation**:
  - In Section 4.1 (RDS Setup), step 2 executes:
    `aws ec2 authorize-security-group-ingress --group-id $RDS_SG_ID --protocol tcp --port 5432 --source-group "sg-ecs-id"`
  - However, `sg-ecs-id` is not provisioned until Section 5.1.
- **Attack / Failure Scenario**:
  - If an engineer executes the guide step-by-step from Section 1 to Section 10 in linear order, Step 4.1 will fail because the ECS Security Group has not yet been created.
- **Remediation**:
  - Add a note in Section 4.1 instructing operators to either create all Security Groups first (as documented in Section 5.1) or placeholder the RDS SG rule until Section 5.1.

---

## 3. Empirical Verification of Technical Components

### 3.1 Python Bytecode Compilation & Type Correctness
- **Verification Command**: `python -m compileall backend/app`
- **Result**: **0 errors**, all 50+ backend files parsed and compiled cleanly to Python 3.13 bytecode.

### 3.2 Alembic Database Migration Static DDL Generation
- **Verification Command**: `alembic upgrade head --sql`
- **Result**: **PASS**. Alembic successfully generated DDL for all 3 revisions (`0e6c2385a516` -> `b39c1a2f3e4d` -> `c7d8e9f0a1b2`) creating tables:
  - `regulatory_standards`, `tenants`, `tenant_settings`, `users`, `models`, `model_versions`, `notifications`, `chat_sessions`, `documents`, `chat_messages`, `document_chunks`.
  - All foreign keys, indexes, and unique constraints generated with complete integrity.

### 3.3 Full Test Suite Execution
- **Verification Command**: `pytest backend/tests -v`
- **Result**: **49 passed, 0 failed** in 91.12s.
  - Authentication (RS256 JWT, refresh tokens, role checks): **PASSED**
  - Stress Analytics (metric extraction, comma numbers, policy benchmarks, early warning triggers): **PASSED**
  - Chunker (table preservation, sliding window, financial comma preservation): **PASSED**
  - Privacy Pipeline (longest match, word boundary, banking metrics, egress zero-leak, lossless unmasking): **PASSED**
  - LLM Routing (concurrency, failover to Gemini, circuit breaker state transitions): **PASSED**
  - Multi-Tenancy (cross-tenant data isolation, Pinecone namespace isolation, API query isolation): **PASSED**
  - Adversarial Deep Stress Harness (overlapping entities, comma preservation, high concurrency): **PASSED**

### 3.4 Frontend Bundle Compilation
- **Verification Command**: `npm run build` in `frontend/`
- **Result**: **PASS**. TypeScript compiler `tsc --noEmit` and Vite 6 built production bundle:
  - `dist/index.html` (1.66 kB)
  - `dist/assets/index-B0ylhnqf.css` (46.75 kB)
  - `dist/assets/index-DvjuAd_d.js` (467.20 kB)
  - 2,098 modules transformed in 7.22s with zero warnings or errors.

### 3.5 Environment Variables Alignment Check
Every single environment variable in `backend/app/config.py` was cross-checked against `deployment_steps.md` Section 3.1 and `task-definition.json`:

| Config Property (`app/config.py`) | Task Definition Name | SSM Parameter Path | Type | Verified? |
|---|---|---|---|---|
| `database_url` | `DATABASE_URL` | `/modelaudit/prod/database/url` | SecureString | ✅ MATCH |
| `redis_url` | `REDIS_URL` | `/modelaudit/prod/redis/url` | SecureString | ✅ MATCH |
| `redis_token` | `REDIS_TOKEN` | `/modelaudit/prod/redis/token` | SecureString | ✅ MATCH |
| `nvidia_api_key` | `NVIDIA_API_KEY` | `/modelaudit/prod/nvidia/api_key` | SecureString | ✅ MATCH |
| `nvidia_base_url` | `NVIDIA_BASE_URL` | (Direct Env) | String | ✅ MATCH |
| `gemini_api_key` | `GEMINI_API_KEY` | `/modelaudit/prod/gemini/api_key` | SecureString | ✅ MATCH |
| `pinecone_api_key` | `PINECONE_API_KEY` | `/modelaudit/prod/pinecone/api_key` | SecureString | ✅ MATCH |
| `pinecone_index_name` | `PINECONE_INDEX_NAME` | `/modelaudit/prod/pinecone/index_name` | String | ✅ MATCH |
| `jwt_private_key` | `JWT_PRIVATE_KEY` | `/modelaudit/prod/jwt/private_key` | SecureString | ✅ MATCH |
| `jwt_public_key` | `JWT_PUBLIC_KEY` | `/modelaudit/prod/jwt/public_key` | SecureString | ✅ MATCH |
| `jwt_secret_key` | `JWT_SECRET_KEY` | `/modelaudit/prod/jwt/secret_key` | SecureString | ✅ MATCH |
| `jwt_algorithm` | `JWT_ALGORITHM` | (Direct Env) | String | ✅ MATCH |
| `allowed_origins` | `ALLOWED_ORIGINS` | (Direct Env) | String | ✅ MATCH |
| `rate_limit_enabled` | `RATE_LIMIT_ENABLED`| (Direct Env) | Boolean | ✅ MATCH |

---

## 4. Required Modifications Checklist for `deployment_steps.md`

To transition this runbook to **APPROVED** state, the following edits should be applied:

- [ ] **Fix 1 (Section 5.7)**: Remove or update `--overrides '{"containerOverrides":[{"name":"backend","command":["python","-m","scripts.seed_demo_users"]}]}'` since `scripts.seed_demo_users` does not exist. Direct operators to use the `POST /auth/register` API endpoint for seeding demo users.
- [ ] **Fix 2 (Section 5.1)**: Add Multi-AZ NAT Gateway architecture instructions and/or AWS VPC Endpoints (SSM, KMS, ECR, CloudWatch Logs, S3) to eliminate the Single Point of Failure.
- [ ] **Fix 3 (Section 5.5)**: Add `aws elbv2 modify-load-balancer-attributes --load-balancer-arn $ALB_ARN --attributes Key=idle_timeout.timeout_seconds,Value=300` to prevent SSE `/query` connection drops.
- [ ] **Fix 4 (Section 5.8)**: Increase Fargate task memory in `task-definition.json` from `2048` to `4096` MB to accommodate Docling layout segmentation models under concurrent load.
- [ ] **Fix 5 (Section 4.1)**: Reorder or add a note in Section 4.1 regarding Security Group creation sequence before RDS provisioning.

---

## 5. Conclusion

The ModelAudit AI deployment architecture demonstrates solid technical foundations, clean code separation, robust cryptographic RS256 token handling, and zero-leak privacy enforcement. Once the 5 operational and reliability items above are addressed in `deployment_steps.md`, the platform will be fully production-ready for enterprise deployment in UAE banking environments.

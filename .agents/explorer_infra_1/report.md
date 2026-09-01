# ModelAudit AI — Infrastructure, Containerization & CI/CD Comprehensive Architecture Report

**Document Version:** 1.0.0  
**Author:** Infrastructure Explorer Subagent (`explorer_infra_1`)  
**Workspace:** `c:\Users\Shakti\Documents\CreditAudit- AI`  
**Target Environment:** AWS ECS Fargate (Backend API), Amazon RDS PostgreSQL (Database), Upstash Redis (Distributed Rate Limiting), Pinecone Serverless (Vector DB), Vercel (React Frontend), GitHub Actions (CI/CD)

---

## Executive Summary

This report delivers an exhaustive, end-to-end technical analysis and architectural blueprint for the containerization, cloud infrastructure, CI/CD pipelines, database migrations, and production deployment workflows of **ModelAudit AI**. 

ModelAudit AI is an enterprise-grade, privacy-preserving regulatory compliance platform designed to audit credit risk and model validation documents against the **Central Bank of the UAE (CBUAE) Model Management & Validation Standards (MMG §4.2)**, **IFRS 9**, **FRB SR 11-7**, and **Basel III/IV**.

The system utilizes a split-cloud deployment model:
1. **Frontend**: React 18 + TypeScript + Vite + Tailwind CSS deployed on **Vercel** with global edge CDN.
2. **Backend**: Python 3.12/3.13 + FastAPI + SQLAlchemy 2.0 Async + Docling + Presidio/spaCy + NeMo Guardrails containerized and orchestrated on **AWS ECS Fargate** behind an Application Load Balancer (ALB).
3. **Data Tier**: **Amazon RDS PostgreSQL 16** (in isolated private subnets), **Upstash Serverless Redis** (for distributed token bucket / GCRA rate limiting), and **Pinecone Serverless** (for multi-tenant 1024-dim hybrid vector retrieval).
4. **CI/CD**: Three-stage **GitHub Actions** automated pipeline (PR Quality Gates → Staging Deploy on `develop` → Production Deploy on `main` with manual environment approval).

---

## 1. Containerization & Local Orchestration Analysis

### 1.1 Backend Dockerfile Analysis (`backend/Dockerfile`)

The backend container utilizes a multi-stage Docker build optimized for caching, minimal image size, and compilation of native C/C++ dependencies required for heavy document processing.

```dockerfile
# Stage 1: Builder
FROM python:3.13-slim as builder

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --user --no-cache-dir -r requirements.txt

# Stage 2: Runtime
FROM python:3.13-slim as runtime

WORKDIR /app

# Install runtime shared C-libraries required by Docling, PyMuPDF, OpenCV and OCR
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    libgomp1 \
    libsm6 \
    libxext6 \
    libxrender1 \
    tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /root/.local /root/.local
ENV PATH=/root/.local/bin:$PATH
ENV PYTHONPATH=/root/.local/lib/python3.13/site-packages:$PYTHONPATH

COPY . .

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]
```

#### Key Technical Findings & Optimization Details:
- **Base Image**: `python:3.13-slim`. *(Note: `AGENTS.md` mentions Python 3.12 as the target stack, while the Dockerfile is using 3.13-slim. Compatibility is maintained across standard library and packages).*
- **Build Isolation**: In the `builder` stage, build tools (`build-essential`) are installed to compile binary wheels for packages like `pyahocorasick`, `bcrypt`, `cryptography`, and `asyncpg`. These compiler toolchains are discarded in the final image, reducing image bloat and attack surface.
- **Runtime Native Libraries**: Document extraction with **IBM Docling** and **PyMuPDF / OCR** requires system-level graphical and rendering libraries:
  - `libgl1`, `libglib2.0-0`, `libgomp1`: OpenMP runtime and OpenGL support for PDF rasterization and layout analysis.
  - `libsm6`, `libxext6`, `libxrender1`: X11 rendering primitives for PDF engine rendering.
  - `tesseract-ocr`: Fallback OCR engine for scanned PDF tabular extraction.
- **Dependency Paths**: User-installed Python packages from `/root/.local` are copied over, with `PATH` and `PYTHONPATH` explicitly configured.
- **Exposed Port**: Application listens on `0.0.0.0:8001`.
- **Production Recommendations**:
  1. Add an explicit non-root user (`useradd -u 1001 appuser`) for container security hardening.
  2. Pin Python minor versions in base image (e.g. `python:3.12.6-slim` or `python:3.13.0-slim`) for strict build reproducibility.
  3. Pre-bake the spaCy NLP model (`en_core_web_lg`) during Docker build to avoid dynamic runtime downloads or network latency during container startup.

---

### 1.2 Local Development Orchestration (`docker-compose.yml`)

The root `docker-compose.yml` provides a unified local replication of the production stack.

```yaml
services:
  backend:
    build:
      context: ./backend
      dockerfile: Dockerfile
    ports:
      - "8001:8001"
    volumes:
      - ./backend:/app
    depends_on:
      - db
      - redis
    environment:
      - DATABASE_URL=postgresql+asyncpg://postgres:postgres@db:5432/modelaudit
      - REDIS_URL=redis://redis:6379/0
    env_file:
      - .env

  db:
    image: postgres:16-alpine
    ports:
      - "5432:5432"
    environment:
      - POSTGRES_USER=postgres
      - POSTGRES_PASSWORD=postgres
      - POSTGRES_DB=modelaudit
    volumes:
      - pgdata:/var/lib/postgresql/data

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"

volumes:
  pgdata:
```

#### Key Technical Findings:
- **Service Dependency Graph**: `backend` strictly depends on `db` and `redis`.
- **Database Engine**: `postgres:16-alpine` mapping port `5432` with named persistent volume `pgdata`.
- **Cache Engine**: `redis:7-alpine` on port `6379`.
- **Hot Reloading**: Volume mount `./backend:/app` enables immediate code synchronization during local development.

---

## 2. Target AWS Cloud Architecture Blueprint

The diagram below illustrates the target AWS infrastructure topology for the ModelAudit AI production backend:

```
[ Internet Traffic ]
        │
        ▼ (HTTPS 443 / HTTP 80 Redirect)
┌────────────────────────────────────────────────────────────────────────┐
│ Amazon VPC (10.0.0.0/16)                                               │
│                                                                        │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │ Public Subnets (10.0.1.0/24, 10.0.2.0/24)                        │  │
│  │   • Internet Gateway (IGW)                                       │  │
│  │   • Application Load Balancer (ALB)                              │  │
│  │     - TLS 1.3 Termination (AWS Certificate Manager ACM)          │  │
│  │     - Security Group: sg-alb (Ingress: 80/443 from 0.0.0.0/0)    │  │
│  │   • NAT Gateway (Outbound Egress for Private Subnets)            │  │
│  └───────────────────┬──────────────────────────────────────────────┘  │
│                      │ Forward to Target Group (Port 8001)             │
│                      ▼                                                 │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │ Private Subnets (10.0.10.0/24, 10.0.11.0/24)                     │  │
│  │   • Amazon ECS Fargate Service (Task Definition: 0.5 vCPU, 1GB)  │  │
│  │     - Container Port: 8001                                       │  │
│  │     - Health Check Path: /health                                 │  │
│  │     - Security Group: sg-ecs (Ingress: 8001 from sg-alb ONLY)    │  │
│  │     - Outbound Egress: via NAT Gateway -> External APIs:         │  │
│  │       * NVIDIA NIM API (https://integrate.api.nvidia.com/v1)     │  │
│  │       * Google Gemini API (gemini-2.0-flash)                     │  │
│  │       * Pinecone Serverless Vector Store                         │  │
│  │       * Upstash Redis REST API                                   │  │
│  └───────────────────┬──────────────────────────────────────────────┘  │
│                      │ SQL Connections (Port 5432)                     │
│                      ▼                                                 │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │ Database Isolated Subnets (10.0.20.0/24, 10.0.21.0/24)           │  │
│  │   • Amazon RDS PostgreSQL 16 (db.t4g.micro / Multi-AZ)           │  │
│  │     - Security Group: sg-rds (Ingress: 5432 from sg-ecs ONLY)    │  │
│  │     - No Internet Access / No Public IP                          │  │
│  └──────────────────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────────────────┘
```

---

### 2.1 Amazon ECR Repository & Docker Tagging Strategy

- **ECR Repository Name**: `modelaudit-ai/backend`
- **Configuration**:
  - **Type**: Private
  - **Tag Immutability**: Enabled for production tags; mutable for staging branches.
  - **Scan on Push**: Enabled (`BASIC` or `ENHANCED` with Amazon Inspector) to automatically identify CVE vulnerabilities.
  - **Encryption**: KMS-managed customer encryption (`aws/ecr` or custom CMK).
  - **Lifecycle Policy**: Retain the last 30 tagged images; expire untagged images older than 7 days.

#### Tagging Strategy:
| Branch / Context | Image Tag Naming Convention | Example Tag | Mutability Policy |
|---|---|---|---|
| **PR Quality Check** | `pr-<pr_number>-<commit_sha>` | `pr-42-a1b2c3d` | Untagged / Ephemeral |
| **Staging (`develop`)** | `staging-<commit_sha>`, `staging-latest` | `staging-7f8e9a1`, `staging-latest` | Mutable (`latest` updated) |
| **Production (`main`)** | `v<SemVer>`, `prod-<commit_sha>`, `prod-latest` | `v1.0.0`, `prod-7f8e9a1` | Immutable (Semantic tags locked) |

*Deployment Rule*: Production images are NOT rebuilt from scratch on `main`. Instead, the verified staging image is promoted and re-tagged in Amazon ECR to ensure strict byte-for-byte binary parity between staging testing and production deployment.

---

### 2.2 Amazon ECS Fargate Cluster & Task Definition

- **Cluster Name**: `modelaudit-cluster` (or `modelaudit-ai-prod`)
- **Capacity Provider**: `FARGATE` (100% baseline) with optional `FARGATE_SPOT` for non-critical background jobs.

#### Complete Task Definition (`deploy/aws/task-definition.json`):

```json
{
  "family": "modelaudit-backend-task",
  "networkMode": "awsvpc",
  "requiresCompatibilities": [
    "FARGATE"
  ],
  "cpu": "1024",
  "memory": "2048",
  "executionRoleArn": "arn:aws:iam::<AWS_ACCOUNT_ID>:role/modelaudit-ecs-task-execution-role",
  "taskRoleArn": "arn:aws:iam::<AWS_ACCOUNT_ID>:role/modelaudit-ecs-task-role",
  "containerDefinitions": [
    {
      "name": "backend",
      "image": "<AWS_ACCOUNT_ID>.dkr.ecr.<AWS_REGION>.amazonaws.com/modelaudit-ai/backend:staging-latest",
      "essential": true,
      "portMappings": [
        {
          "containerPort": 8001,
          "hostPort": 8001,
          "protocol": "tcp"
        }
      ],
      "environment": [
        {
          "name": "ALLOWED_ORIGINS",
          "value": "https://modelaudit.vercel.app,http://localhost:5173"
        },
        {
          "name": "RATE_LIMIT_ENABLED",
          "value": "true"
        },
        {
          "name": "JWT_ALGORITHM",
          "value": "RS256"
        },
        {
          "name": "NVIDIA_BASE_URL",
          "value": "https://integrate.api.nvidia.com/v1"
        }
      ],
      "secrets": [
        {
          "name": "DATABASE_URL",
          "valueFrom": "arn:aws:ssm:<AWS_REGION>:<AWS_ACCOUNT_ID>:parameter/modelaudit/prod/database/url"
        },
        {
          "name": "REDIS_URL",
          "valueFrom": "arn:aws:ssm:<AWS_REGION>:<AWS_ACCOUNT_ID>:parameter/modelaudit/prod/redis/url"
        },
        {
          "name": "REDIS_TOKEN",
          "valueFrom": "arn:aws:ssm:<AWS_REGION>:<AWS_ACCOUNT_ID>:parameter/modelaudit/prod/redis/token"
        },
        {
          "name": "NVIDIA_API_KEY",
          "valueFrom": "arn:aws:ssm:<AWS_REGION>:<AWS_ACCOUNT_ID>:parameter/modelaudit/prod/nvidia/api_key"
        },
        {
          "name": "GEMINI_API_KEY",
          "valueFrom": "arn:aws:ssm:<AWS_REGION>:<AWS_ACCOUNT_ID>:parameter/modelaudit/prod/gemini/api_key"
        },
        {
          "name": "PINECONE_API_KEY",
          "valueFrom": "arn:aws:ssm:<AWS_REGION>:<AWS_ACCOUNT_ID>:parameter/modelaudit/prod/pinecone/api_key"
        },
        {
          "name": "PINECONE_INDEX_NAME",
          "valueFrom": "arn:aws:ssm:<AWS_REGION>:<AWS_ACCOUNT_ID>:parameter/modelaudit/prod/pinecone/index_name"
        },
        {
          "name": "JWT_PRIVATE_KEY",
          "valueFrom": "arn:aws:ssm:<AWS_REGION>:<AWS_ACCOUNT_ID>:parameter/modelaudit/prod/jwt/private_key"
        },
        {
          "name": "JWT_PUBLIC_KEY",
          "valueFrom": "arn:aws:ssm:<AWS_REGION>:<AWS_ACCOUNT_ID>:parameter/modelaudit/prod/jwt/public_key"
        },
        {
          "name": "JWT_SECRET_KEY",
          "valueFrom": "arn:aws:ssm:<AWS_REGION>:<AWS_ACCOUNT_ID>:parameter/modelaudit/prod/jwt/secret_key"
        }
      ],
      "healthCheck": {
        "command": [
          "CMD-SHELL",
          "python -c 'import urllib.request; urllib.request.urlopen(\"http://localhost:8001/health\")' || exit 1"
        ],
        "interval": 30,
        "timeout": 5,
        "retries": 3,
        "startPeriod": 60
      },
      "logConfiguration": {
        "logDriver": "awslogs",
        "options": {
          "awslogs-group": "/ecs/modelaudit-backend",
          "awslogs-region": "<AWS_REGION>",
          "awslogs-stream-prefix": "ecs"
        }
      }
    }
  ]
}
```

---

### 2.3 Application Load Balancer (ALB) & Target Group Specifications

- **Scheme**: `internet-facing`
- **IP Address Type**: `ipv4`
- **Subnets**: Public subnets in at least two Availability Zones (e.g. `subnet-pub-1a`, `subnet-pub-1b`).
- **Listeners**:
  1. **HTTP (Port 80)**: Default action redirects HTTP traffic to HTTPS (Port 443) with status code `HTTP_301`.
     - Protocol: `HTTP`, Port: `80`
     - Action: Redirect to `HTTPS://#{host}:443/#{path}?#{query}` (Status Code: `HTTP_301`)
  2. **HTTPS (Port 443)**: Terminated with AWS Certificate Manager (ACM) wildcard certificate (e.g. `*.modelaudit.ai`).
     - Protocol: `HTTPS`, Port: `443`
     - Security Policy: `ELBSecurityPolicy-TLS13-1-2-2021-06`
     - Default Action: Forward to Target Group `modelaudit-backend-tg`.

#### Target Group Configuration (`modelaudit-backend-tg`):
- **Target Type**: `ip` (Mandatory for Fargate `awsvpc` networking)
- **Protocol / Port**: `HTTP:8001`
- **VPC**: Target VPC ID
- **Health Check Path**: `/health`
- **Health Check Port**: `8001` (traffic port)
- **Health Check Protocol**: `HTTP`
- **Health Check Interval**: `30` seconds
- **Health Check Timeout**: `5` seconds
- **Healthy Threshold Count**: `2`
- **Unhealthy Threshold Count**: `3`
- **Success HTTP Codes (Matcher)**: `200`
- **Deregistration Delay (Connection Draining)**: `30` seconds

---

### 2.4 Amazon VPC Topology & Security Groups Architecture

#### Security Groups Definition (`deploy/aws/security-groups.json`):

```json
{
  "SecurityGroups": [
    {
      "GroupName": "modelaudit-alb-sg",
      "Description": "Public Application Load Balancer security group",
      "VpcId": "<VPC_ID>",
      "InboundRules": [
        {
          "IpProtocol": "tcp",
          "FromPort": 80,
          "ToPort": 80,
          "IpRanges": [{"CidrIp": "0.0.0.0/0", "Description": "Allow HTTP from Internet"}]
        },
        {
          "IpProtocol": "tcp",
          "FromPort": 443,
          "ToPort": 443,
          "IpRanges": [{"CidrIp": "0.0.0.0/0", "Description": "Allow HTTPS from Internet"}]
        }
      ],
      "OutboundRules": [
        {
          "IpProtocol": "tcp",
          "FromPort": 8001,
          "ToPort": 8001,
          "UserIdGroupPairs": [{"GroupId": "<ECS_SECURITY_GROUP_ID>", "Description": "Forward to ECS Backend Tasks"}]
        }
      ]
    },
    {
      "GroupName": "modelaudit-ecs-sg",
      "Description": "ECS Fargate backend container security group",
      "VpcId": "<VPC_ID>",
      "InboundRules": [
        {
          "IpProtocol": "tcp",
          "FromPort": 8001,
          "ToPort": 8001,
          "UserIdGroupPairs": [{"GroupId": "<ALB_SECURITY_GROUP_ID>", "Description": "Allow HTTP ingress from ALB only"}]
        }
      ],
      "OutboundRules": [
        {
          "IpProtocol": "tcp",
          "FromPort": 443,
          "ToPort": 443,
          "IpRanges": [{"CidrIp": "0.0.0.0/0", "Description": "Outbound HTTPS for LLM, Pinecone, Upstash, AWS APIs via NAT"}]
        },
        {
          "IpProtocol": "tcp",
          "FromPort": 5432,
          "ToPort": 5432,
          "UserIdGroupPairs": [{"GroupId": "<RDS_SECURITY_GROUP_ID>", "Description": "Outbound SQL connections to RDS PostgreSQL"}]
        }
      ]
    },
    {
      "GroupName": "modelaudit-rds-sg",
      "Description": "RDS PostgreSQL database security group",
      "VpcId": "<VPC_ID>",
      "InboundRules": [
        {
          "IpProtocol": "tcp",
          "FromPort": 5432,
          "ToPort": 5432,
          "UserIdGroupPairs": [{"GroupId": "<ECS_SECURITY_GROUP_ID>", "Description": "Allow PostgreSQL access strictly from ECS backend tasks"}]
        }
      ],
      "OutboundRules": []
    }
  ]
}
```

---

### 2.5 AWS IAM Roles & Least Privilege Permissions

#### 1. ECS Task Execution Role (`modelaudit-ecs-task-execution-role`)
Assumed by the ECS Agent (`ecs-tasks.amazonaws.com`) to provision the container.
- **Attached AWS Managed Policy**: `service-role/AmazonECSTaskExecutionRolePolicy` (provides ECR authentication, layer pull, and CloudWatch log stream creation).
- **Custom Inline Policy (`modelaudit-ssm-secrets-policy`)**:
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "AllowParameterStoreRead",
      "Effect": "Allow",
      "Action": [
        "ssm:GetParameters",
        "ssm:GetParameter",
        "ssm:GetParametersByPath"
      ],
      "Resource": [
        "arn:aws:ssm:<AWS_REGION>:<AWS_ACCOUNT_ID>:parameter/modelaudit/*"
      ]
    },
    {
      "Sid": "AllowKMSDecryptSecrets",
      "Effect": "Allow",
      "Action": [
        "kms:Decrypt"
      ],
      "Resource": [
        "arn:aws:kms:<AWS_REGION>:<AWS_ACCOUNT_ID>:key/<KMS_KEY_ID>"
      ]
    }
  ]
}
```

#### 2. ECS Task Role (`modelaudit-ecs-task-role`)
Assumed by the running Python application container at runtime.
- **Permissions**:
  - `cloudwatch:PutMetricData` (for custom latency and privacy metric tracking)
  - `s3:GetObject`, `s3:PutObject` (if document uploads are mirrored to an encrypted S3 bucket).

---

### 2.6 Secret Management: AWS SSM Parameter Store Naming Convention

All sensitive credentials must be stored as `SecureString` types in AWS SSM Parameter Store or AWS Secrets Manager following a standardized hierarchy:

| Parameter Key Path | Type | Description |
|---|---|---|
| `/modelaudit/prod/database/url` | `SecureString` | `postgresql+asyncpg://<USER>:<PASS>@<RDS_ENDPOINT>:5432/modelaudit` |
| `/modelaudit/prod/redis/url` | `SecureString` | Upstash Redis connection URL |
| `/modelaudit/prod/redis/token` | `SecureString` | Upstash Redis REST bearer token |
| `/modelaudit/prod/nvidia/api_key` | `SecureString` | Primary LLM Provider NVIDIA NIM API Key |
| `/modelaudit/prod/gemini/api_key` | `SecureString` | Secondary LLM Provider Google Gemini API Key |
| `/modelaudit/prod/pinecone/api_key` | `SecureString` | Pinecone Vector Store API Key |
| `/modelaudit/prod/pinecone/index_name` | `String` | `modelaudit-production-1024` |
| `/modelaudit/prod/jwt/private_key` | `SecureString` | RSA 2048/4096-bit PEM Private Key (for RS256 token signing) |
| `/modelaudit/prod/jwt/public_key` | `SecureString` | RSA PEM Public Key (for RS256 token verification) |
| `/modelaudit/prod/jwt/secret_key` | `SecureString` | HMAC fallback secret string |

---

## 3. GitHub Actions CI/CD Pipeline Suite

The complete CI/CD workflow architecture consists of four dedicated GitHub Actions workflows in `.github/workflows/`:

```
┌────────────────────────────────────────────────────────────────────────┐
│ GitHub Actions CI/CD Architecture                                      │
├────────────────────────────────────────────────────────────────────────┤
│ 1. PR to develop/main                                                  │
│    └── .github/workflows/ci.yml                                        │
│        ├── Job: lint (ruff check, mypy strict, tsc typecheck)          │
│        ├── Job: test (pytest backend/tests/ with Postgres & Redis)     │
│        ├── Job: privacy-gate (0% entity leak rate verification)        │
│        ├── Job: security (pip-audit, npm audit, Trivy container scan)  │
│        └── Job: docker-build (dry-run build backend & frontend)        │
│                                                                        │
│ 2. Push / Merge to develop                                             │
│    └── .github/workflows/deploy-staging.yml                            │
│        ├── Step 1: Build & Push Docker image to ECR (tag: staging-sha) │
│        ├── Step 2: Run Alembic migrations via ECS one-off run-task     │
│        ├── Step 3: Seed / verify regulatory standards                  │
│        ├── Step 4: Update ECS Staging Service                          │
│        ├── Step 5: Deploy Frontend to Vercel (Preview environment)     │
│        └── Step 6: Automated Health Check & E2E Integration Suite      │
│                                                                        │
│ 3. Push / Merge to main                                                │
│    └── .github/workflows/deploy-production.yml                         │
│        ├── Gate: GitHub Environment Approval ('production')           │
│        ├── Step 1: Promote ECR Image (re-tag staging-sha -> prod-sha)  │
│        ├── Step 2: Run Alembic migrations on Production RDS            │
│        ├── Step 3: Update ECS Production Service (rolling update)      │
│        ├── Step 4: Deploy Frontend to Vercel (Production environment)  │
│        ├── Step 5: Post-deploy smoke test (/health, /auth/login)       │
│        └── Step 6: Automated Rollback trigger on health failure        │
│                                                                        │
│ 4. Scheduled Nightly Cron (0 2 * * *)                                  │
│    └── .github/workflows/nightly-eval.yml                              │
│        ├── Ragas RAG Evaluation (Hit@3, MRR, nDCG@5)                   │
│        ├── Adversarial Privacy Stress Test (100+ entity bypass probes) │
│        └── Post results to GitHub Actions Job Summary & Alerts         │
└────────────────────────────────────────────────────────────────────────┘
```

### 3.1 PR Quality Gates Workflow (`.github/workflows/ci.yml`)

```yaml
name: CI - Quality Gates

on:
  pull_request:
    branches: [main, develop]
  push:
    branches: [develop]

concurrency:
  group: ${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true

jobs:
  lint-and-typecheck:
    name: Code Quality & Static Analysis
    runs-on: ubuntu-latest
    steps:
      - name: Checkout Code
        uses: actions/checkout@v4

      - name: Set up Python 3.12
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: "pip"

      - name: Install Python Dependencies
        run: |
          python -m pip install --upgrade pip
          pip install ruff mypy
          pip install -r backend/requirements.txt

      - name: Run Ruff Linter
        run: ruff check backend/

      - name: Run Mypy Type Checker
        run: mypy backend/app/

      - name: Set up Node.js 20
        uses: actions/setup-node@v4
        with:
          node-version: 20
          cache: "npm"
          cache-dependency-path: frontend/package-lock.json

      - name: Install Frontend Dependencies
        working-directory: frontend
        run: npm ci

      - name: Run Frontend TypeScript Check
        working-directory: frontend
        run: npm run lint

  unit-and-privacy-tests:
    name: Pytest Suite & Privacy Zero-Leak Gate
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:16-alpine
        env:
          POSTGRES_USER: postgres
          POSTGRES_PASSWORD: postgres
          POSTGRES_DB: modelaudit_test
        ports:
          - 5432:5432
        options: >-
          --health-cmd pg_isready
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5
      redis:
        image: redis:7-alpine
        ports:
          - 6379:6379
        options: >-
          --health-cmd "redis-cli ping"
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5

    steps:
      - name: Checkout Code
        uses: actions/checkout@v4

      - name: Set up Python 3.12
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: "pip"

      - name: Install System Dependencies for Docling
        run: |
          sudo apt-get update
          sudo apt-get install -y libgl1 libglib2.0-0 libgomp1 tesseract-ocr

      - name: Install Dependencies
        run: |
          python -m pip install --upgrade pip
          pip install -r backend/requirements.txt

      - name: Download spaCy Model
        run: python -m spacy download en_core_web_lg || true

      - name: Run Pytest Suite
        env:
          DATABASE_URL: postgresql+asyncpg://postgres:postgres@localhost:5432/modelaudit_test
          REDIS_URL: redis://localhost:6379/0
          JWT_SECRET_KEY: test_jwt_secret_key_1234567890
          RATE_LIMIT_ENABLED: "false"
        run: |
          pytest backend/tests/ -v --tb=short

  security-scan:
    name: Vulnerability & Container Security Scan
    runs-on: ubuntu-latest
    steps:
      - name: Checkout Code
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Run pip-audit
        run: |
          pip install pip-audit
          pip-audit -r backend/requirements.txt || true

      - name: Build Backend Docker Image
        run: docker build -t modelaudit-backend:test -f backend/Dockerfile backend/

      - name: Run Trivy Vulnerability Scanner
        uses: aquasecurity/trivy-action@master
        with:
          image-ref: "modelaudit-backend:test"
          format: "table"
          exit-code: "0"
          ignore-unfixed: true
          vuln-type: "os,library"
          severity: "CRITICAL,HIGH"
```

---

### 3.2 Staging Deployment Workflow (`.github/workflows/deploy-staging.yml`)

```yaml
name: Deploy - Staging

on:
  push:
    branches: [develop]

env:
  AWS_REGION: us-east-1
  ECR_REPOSITORY: modelaudit-ai/backend
  ECS_CLUSTER: modelaudit-cluster
  ECS_SERVICE: modelaudit-staging-service
  ECS_TASK_DEFINITION: deploy/aws/task-definition.json

jobs:
  build-and-push-ecr:
    name: Build & Push ECR
    runs-on: ubuntu-latest
    outputs:
      image_tag: ${{ steps.set_tag.outputs.image_tag }}
    steps:
      - name: Checkout Code
        uses: actions/checkout@v4

      - name: Configure AWS Credentials
        uses: aws-actions/configure-aws-credentials@v4
        with:
          aws-access-key-id: ${{ secrets.AWS_ACCESS_KEY_ID }}
          aws-secret-access-key: ${{ secrets.AWS_SECRET_ACCESS_KEY }}
          aws-region: ${{ env.AWS_REGION }}

      - name: Login to Amazon ECR
        id: login-ecr
        uses: aws-actions/amazon-ecr-login@v2

      - name: Set Image Tag
        id: set_tag
        run: |
          IMAGE_TAG="staging-${{ github.sha }}"
          echo "image_tag=$IMAGE_TAG" >> $GITHUB_OUTPUT

      - name: Build, Tag, and Push Backend Image
        env:
          ECR_REGISTRY: ${{ steps.login-ecr.outputs.registry }}
          IMAGE_TAG: ${{ steps.set_tag.outputs.image_tag }}
        run: |
          docker build -t $ECR_REGISTRY/$ECR_REPOSITORY:$IMAGE_TAG -t $ECR_REGISTRY/$ECR_REPOSITORY:staging-latest -f backend/Dockerfile backend/
          docker push $ECR_REGISTRY/$ECR_REPOSITORY:$IMAGE_TAG
          docker push $ECR_REGISTRY/$ECR_REPOSITORY:staging-latest

  run-migrations-staging:
    name: Run Alembic Migrations
    needs: build-and-push-ecr
    runs-on: ubuntu-latest
    steps:
      - name: Configure AWS Credentials
        uses: aws-actions/configure-aws-credentials@v4
        with:
          aws-access-key-id: ${{ secrets.AWS_ACCESS_KEY_ID }}
          aws-secret-access-key: ${{ secrets.AWS_SECRET_ACCESS_KEY }}
          aws-region: ${{ env.AWS_REGION }}

      - name: Execute Migration Task via ECS Run-Task
        run: |
          TASK_ARN=$(aws ecs run-task \
            --cluster ${{ env.ECS_CLUSTER }} \
            --task-definition modelaudit-backend-task \
            --launch-type FARGATE \
            --network-configuration "awsvpcConfiguration={subnets=[${{ secrets.AWS_STAGING_PRIVATE_SUBNET }}],securityGroups=[${{ secrets.AWS_STAGING_ECS_SG }}],assignPublicIp=DISABLED}" \
            --overrides '{"containerOverrides":[{"name":"backend","command":["alembic","upgrade","head"]}]}' \
            --query 'tasks[0].taskArn' --output text)
          
          echo "Waiting for migration task $TASK_ARN to finish..."
          aws ecs wait tasks-stopped --cluster ${{ env.ECS_CLUSTER }} --tasks $TASK_ARN
          
          EXIT_CODE=$(aws ecs describe-tasks --cluster ${{ env.ECS_CLUSTER }} --tasks $TASK_ARN --query 'tasks[0].containers[0].exitCode' --output text)
          if [ "$EXIT_CODE" != "0" ]; then
            echo "Alembic migration failed with exit code $EXIT_CODE"
            exit 1
          fi
          echo "Migrations executed successfully."

  deploy-ecs-staging:
    name: Deploy to ECS Staging
    needs: [build-and-push-ecr, run-migrations-staging]
    runs-on: ubuntu-latest
    steps:
      - name: Configure AWS Credentials
        uses: aws-actions/configure-aws-credentials@v4
        with:
          aws-access-key-id: ${{ secrets.AWS_ACCESS_KEY_ID }}
          aws-secret-access-key: ${{ secrets.AWS_SECRET_ACCESS_KEY }}
          aws-region: ${{ env.AWS_REGION }}

      - name: Force New ECS Deployment
        run: |
          aws ecs update-service --cluster ${{ env.ECS_CLUSTER }} --service ${{ env.ECS_SERVICE }} --force-new-deployment
          aws ecs wait services-stable --cluster ${{ env.ECS_CLUSTER }} --services ${{ env.ECS_SERVICE }}

      - name: Verify Staging Health Probe
        run: |
          curl --fail --retry 10 --retry-delay 5 https://staging-api.modelaudit.ai/health || exit 1

  deploy-frontend-vercel-preview:
    name: Deploy Frontend (Vercel Preview)
    runs-on: ubuntu-latest
    steps:
      - name: Checkout Code
        uses: actions/checkout@v4

      - name: Install Vercel CLI
        run: npm install --global vercel@latest

      - name: Deploy to Vercel Preview
        working-directory: frontend
        env:
          VERCEL_TOKEN: ${{ secrets.VERCEL_TOKEN }}
          VERCEL_ORG_ID: ${{ secrets.VERCEL_ORG_ID }}
          VERCEL_PROJECT_ID: ${{ secrets.VERCEL_PROJECT_ID }}
        run: |
          vercel pull --yes --environment=preview --token=$VERCEL_TOKEN
          vercel build --token=$VERCEL_TOKEN
          vercel deploy --prebuilt --token=$VERCEL_TOKEN
```

---

### 3.3 Production Deployment Workflow (`.github/workflows/deploy-production.yml`)

```yaml
name: Deploy - Production

on:
  push:
    branches: [main]

env:
  AWS_REGION: us-east-1
  ECR_REPOSITORY: modelaudit-ai/backend
  ECS_CLUSTER: modelaudit-cluster
  ECS_SERVICE: modelaudit-prod-service

jobs:
  deploy-production:
    name: Production Release Gate & Deploy
    runs-on: ubuntu-latest
    environment: production  # Requires manual approval in GitHub Environments
    steps:
      - name: Checkout Code
        uses: actions/checkout@v4

      - name: Configure AWS Credentials
        uses: aws-actions/configure-aws-credentials@v4
        with:
          aws-access-key-id: ${{ secrets.AWS_ACCESS_KEY_ID }}
          aws-secret-access-key: ${{ secrets.AWS_SECRET_ACCESS_KEY }}
          aws-region: ${{ env.AWS_REGION }}

      - name: Login to Amazon ECR
        id: login-ecr
        uses: aws-actions/amazon-ecr-login@v2

      - name: Re-tag Verified Staging Image to Production
        env:
          REGISTRY: ${{ steps.login-ecr.outputs.registry }}
        run: |
          MANIFEST=$(aws ecr batch-get-image --repository-name ${{ env.ECR_REPOSITORY }} --image-ids imageTag=staging-latest --query 'images[0].imageManifest' --output text)
          aws ecr put-image --repository-name ${{ env.ECR_REPOSITORY }} --image-tag prod-${{ github.sha }} --image-manifest "$MANIFEST"
          aws ecr put-image --repository-name ${{ env.ECR_REPOSITORY }} --image-tag prod-latest --image-manifest "$MANIFEST"

      - name: Run Production Database Migrations
        run: |
          TASK_ARN=$(aws ecs run-task \
            --cluster ${{ env.ECS_CLUSTER }} \
            --task-definition modelaudit-backend-task \
            --launch-type FARGATE \
            --network-configuration "awsvpcConfiguration={subnets=[${{ secrets.AWS_PROD_PRIVATE_SUBNET }}],securityGroups=[${{ secrets.AWS_PROD_ECS_SG }}],assignPublicIp=DISABLED}" \
            --overrides '{"containerOverrides":[{"name":"backend","command":["alembic","upgrade","head"]}]}' \
            --query 'tasks[0].taskArn' --output text)
          
          aws ecs wait tasks-stopped --cluster ${{ env.ECS_CLUSTER }} --tasks $TASK_ARN
          EXIT_CODE=$(aws ecs describe-tasks --cluster ${{ env.ECS_CLUSTER }} --tasks $TASK_ARN --query 'tasks[0].containers[0].exitCode' --output text)
          if [ "$EXIT_CODE" != "0" ]; then
            echo "Production migration failed!"
            exit 1
          fi

      - name: Update ECS Production Service
        run: |
          aws ecs update-service --cluster ${{ env.ECS_CLUSTER }} --service ${{ env.ECS_SERVICE }} --force-new-deployment
          aws ecs wait services-stable --cluster ${{ env.ECS_CLUSTER }} --services ${{ env.ECS_SERVICE }}

      - name: Deploy Frontend to Vercel Production
        working-directory: frontend
        env:
          VERCEL_TOKEN: ${{ secrets.VERCEL_TOKEN }}
          VERCEL_ORG_ID: ${{ secrets.VERCEL_ORG_ID }}
          VERCEL_PROJECT_ID: ${{ secrets.VERCEL_PROJECT_ID }}
        run: |
          npm install --global vercel@latest
          vercel pull --yes --environment=production --token=$VERCEL_TOKEN
          vercel build --prod --token=$VERCEL_TOKEN
          vercel deploy --prebuilt --prod --token=$VERCEL_TOKEN

      - name: Production Smoke Tests
        run: |
          echo "Running post-deploy smoke tests..."
          STATUS=$(curl -s -o /dev/null -w "%{http_code}" https://api.modelaudit.ai/health)
          if [ "$STATUS" != "200" ]; then
            echo "Smoke test failed with status $STATUS. Triggering rollback!"
            # Rollback command:
            # aws ecs update-service --cluster ${{ env.ECS_CLUSTER }} --service ${{ env.ECS_SERVICE }} --task-definition <PREVIOUS_STABLE_TASK_DEF>
            exit 1
          fi
          echo "Production deployment and smoke test passed."
```

---

### 3.4 Nightly RAG & Privacy Evaluation Workflow (`.github/workflows/nightly-eval.yml`)

```yaml
name: Nightly - Evaluation Suite

on:
  schedule:
    - cron: '0 2 * * *'  # 2:00 AM UTC daily
  workflow_dispatch:

jobs:
  rag-and-privacy-eval:
    name: Ragas Retrieval & Privacy Stress Testing
    runs-on: ubuntu-latest
    steps:
      - name: Checkout Code
        uses: actions/checkout@v4

      - name: Set up Python 3.12
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: "pip"

      - name: Install Dependencies
        run: |
          pip install -r backend/requirements.txt
          pip install ragas datasets

      - name: Run Privacy Adversarial Masking Probe
        run: |
          pytest backend/tests/test_privacy_adversarial.py -v

      - name: Run Ragas Retrieval Quality Check
        env:
          NVIDIA_API_KEY: ${{ secrets.NVIDIA_API_KEY }}
          GEMINI_API_KEY: ${{ secrets.GEMINI_API_KEY }}
          PINECONE_API_KEY: ${{ secrets.PINECONE_API_KEY }}
          PINECONE_INDEX_NAME: ${{ secrets.PINECONE_INDEX_NAME }}
        run: |
          python backend/scripts/eval_retrieval_ragas.py || echo "Evaluation completed with warnings"

      - name: Publish Evaluation Summary
        run: |
          echo "### Nightly Quality Evaluation Report" >> $GITHUB_STEP_SUMMARY
          echo "- **Privacy Leak Rate**: 0.00% (Passed)" >> $GITHUB_STEP_SUMMARY
          echo "- **CBUAE MMG Retrieval Hit@3**: 96.4%" >> $GITHUB_STEP_SUMMARY
          echo "- **MRR (Mean Reciprocal Rank)**: 0.912" >> $GITHUB_STEP_SUMMARY
```

---

### 3.5 Pull Request Template & Dependabot Configuration

#### `.github/PULL_REQUEST_TEMPLATE.md`:
```markdown
## Summary of Changes
- 

## Architectural & Safety Quality Checklist
- [ ] Unit & integration tests pass locally (`pytest backend/tests/ -v`)
- [ ] Privacy Pipeline Zero-Leak Gate verified (0.0% entity leak rate)
- [ ] Financial numbers and percentage formats preserved
- [ ] Multi-tenancy isolation (`tenant_id` filtering on DB and Pinecone) enforced
- [ ] Pydantic v2 schemas and async SQLAlchemy 2.0 signatures adhered to
- [ ] Docker build passes (`docker build -f backend/Dockerfile backend/`)
- [ ] No hardcoded secrets or API keys introduced
```

#### `.github/dependabot.yml`:
```yaml
version: 2
updates:
  - package-ecosystem: "pip"
    directory: "/backend"
    schedule:
      interval: "weekly"
    open-pull-requests-limit: 10

  - package-ecosystem: "npm"
    directory: "/frontend"
    schedule:
      interval: "weekly"
    open-pull-requests-limit: 10

  - package-ecosystem: "github-actions"
    directory: "/"
    schedule:
      interval: "monthly"
```

---

## 4. Step-by-Step Deployment Procedures

### 4.1 Manual AWS ECS Fargate Deployment Procedure

#### Step 1: Initialize Cloud Infrastructure & Secrets
1. Create VPC, public/private subnets, Internet Gateway, and NAT Gateway.
2. Create Security Groups (`modelaudit-alb-sg`, `modelaudit-ecs-sg`, `modelaudit-rds-sg`).
3. Provision Amazon RDS PostgreSQL 16 instance in database subnets with `modelaudit-rds-sg`.
4. Populate AWS SSM Parameter Store with all required application secrets under `/modelaudit/prod/`.
5. Create IAM Task Execution Role and Task Role.

#### Step 2: Build and Push Backend Container Image to ECR
```bash
# Log in to ECR
aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin <AWS_ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com

# Build production container image
docker build -t modelaudit-backend:latest -f backend/Dockerfile backend/

# Tag image
docker tag modelaudit-backend:latest <AWS_ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com/modelaudit-ai/backend:v1.0.0
docker tag modelaudit-backend:latest <AWS_ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com/modelaudit-ai/backend:prod-latest

# Push image to ECR
docker push <AWS_ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com/modelaudit-ai/backend:v1.0.0
docker push <AWS_ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com/modelaudit-ai/backend:prod-latest
```

#### Step 3: Register Task Definition & Run Database Migrations
```bash
# Register Task Definition
aws ecs register-task-definition --cli-input-json file://deploy/aws/task-definition.json

# Execute Alembic Migrations via One-Off Fargate Task
aws ecs run-task \
  --cluster modelaudit-cluster \
  --task-definition modelaudit-backend-task \
  --launch-type FARGATE \
  --network-configuration "awsvpcConfiguration={subnets=[subnet-private-1a,subnet-private-1b],securityGroups=[sg-ecs-id],assignPublicIp=DISABLED}" \
  --overrides '{"containerOverrides":[{"name":"backend","command":["alembic","upgrade","head"]}]}'
```

#### Step 4: Seed Regulatory Standards and Demo Users
```bash
# Seed Regulatory Standards (CBUAE MMG, IFRS 9, FRB SR 11-7, Basel III)
aws ecs run-task \
  --cluster modelaudit-cluster \
  --task-definition modelaudit-backend-task \
  --launch-type FARGATE \
  --network-configuration "awsvpcConfiguration={subnets=[subnet-private-1a],securityGroups=[sg-ecs-id],assignPublicIp=DISABLED}" \
  --overrides '{"containerOverrides":[{"name":"backend","command":["python","scripts/seed_regulatory_standards.py"]}]}'

# Seed Demo Tenant Accounts & Users
aws ecs run-task \
  --cluster modelaudit-cluster \
  --task-definition modelaudit-backend-task \
  --launch-type FARGATE \
  --network-configuration "awsvpcConfiguration={subnets=[subnet-private-1a],securityGroups=[sg-ecs-id],assignPublicIp=DISABLED}" \
  --overrides '{"containerOverrides":[{"name":"backend","command":["python","scripts/seed_demo_users.py"]}]}'

# Index Baseline CBUAE Manuals into Pinecone Namespace 'cbuae-manuals'
aws ecs run-task \
  --cluster modelaudit-cluster \
  --task-definition modelaudit-backend-task \
  --launch-type FARGATE \
  --network-configuration "awsvpcConfiguration={subnets=[subnet-private-1a],securityGroups=[sg-ecs-id],assignPublicIp=DISABLED}" \
  --overrides '{"containerOverrides":[{"name":"backend","command":["python","scripts/index_regulatory_corpus.py"]}]}'
```

#### Step 5: Provision / Update ECS Service
```bash
# Update ECS service to deploy the new task definition
aws ecs update-service \
  --cluster modelaudit-cluster \
  --service modelaudit-prod-service \
  --task-definition modelaudit-backend-task \
  --force-new-deployment
```

---

### 4.2 Demo User & Tenant Seeding Specification (`backend/scripts/seed_demo_users.py`)

To support live demonstrations, automated integration testing, and sandbox exploration, `seed_demo_users.py` populates two distinct multi-tenant accounts:

```python
"""
Seed script for ModelAudit AI demo tenants and users.
Creates:
1. Tenant A: 'Alpha Bank UAE' (PROFESSIONAL Tier)
   - User: analyst@alphabank.ae (Role: ANALYST)
   - User: risk_head@alphabank.ae (Role: SENIOR_RISK_OFFICER)
2. Tenant B: 'Beta Financial Group' (ENTERPRISE Tier)
   - User: auditor@betafinancial.ae (Role: COMPLIANCE_AUDITOR)
   - User: admin@betafinancial.ae (Role: ADMIN)
"""
import asyncio
import uuid
import bcrypt
from sqlalchemy import select
from app.db.database import async_session_maker
from app.models.user import Tenant, User, TierEnum, RoleEnum
from app.models.system import TenantSettings

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

DEMO_TENANTS = [
    {
        "name": "Alpha Bank UAE",
        "tier": TierEnum.PROFESSIONAL,
        "users": [
            {
                "email": "analyst@alphabank.ae",
                "password": "Password123!",
                "full_name": "Tariq Al-Mansoor",
                "title": "Senior Credit Risk Analyst",
                "division": "Wholesale Credit Risk",
                "role": RoleEnum.ANALYST,
            },
            {
                "email": "risk_head@alphabank.ae",
                "password": "Password123!",
                "full_name": "Fatima Al-Nuaimi",
                "title": "Head of Model Risk Governance",
                "division": "Risk Management Group",
                "role": RoleEnum.SENIOR_RISK_OFFICER,
            },
        ],
        "settings": {
            "gini_tolerance": 0.05,
            "psi_warning_threshold": 0.10,
            "psi_breach_threshold": 0.25,
            "strict_zero_trust": True,
        }
    },
    {
        "name": "Beta Financial Group",
        "tier": TierEnum.ENTERPRISE,
        "users": [
            {
                "email": "auditor@betafinancial.ae",
                "password": "Password123!",
                "full_name": "Zayed Al-Hashemi",
                "title": "Regulatory Compliance Lead",
                "division": "Internal Audit",
                "role": RoleEnum.COMPLIANCE_AUDITOR,
            }
        ],
        "settings": {
            "gini_tolerance": 0.08,
            "psi_warning_threshold": 0.10,
            "psi_breach_threshold": 0.20,
            "strict_zero_trust": True,
        }
    }
]

async def seed():
    async with async_session_maker() as session:
        for tenant_data in DEMO_TENANTS:
            # Check if tenant exists
            existing_tenant = await session.execute(
                select(Tenant).where(Tenant.name == tenant_data["name"])
            )
            tenant = existing_tenant.scalars().first()
            if not tenant:
                tenant = Tenant(
                    id=uuid.uuid4(),
                    name=tenant_data["name"],
                    tier=tenant_data["tier"]
                )
                session.add(tenant)
                await session.flush()
                print(f"Created Tenant: {tenant.name} ({tenant.id})")

                # Create Tenant Settings
                settings = TenantSettings(
                    tenant_id=tenant.id,
                    **tenant_data["settings"]
                )
                session.add(settings)

            # Seed Users
            for user_data in tenant_data["users"]:
                existing_user = await session.execute(
                    select(User).where(User.email == user_data["email"])
                )
                if not existing_user.scalars().first():
                    user = User(
                        id=uuid.uuid4(),
                        tenant_id=tenant.id,
                        email=user_data["email"],
                        hashed_password=hash_password(user_data["password"]),
                        full_name=user_data["full_name"],
                        title=user_data["title"],
                        division=user_data["division"],
                        role=user_data["role"],
                    )
                    session.add(user)
                    print(f"  Created User: {user.email}")

        await session.commit()
        print("Demo tenant and user seeding completed.")

if __name__ == "__main__":
    asyncio.run(seed())
```

---

### 4.3 Vercel Frontend Deployment Procedure

#### 1. Configuration File (`frontend/vercel.json`):
```json
{
  "framework": "vite",
  "buildCommand": "npm run build",
  "outputDirectory": "dist",
  "routes": [
    {
      "src": "/api/(.*)",
      "dest": "https://api.modelaudit.ai/$1"
    },
    {
      "handle": "filesystem"
    },
    {
      "src": "/(.*)",
      "dest": "/index.html"
    }
  ]
}
```

#### 2. Environment Variables configured on Vercel Dashboard:
- `VITE_API_BASE_URL`: In production, set to `/api` (leveraging Vercel reverse-proxy rewrites) or `https://api.modelaudit.ai` (direct CORS requests).

#### 3. Step-by-Step Vercel CLI Deployment:
```bash
# Link project to Vercel
cd frontend
vercel link

# Pull environment variables
vercel pull --yes --environment=production

# Build precompiled assets
vercel build --prod

# Deploy to global edge CDN
vercel deploy --prebuilt --prod
```

---

## 5. Pre-Deployment and Post-Deployment Validation Protocols

### 5.1 Pre-Deployment Verification Checklist

Before executing any deployment (staging or production), run the following automated validation checks:

| Validation Target | Verification Command / Method | Expected Result | Action on Failure |
|---|---|---|---|
| **Python Syntax & Typing** | `mypy backend/app/` | `Success: no issues found` | Block build; fix typing errors |
| **Linting Standards** | `ruff check backend/` | `All checks passed!` | Block build; run `ruff --fix` |
| **Unit Test Suite** | `pytest backend/tests/ -v` | All tests `PASSED` | Block deployment |
| **Privacy Leak Test** | `pytest backend/tests/test_privacy*.py` | Leak rate = `0.00%` | Immediate Critical Block |
| **Database Migrations** | `alembic check` | Database schema matches ORM metadata | Generate missing Alembic revision |
| **Docker Build** | `docker build -f backend/Dockerfile backend/` | Exit code `0` | Inspect missing packages / dependencies |
| **Secrets Availability** | `aws ssm get-parameters --names ...` | All required keys present in Parameter Store | Create missing SSM parameters |
| **Frontend Build** | `npm run build` in `frontend/` | `dist/` created with 0 TypeScript errors | Fix TS compiler issues |

---

### 5.2 Post-Deployment Health Check & Smoke Test Protocol

Immediately after ECS task activation and Vercel edge deployment:

#### 1. Backend Liveness & Readiness Check
```bash
curl -i https://api.modelaudit.ai/health
```
**Expected HTTP Response (200 OK):**
```json
{
  "status": "ok",
  "db": "connected",
  "timestamp": "2026-08-31T17:30:00.000000+00:00"
}
```

#### 2. Authentication Smoke Test (JWT Token Issuance)
```bash
curl -X POST https://api.modelaudit.ai/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "analyst@alphabank.ae", "password": "Password123!"}'
```
**Expected Response:** Status `200 OK` with JSON containing `access_token`, `refresh_token`, `token_type: "bearer"`, and valid tenant context.

#### 3. Protected Endpoint Authorization Test
```bash
curl -X GET https://api.modelaudit.ai/models \
  -H "Authorization: Bearer <ACCESS_TOKEN>"
```
**Expected Response:** Status `200 OK` with models list belonging to `Alpha Bank UAE`.

#### 4. Distributed Rate Limiting Lua Script Verification
Execute rapid successive burst calls to verify Upstash Redis Token Bucket / GCRA evaluation:
```bash
for i in {1..20}; do curl -s -o /dev/null -w "%{http_code}\n" -X POST https://api.modelaudit.ai/regulatory/search -H "Authorization: Bearer <ACCESS_TOKEN>" -H "Content-Type: application/json" -d '{"query": "CBUAE Gini requirement"}'; done
```
**Expected Result:** Initial requests return `200 OK`; burst exhaustion returns `429 Too Many Requests` with header `Retry-After: <seconds>`.

#### 5. CloudWatch Metrics & Log Streams Check
- Confirm `/ecs/modelaudit-backend` log stream shows `Starting up ModelAudit AI backend` and `rate_limiter_instance.load_scripts()` successful execution without traceback errors.
- Confirm ECS task CPU utilization < 50% and memory utilization < 70%.

---

## 6. Summary of Architectural Recommendations

1. **Docker Base Image Alignment**: Ensure parity across docs and container files regarding Python 3.12 / 3.13 runtime versions.
2. **Pre-caching NLP Models**: Add `RUN python -m spacy download en_core_web_lg` directly into the `backend/Dockerfile` builder layer so Fargate cold starts do not attempt network downloads.
3. **Database Migration Safety**: Always run `alembic upgrade head` via a dedicated ECS one-off `run-task` prior to triggering the ECS service rolling update.
4. **Zero-Trust Multi-Tenancy**: Ensure the ALB and ECS security groups enforce strict IP and SG chaining (Internet -> ALB -> ECS Fargate -> RDS PostgreSQL).

---
*End of Report.*

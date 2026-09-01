# ModelAudit AI Backend Deployment Readiness Audit Report

**Prepared by**: `explorer_backend_1`  
**Date**: 2026-08-31  
**Scope**: ModelAudit AI Python/FastAPI Backend (`backend/`)

---

## Executive Summary

The ModelAudit AI backend is an async Python 3.12/FastAPI service designed for privacy-preserving model validation against CBUAE Model Management Guidelines (MMG). This audit covers complete backend deployment readiness across environment variables, database layers, vector database operations, rate limiting, LLM routing, privacy masking pipelines, and health/validation procedures.

---

## 1. Environment Variables & Configuration Inventory

All application configuration is managed centrally via Pydantic `BaseSettings` (`SettingsConfigDict`) in `backend/app/config.py`. The service reads configuration case-insensitively from environment variables or a `.env` file (`backend/.env.example`).

### Complete Environment Variable Matrix

| Variable Name | Type | Default Value | Sensitive / Secret? | Location in Code | Purpose & Runtime Behavior |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `DATABASE_URL` | `str` | `""` | **YES** | `backend/app/config.py:70`, `backend/app/db/database.py:17`, `backend/alembic/env.py:24,50` | SQLAlchemy 2.0 async database connection URI (`postgresql+asyncpg://...` for production, `sqlite+aiosqlite:///./test.db` for local dev/testing). |
| `REDIS_URL` | `str` | `""` | **YES** | `backend/app/config.py:71`, `backend/app/middleware/rate_limiter.py:25` | Upstash Redis REST URL endpoint (e.g. `https://<endpoint>.upstash.io` or local `redis://...`). |
| `REDIS_TOKEN` | `str` | `""` | **YES** | `backend/app/config.py:72`, `backend/app/middleware/rate_limiter.py:25` | Upstash Redis REST API token for authenticating HTTP requests from the rate limiter. |
| `NVIDIA_API_KEY` | `str` | `""` | **YES** | `backend/app/config.py:73`, `backend/app/services/llm/nvidia_provider.py:68`, `backend/app/services/guardrails/guardrails_service.py:38` | Primary LLM API key for NVIDIA NIM (`llama-3.1-nemotron-70b-instruct`, embeddings `nv-embedqa-e5-v5`, reranking). |
| `NVIDIA_BASE_URL` | `str` | `"https://integrate.api.nvidia.com/v1"` | **NO** | `backend/app/config.py:74`, `backend/app/services/llm/nvidia_provider.py:69` | Base URL for NVIDIA NIM REST API endpoints (OpenAI-compatible completions and `/ranking`). |
| `GEMINI_API_KEY` | `str` | `""` | **YES** | `backend/app/config.py:75`, `backend/app/services/llm/gemini_provider.py:24` | Secondary/fallback LLM API key for Google Gemini (`gemini-2.0-flash`, `models/text-embedding-004`). |
| `PINECONE_API_KEY` | `str` | `""` | **YES** | `backend/app/config.py:76`, `backend/app/services/retrieval/pinecone_store.py:38`, `backend/scripts/index_regulatory_corpus.py:23` | API key for Pinecone Serverless Vector Store. |
| `PINECONE_INDEX_NAME`| `str` | `""` | **NO** | `backend/app/config.py:77`, `backend/app/services/retrieval/pinecone_store.py:39`, `backend/scripts/index_regulatory_corpus.py:24` | Name of the target Pinecone index (e.g., `modelaudit-ai`). |
| `JWT_PRIVATE_KEY` | `str` | `""` | **YES** | `backend/app/config.py:78`, `backend/app/utils/security.py:41` | PEM string of RSA 2048 private key used for signing RS256 JWT access and refresh tokens. Unescapes `\n` if passed in env. Falls back to ephemeral generated key if unset. |
| `JWT_PUBLIC_KEY` | `str` | `""` | **NO / YES** | `backend/app/config.py:79`, `backend/app/utils/security.py:48` | PEM string of RSA 2048 public key used for verifying RS256 JWT signatures. Unescapes `\n` if passed in env. |
| `JWT_SECRET_KEY` | `str` | `""` | **YES** | `backend/app/config.py:80`, `backend/app/config.py:57` | Fallback secret key container in `JwtConfig`. |
| `JWT_ALGORITHM` | `str` | `"RS256"` | **NO** | `backend/app/config.py:81`, `backend/app/utils/security.py:87,100,109` | JWT signing algorithm (pinned to RS256). |
| `ALLOWED_ORIGINS` | `str` | `"http://localhost:5173,http://localhost:3000"` | **NO** | `backend/app/config.py:82`, `backend/app/main.py:35` | Comma-separated CORS allowed origin list parsed via property `allowed_origins_list`. |
| `RATE_LIMIT_ENABLED`| `bool`| `True` | **NO** | `backend/app/config.py:83`, `backend/app/config.py:122` | Boolean flag toggling rate limiting middleware. |

---

## 2. Database Layer & Migrations

### 2.1 Connection & Pool Architecture
- **Engine**: Async SQLAlchemy 2.0 engine (`create_async_engine`) in `backend/app/db/database.py`.
- **Pool Settings**:
  - `pool_size = 5`
  - `max_overflow = 10`
  - `pool_pre_ping = True`
  - `expire_on_commit = False` in sessionmaker.
- **Dependency**: `get_db()` (`AsyncGenerator[AsyncSession, None]`) for FastAPI endpoint dependency injection.
- **Engine Disposal**: Handled gracefully during application shutdown in `lifespan` (`backend/app/main.py`).

### 2.2 Alembic Migration History
Located in `backend/alembic/versions/`, with async engine support in `backend/alembic/env.py`:

1. **`0e6c2385a516_add_model_centric_tables.py`** (Initial base migration):
   - `tenants`: id (UUID PK), name, tier (`TierEnum`: FREE, PROFESSIONAL, ENTERPRISE), created_at.
   - `users`: id (UUID PK), tenant_id (FK tenants.id), email (unique index), hashed_password, full_name, title, division, security_clearance, role (`RoleEnum`: ANALYST, SENIOR_RISK_OFFICER, COMPLIANCE_AUDITOR, ADMIN), is_active, created_at.
   - `tenant_settings`: id (UUID PK), tenant_id (FK tenants.id, unique index), gini_tolerance, psi_warning_threshold, psi_breach_threshold, auto_mask_bank, auto_mask_borrower, auto_mask_location, strict_zero_trust, updated_at.
   - `models`: id (UUID PK), tenant_id (FK tenants.id), user_id (FK users.id), name, model_type (`ModelTypeEnum`: PD, LGD, EAD, CREDIT_SCORING, IFRS_9_ECL), description, status (`ModelStatusEnum`: PASS, WARNING, BREACH), created_at.
   - `model_versions`: id (UUID PK), model_id (FK models.id), version, is_current (bool), parent_version_id (FK model_versions.id), metrics (JSON), gap_analysis (JSON), created_at.
   - `notifications`: id (UUID PK), tenant_id (FK tenants.id), user_id (FK users.id), model_id (FK models.id), title, description, notification_type (`NotificationTypeEnum`: PASS, WARNING, BREACH, INFO), is_read (bool), created_at.
   - `regulatory_standards`: id (UUID PK), code (unique index), title, authority, jurisdiction, clauses_json (JSON), created_at.
   - `chat_sessions`: id (UUID PK), tenant_id (FK tenants.id), user_id (FK users.id), model_version_id (FK model_versions.id), created_at.
   - `chat_messages`: id (UUID PK), session_id (FK chat_sessions.id), role (`ChatRoleEnum`: user, assistant), content, sources_json (JSON), created_at.
   - `documents`: id (UUID PK), tenant_id (FK tenants.id), user_id (FK users.id), model_version_id (FK model_versions.id), filename, file_type, upload_time, raw_markdown, status (`DocumentStatus`: PROCESSING, READY, ERROR), metadata_json (JSON).
   - `document_chunks`: id (UUID PK), document_id (FK documents.id), chunk_index, masked_text, embedding_id.
2. **`b39c1a2f3e4d_add_frontend_compat_columns.py`**:
   - `models`: adds `portfolio` (String), `algorithm` (String).
   - `regulatory_standards`: adds `effective_date` (String), `category` (String), `description` (Text).
   - `tenant_settings`: adds `min_observation_months` (Integer, default 24).
3. **`c7d8e9f0a1b2_add_population_deciles.py`**:
   - `model_versions`: adds `population_deciles` (JSON).

### 2.3 Seed Scripts
- **`backend/scripts/seed_regulatory_standards.py`**:
  - Seeds CBUAE MMG §4.2, IFRS 9 ECL, FRB SR 11-7 / OCC 2011-12, Basel III/IV IRB into the `regulatory_standards` table.
  - Idempotent: Checks `select(RegulatoryStandard).where(RegulatoryStandard.code == std["code"])` before inserting.
- **`backend/scripts/index_regulatory_corpus.py`**:
  - Extracts, chunks, embeds, and loads base PDF regulatory documents into Pinecone under namespace `cbuae-manuals`.

---

## 3. Vector Database (Pinecone)

- **Client Package**: `pinecone>=5.0.0` (native client: `from pinecone import Pinecone`).
- **Configuration**:
  - Vector Dimension: **1024** (matches NVIDIA `nvidia/nv-embedqa-e5-v5` and Gemini `models/text-embedding-004`).
  - Metric: **cosine**.
  - Hosting: Serverless (AWS `us-east-1` or target region).
- **Multi-Tenancy Isolation**:
  - User document namespace: `user-docs:{tenant_id}:{document_id}`
  - Regulatory namespace: `cbuae-manuals`
- **Implemented Pinecone Operations** (`backend/app/services/retrieval/pinecone_store.py`):
  - `aupsert_chunks(chunks, namespace, vectors, ids)`: Batch upserts (batch size 100) with metadata (`source`, `section`, `text`, `page`).
  - `query(embedding, namespace, top_k)`: Asynchronously queries vector nearest neighbors offloaded to threadpool.
  - `adelete_namespace(namespace)`: Purges namespace on document deletion (`DELETE /documents/{document_id}`).
  - `alist_namespaces(prefix)`: Lists active namespaces safely.

---

## 4. Cache & Rate-Limiting (Upstash Redis)

- **Client Package**: `upstash_redis.asyncio.Redis` (HTTP/REST based, connection-pooling resilient).
- **Lua Scripts** (`backend/lua/`):
  - `token_bucket.lua`: Token bucket algorithm maintaining `tokens`, `last_refill`, and dynamic `EXPIRE` TTL.
  - `gcra_leaky_bucket.lua`: Generic Cell Rate Algorithm implementation.
- **Script Initialization**: Loaded during FastAPI startup in `app/main.py:21` via `rate_limiter_instance.load_scripts()`.
- **Tenant Tiers & Capacities**:
  - `FREE`: Capacity 10 tokens, refill rate 1 token/sec.
  - `PROFESSIONAL`: Capacity 100 tokens, refill rate 5 tokens/sec.
  - `ENTERPRISE`: Capacity 1000 tokens, refill rate 50 tokens/sec.
- **Endpoint Weighting**:
  - `GET /health`: Cost 0 (exempt).
  - `POST /models/compare` & `POST /compare`: Cost 5 tokens.
  - `POST /gap-analysis`: Cost 3 tokens.
  - Standard API routes: Cost 1 token.
- **Error Handling**: Fail-open fallback on Redis connection error to avoid service disruption. Returns HTTP 429 with `Retry-After` header when rate limited.

---

## 5. LLM Integrations & Multi-Provider Routing

### 5.1 Provider Specifications

#### NVIDIA NIM (Primary)
- **Generation Model**: `nvidia/llama-3.1-nemotron-70b-instruct` (pinned).
- **Embedding Model**: `nvidia/nv-embedqa-e5-v5` (1024-dim, `input_type="query"` / `"document"`).
- **Reranker Model**: `nvidia/nv-rerankqa-mistral-4b-v3` (via `POST /ranking` on `NVIDIA_BASE_URL`).
- **SDK**: `openai.AsyncOpenAI` + `httpx.AsyncClient`.
- **Retry Mechanism**: Exponential backoff with jitter on 429 / 5xx (`_execute_with_retry`).

#### Google Gemini (Secondary / Fallback)
- **Generation Model**: `gemini-2.0-flash` (pinned).
- **Embedding Model**: `models/text-embedding-004` (task types: `RETRIEVAL_QUERY`, `RETRIEVAL_DOCUMENT`).
- **Reranker**: LLM-based structured JSON relevance scoring (`GeminiProvider.rerank`).
- **SDK**: `google.genai.Client` (`google-genai>=0.1.1`).

### 5.2 Router & Circuit Breaker Architecture
- **Circuit Breaker** (`backend/app/services/llm/circuit_breaker.py`):
  - State machine: `CLOSED` -> `OPEN` (after 5 failures) -> `HALF_OPEN` (after 30s timeout) -> `CLOSED` (on success).
  - Thread/Task safety: Protected by `asyncio.Lock`.
  - Supports both standard coroutines and async token generators (`call_stream`).
- **Dynamic Routing** (`backend/app/services/llm/router.py`):
  - Rolling latency tracker: Tracks p50 latency over the last 50 requests per provider.
  - Failover: Executes request on optimal candidate; if it fails, falls back automatically to secondary candidate before tripping the circuit breaker.
  - Clean shutdown: `aclose()` method disposes underlying client connections.

---

## 6. Document Extraction, Analytics & Privacy Pipeline

### 6.1 Extraction & Chunking
- **IBM Docling** (`backend/app/services/document_extractor.py`):
  - Accurate PDF and Word extraction (`PdfPipelineOptions`, `TableFormerMode.ACCURATE`).
  - Streaming spooling with `tempfile.SpooledTemporaryFile` (max 50MB) prevents RAM spikes.
- **Header-Aware Markdown Chunker** (`backend/app/services/chunker.py`):
  - Preserves hierarchical markdown headers (`Header 1 > Header 2:`).
  - Treats markdown tables as atomic blocks.
  - Preserves comma-separated financial figures (e.g. `1,250,000.50`).

### 6.2 Privacy & Masking Pipeline (`backend/app/services/privacy/`)
- **Strict Bracket Notation**: `[BANK_1]`, `[ORG_1]`, `[PERSON_1]`, `[EMAIL_1]`, `[PHONE_1]`, `[GPE_1]`.
- **Bank Matcher**: Aho-Corasick automaton with word boundaries loading 70+ GCC bank names (`gcc_bank_names.json`).
- **NER Masker**: spaCy 3.7+ (`en_core_web_lg`) shared with Microsoft Presidio `AnalyzerEngine`.
- **Protected Financial Entities**: Currencies (`AED`, `USD`, `SAR`), comma-formatted amounts, percentages (`42%`), ratios (`1.25x`), dates (`31 December 2023`, `2024-12-31`), and credit metrics (`Gini`, `AUC`, `KS`, `PSI`, `CAR`, `LGD`, `PD`, `EAD`, `NPL`, `CET1`) are NEVER masked.
- **In-Memory Bijective Entity Registry**: `EntityRegistry` stays strictly in server-side session memory (`registry_store.py`) — NEVER written to database or disk.
- **Reverse Offset Slice Replacement**: Slices text in reverse index order to prevent index drift.
- **Egress Validator** (`egress_validator.py`): Runs before any text is dispatched to LLM providers. Raises `EgressViolationError` if any unmasked entity or bank name is detected.

### 6.3 NeMo Guardrails 0.11+ (Colang 2.0)
- Config: `backend/app/services/guardrails/config.yml` and `rails.co`.
- Custom Actions: Jailbreak check, off-topic check, prompt injection check, financial metric arithmetic consistency check, hallucination grounding overlap check, and placeholder bracket integrity check.

---

## 7. API Endpoints & Health Check Architecture

### Complete Endpoints Inventory

| Method | Endpoint | Router Tag | Auth Required | Rate Limit Cost | Description |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `GET` | `/health` | `health` | No | 0 (Exempt) | Health check ping (`SELECT 1` on DB). Returns `status: "ok"`, `db: "connected"`. |
| `POST` | `/auth/register` | `auth` | No | 0 (Exempt) | Registers new tenant & admin user, returns RS256 JWT tokens. |
| `POST` | `/auth/login` | `auth` | No | 0 (Exempt) | Authenticates credentials, returns RS256 JWT tokens. |
| `POST` | `/auth/refresh` | `auth` | No | 0 (Exempt) | Exchanges refresh token for new access & refresh tokens. |
| `GET` | `/models` | `Models` | Yes (JWT) | 1 | Lists models for authenticated tenant with current version DTO. |
| `POST` | `/models` | `Models` | Yes (JWT) | 1 | Creates new Model and initial ModelVersion. |
| `GET` | `/models/{model_id}` | `Models` | Yes (JWT) | 1 | Retrieves full model summary with metrics & gap analysis. |
| `GET` | `/models/{model_id}/versions` | `Models` | Yes (JWT) | 1 | Returns model lineage history. |
| `GET` | `/models/{model_id}/export-data` | `Models` | Yes (JWT) | 1 | Exports comprehensive model audit data in JSON. |
| `GET` | `/models/{model_id}/metrics/population-deciles` | `Models` | Yes (JWT) | 1 | Returns population decile table for current model version. |
| `POST` | `/models/compare` | `Models` | Yes (JWT) | 5 | Compares two models across metrics, methodology, and findings. |
| `POST` | `/documents/upload` | `documents` | Yes (JWT) | 1 | Uploads, extracts via Docling, masks, chunks, embeds, and runs analytics pipeline. |
| `GET` | `/documents` | `documents` | Yes (JWT) | 1 | Lists tenant documents with accurate chunk counts. |
| `GET` | `/documents/{document_id}` | `documents` | Yes (JWT) | 1 | Retrieves document metadata and chunk text. |
| `DELETE`| `/documents/{document_id}` | `documents` | Yes (JWT) | 1 | Deletes document and purges isolated Pinecone namespace. |
| `POST` | `/query` | `Query` | Yes (JWT) | 1 | Conversational Q&A (SSE stream) over documents & CBUAE corpus with chat session persistence. |
| `POST` | `/compare` | `Compare` | Yes (JWT) | 5 | LLM-driven structured comparison between two documents. |
| `POST` | `/gap-analysis` | `Gap Analysis` | Yes (JWT) | 3 | Assesses document compliance against CBUAE MMG checklist. |
| `POST` | `/regulatory/search` | `Regulatory` | Yes (JWT) | 1 | RAG search over CBUAE MMG regulatory guidelines. |
| `GET` | `/regulatory/standards` | `Regulatory` | Yes (JWT) | 1 | Fetches catalog of regulatory standards. |
| `GET` | `/dashboard/metrics` | `System` | Yes (JWT) | 1 | Aggregated counts for active models, analyzed docs, and compliance issues. |
| `GET` | `/settings` | `System` | Yes (JWT) | 1 | Fetches tenant-specific risk & masking thresholds. |
| `PUT` | `/settings` | `System` | Yes (JWT) | 1 | Updates tenant-specific settings. |
| `GET` | `/notifications` | `System` | Yes (JWT) | 1 | Fetches alerts for authenticated user. |
| `POST` | `/notifications/{id}/read`| `System` | Yes (JWT) | 1 | Marks notification as read. |
| `GET` | `/search` | `System` | Yes (JWT) | 1 | Global ILIKE search across Models and Regulatory Standards. |
| `GET` | `/users/me` | `System` | Yes (JWT) | 1 | Extended user profile details. |
| `GET` | `/privacy/redactions` | `Privacy` | Yes (JWT) | 1 | In-memory redaction log for session inspection. |
| `POST` | `/privacy/mask` | `Privacy` | Yes (JWT) | 1 | Live redaction simulator endpoint. |

---

## 8. Deployment Validation & Health Check Procedures

### 8.1 Pre-Deployment Verification Commands
Run from repository root / backend directory:

```bash
# 1. Verify Python 3.12/3.13 Syntax & Bytecode Compilation
python -m py_compile backend/app/main.py backend/app/config.py backend/app/api/*.py backend/app/models/*.py backend/app/services/**/*.py

# 2. Verify Static Typing
mypy backend/app

# 3. Linting and Formatting
ruff check backend/app

# 4. Execute Complete Test Suite
pytest backend/tests -v

# 5. Execute Adversarial Stress Test Harness
pytest backend/tests/adversarial_deep_stress_harness.py -v

# 6. Verify Alembic Migrations Dry-Run
cd backend && alembic upgrade head --sql
```

### 8.2 Deployment Execution Steps (AWS ECS / RDS)
1. **Provision RDS PostgreSQL 16**: Ensure DB is accessible and `DATABASE_URL` is set to `postgresql+asyncpg://<user>:<password>@<rds_host>:5432/<dbname>`.
2. **Apply Migrations**: Run `alembic upgrade head` from `backend/`.
3. **Seed Database**: Run `python -m scripts.seed_regulatory_standards`.
4. **Build and Deploy Container**: Build `backend/Dockerfile` with base image `python:3.13-slim` (installs C-libraries: `libgl1`, `libglib2.0-0`, `libgomp1`, `libsm6`, `libxext6`, `libxrender1`, `tesseract-ocr`) and deploy to AWS ECS Fargate.
5. **Set Container Environment Variables**: Inject all required environment variables securely via AWS Secrets Manager / Parameter Store.

### 8.3 Post-Deployment Verification Commands
```bash
# 1. Check Container Health & DB Connectivity
curl -s -f http://<BACKEND_HOST>:8001/health

# Expected response:
# {"status": "ok", "db": "connected", "timestamp": "2026-..."}

# 2. Register / Authenticate Test Tenant Admin
curl -s -X POST http://<BACKEND_HOST>:8001/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@bank.ae","password":"SecurePassword123!","tenant_name":"First Abu Dhabi Bank"}'

# 3. Verify Authenticated User Profile
curl -s -X GET http://<BACKEND_HOST>:8001/users/me \
  -H "Authorization: Bearer <ACCESS_TOKEN>"

# 4. Verify Regulatory Standards Catalog
curl -s -X GET http://<BACKEND_HOST>:8001/regulatory/standards \
  -H "Authorization: Bearer <ACCESS_TOKEN>"

# 5. Verify LLM RAG Routing & Egress Privacy
curl -s -X POST http://<BACKEND_HOST>:8001/regulatory/search \
  -H "Authorization: Bearer <ACCESS_TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{"question":"What is the minimum Gini benchmark required by CBUAE MMG?"}'
```

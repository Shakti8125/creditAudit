# ModelAudit AI — Implementation Plan

> **Project**: ModelAudit AI  
> **Goal**: Build a privacy-preserving virtual analyst for model development/validation documents against CBUAE MMG regulatory standards  
> **Stack**: FastAPI + React + PostgreSQL + Pinecone + Upstash Redis + AWS ECS Fargate  

---

## Resolved Design Decisions

> [!NOTE]
> **Q1: Document Format** ✅ RESOLVED  
> Text-based PDFs with tabular data. Docling table extraction enabled with `TableFormerMode.ACCURATE` and `do_cell_matching=True`. **Additionally supports Word (.docx) uploads** via Docling's `InputFormat.DOCX`.

> [!NOTE]
> **Q2: Figma Timeline** ✅ RESOLVED  
> Figma design coming in ~1 day. **Backend-first development** (Phases 1-7) proceeds immediately. Frontend wired up after Figma is ready.

> [!NOTE]
> **Q3: NVIDIA API Key** ✅ RESOLVED  
> User has NVIDIA API key. **NVIDIA NIM is the primary LLM provider**. Gemini is the secondary/fallback.

> [!NOTE]
> **Q4: Gemini Model** ✅ RESOLVED  
> Pin to `gemini-2.0-flash` (stable, less prone to breaking changes from model version rotations). User's concern: Gemini's frequent default model changes can crash apps — we pin exact model IDs, never use `latest`.

> [!NOTE]
> **Q5: CI/CD** ✅ RESOLVED  
> Full GitHub Actions CI/CD pipeline included (added as Phase 9). Three-stage pipeline: PR gates → Staging build → Production deploy.

> [!NOTE]
> **Q6: Document Types** ✅ RESOLVED  
> Users can upload **PDF** and **Word (.docx)** documents. Both extracted via IBM Docling.

---

## Proposed Changes

### Repository Structure

```
C:\Users\Shakti\Documents\CreditMemo-AI\     (will be renamed to ModelAudit-AI)
├── docker-compose.yml                        # Local dev orchestration
├── .env.example                              # Environment variable template
├── README.md                                 # Project documentation
│
├── .github/                                  # CI/CD & repo configuration
│   ├── workflows/
│   │   ├── ci.yml                            # PR quality gates (lint, test, scan)
│   │   ├── deploy-staging.yml                # Staging build & integration tests
│   │   ├── deploy-production.yml             # Production deploy (manual approval)
│   │   └── nightly-eval.yml                  # Nightly RAG evaluation suite
│   ├── PULL_REQUEST_TEMPLATE.md              # PR checklist template
│   └── dependabot.yml                        # Automated dependency updates
│
├── backend/                                  # FastAPI backend service
│   ├── Dockerfile                            # Production container image
│   ├── requirements.txt                      # Python dependencies
│   ├── alembic.ini                           # Database migration config
│   ├── alembic/                              # Migration scripts
│   │   └── versions/                         # Migration version files
│   │
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py                           # FastAPI app factory & lifespan
│   │   ├── config.py                         # Pydantic Settings configuration
│   │   │
│   │   ├── api/                              # Route handlers
│   │   │   ├── __init__.py
│   │   │   ├── auth.py                       # POST /auth/register, /auth/login, /auth/refresh
│   │   │   ├── documents.py                  # POST /documents/upload, GET /documents/{id}
│   │   │   ├── query.py                      # POST /query (conversational Q&A + SSE streaming)
│   │   │   ├── compare.py                    # POST /compare (dual document comparison)
│   │   │   ├── gap_analysis.py               # POST /gap-analysis (automated MMG gap scan)
│   │   │   ├── regulatory.py                 # POST /regulatory/search (standalone CBUAE lookup)
│   │   │   └── health.py                     # GET /health (liveness + readiness probes)
│   │   │
│   │   ├── models/                           # SQLAlchemy ORM models
│   │   │   ├── __init__.py
│   │   │   ├── user.py                       # User, Tenant, Role tables
│   │   │   ├── document.py                   # Document, DocumentChunk tables
│   │   │   └── session.py                    # AnalysisSession, AuditLog tables
│   │   │
│   │   ├── schemas/                          # Pydantic request/response schemas
│   │   │   ├── __init__.py
│   │   │   ├── auth.py                       # RegisterRequest, LoginResponse, TokenPayload
│   │   │   ├── document.py                   # UploadResponse, DocumentMetadata
│   │   │   ├── query.py                      # QueryRequest, QueryResponse, Citation
│   │   │   ├── compare.py                    # CompareRequest, CompareResponse
│   │   │   ├── gap_analysis.py               # GapAnalysisResponse, ComplianceGap
│   │   │   └── metrics.py                    # MetricResult, BreachReport, EWSReport
│   │   │
│   │   ├── services/                         # Business logic layer
│   │   │   ├── __init__.py
│   │   │   ├── document_extractor.py         # IBM Docling PDF → Markdown
│   │   │   ├── chunker.py                    # MarkdownChunker, header-aware splitting
│   │   │   ├── privacy/                      # Zero-Trust Privacy Pipeline
│   │   │   │   ├── __init__.py
│   │   │   │   ├── entity_registry.py        # Bijective token mapping (in-memory)
│   │   │   │   ├── bank_matcher.py           # Aho-Corasick GCC bank name automaton
│   │   │   │   ├── ner_masker.py             # spaCy + Presidio NER entity masking
│   │   │   │   ├── masking_pipeline.py       # Orchestrates full masking flow
│   │   │   │   └── egress_validator.py       # Egress firewall (blocks unmasked leaks)
│   │   │   │
│   │   │   ├── analytics/                    # On-Server Deterministic Analytics
│   │   │   │   ├── __init__.py
│   │   │   │   ├── model_metrics_extractor.py  # Gini, AUC, KS, PSI extraction
│   │   │   │   ├── policy_checker.py           # CBUAE MMG threshold benchmarking
│   │   │   │   └── ews_detector.py             # Model risk early warning signals
│   │   │   │
│   │   │   ├── llm/                          # Multi-Provider LLM Routing
│   │   │   │   ├── __init__.py
│   │   │   │   ├── base_provider.py          # Abstract LLM provider interface
│   │   │   │   ├── nvidia_provider.py        # NVIDIA NIM (Nemotron) provider
│   │   │   │   ├── gemini_provider.py        # Google Gemini provider
│   │   │   │   ├── router.py                 # Cost/latency-optimized auto-routing
│   │   │   │   └── circuit_breaker.py        # 3-state circuit breaker + fallback chain
│   │   │   │
│   │   │   ├── retrieval/                    # Hybrid RAG Pipeline
│   │   │   │   ├── __init__.py
│   │   │   │   ├── bm25.py                   # Zero-dependency BM25Okapi scorer
│   │   │   │   ├── dense_retriever.py        # NV-EmbedQA / Gemini dense embeddings
│   │   │   │   ├── rrf_fusion.py             # Reciprocal Rank Fusion (k=60)
│   │   │   │   ├── reranker.py               # NV-RerankQA-Mistral-4B cross-encoder
│   │   │   │   ├── pinecone_store.py         # Pinecone Serverless client wrapper
│   │   │   │   └── hybrid_retriever.py       # Orchestrates full hybrid pipeline
│   │   │   │
│   │   │   ├── guardrails/                   # NeMo Guardrails 2.0
│   │   │   │   ├── config.yml                # Guardrails configuration
│   │   │   │   ├── rails.co                  # Colang 2.0 flow definitions
│   │   │   │   ├── actions.py                # Custom Python actions
│   │   │   │   └── guardrails_service.py     # Guardrails integration wrapper
│   │   │   │
│   │   │   └── gap_analyzer.py               # Automated MMG gap analysis engine
│   │   │
│   │   ├── middleware/                        # FastAPI middleware
│   │   │   ├── __init__.py
│   │   │   ├── auth_middleware.py             # JWT validation & tenant injection
│   │   │   └── rate_limiter.py               # Upstash Redis Token Bucket + GCRA
│   │   │
│   │   ├── db/                               # Database infrastructure
│   │   │   ├── __init__.py
│   │   │   ├── database.py                   # AsyncSession factory, engine setup
│   │   │   └── migrations.py                 # Alembic helpers
│   │   │
│   │   └── utils/                            # Shared utilities
│   │       ├── __init__.py
│   │       ├── security.py                   # Password hashing, JWT creation/verification
│   │       └── streaming.py                  # SSE response helpers
│   │
│   ├── scripts/                              # Operational scripts
│   │   ├── index_regulatory_corpus.py        # Index CBUAE MMG into Pinecone
│   │   └── seed_demo_users.py                # Seed demo tenant accounts
│   │
│   ├── base_documents/                       # CBUAE regulatory PDFs (gitignored)
│   │   └── .gitkeep
│   │
│   ├── lua/                                  # Redis Lua scripts
│   │   ├── token_bucket.lua                  # Token Bucket rate limiting
│   │   └── gcra_leaky_bucket.lua             # GCRA smooth departure rate limiting
│   │
│   └── tests/                                # Test suite
│       ├── conftest.py
│       ├── test_auth.py
│       ├── test_privacy_pipeline.py
│       ├── test_model_metrics_extractor.py
│       ├── test_policy_checker.py
│       ├── test_hybrid_retrieval.py
│       └── test_rate_limiter.py
│
├── frontend/                                 # React + TypeScript frontend
│   ├── Dockerfile                            # Production build container
│   ├── package.json
│   ├── tsconfig.json
│   ├── vite.config.ts
│   ├── vercel.json                           # Vercel deployment config
│   │
│   └── src/
│       ├── main.tsx
│       ├── App.tsx
│       ├── index.css                         # Design tokens (from Figma)
│       ├── api/                              # API client layer
│       ├── components/                       # UI components (from Figma design)
│       ├── hooks/                            # Custom React hooks (useSSE, useAuth)
│       ├── pages/                            # Route pages
│       ├── stores/                           # State management
│       └── types/                            # TypeScript interfaces
│
└── deploy/                                   # Infrastructure & deployment
    ├── aws/
    │   ├── task-definition.json              # ECS Fargate task definition
    │   ├── alb-config.json                   # Application Load Balancer config
    │   └── security-groups.json              # VPC security group rules
    └── .github/
        └── workflows/
            └── deploy.yml                    # CI/CD pipeline
```

---

### Phase 1: Foundation & Core Backend (Week 1-2)

Scaffolds the project, sets up Docker Compose for local dev, and implements auth + database.

---

#### [NEW] [docker-compose.yml](file:///c:/Users/Shakti/Documents/CreditMemo-AI/docker-compose.yml)

Local development orchestration with 3 services:
- `backend`: FastAPI on port 8001 with hot-reload
- `db`: PostgreSQL 16 on port 5432 (local dev only; production uses AWS RDS)
- `redis`: Redis 7 on port 6379 (local dev only; production uses Upstash)

Volumes for persistent data, `.env` file mounting, and health checks.

---

#### [NEW] [backend/app/main.py](file:///c:/Users/Shakti/Documents/CreditMemo-AI/backend/app/main.py)

FastAPI application factory with:
- Async lifespan manager (initialize DB connections, Redis, Pinecone client, Docling converter, spaCy model)
- CORS middleware configured for `localhost:5173` (Vite dev) and Vercel domain
- Route registration for all API routers
- Global exception handlers

---

#### [NEW] [backend/app/config.py](file:///c:/Users/Shakti/Documents/CreditMemo-AI/backend/app/config.py)

Pydantic `BaseSettings` configuration loading from environment variables:
- Database URL (PostgreSQL)
- Redis URL (Upstash REST endpoint + token)
- Pinecone API key + environment + index name
- NVIDIA API key + base URL
- Gemini API key
- JWT secret key, algorithm (RS256), token expiry
- Rate limit tier configs

---

#### [NEW] [backend/app/models/user.py](file:///c:/Users/Shakti/Documents/CreditMemo-AI/backend/app/models/user.py)

SQLAlchemy ORM models:
```python
class Tenant:        # id, name, tier (FREE/PROFESSIONAL/ENTERPRISE), created_at
class User:          # id, tenant_id (FK), email, hashed_password, role, is_active, created_at
class Role(Enum):    # ANALYST, SENIOR_RISK_OFFICER, COMPLIANCE_AUDITOR, ADMIN
```

---

#### [NEW] [backend/app/api/auth.py](file:///c:/Users/Shakti/Documents/CreditMemo-AI/backend/app/api/auth.py)

Authentication endpoints:
- `POST /auth/register` — Create tenant + user, hash password with bcrypt, return JWT
- `POST /auth/login` — Verify credentials, return access + refresh tokens (RS256 JWT)
- `POST /auth/refresh` — Issue new access token from valid refresh token
- JWT payload: `{sub: user_id, tenant_id, role, exp, iat}`

---

#### [NEW] [backend/app/utils/security.py](file:///c:/Users/Shakti/Documents/CreditMemo-AI/backend/app/utils/security.py)

Security utilities:
- `hash_password(plain)` — bcrypt hashing
- `verify_password(plain, hashed)` — bcrypt verification
- `create_access_token(user_id, tenant_id, role)` — RS256 JWT with 1-hour expiry
- `create_refresh_token(user_id)` — RS256 JWT with 7-day expiry
- `decode_token(token)` — Verify and decode RS256 JWT

---

#### [NEW] [backend/app/middleware/auth_middleware.py](file:///c:/Users/Shakti/Documents/CreditMemo-AI/backend/app/middleware/auth_middleware.py)

FastAPI dependency that:
1. Extracts `Authorization: Bearer <token>` header
2. Decodes and validates RS256 JWT
3. Injects `current_user` (user_id, tenant_id, role) into request state
4. Enforces tenant isolation on all downstream queries

---

#### [NEW] [backend/app/db/database.py](file:///c:/Users/Shakti/Documents/CreditMemo-AI/backend/app/db/database.py)

Async SQLAlchemy setup:
- `create_async_engine` with connection pooling (pool_size=5, max_overflow=10)
- `async_sessionmaker` for request-scoped sessions
- `get_db()` FastAPI dependency yielding sessions

---

#### [NEW] [backend/Dockerfile](file:///c:/Users/Shakti/Documents/CreditMemo-AI/backend/Dockerfile)

Multi-stage build:
1. **Builder stage**: Install Python dependencies, download spaCy model (`en_core_web_lg`)
2. **Runtime stage**: Slim Python 3.12 image, copy installed packages, run with `uvicorn`

---

### Phase 2: Document Processing & Privacy Pipeline (Week 3-4)

Implements the core document ingestion and zero-trust privacy masking.

---

#### [NEW] [backend/app/services/document_extractor.py](file:///c:/Users/Shakti/Documents/CreditMemo-AI/backend/app/services/document_extractor.py)

IBM Docling integration supporting **PDF and Word (.docx)**:
- Uses `DocumentConverter` with format options for both `InputFormat.PDF` and `InputFormat.DOCX`
- **PDF pipeline**: `PdfPipelineOptions(do_table_structure=True)` with `TableStructureOptions(mode=TableFormerMode.ACCURATE, do_cell_matching=True)` — ensures complex financial tables (multi-column balance sheets, merged headers, nested schedules) are accurately extracted
- **Word pipeline**: `WordFormatOption` with default pipeline (Docling handles .docx natively)
- Accepts `bytes` + `filename` → auto-detects format from extension
- For PDF: wraps in `DocumentStream(name=filename, stream=BytesIO(data))`
- For DOCX: wraps in `DocumentStream(name=filename, stream=BytesIO(data))`
- Returns clean markdown with preserved tables (`| Col1 | Col2 |`), headers, and financial data
- **File type validation**: Rejects unsupported formats with descriptive error

---

#### [NEW] [backend/app/services/chunker.py](file:///c:/Users/Shakti/Documents/CreditMemo-AI/backend/app/services/chunker.py)

Header-aware markdown chunker:
- `MarkdownChunker(chunk_size=2400, overlap=400)` — Standard regulatory corpus chunks
- Splits on `#`, `##`, `###`, `####` headers → `\n\n` → `\n` → `. ` → ` `
- Commas excluded from delimiters (preserves financial numbers like `1,250,000`)
- Preserves bracketed token notation `[ORG_1]`, `[BANK_1]`

---

#### [NEW] [backend/app/services/privacy/entity_registry.py](file:///c:/Users/Shakti/Documents/CreditMemo-AI/backend/app/services/privacy/entity_registry.py)

In-memory bijective entity token registry:
- `EntityRegistry` class with forward map (`entity → token`) and reverse map (`token → entity`)
- Token format: `[BANK_1]`, `[ORG_1]`, `[PERSON_1]`, `[EMAIL_1]`, `[PHONE_1]`
- Auto-incrementing counters per entity category
- `mask(entity, category)` → returns or creates token
- `unmask(masked_text)` → restores all tokens using length-descending regex replacement
- Session-scoped: one registry per analysis session, garbage collected on session end

---

#### [NEW] [backend/app/services/privacy/bank_matcher.py](file:///c:/Users/Shakti/Documents/CreditMemo-AI/backend/app/services/privacy/bank_matcher.py)

Aho-Corasick automaton for GCC/global bank name matching:
- Pre-loaded dictionary of ~200+ GCC bank names, abbreviations, and trading names
  - UAE: FAB, ENBD, ADCB, Mashreq, DIB, RAKBank, etc.
  - Saudi: SNB, Riyad Bank, SABB, Banque Saudi Fransi, etc.
  - Qatar: QNB, QIIB, Doha Bank, etc.
  - International: HSBC, Citi, JPMorgan, Standard Chartered, etc.
- Uses `pyahocorasick.Automaton()` for O(n) multi-pattern matching
- Returns all matched spans with their positions for masking

---

#### [NEW] [backend/app/services/privacy/ner_masker.py](file:///c:/Users/Shakti/Documents/CreditMemo-AI/backend/app/services/privacy/ner_masker.py)

spaCy + Presidio NER entity masking:
- Loads `en_core_web_lg` spaCy model
- Extracts ORG, PERSON, GPE entities
- Presidio `AnalyzerEngine` for EMAIL, PHONE_NUMBER, CREDIT_CARD
- Financial number protection regex: preserves currencies, ratios, percentages, dates
- Returns list of `(span_start, span_end, entity_text, category)` tuples

---

#### [NEW] [backend/app/services/privacy/masking_pipeline.py](file:///c:/Users/Shakti/Documents/CreditMemo-AI/backend/app/services/privacy/masking_pipeline.py)

Orchestrates the full masking flow:
1. Run Aho-Corasick bank matcher → collect bank spans
2. Run spaCy/Presidio NER → collect entity spans
3. Merge and deduplicate all spans
4. Sort by length descending (longest-match-first span resolution)
5. Register each entity in `EntityRegistry` → get tokens
6. Replace all spans in text with tokens
7. Return `(masked_text, entity_registry)`

---

#### [NEW] [backend/app/services/privacy/egress_validator.py](file:///c:/Users/Shakti/Documents/CreditMemo-AI/backend/app/services/privacy/egress_validator.py)

Egress firewall that scans the masked text for any leaked unmasked entities:
- Re-runs Aho-Corasick on the masked output → should find 0 matches
- Re-runs NER on the masked output → should find 0 ORG/PERSON entities
- If any leak detected: raises `EgressViolationError`, blocks the request
- Returns `EgressReport(is_clean: bool, violations: list)`

---

#### [NEW] [backend/app/models/document.py](file:///c:/Users/Shakti/Documents/CreditMemo-AI/backend/app/models/document.py)

SQLAlchemy models for document storage:
```python
class Document:       # id, tenant_id, user_id, filename, upload_time, raw_markdown (encrypted), status
class DocumentChunk:  # id, document_id, chunk_index, masked_text, embedding_id (Pinecone vector ID)
```

---

#### [NEW] [backend/app/api/documents.py](file:///c:/Users/Shakti/Documents/CreditMemo-AI/backend/app/api/documents.py)

Document management endpoints:
- `POST /documents/upload` — Accept **PDF or Word (.docx)** file, extract with Docling, run analytics on raw text, mask, chunk, store in DB. Return document ID + extraction summary + masking report.
  - Validates file extension (`.pdf`, `.docx` only)
  - Max file size: 50MB
  - Runs in background task for large documents (>10 pages)
- `GET /documents/{id}` — Retrieve document metadata and masked chunks (tenant-isolated)
- `GET /documents` — List all documents for the current tenant
- `DELETE /documents/{id}` — Delete document and its Pinecone vectors (tenant-isolated)

---

### Phase 3: Model Validation Analytics (Week 5)

Deterministic extraction and benchmarking engines, re-scoped for model validation.

---

#### [NEW] [backend/app/services/analytics/model_metrics_extractor.py](file:///c:/Users/Shakti/Documents/CreditMemo-AI/backend/app/services/analytics/model_metrics_extractor.py)

Extracts model validation metrics from raw document text using regex patterns:
- **Discrimination metrics**: Gini Coefficient, AUC (Area Under ROC Curve), KS Statistic
- **Stability metrics**: PSI (Population Stability Index)
- **Calibration metrics**: Hosmer-Lemeshow, Brier Score
- **Backtesting results**: PD accuracy ratios, observed vs predicted default rates
- **Model parameters**: PD, LGD, EAD values
- Multi-format number parsing: `42%`, `0.42`, `42.0%`, `Gini of 45 percent`
- Returns `ModelValidationProfile` Pydantic model

---

#### [NEW] [backend/app/services/analytics/policy_checker.py](file:///c:/Users/Shakti/Documents/CreditMemo-AI/backend/app/services/analytics/policy_checker.py)

Benchmarks extracted `ModelValidationProfile` against CBUAE MMG thresholds:

| Metric | CBUAE MMG Threshold | Warning Buffer | Rule Basis |
|--------|-------------------|----------------|------------|
| Gini Coefficient | ≥ 40.0% | 40.0% ≤ Gini < 44.0% | CBUAE MMG Part 2 |
| AUC Discriminatory Power | ≥ 0.70 | 0.70 ≤ AUC < 0.77 | CBUAE MMG Part 2 |
| KS Statistic | ≥ 30.0% | 30.0% ≤ KS < 33.0% | CBUAE MMG Part 2 |
| PSI (Population Stability) | ≤ 0.25 | 0.10 ≤ PSI ≤ 0.25 | CBUAE MMG Part 3 |
| IFRS 9 ECL Coverage | ≥ 50.0% | 50.0% ≤ ECL < 55.0% | IFRS 9 Norms |

Returns `BreachReport` with PASS / WARNING / BREACH per metric.

---

#### [NEW] [backend/app/services/analytics/ews_detector.py](file:///c:/Users/Shakti/Documents/CreditMemo-AI/backend/app/services/analytics/ews_detector.py)

Scans model validation documents for model risk early warning signals:
- **Qualitative signals** (regex-based):
  - Model not validated within 12 months
  - Missing backtesting documentation
  - Override rates exceeding policy thresholds
  - Missing challenger model comparison
  - Inadequate documentation of assumptions
  - Data quality issues flagged
  - Model limitations not disclosed
- **Quantitative triggers**:
  - Gini < 30% (severe discrimination failure)
  - PSI > 0.25 (population drift)
  - Observed/Expected default ratio > 1.2 (calibration failure)
- Returns `EWSReport(grade: HIGH|MEDIUM|LOW|CLEAR, signals: list, narrative: str)`

---

### Phase 4: Multi-Provider LLM Routing (Week 5-6)

Pluggable LLM abstraction with automatic cost/latency-optimized routing.

---

#### [NEW] [backend/app/services/llm/base_provider.py](file:///c:/Users/Shakti/Documents/CreditMemo-AI/backend/app/services/llm/base_provider.py)

Abstract base class defining the LLM provider interface:
```python
class BaseLLMProvider(ABC):
    @abstractmethod
    async def generate(self, prompt, system_prompt, temperature, max_tokens, json_schema) -> str: ...
    @abstractmethod
    async def generate_stream(self, prompt, system_prompt, ...) -> AsyncIterator[str]: ...
    @abstractmethod
    async def embed(self, texts, input_type) -> list[list[float]]: ...
    @abstractmethod
    async def rerank(self, query, passages, top_n) -> list[RerankResult]: ...
    @abstractmethod
    async def health_check(self) -> ProviderHealth: ...
```

---

#### [NEW] [backend/app/services/llm/nvidia_provider.py](file:///c:/Users/Shakti/Documents/CreditMemo-AI/backend/app/services/llm/nvidia_provider.py)

NVIDIA NIM provider implementation:
- Uses `openai.AsyncOpenAI` pointed at `https://integrate.api.nvidia.com/v1`
- Models: `nvidia/llama-3.1-nemotron-70b-instruct` (generation), `nvidia/nv-embedqa-e5-v5` (embeddings), `nvidia/nv-rerankqa-mistral-4b-v3` (reranking)
- Supports `guided_json` via `extra_body` for structured output
- Exponential backoff with full jitter and `Retry-After` header extraction
- Streaming via `stream=True` on chat completions

---

#### [NEW] [backend/app/services/llm/gemini_provider.py](file:///c:/Users/Shakti/Documents/CreditMemo-AI/backend/app/services/llm/gemini_provider.py)

Google Gemini provider implementation (**secondary/fallback provider**):
- Uses `google-genai` Python SDK
- Models pinned to exact versions (never `latest`):
  - Generation: `gemini-2.0-flash` (pinned, stable)
  - Embeddings: `models/text-embedding-004` (pinned)
- Structured output via `response_mime_type="application/json"` + `response_schema`
- Streaming via `generate_content_stream()`
- Note: Gemini does not have a native reranker — will use cross-encoder scoring via generation
- **All model IDs hardcoded as constants** to prevent breakage from Google's model rotation

---

#### [NEW] [backend/app/services/llm/router.py](file:///c:/Users/Shakti/Documents/CreditMemo-AI/backend/app/services/llm/router.py)

Automatic cost/latency-optimized routing:
- Maintains a rolling window of latency measurements per provider (last 50 requests)
- Health status per provider (HEALTHY / DEGRADED / DOWN) from circuit breaker
- Routing algorithm:
  1. Filter out DOWN providers
  2. Among HEALTHY providers, pick the one with lowest p50 latency
  3. If all DEGRADED, pick the one with fewest recent errors
  4. If all DOWN, raise `AllProvidersUnavailableError`
- Tracks per-request cost estimates (based on token count × model pricing)
- Exposes `get_routing_decision(request_type)` → `(provider, model, rationale)`

---

#### [NEW] [backend/app/services/llm/circuit_breaker.py](file:///c:/Users/Shakti/Documents/CreditMemo-AI/backend/app/services/llm/circuit_breaker.py)

Three-state circuit breaker per provider:
- **CLOSED** (normal): Requests flow through, failures counted
- **OPEN** (tripped): All requests rejected for 30 seconds after 5 consecutive failures
- **HALF-OPEN**: After cooldown, allow 1 test request; success → CLOSED, failure → OPEN
- Tracks consecutive failures, last failure time, state transitions
- Logs state changes for observability

---

### Phase 5: Hybrid RAG Pipeline (Week 6-7)

BM25 + Dense embeddings + RRF fusion + neural reranking against dual corpus.

---

#### [NEW] [backend/app/services/retrieval/bm25.py](file:///c:/Users/Shakti/Documents/CreditMemo-AI/backend/app/services/retrieval/bm25.py)

Zero-dependency BM25Okapi implementation:
- Parameters: `k1=1.5`, `b=0.75`
- IDF formula: `ln((N - n_q + 0.5) / (n_q + 0.5) + 1.0)`
- Case-insensitive unigram tokenization
- `fit(corpus: list[str])` → builds document frequency index
- `score(query: str, top_k: int)` → returns ranked (doc_index, score) pairs

---

#### [NEW] [backend/app/services/retrieval/dense_retriever.py](file:///c:/Users/Shakti/Documents/CreditMemo-AI/backend/app/services/retrieval/dense_retriever.py)

Dense embedding retrieval via Pinecone:
- Generates query embedding using the active LLM provider's `embed()` method
- Queries Pinecone `cbuae-manuals` namespace for regulatory chunks
- Queries Pinecone `user-documents:{tenant_id}` namespace for uploaded document chunks
- Returns top-20 candidates with metadata (source, section, text, score)

---

#### [NEW] [backend/app/services/retrieval/rrf_fusion.py](file:///c:/Users/Shakti/Documents/CreditMemo-AI/backend/app/services/retrieval/rrf_fusion.py)

Reciprocal Rank Fusion:
- Constant: `k=60`
- `RRF_Score(d) = Σ [1.0 / (60 + Rank_dense(d)) + 1.0 / (60 + Rank_bm25(d))]`
- Input: ranked lists from BM25 and dense retriever
- Output: fused top-20 candidate list sorted by RRF score

---

#### [NEW] [backend/app/services/retrieval/reranker.py](file:///c:/Users/Shakti/Documents/CreditMemo-AI/backend/app/services/retrieval/reranker.py)

Neural cross-encoder reranking:
- Uses NVIDIA `nv-rerankqa-mistral-4b-v3` via `POST /v1/ranking`
- Falls back to Gemini-based relevance scoring if NVIDIA unavailable
- Input: query + top-20 fused candidates
- Output: top-6 calibrated citations with logit scores

---

#### [NEW] [backend/app/services/retrieval/pinecone_store.py](file:///c:/Users/Shakti/Documents/CreditMemo-AI/backend/app/services/retrieval/pinecone_store.py)

Pinecone Serverless client wrapper:
- Namespaces: `cbuae-manuals` (regulatory), `user-docs:{tenant_id}:{doc_id}` (uploaded docs)
- `upsert_chunks(chunks, namespace)` — batch upsert with metadata
- `query(embedding, namespace, top_k)` — similarity search
- `delete_namespace(namespace)` — cleanup on document deletion

---

#### [NEW] [backend/app/services/retrieval/hybrid_retriever.py](file:///c:/Users/Shakti/Documents/CreditMemo-AI/backend/app/services/retrieval/hybrid_retriever.py)

Orchestrates the full hybrid pipeline:
1. Embed query via active provider
2. Dense retrieval from Pinecone (both regulatory + uploaded doc namespaces)
3. BM25 lexical retrieval from in-memory corpus
4. RRF fusion of dense + BM25 results
5. Neural cross-encoder reranking → top-6 citations
6. Returns `RetrievalResult(citations: list[Citation], latency_ms: float)`

---

#### [NEW] [backend/scripts/index_regulatory_corpus.py](file:///c:/Users/Shakti/Documents/CreditMemo-AI/backend/scripts/index_regulatory_corpus.py)

One-time script to index CBUAE MMG PDFs into Pinecone:
1. Read PDFs from `base_documents/` directory
2. Extract to markdown via Docling
3. Chunk with `MarkdownChunker(chunk_size=2400, overlap=400)`
4. Generate dense embeddings
5. Upsert into Pinecone `cbuae-manuals` namespace with metadata (source_file, section, page)

---

### Phase 6: API Endpoints, SSE Streaming & Rate Limiting (Week 7-8)

Wire everything together with production API endpoints and infrastructure.

---

#### [NEW] [backend/app/api/query.py](file:///c:/Users/Shakti/Documents/CreditMemo-AI/backend/app/api/query.py)

Conversational Q&A endpoint with SSE streaming:
- `POST /query` — Accept `QueryRequest(document_id, question, session_id)`
- Flow:
  1. Load document chunks (masked) from DB
  2. Hybrid retrieval: query against both CBUAE corpus + uploaded doc chunks
  3. Build prompt with retrieved context (MMG chunks + document chunks)
  4. NeMo Guardrails input rails (jailbreak + PII check)
  5. Stream LLM response via SSE (`text/event-stream`)
  6. NeMo Guardrails output rails (hallucination + arithmetic check)
  7. Return citations alongside streamed response
- SSE event format: `data: {"type": "token", "content": "..."}\n\n`

---

#### [NEW] [backend/app/api/compare.py](file:///c:/Users/Shakti/Documents/CreditMemo-AI/backend/app/api/compare.py)

Document comparison endpoint:
- `POST /compare` — Accept `CompareRequest(document_id_a, document_id_b, focus_areas)`
- Retrieves chunks from both documents
- Uses LLM to generate structured comparison across:
  - Methodology differences
  - Assumption changes
  - Validation result deltas
  - Metric improvements/deteriorations
- Returns `CompareResponse` with side-by-side analysis

---

#### [NEW] [backend/app/api/gap_analysis.py](file:///c:/Users/Shakti/Documents/CreditMemo-AI/backend/app/api/gap_analysis.py)

Automated MMG gap analysis:
- `POST /gap-analysis` — Accept `GapAnalysisRequest(document_id)`
- Flow:
  1. Retrieve all chunks of the uploaded document
  2. Retrieve CBUAE MMG regulatory requirements (predefined checklist)
  3. For each MMG requirement, query the document chunks to check coverage
  4. Use LLM to assess compliance level per requirement
  5. Return `GapAnalysisResponse(gaps: list[ComplianceGap], coverage_score: float)`

---

#### [NEW] [backend/app/api/regulatory.py](file:///c:/Users/Shakti/Documents/CreditMemo-AI/backend/app/api/regulatory.py)

Standalone regulatory lookup (no document upload required):
- `POST /regulatory/search` — Accept `RegulatoryQuery(question)`
- Pure RAG against CBUAE corpus → returns answer with citations
- Useful for quick regulatory reference without uploading a document

---

#### [NEW] [backend/app/middleware/rate_limiter.py](file:///c:/Users/Shakti/Documents/CreditMemo-AI/backend/app/middleware/rate_limiter.py)

Upstash Redis rate limiting middleware:
- Loads Lua scripts (`token_bucket.lua`, `gcra_leaky_bucket.lua`) at startup
- `script_load()` for SHA-based `EVALSHA` execution
- Applies Token Bucket to client-facing endpoints (`/query`, `/compare`, `/gap-analysis`)
- Applies GCRA to upstream LLM calls
- Endpoint cost multipliers: `/query`=1, `/compare`=5, `/gap-analysis`=3
- Returns standard `429 Too Many Requests` with `Retry-After` header
- Pre-validates `cost ≤ capacity` to prevent unrecoverable 429 loops

---

#### [NEW] [backend/lua/token_bucket.lua](file:///c:/Users/Shakti/Documents/CreditMemo-AI/backend/lua/token_bucket.lua)

Atomic Token Bucket Lua script as specified in the architecture plan.

---

#### [NEW] [backend/lua/gcra_leaky_bucket.lua](file:///c:/Users/Shakti/Documents/CreditMemo-AI/backend/lua/gcra_leaky_bucket.lua)

Atomic GCRA Leaky Bucket Lua script as specified in the architecture plan.

---

### Phase 7: NeMo Guardrails 2.0 Integration (Week 8-9)

Full guardrails pipeline with Colang 2.0 flows and custom actions.

---

#### [NEW] [backend/app/services/guardrails/config.yml](file:///c:/Users/Shakti/Documents/CreditMemo-AI/backend/app/services/guardrails/config.yml)

NeMo Guardrails configuration:
- Registers both Gemini and NVIDIA NIM as LLM providers via LangChain adapter
- Uses `langchain-google-genai` for Gemini registration
- Uses `langchain-nvidia-ai-endpoints` for NVIDIA NIM registration
- Input rails: jailbreak check, prompt injection check, PII leakage scan
- Dialog rails: domain boundary enforcement (model validation + CBUAE only)
- Output rails: hallucination check, arithmetic verification, placeholder integrity

---

#### [NEW] [backend/app/services/guardrails/rails.co](file:///c:/Users/Shakti/Documents/CreditMemo-AI/backend/app/services/guardrails/rails.co)

Colang 2.0 flow definitions (adapted from architecture plan):
- `check jailbreak` → executes `check_jailbreak_action`
- `enforce credit domain boundary` → rejects off-topic queries
- `check hallucination against context` → `check_hallucination_action` with 0.3 threshold
- `verify financial calculation consistency` → `verify_financial_arithmetic_action`

Off-topic examples updated for model validation context (rejects stock advice, coding requests, general chitchat).

---

#### [NEW] [backend/app/services/guardrails/actions.py](file:///c:/Users/Shakti/Documents/CreditMemo-AI/backend/app/services/guardrails/actions.py)

Custom Python actions:
- `verify_financial_arithmetic_action` — Verifies Gini, AUC, KS, PSI calculations in LLM output
- `check_hallucination_action` — Grounding overlap check with decimal-safe sentence tokenization
- `check_placeholder_integrity_action` — Ensures no unmasked entities leaked into response

---

#### [NEW] [backend/app/services/guardrails/guardrails_service.py](file:///c:/Users/Shakti/Documents/CreditMemo-AI/backend/app/services/guardrails/guardrails_service.py)

Service wrapper that integrates NeMo Guardrails with the query pipeline:
- Initializes `RailsConfig` from config directory
- Provides `generate_with_guardrails(prompt, context)` method
- Handles guardrails blocking (returns user-friendly error messages)
- Bypasses guardrails for regulatory-only queries (no safety risk)

---

### Phase 8: React Frontend & AWS Deployment (Week 9-13)

> [!NOTE]
> Frontend component implementation depends on **Figma design** from the user. The structure below defines the technical scaffolding and component contracts.

---

#### [NEW] [frontend/](file:///c:/Users/Shakti/Documents/CreditMemo-AI/frontend/)

React 18 + TypeScript 5 + Vite project:
- **Auth pages**: Login, Register
- **Main dashboard** with 7 panels (layout from Figma):
  - Chat interface with SSE streaming (`EventSource` API)
  - Document viewer (extracted markdown rendered)
  - Metrics dashboard (Gini/AUC/KS/PSI cards with PASS/WARNING/BREACH)
  - Gap analysis checklist
  - Masking inspector (entity → token mapping table)
  - Document comparison split view
  - Citations panel (expandable source cards)
- **Custom hooks**: `useSSE()`, `useAuth()`, `useDocuments()`
- **API client**: Axios/fetch wrapper with JWT interceptor

---

#### [NEW] [deploy/aws/](file:///c:/Users/Shakti/Documents/CreditMemo-AI/deploy/aws/)

AWS deployment configuration:
- ECS Fargate task definition (backend container, 0.5 vCPU, 1GB RAM)
- ALB configuration with TLS termination
- Security groups (ALB → ECS only, ECS → RDS only)
- RDS PostgreSQL db.t4g.micro configuration

---

#### [NEW] [frontend/vercel.json](file:///c:/Users/Shakti/Documents/CreditMemo-AI/frontend/vercel.json)

Vercel deployment config:
- Build command: `npm run build`
- Output directory: `dist`
- Rewrites: API requests proxied to ECS Fargate backend URL
- Environment variables: `VITE_API_URL`

### Phase 9: CI/CD Pipeline (Week 13-14)

GitHub Actions CI/CD with three stages — this is a key FDE talking point.

---

#### [NEW] [.github/workflows/ci.yml](file:///c:/Users/Shakti/Documents/CreditMemo-AI/.github/workflows/ci.yml)

**Stage 1: PR-Level Quality Gates** (triggers on every Pull Request, ~2 minutes)

```yaml
name: CI - Quality Gates
on:
  pull_request:
    branches: [main, develop]

jobs:
  lint-and-type-check:
    # - Ruff linter (Python) + mypy type checking
    # - ESLint + TypeScript compiler (frontend)

  unit-tests:
    # - pytest backend/tests/ with PostgreSQL service container
    # - Privacy pipeline leak tests (0% leak tolerance)
    # - Financial metric extraction tests
    # - Rate limiter Lua script tests (Redis service container)

  security-scan:
    # - pip-audit for Python dependency vulnerabilities
    # - npm audit for frontend dependencies
    # - Trivy container image scan

  docker-build-check:
    # - Build backend Docker image (no push, validate Dockerfile)
    # - Build frontend Docker image (no push, validate Dockerfile)
```

Quality gates — PR is **blocked** if any of these fail:
- All unit tests pass (privacy leak rate must be 0.0%)
- No critical/high security vulnerabilities
- Docker images build successfully
- Linting and type checking pass

---

#### [NEW] [.github/workflows/deploy-staging.yml](file:///c:/Users/Shakti/Documents/CreditMemo-AI/.github/workflows/deploy-staging.yml)

**Stage 2: Staging Build & Integration Tests** (triggers on merge to `develop`)

```yaml
name: Deploy - Staging
on:
  push:
    branches: [develop]

jobs:
  build-and-push:
    # - Build backend Docker image
    # - Push to Amazon ECR (staging tag)
    # - Build frontend, deploy to Vercel preview

  integration-tests:
    # - Spin up full stack via Docker Compose in GitHub Actions
    # - Run end-to-end API tests (upload → mask → query → response)
    # - Verify SSE streaming works
    # - Test auth flow (register → login → protected endpoint)
    # - Test rate limiting (burst → 429 → retry-after)

  deploy-staging:
    # - Update ECS Fargate staging service with new task definition
    # - Run Alembic migrations against staging RDS
    # - Health check: poll /health until ready
```

---

#### [NEW] [.github/workflows/deploy-production.yml](file:///c:/Users/Shakti/Documents/CreditMemo-AI/.github/workflows/deploy-production.yml)

**Stage 3: Production Deployment** (triggers on merge to `main`, requires manual approval)

```yaml
name: Deploy - Production
on:
  push:
    branches: [main]

jobs:
  deploy-production:
    environment: production  # Requires manual approval in GitHub
    # - Pull staging-tested image from ECR
    # - Re-tag as production
    # - Update ECS Fargate production service
    # - Run Alembic migrations against production RDS
    # - Smoke test: hit /health, /auth/login, /query endpoints
    # - Rollback on failure: revert to previous task definition
```

---

#### [NEW] [.github/workflows/nightly-eval.yml](file:///c:/Users/Shakti/Documents/CreditMemo-AI/.github/workflows/nightly-eval.yml)

**Nightly Evaluation** (cron schedule, optional but impressive)

```yaml
name: Nightly - Evaluation Suite
on:
  schedule:
    - cron: '0 2 * * *'  # 2 AM UTC daily

jobs:
  evaluation:
    # - Run Ragas evaluation against golden test dataset
    # - Check retrieval quality (Hit@3, MRR, nDCG@5)
    # - Privacy adversarial stress test (100 adversarial masking cases)
    # - Post results to GitHub Actions summary
    # - Alert on Slack if any metric drops >5% from baseline
```

---

#### CI/CD Infrastructure Requirements

| Component | Service | Purpose |
|-----------|---------|---------|
| Container Registry | **Amazon ECR** (free tier: 500MB) | Store backend Docker images |
| CI Runner | **GitHub Actions** (free: 2000 min/month) | Run all pipelines |
| Staging Environment | Same ECS cluster, separate service | Pre-production validation |
| Secrets | **GitHub Actions Secrets** | AWS credentials, API keys, DB URLs |
| Manual Approval | **GitHub Environments** | Production deploy gate |

---

#### Repo Structure Addition (`.github/`)

```
.github/
├── workflows/
│   ├── ci.yml                    # PR quality gates
│   ├── deploy-staging.yml        # Staging build & deploy
│   ├── deploy-production.yml     # Production deploy (manual approval)
│   └── nightly-eval.yml          # Nightly evaluation suite
├── PULL_REQUEST_TEMPLATE.md      # PR checklist template
└── dependabot.yml                # Automated dependency updates
```

---

## Verification Plan

### Automated Tests (run in CI)

```bash
# Phase 1: Auth & DB
pytest backend/tests/test_auth.py -v

# Phase 2: Privacy Pipeline
pytest backend/tests/test_privacy_pipeline.py -v
# Includes: 0% entity leak rate, financial number preservation = 100%

# Phase 3: Analytics
pytest backend/tests/test_model_metrics_extractor.py -v
pytest backend/tests/test_policy_checker.py -v

# Phase 5: Retrieval
pytest backend/tests/test_hybrid_retrieval.py -v

# Phase 6: Rate Limiting
pytest backend/tests/test_rate_limiter.py -v

# Phase 7: Guardrails
pytest backend/tests/test_guardrails.py -v

# Full suite
pytest backend/tests/ -v --tb=short

# Linting & type checking
ruff check backend/
mypy backend/app/ --strict
```

### Integration Tests (run in CI staging)

```bash
# End-to-end API tests
pytest backend/tests/integration/ -v --timeout=60

# Includes:
# - Upload PDF → extract → mask → verify no leaks
# - Upload DOCX → extract → mask → verify no leaks
# - Query with RAG → verify citations returned
# - Compare two documents → verify delta analysis
# - Gap analysis → verify checklist completeness
# - Rate limit burst → verify 429 + Retry-After
# - Auth flow → verify tenant isolation
# - Jailbreak prompt → verify guardrails block
```

### Manual Verification

1. **Docker Compose smoke test**: `docker compose up` → all 3 services healthy
2. **Auth flow**: Register two demo users in different tenants → verify tenant isolation
3. **Upload flow**: Upload a sample model validation PDF **and DOCX** → verify Docling extraction + table accuracy + masking
4. **Q&A flow**: Ask "Does this model meet CBUAE Gini requirements?" → verify RAG response with citations from both MMG corpus and uploaded doc
5. **Gap analysis**: Run automated gap scan → verify checklist against known document
6. **Masking inspector**: Verify entity registry shows correct token mappings
7. **Provider routing**: Test with both NVIDIA (primary) and Gemini (fallback) keys → verify automatic routing and fallback behavior
8. **Rate limiting**: Send rapid-fire requests → verify 429 responses with correct `Retry-After`
9. **Guardrails**: Send jailbreak prompt → verify blocking; send off-topic → verify refusal
10. **CI/CD**: Push a PR → verify quality gates run; merge → verify staging deploy; approve → verify production deploy
11. **AWS deployment**: Verify live URL responds, ECS health checks pass, ALB routes correctly


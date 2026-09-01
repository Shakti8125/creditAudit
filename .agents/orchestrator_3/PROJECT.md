# Project: ModelAudit AI Backend Deep Review & Remediation

## Architecture
- FastAPI Python 3.12 Backend (`backend/app/`)
- Multi-tenancy isolation (`tenant_id` on all DB queries and vector namespaces)
- Zero-trust Privacy Masking (reverse character slicing, in-memory session registry, strict egress validation)
- Dual-provider LLM routing (NVIDIA NIM primary, Gemini 2.0 Flash secondary with circuit breaker)
- Hybrid Retrieval (BM25 + Pinecone 1024-dim dense with RRF fusion and reranking)
- Analytics & CBUAE MMG Policy Engine (AUC, Gini, PSI, Hosmer-Lemeshow, Brier score, PD accuracy ratio)
- NeMo Guardrails (Colang 2.0 flow override, placeholder checks)

## Feature Inventory
| # | Feature | Description | Milestone | Source |
|---|---------|-------------|-----------|--------|
| 1 | Privacy Pipeline | EntityRegistry, BankMatcher, NERMasker, MaskingPipeline, EgressValidator | M1 | ORIGINAL_REQUEST |
| 2 | LLM Routing & Providers | NVIDIA NIM, Gemini, CircuitBreaker, LLMRouter | M2 | ORIGINAL_REQUEST |
| 3 | Document Extraction | Docling extractor, Word format, Markdown chunker, table preservation | M3 | ORIGINAL_REQUEST |
| 4 | Retrieval & Hybrid RAG | BM25Okapi, PineconeStore, DenseRetriever, RRFFusion, Reranker, Orchestrator | M4 | ORIGINAL_REQUEST |
| 5 | Analytics Engine | ModelMetricsExtractor, PolicyChecker, EarlyWarning | M5 | ORIGINAL_REQUEST |
| 6 | API, Auth, Streaming, Guardrails | Auth endpoints, document upload, gap analysis, SSE streaming, Upstash rate limiting, NeMo | M6 | ORIGINAL_REQUEST |
| 7 | DB Models & Schemas | SQLAlchemy 2.0 async models, Alembic migrations, Pydantic v2 schemas, config | M7 | ORIGINAL_REQUEST |

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| M1 | Exploration | Comprehensive inspection of all backend code for bugs/edge cases | None | IN_PROGRESS |
| M2 | Worker Remediation | Apply fixes with inline comments explaining each issue resolved | M1 | PLANNED |
| M3 | Code Review & Challenge | Senior peer review and test suite execution | M2 | PLANNED |
| M4 | Forensic Audit | Zero-tolerance integrity & privacy check | M3 | PLANNED |
| M5 | Master Handoff | Final synthesis and report to Sentinel | M4 | PLANNED |

## Code Layout
- `backend/app/privacy/` — Zero-trust masking, entity registry, bank matcher, egress validator
- `backend/app/llm/` or `backend/app/services/llm/` — NVIDIA NIM, Gemini, Circuit breaker, Router
- `backend/app/extraction/` / `backend/app/chunking/` — Docling integration, Markdown chunker
- `backend/app/retrieval/` / `backend/app/vector/` — BM25, Pinecone store, RRF fusion, Reranker
- `backend/app/analytics/` / `backend/app/policy/` — Metric extraction, CBUAE policy checks
- `backend/app/api/` — FastAPI routes (auth, documents, gap_analysis, chat)
- `backend/app/core/` / `backend/app/middleware/` — Security, config, rate limiting, streaming
- `backend/app/guardrails/` — NeMo Guardrails service, actions, configs
- `backend/app/models/` — SQLAlchemy 2.0 DeclarativeBase models
- `backend/app/schemas/` — Pydantic v2 BaseModel schemas
- `backend/tests/` — Pytest test suites

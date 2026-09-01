# Plan — ModelAudit AI Backend Deep Review & Remediation (orchestrator_3)

## Objective
Conduct a full-scale multi-agent review of the Python FastAPI backend codebase across all modules for bugs, edge cases, Python 3.12 compatibility, Docling/LLM APIs, privacy and multi-tenancy rules, implement robust fixes with inline explanatory comments, and verify via py_compile, tests, code reviews, adversarial challenges, and forensic audit.

## Decomposition into Domains
1. **Domain 1: Privacy Pipeline & Zero-Trust Masking** (`backend/app/privacy/` or `app/services/privacy/`)
   - Components: `entity_registry.py`, `bank_matcher.py`, `ner_masker.py`, `masking_pipeline.py`, `egress_validator.py`
   - Focus: Character offset preservation, reverse replacement, bracket tokens, entity leak prevention, in-memory session isolation.

2. **Domain 2: LLM Providers, Routing & Circuit Breakers** (`backend/app/llm/` or `app/services/llm/`)
   - Components: `nvidia_nim.py`, `gemini.py`, `circuit_breaker.py`, `router.py`, base provider interfaces.
   - Focus: Async streaming generators, graceful fallback/failover, locked state transitions, aclose lifecycle, API payload schemas.

3. **Domain 3: Document Extraction & Chunking** (`backend/app/extraction/`, `backend/app/chunking/` or `app/services/extraction/`)
   - Components: Docling integration, Word docx option, Markdown table preservation, overlapping chunk aggregation, financial comma handling.

4. **Domain 4: Retrieval & Hybrid Search (BM25 + Vector)** (`backend/app/retrieval/`, `backend/app/vector/` or `app/services/retrieval/`)
   - Components: `bm25.py`, `pinecone_store.py`, `dense_retriever.py`, `rrf_fusion.py`, `reranker.py`, hybrid orchestrator.
   - Focus: Multi-tenant namespace isolation (`tenant_id`), async wrapping (`asyncio.to_thread`), zero-division guards, score normalization.

5. **Domain 5: Analytics & Regulatory Verification Engine** (`backend/app/analytics/`, `backend/app/policy/`)
   - Components: `model_metrics_extractor.py`, `policy_checker.py`, `early_warning.py`.
   - Focus: Comma-formatted numbers (`1,250,000`), CBUAE MMG compliance thresholds (AUC, PSI, Gini, Hosmer-Lemeshow, Brier, PD accuracy ratio).

6. **Domain 6: API Routes, Auth, Streaming, Rate Limiter & NeMo Guardrails** (`backend/app/api/`, `backend/app/core/`, `backend/app/guardrails/`, `backend/app/middleware/`)
   - Components: Auth routes/deps, Document upload streaming, Gap analysis SSE streaming, Upstash Redis Lua scripts, Colang flows.
   - Focus: Multi-tenancy JWT validation, safe file streaming, reverse-proxy SSE headers, Colang 2.0 override.

7. **Domain 7: Database Models, Migrations, Async DB Sessions & Pydantic v2 Schemas** (`backend/app/models/`, `backend/app/schemas/`, `backend/app/db/`, `alembic/`)
   - Components: SQLAlchemy 2.0 `DeclarativeBase`, `Mapped[]`, `pool_pre_ping`, `alembic/env.py`, `model_config = ConfigDict(from_attributes=True)`.

## Execution Workflow
- **Step 1**: Dispatch 6 parallel Explorers (`explorer_m1` .. `explorer_m6`) across the domains to systematically inspect all files under `backend/app/` for any outstanding bugs, syntax issues, runtime edge cases, or missing comments.
- **Step 2**: Aggregate Explorer findings and synthesize domain remediation work orders.
- **Step 3**: Dispatch parallel Workers (`worker_m1` .. `worker_m6`) to implement verified fixes, ensure all modified code has clear inline explanatory comments, and verify via `python -m py_compile`.
- **Step 4**: Dispatch Reviewers (`reviewer_1`, `reviewer_2`) to independently verify correctness and tech stack compliance.
- **Step 5**: Dispatch Adversarial Challengers (`challenger_1`, `challenger_2`) to execute the comprehensive test suite (`pytest backend/tests`).
- **Step 6**: Dispatch Forensic Auditor (`auditor_1`) to verify 0 integrity violations, 0 cheating, and 100% adherence to privacy and multi-tenancy rules.
- **Step 7**: Compile `GATE_STATUS.md` and master handoff report at `.agents/orchestrator_3/handoff.md`.

# ModelAudit AI Backend Remediation Plan

## Architecture & Code Layout
- Root: `c:\Users\Shakti\Documents\CreditAudit- AI`
- Backend Source: `backend/app/`
- Configuration & Database: `backend/app/config.py`, `backend/app/db/`, `backend/app/models/`, `backend/alembic/`
- Schemas: `backend/app/schemas/`
- Services:
  - Privacy: `backend/app/services/privacy/`
  - Extraction & Chunking: `backend/app/services/chunker.py`, `backend/app/services/document_extractor.py`
  - LLM: `backend/app/services/llm/`
  - Guardrails: `backend/app/services/guardrails/`
  - Retrieval: `backend/app/services/retrieval/`
  - Analytics: `backend/app/services/analytics/`
- API & Middleware: `backend/app/api/`, `backend/app/middleware/`, `backend/app/main.py`
- Dependencies & Docker: `backend/requirements.txt`, `backend/Dockerfile`

---

## Milestone Decomposition

### Milestone 1: Foundation, Dependencies, Config & Database Models
- **Issues**: DEP-01 to DEP-08, CFG-01, CFG-04, MOD-01 to MOD-05, SCH-01 to SCH-03
- **Files Owned**: `backend/requirements.txt`, `backend/Dockerfile`, `backend/app/config.py`, `backend/app/utils/security.py`, `backend/app/db/database.py`, `backend/app/models/`, `backend/alembic/env.py`, `backend/app/schemas/`
- **Domain Skill**: `p1-database-auth`, `p1-project-scaffold`
- **Key Deliverables**:
  - Update `requirements.txt` with PyJWT, bcrypt 4.x, pinecone>=5.0.0, spacy>=3.7.2, remove langchain redundancies.
  - Fix Dockerfile runtime stage C-libraries (`libgl1`, `libglib2.0-0`, `libgomp1`).
  - Configure RS256 RSA PEM key pairs in `config.py` and implement `security.py` using `PyJWT` and direct `bcrypt`.
  - Update `database.py` with `DeclarativeBase` and `pool_pre_ping=True`.
  - Add `index=True` to multi-tenant foreign keys in `models/user.py`, `models/document.py`.
  - Re-export models in `models/__init__.py` and import them in `alembic/env.py`.
  - Add `model_config = ConfigDict(from_attributes=True)` across all schemas and export in `schemas/__init__.py`.
  - Replace `datetime.utcnow()` with `datetime.now(timezone.utc)`.

### Milestone 2: Privacy Pipeline & Zero-Trust Masking Core
- **Issues**: PRV-01 to PRV-12
- **Files Owned**: `backend/app/services/privacy/`
- **Domain Skill**: `p2-privacy-pipeline`
- **Key Deliverables**:
  - Fix `masking_pipeline.py`: perform replacements in reverse character offset slice order on `raw_text`.
  - Fix `egress_validator.py`: verify all `registry.get_mapping().keys()` against text, exclude valid bracket tokens `r"^\[(BANK|ORG|PERSON|EMAIL|PHONE|GPE|LOC|PRODUCT|SYSTEM|METRIC)_\d+\]$"`, support injected/singleton models.
  - Fix `bank_matcher.py`: convert Aho-Corasick `end_char_index` to standard half-open `[start, end)` slice, lowercase matching with word boundary validation.
  - Fix `ner_masker.py`: remove runtime `spacy.cli.download`, expand `FINANCIAL_PATTERNS` regex to include GCC currencies, formatted decimal numbers, ISO dates, reuse spaCy instance in Presidio.
  - Fix `entity_registry.py`: single-pass atomic regex replacement for `unmask_text`, strip whitespace in `mask()`.
  - Fix `gcc_bank_names.json`: fix typo "Barclids" -> "Barclays".

### Milestone 3: Document Extraction & Chunking
- **Issues**: DOC-01 to DOC-07
- **Files Owned**: `backend/app/services/chunker.py`, `backend/app/services/document_extractor.py`, `backend/app/services/__init__.py`
- **Domain Skill**: `p2-document-extraction`
- **Key Deliverables**:
  - Fix `chunker.py`: fix `_split_text` accumulation bug so chunks reach `chunk_size`, detect and preserve Markdown tables as atomic chunks exempt from 8-word filter, implement sliding window `overlap`, preserve punctuation/formatting and double newlines.
  - Fix `document_extractor.py`: wrap Docling `convert()` with structured `DocumentExtractionError`, add `WordFormatOption` for DOCX.

### Milestone 4: LLM Providers, Circuit Breaker & Routing
- **Issues**: LLM-01 to LLM-07
- **Files Owned**: `backend/app/services/llm/`
- **Domain Skill**: `p4-llm-routing`
- **Key Deliverables**:
  - Fix `router.py`: implement `generate_stream` as a direct async generator yielding chunks, add automatic multi-provider fallback/failover.
  - Fix `circuit_breaker.py`: dedicated `call_stream` async generator wrapper, `asyncio.Lock()` on state transitions.
  - Fix `nvidia_provider.py`: fix `/v1/ranking` structured payload `{"model": ..., "query": {"text": ...}, "passages": [{"text": p} ...]}` and use relative URL `"ranking"`, add `aclose()` for `AsyncClient`.
  - Fix `base_provider.py`: add default parameters `temperature: float = 0.7`, `max_tokens: int = 1024` to abstract methods and implementations.

### Milestone 5: NeMo Guardrails Integration & Colang Flows
- **Issues**: GRD-01 to GRD-06
- **Files Owned**: `backend/app/services/guardrails/`
- **Domain Skill**: `p7-nemo-guardrails`
- **Key Deliverables**:
  - Fix `guardrails_service.py`: handle dict response from `generate_async` extracting string content, pass `context` and `retrieved_contexts` into `generate_async`.
  - Fix `rails.co`: define missing `bot refuse to respond` utterance.
  - Fix `config.yml`: set `colang_version: "2.x"` and resolve conflicting `type: main` models.
  - Fix `actions.py`: implement entity placeholder integrity validation, preserve comma-formatted numbers and filter English stop words in hallucination metric.

### Milestone 6: Retrieval Pipeline & Hybrid Search
- **Issues**: RET-01 to RET-14
- **Files Owned**: `backend/app/services/retrieval/`
- **Domain Skill**: `p5-hybrid-rag`
- **Key Deliverables**:
  - Fix `pinecone_store.py`: default settings in `__init__`, implement `upsert_chunks`, safe guard on empty index `stats.namespaces`, log exceptions, `asyncio.to_thread` for blocking calls.
  - Fix `hybrid_retriever.py`: enforce `Document.tenant_id == tenant_id` join filter in `_fetch_chunks_for_document` (RET-06), index regulatory guidelines in BM25.
  - Fix `bm25.py`: reset state in `fit()`, regex tokenization preserving comma-formatted financial numbers, guard `avgdl == 0`.
  - Fix `dense_retriever.py`: use `asyncio.gather` for parallel namespace querying.
  - Fix `reranker.py` & `rrf_fusion.py`: clone candidate objects via `model_copy`, fallback to RRF candidates on reranker failure, normalize RRF scores.

### Milestone 7: Analytics Engine & Regulatory Verification
- **Issues**: ANA-01 to ANA-09
- **Files Owned**: `backend/app/services/analytics/`
- **Domain Skill**: `p3-model-validation-analytics`
- **Key Deliverables**:
  - Fix `model_metrics_extractor.py`: comma-formatted numbers regex `\d{1,3}(?:,\d{3})*(?:\.\d+)?|\d+(?:\.\d+)?`, fix unit quantifier alternation `(?P<unit>%|percent|bps|bp)?`, include Markdown table delimiter support `[:=|\|\s]+`, normalize `bps` by dividing by 100.
  - Fix `policy_checker.py`: normalize unflagged percentages when `val > 1.0`, align CBUAE AUC thresholds (<0.70 breach, 0.70-0.75 warning, >=0.75 pass), implement Hosmer-Lemeshow / Brier / PD calibration checks.
  - Fix `ews_detector.py`: normalize observed vs predicted ratios when `val > 10.0`, add medium severity warning signal for 0.10 <= PSI <= 0.25.

### Milestone 8: API Endpoints, Middleware, Auth & Integration
- **Issues**: API-01 to API-11, MID-01 to MID-04, CFG-02, CFG-03
- **Files Owned**: `backend/app/api/`, `backend/app/middleware/`, `backend/app/utils/streaming.py`, `backend/app/main.py`
- **Domain Skill**: `p6-api-streaming-ratelimit`, `p1-database-auth`
- **Key Deliverables**:
  - Fix `TokenPayload` attribute access: use `current_user.tenant_id` across `query.py`, `compare.py`, `gap_analysis.py`, `regulatory.py`, and `rate_limiter.py`.
  - Fix `query.py`: verify document tenant ownership in DB before retrieval (API-02).
  - Fix `query.py`, `compare.py`, `regulatory.py`: run user prompt through `MaskingPipeline` and `EgressValidator` before LLM generation (API-03).
  - Fix `documents.py`: chunked streaming file upload with running byte counter (API-04), sanitize filename (API-05), omit raw entity mapping in response (API-06), DB rollback on failure (API-07).
  - Fix `deps.py` & `auth.py`: consolidate canonical `get_current_user`, verify `user.is_active` (API-09), verify token `type == 'access'` (API-10).
  - Fix `gap_analysis.py`: return structured error on LLM failure (API-11).
  - Fix `rate_limiter.py`: dynamic Lua path resolution (MID-02), include `tier` claim in JWT (MID-03).
  - Fix `auth_middleware.py`: re-raise `HTTPException` (MID-04).
  - Fix `streaming.py`: add `X-Accel-Buffering: no` and `Cache-Control: no-cache` headers (CFG-03).
  - Fix `main.py`: register `CORSMiddleware` with default allowed origins (CFG-02).

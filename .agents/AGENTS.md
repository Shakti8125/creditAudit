# ModelAudit AI — Agent Rules

## Project Identity

- **Name**: ModelAudit AI
- **Purpose**: Privacy-preserving virtual analyst for model development/validation documents against CBUAE MMG regulatory standards
- **Type**: Portfolio project targeting FDE (Forward Deployed Engineer) roles in UAE banking/finance

## Tech Stack (STRICT — do NOT substitute)

- **Backend**: Python 3.12, FastAPI 0.112+, Uvicorn, Pydantic v2
- **Frontend**: React 18, TypeScript 5, Vite (design from Figma — pending)
- **Database**: PostgreSQL 16 (AWS RDS db.t4g.micro in prod, Docker locally)
- **ORM**: SQLAlchemy 2.0+ (async), Alembic for migrations
- **Vector Store**: Pinecone Serverless (free tier, 1024-dim vectors)
- **Rate Limiting**: Upstash Serverless Redis (REST API) with atomic Lua scripts
- **LLM Providers**: NVIDIA NIM (primary), Google Gemini (secondary/fallback)
- **LLM SDK**: `openai` 1.40+ (for NVIDIA NIM), `google-genai` (for Gemini)
- **Document Extraction**: IBM Docling 2.0+ (PDF + Word)
- **NER / Privacy**: spaCy 3.7+ (`en_core_web_lg`), Microsoft Presidio, pyahocorasick
- **Guardrails**: NeMo Guardrails 0.11+ (Colang 2.0)
- **Auth**: Custom RS256 JWT (PyJWT, bcrypt)
- **Deployment**: Docker Compose (local), AWS ECS Fargate (prod), Vercel (frontend)
- **CI/CD**: GitHub Actions

## Code Conventions

1. **All backend code** lives under `backend/app/`. Use absolute imports from `app.` prefix.
2. **Async-first**: All service methods, API handlers, and DB operations MUST be async (`async def`).
3. **Type hints required**: Every function must have full type annotations. Use `from __future__ import annotations`.
4. **Pydantic v2**: All request/response schemas use Pydantic `BaseModel` with `model_config = ConfigDict(...)`.
5. **Error handling**: Never use bare `except:`. Always catch specific exceptions. Log with `logging.getLogger(__name__)`.
6. **Docstrings**: Every class and public method must have a Google-style docstring.
7. **Tests**: Every module gets a corresponding test file in `backend/tests/`. Use pytest + pytest-asyncio.
8. **Environment variables**: All config loaded via Pydantic `BaseSettings` in `app/config.py`. Never hardcode secrets.
9. **Pinned model IDs** *(amended 2026-09-30, D2)*: LLM, embedding and rerank model identifiers are exact model IDs defined in `app/config.py` settings, never `latest` or other moving aliases. NVIDIA NIM is the primary provider. Gemini is the **failover-only backup** for generation, streaming and structured output (default `gemini-3.6-flash`; never `gemini-2.5-flash`, which has an announced shutdown). Before changing a model ID, confirm the model is GA with no announced shutdown. A weekly provider canary catches retirements. (Target state is implemented by remediation PR-01; until then the code still has the retired `gemini-2.0-flash` constant.)
10. **Financial numbers**: Commas in numbers (e.g., `1,250,000`) must be preserved during text processing. Never split on commas.

## Architecture Reference

- **Full architecture spec**: See `architecture_plan.md` in repo root
- **Approved implementation plan**: See the implementation plan artifact in the conversation
- **Finalized scope**: See the finalized scope artifact in the conversation

## Privacy Rules (CRITICAL)

- Entity registry MUST stay in server-side session memory only — NEVER persist to disk or database. (A registry *rebuilt* deterministically from already-persisted chat messages is allowed; nothing new is persisted. See remediation plan QA-011.)
- No real entity names (bank names, org names, person names) may be sent to any LLM provider
- Financial numbers (currencies, ratios, percentages, dates) are NEVER masked
- The egress validator MUST run before any text is sent to an LLM provider
- All masking tokens use bracket notation: `[BANK_1]`, `[ORG_1]`, `[PERSON_1]`
- *(Amended 2026-09-30, D2)* **Public regulatory reference text** listed in `backend/regulatory_corpus/manifest.yaml` (CBUAE rulebook text, Basel excerpts, IFRS 9 reference cards) is not tenant data. It may be embedded, reranked and sent to providers **unmasked**, provided that the bank-name egress lint ran on it at ingest. Every prompt still passes the egress validator. Tenant data (questions, history, uploaded documents, filenames) is masked exactly as before.
- Raw upload filenames are never sent to any provider and never stored in Pinecone metadata (use `document_id` and `DOC-n` aliases).

## Multi-Tenancy Rules

- Every database query MUST filter by `tenant_id` from the JWT. *(Exception, amended 2026-09-30, D2)*: the global public reference tables `regulatory_standards`, `regulatory_documents`, `regulatory_chunks`, `regulatory_thresholds` and `corpus_ingest_runs` have no `tenant_id`. They are written only by the corpus ingest job and are read-only through the API.
- Every Pinecone namespace for user documents MUST include `tenant_id`
- Users in different tenants MUST NOT see each other's documents or sessions
- The shared regulatory Pinecone namespace (`reg-<generation>`) holds only public reference text and is the one namespace without `tenant_id`.

## Regulatory Corpus Rules (approved 2026-09-30)

- **Never run `scripts/seed_regulatory_standards.py` or `scripts/index_regulatory_corpus.py`.** The seed contains thresholds CBUAE never published, and the indexer exits 0 without doing anything. Both are replaced by `python -m scripts.regulatory` (corpus plan C1-C3).
- The corpus is data, not code: sources live in the private S3 bucket and are listed in the git manifest; Postgres is the source of truth; Pinecone and BM25 are derived.
- **Embeddings never fail over across providers.** Index and query vectors must come from the same pinned model and dimension.
- **Licence gates are mandatory**: an ingest mode must be allowed by the source's `license.status` (`docs/qa/regulatory-corpus-ingestion-plan.md` §2.1). Basel stays `brief_excerpt` and IFRS 9 stays `reference_only` until the owner records written permission.
- Never present international material (Basel, IFRS 9) as a CBUAE requirement, and never state a numeric threshold as regulatory unless it is in `regulatory_thresholds` with a verified verbatim source.

## Current work stream

- Start at `docs/qa/README.md`: owner decisions, the work queue with live status, and the protocol for picking up and finishing items.

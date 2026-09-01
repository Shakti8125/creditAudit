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
9. **Pinned model IDs**: LLM model identifiers are constants, never `latest`. Gemini pinned to `gemini-2.0-flash`.
10. **Financial numbers**: Commas in numbers (e.g., `1,250,000`) must be preserved during text processing. Never split on commas.

## Architecture Reference

- **Full architecture spec**: See `architecture_plan.md` in repo root
- **Approved implementation plan**: See the implementation plan artifact in the conversation
- **Finalized scope**: See the finalized scope artifact in the conversation

## Privacy Rules (CRITICAL)

- Entity registry MUST stay in server-side session memory only — NEVER persist to disk or database
- No real entity names (bank names, org names, person names) may be sent to any LLM provider
- Financial numbers (currencies, ratios, percentages, dates) are NEVER masked
- The egress validator MUST run before any text is sent to an LLM provider
- All masking tokens use bracket notation: `[BANK_1]`, `[ORG_1]`, `[PERSON_1]`

## Multi-Tenancy Rules

- Every database query MUST filter by `tenant_id` from the JWT
- Every Pinecone namespace for user documents MUST include `tenant_id`
- Users in different tenants MUST NOT see each other's documents or sessions

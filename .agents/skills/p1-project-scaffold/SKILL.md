---
name: p1-project-scaffold
description: >-
  Use this skill to scaffold the entire monorepo project structure for ModelAudit AI Phase 1, including backend, frontend, deployment, and configuration files.
---

# p1-project-scaffold

Detailed step-by-step instructions for the agent to scaffold the ModelAudit AI project.

## Steps

1. **Create the monorepo directory structure**:
   - `backend/app/` with subdirectories: `api/`, `models/`, `schemas/`, `services/`, `middleware/`, `db/`, `utils/`
   - `backend/app/services/` with subdirectories: `privacy/`, `analytics/`, `llm/`, `retrieval/`, `guardrails/`
   - `backend/tests/`, `backend/tests/integration/`
   - `backend/scripts/`, `backend/base_documents/`, `backend/lua/`
   - `frontend/src/` with subdirectories: `api/`, `components/`, `hooks/`, `pages/`, `stores/`, `types/`
   - `deploy/aws/`
   - `.github/workflows/`

2. **Create `__init__.py` files**:
   - Create an empty `__init__.py` in every Python package directory created above.

3. **Create `.env.example`** with all required environment variables:
   ```env
   DATABASE_URL=
   REDIS_URL=
   REDIS_TOKEN=
   NVIDIA_API_KEY=
   NVIDIA_BASE_URL=
   GEMINI_API_KEY=
   PINECONE_API_KEY=
   PINECONE_INDEX_NAME=
   JWT_SECRET_KEY=
   JWT_ALGORITHM=RS256
   ALLOWED_ORIGINS=
   ```

4. **Create `backend/requirements.txt`** with ALL pinned dependencies:
   ```text
   fastapi>=0.112.0
   uvicorn[standard]
   pydantic[dotenv]>=2.0
   pydantic-settings
   sqlalchemy[asyncio]>=2.0
   asyncpg
   alembic
   openai>=1.40.0
   google-genai
   docling>=2.0.0
   docling-core
   spacy>=3.7.0
   presidio-analyzer
   presidio-anonymizer
   pyahocorasick
   pinecone-client
   upstash-redis
   nemoguardrails>=0.11.0
   python-jose[cryptography]
   passlib[bcrypt]
   python-multipart
   httpx
   tiktoken
   pytest
   pytest-asyncio
   ruff
   mypy
   ```

5. **Create `docker-compose.yml`** with 3 services:
   - `backend`: Build from `./backend/Dockerfile`, port 8001, volumes for hot-reload, depends on db and redis.
   - `db`: postgres:16-alpine, port 5432, volume `pgdata`, env POSTGRES_DB/USER/PASSWORD.
   - `redis`: redis:7-alpine, port 6379.

6. **Create `backend/Dockerfile`**:
   - Multi-stage build: builder installs dependencies and spacy model, runtime runs uvicorn.

7. **Create `.gitignore`**:
   - Ignore Python (`__pycache__`, `*.pyc`, etc.)
   - Ignore Node (`node_modules/`, etc.)
   - Ignore `.env` files.
   - Ignore `backend/base_documents/`

## Verification
- Running `docker compose config` should validate without errors.

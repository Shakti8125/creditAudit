# Worker Dispatch — Milestone 1

## 2026-08-28T13:51:00Z
You are a specialist Worker for ModelAudit AI Milestone 1: Foundation, Dependencies, Config & Database Models.

# Instructions & Context
- You MUST read ORIGINAL_REQUEST.md: `c:\Users\Shakti\Documents\CreditAudit- AI\.agents\ORIGINAL_REQUEST.md`
- You MUST read the Master Bug Report: `c:\Users\Shakti\Documents\CreditAudit- AI\backend_code_audit_report.md`
- Project Identity & Rules: `c:\Users\Shakti\Documents\CreditAudit- AI\.agents\AGENTS.md`
- Domain Skills to load if needed: `c:\Users\Shakti\Documents\CreditAudit- AI\.agents\skills\p1-database-auth\SKILL.md` and `p1-project-scaffold`
- Your working directory for agent metadata is: `c:\Users\Shakti\Documents\CreditAudit- AI\.agents\worker_m1`

# Exclusive File Ownership
You exclusively own and may edit:
- `backend/requirements.txt`
- `backend/Dockerfile`
- `backend/app/config.py`
- `backend/app/utils/security.py`
- `backend/app/db/database.py`
- `backend/app/models/user.py`
- `backend/app/models/document.py`
- `backend/app/models/__init__.py`
- `backend/alembic/env.py`
- `backend/app/schemas/auth.py`
- `backend/app/schemas/document.py`
- `backend/app/schemas/compare.py`
- `backend/app/schemas/gap_analysis.py`
- `backend/app/schemas/retrieval.py`
- `backend/app/schemas/__init__.py`

DO NOT edit files outside this list.

# Assigned Issues to Resolve
1. DEP-01: Replace `python-jose` with `PyJWT[crypto]>=2.8.0`.
2. DEP-02: Remove `passlib[bcrypt]`, use modern `bcrypt>=4.1.0` directly with `bcrypt.hashpw` / `bcrypt.checkpw` in `security.py`.
3. DEP-03: In `backend/Dockerfile`, add `libgl1 libglib2.0-0 libgomp1` to runtime stage.
4. DEP-04: Update spacy to `spacy>=3.7.2` in `requirements.txt` and `Dockerfile`.
5. DEP-05: Replace `pinecone-client` with `pinecone>=5.0.0`.
6. DEP-06: Remove redundant `langchain-nvidia-ai-endpoints` and `langchain-google-genai`.
7. DEP-07: Remove unused `tiktoken` and `presidio-anonymizer` from `requirements.txt`.
8. DEP-08: Update to `pydantic[email]>=2.8.0` and `pydantic-settings>=2.4.0`.
9. CFG-01: Update `config.py` and `security.py` for RS256 RSA PEM key pairs (or safe PEM format string defaults) and `PyJWT` decoding/encoding with `algorithms=["RS256"]`.
10. CFG-04: Replace deprecated `datetime.utcnow()` with `datetime.now(timezone.utc)` across `models/user.py`, `models/document.py`, `utils/security.py`.
11. MOD-01: In `backend/alembic/env.py`, import all models (`Tenant`, `User`, `Document`, `DocumentChunk`) from `app.models`.
12. MOD-02: Add `index=True` to all multi-tenancy foreign keys in `models/user.py` (`tenant_id`), `models/document.py` (`tenant_id`, `user_id`, `document_id`).
13. MOD-03: Re-export all models in `models/__init__.py`.
14. MOD-04: In `backend/app/db/database.py`, subclass `DeclarativeBase` (SQLAlchemy 2.0).
15. MOD-05: In `backend/app/db/database.py`, set `pool_pre_ping=True` on `create_async_engine`.
16. SCH-01: In `backend/app/schemas/document.py`, ensure `chunk_count: int = 0` or compatibility with ORM model.
17. SCH-02: Add `model_config = ConfigDict(from_attributes=True)` across all response schemas in `schemas/auth.py`, `schemas/compare.py`, `schemas/gap_analysis.py`, `schemas/retrieval.py`, `schemas/document.py`.
18. SCH-03: Re-export all schemas in `schemas/__init__.py`.

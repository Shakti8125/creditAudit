---
name: p1-database-auth
description: >-
  Use this skill to build the PostgreSQL database layer and JWT authentication system for ModelAudit AI Phase 1.
---

# p1-database-auth

Detailed step-by-step instructions for the agent to build the database layer and authentication system.

## Steps

1. **Create `backend/app/config.py`**:
   - Define a Pydantic BaseSettings loading all env vars.
   - Include nested config classes for database, redis, pinecone, nvidia, gemini, jwt, rate_limits.

2. **Create `backend/app/db/database.py`**:
   - Async SQLAlchemy engine + session factory.
   - `create_async_engine` with `asyncpg` driver, `pool_size=5`, `max_overflow=10`.
   - `async_sessionmaker` with `expire_on_commit=False`.
   - `get_db()` FastAPI dependency yielding async sessions.

3. **Create `backend/app/models/user.py`** (SQLAlchemy ORM models, SQLAlchemy 2.0 style using `Mapped[]` and `mapped_column`):
   - `Tenant(id: UUID, name: str, tier: TierEnum, created_at: datetime)`
     - TierEnum: FREE, PROFESSIONAL, ENTERPRISE
   - `User(id: UUID, tenant_id: FK, email: str unique, hashed_password: str, role: RoleEnum, is_active: bool, created_at)`
     - RoleEnum: ANALYST, SENIOR_RISK_OFFICER, COMPLIANCE_AUDITOR, ADMIN

4. **Create `backend/app/utils/security.py`**:
   - Password hashing (bcrypt) and JWT RS256 token creation/verification.
   - `hash_password(plain: str) -> str`
   - `verify_password(plain: str, hashed: str) -> bool`
   - `create_access_token(user_id: UUID, tenant_id: UUID, role: str) -> str` (1-hour expiry)
   - `create_refresh_token(user_id: UUID) -> str` (7-day expiry)
   - `decode_token(token: str) -> TokenPayload` (validates RS256 signature)

5. **Create `backend/app/schemas/auth.py`** (Pydantic schemas):
   - `RegisterRequest(email, password, tenant_name)`
   - `LoginRequest(email, password)`
   - `TokenResponse(access_token, refresh_token, token_type, expires_in)`
   - `TokenPayload(sub: UUID, tenant_id: UUID, role: str, exp: int)`

6. **Create `backend/app/api/auth.py`** (FastAPI router):
   - `POST /auth/register`: Create tenant + user, return tokens.
   - `POST /auth/login`: Verify credentials, return tokens.
   - `POST /auth/refresh`: Issue new access token from valid refresh token.

7. **Create `backend/app/middleware/auth_middleware.py`**:
   - FastAPI dependency `get_current_user`.
   - Extracts Bearer token, decodes JWT, returns `TokenPayload`.
   - Raises 401 on invalid/expired tokens.

8. **Create `backend/app/api/health.py`**:
   - `GET /health` endpoint returning `{"status": "ok", "db": "connected", "timestamp": "..."}`.

9. **Create `backend/app/main.py`**:
   - FastAPI app factory with lifespan, CORS, route registration.

10. **Set up Alembic**:
    - Configured for async SQLAlchemy via `alembic.ini` and `backend/alembic/env.py`.

## Verification
- Run `pytest backend/tests/test_auth.py` to test register, login, refresh, invalid token rejection, and tenant isolation.

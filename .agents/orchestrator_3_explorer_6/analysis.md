# Deep Audit & Architectural Review Report: API, Auth, Database Models & Schemas

**Target Scope**: `backend/app/api/`, `backend/app/middleware/`, `backend/app/models/`, `backend/app/schemas/`, `backend/app/db/`, `backend/app/utils/`, `backend/app/config.py`, `backend/alembic/`  
**Auditor**: `explorer_6`  
**Date**: 2026-08-29  
**Status**: Comprehensive Analysis Complete  

---

## 1. Executive Summary

A deep static code review and architectural analysis was conducted across all files governing API routing, dependency injection, authentication, middleware, database models, database migrations, and Pydantic v2 schemas.

The ModelAudit AI backend demonstrates strong adherence to modern Python 3.12, FastAPI, SQLAlchemy 2.0 async, and Pydantic v2 best practices. Key core security pillars—such as multi-tenant query isolation, PyJWT RS256 token verification, direct bcrypt password hashing, 1MB chunked streaming file uploads with a 50MB ceiling, SSE streaming headers (`X-Accel-Buffering`, `Cache-Control`), and Upstash Redis rate limiting—are well-structured.

However, several specific gaps, schema inconsistencies, missing `model_config` declarations, edge cases in tier-based rate limiting, missing return type annotations, and opportunities for defense-in-depth isolation were identified.

### Summary of Audit Findings by Severity

| Severity | Count | Key Focus Areas |
|:---|:---:|:---|
| **High** | 2 | Missing `tier` in `TokenPayload` preventing tiered rate limits; Missing Pydantic v2 `ConfigDict(from_attributes=True)` on multiple response/request schemas |
| **Medium** | 4 | Incomplete `schemas/__init__.py` export index; Missing explicit return type hints on API endpoint handlers; Missing `tenant_id` defense-in-depth on `/users/me`; RSA PEM newline unescaping edge case in config |
| **Low / Improvement** | 3 | In-memory session registry tenant binding; Unclosed `LLMRouter` sessions in non-streaming routes (`compare.py`, `gap_analysis.py`); Pinecone vector cleanup on document deletion |

---

## 2. Detailed Assessment of Core Verification Areas

### 2.1 Multi-Tenant `tenant_id` Enforcement Across All API Endpoints & Database Queries

| Endpoint / Component | Verification Status | Exact Lines / Query Evidence | Assessment |
|:---|:---:|:---|:---|
| `POST /auth/register` | **Compliant** | `app/api/auth.py:24-33` | Creates a new `Tenant` record, binds `User.tenant_id = new_tenant.id`. |
| `POST /auth/login` | **Compliant** | `app/api/auth.py:46-61` | Finds user by email, embeds `user.tenant_id` into the signed RS256 JWT payload. |
| `POST /auth/refresh` | **Compliant** | `app/api/auth.py:94-108` | Validates active user state, re-issues access token with verified `user.tenant_id`. |
| `app/api/deps.py:get_current_user` | **Compliant** | `app/api/deps.py:52-75` | Retrieves `User` from DB by `sub` (UUID), validates `user.is_active`, extracts `user.tenant_id`. |
| `POST /documents/upload` | **Compliant** | `app/api/documents.py:67-74, 110, 169` | Validates `ModelVersion` ownership via `Model.tenant_id == current_user.tenant_id`. Binds `Document.tenant_id = current_user.tenant_id`. Upserts Pinecone vectors under namespace `str(current_user.tenant_id)`. |
| `GET /documents` | **Compliant** | `app/api/documents.py:257-259` | Filters `where(Document.tenant_id == current_user.tenant_id)`. |
| `GET /documents/{id}` | **Compliant** | `app/api/documents.py:284-287` | Filters `where(Document.id == document_id, Document.tenant_id == current_user.tenant_id)`. |
| `DELETE /documents/{id}` | **Compliant** | `app/api/documents.py:315-318` | Filters `where(Document.id == document_id, Document.tenant_id == current_user.tenant_id)`. |
| `GET /models` | **Compliant** | `app/api/models.py:26-28` | Filters `where(Model.tenant_id == current_user.tenant_id)`. |
| `POST /models` | **Compliant** | `app/api/models.py:54-60` | Assigns `Model.tenant_id = current_user.tenant_id, Model.user_id = current_user.sub`. |
| `GET /models/{id}` | **Compliant** | `app/api/models.py:91-93` | Filters `where(Model.id == model_id, Model.tenant_id == current_user.tenant_id)`. |
| `GET /models/{id}/versions` | **Compliant** | `app/api/models.py:120-123` | Checks `Model.id == model_id, Model.tenant_id == current_user.tenant_id` before querying versions. |
| `GET /models/{id}/export-data` | **Compliant** | `app/api/models.py:141-144` | Checks `Model.id == model_id, Model.tenant_id == current_user.tenant_id`. |
| `POST /compare` | **Compliant** | `app/api/compare.py:32-64` | Validates both `Document A` and `Document B` independently with `Document.tenant_id == current_user.tenant_id`. |
| `POST /gap-analysis` | **Compliant** | `app/api/gap_analysis.py:29-35` | Validates `Document.id == request.document_id, Document.tenant_id == current_user.tenant_id`. |
| `POST /query` | **Compliant** | `app/api/query.py:39-75, 105` | Validates `Document.tenant_id`, validates/creates `ChatSession.tenant_id`, passes `tenant_id` to `HybridRetriever`. |
| `POST /regulatory/search` | **Compliant** | `app/api/regulatory.py:45` | Passes `tenant_id=current_user.tenant_id` to retriever. |
| `GET /dashboard/metrics` | **Compliant** | `app/api/system.py:40, 46, 54` | All `func.count()` queries filter by `Model.tenant_id == current_user.tenant_id` and `Document.tenant_id == current_user.tenant_id`. |
| `GET /settings`, `PUT /settings` | **Compliant** | `app/api/system.py:73, 94` | Filters `TenantSettings.tenant_id == current_user.tenant_id`. |
| `GET /notifications` | **Compliant** | `app/api/system.py:120-121` | Filters `Notification.tenant_id == current_user.tenant_id, Notification.user_id == current_user.sub`. |
| `GET /search` | **Compliant** | `app/api/system.py:143` | Model search filters `Model.tenant_id == current_user.tenant_id`. |
| `GET /users/me` | **Partially Compliant** | `app/api/system.py:193` | Queries `User.id == current_user.sub`. Safe because `sub` is derived from authenticated token, but adding `User.tenant_id == current_user.tenant_id` provides defense-in-depth. |

---

### 2.2 PyJWT RS256 Token Verification & Direct Bcrypt Password Hashing

- **Bcrypt Implementation (`app/utils/security.py`)**:
  - Direct use of `import bcrypt` (avoids passlib's compatibility issues with Python 3.12+ and bcrypt 4.0+).
  - Password hashing: `bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")` (lines 53-56).
  - Password verification: `bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))` with safe `(ValueError, TypeError)` exception handling (lines 59-64).
- **RS256 JWT Cryptographic Operations (`app/utils/security.py`)**:
  - `create_access_token` (1-hour expiration) and `create_refresh_token` (7-day expiration) both specify `algorithm=settings.jwt.algorithm` ("RS256").
  - `decode_token` explicitly enforces `algorithms=[settings.jwt.algorithm]` to prevent algorithm downgrade attacks (lines 95-106).
  - Ephemeral RSA 2048-bit key-pair fallback is automatically generated via `cryptography.hazmat.primitives.asymmetric.rsa` when environment variables are not supplied (lines 18-36).
- **Token Verification Flow (`app/api/deps.py`)**:
  - `get_current_user` extracts bearer token, checks `type == "access"`, parses `sub` as UUID, queries the database, and verifies `user.is_active` before returning `TokenPayload`.

---

### 2.3 1MB Streaming File Upload with Size Limits (50MB) and Filename Sanitization

- **File Upload Handler (`app/api/documents.py:38-105`)**:
  - Constants: `MAX_FILE_SIZE = 50 * 1024 * 1024` (50MB) and `CHUNK_READ_SIZE = 1024 * 1024` (1MB).
  - Filename Sanitization: `safe_filename = Path(file.filename).name.strip()`, stripping directory traversal characters (e.g. `../../evil.pdf` -> `evil.pdf`).
  - Allowed extensions strictly restricted to `("pdf", "docx")`.
  - Streaming spooling: `tempfile.SpooledTemporaryFile(max_size=1024 * 1024)` buffers up to 1MB in RAM and spills to disk for larger files.
  - Chunked read loop:
    ```python
    total_bytes = 0
    while True:
        chunk = await file.read(CHUNK_READ_SIZE)
        if not chunk:
            break
        total_bytes += len(chunk)
        if total_bytes > MAX_FILE_SIZE:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail="File too large (max 50MB)",
            )
        await run_in_threadpool(spool.write, chunk)
    ```
  - Spool cleanup is guaranteed via `finally: spool.close()`.

---

### 2.4 SSE Streaming Transport & Headers

- **Streaming Response Utility (`app/utils/streaming.py:8-36`)**:
  - Returns `StreamingResponse` with:
    - `media_type="text/event-stream"`
    - `headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"}`
  - Properly formats payloads as Server-Sent Events (`data: {...}\n\n`).
  - Handled event types:
    - Token chunks: `{"type": "token", "content": "..."}`
    - Custom metadata (e.g., `session_id`, `citations`, `suggestedActions`)
    - Stream termination: `{"type": "done"}`
    - Stream errors: `{"type": "error", "content": "..."}`
- **Integration in `/query` (`app/api/query.py:138-170`)**:
  - Streams tokens asynchronously from `llm_router.generate_stream()`.
  - Emits `session_id` and `citations` prior to token stream.
  - Persists completed response to `ChatMessage` in DB.
  - Emits `suggestedActions` upon completion.

---

### 2.5 Upstash Redis Rate Limiter & Lua Script Resolution

- **Lua Script Path Resolution (`app/middleware/rate_limiter.py:18-48`)**:
  - `LUA_DIR = Path(__file__).resolve().parent.parent.parent / "lua"` resolves accurately to `backend/lua/`.
  - Non-blocking async file reads: `await anyio.Path(token_bucket_path).read_text(encoding="utf-8")`.
  - Scripts `backend/lua/token_bucket.lua` and `backend/lua/gcra_leaky_bucket.lua` exist, are well-formed, and load with SHA caching (`script_load`).
- **Execution & Rate Enforcement (`app/middleware/rate_limiter.py:49-129`)**:
  - Cost allocation: `/compare` = 5, `/gap-analysis` = 3, `/health` = 0, others = 1.
  - Tier capacities: `FREE` (10 capacity / 1 refill), `PROFESSIONAL` (100 / 5), `ENTERPRISE` (1000 / 50).
  - Evaluates via `self.redis.evalsha(self.token_bucket_sha, [key], [capacity, refill_rate, cost, now])`.
  - Raises HTTP 429 with `Retry-After` header when exhausted.
  - Fails open gracefully on Redis network errors.

---

### 2.6 SQLAlchemy 2.0 Async ORM DeclarativeBase & Alembic env.py

- **Async Database Setup (`app/db/database.py`)**:
  - `Base = DeclarativeBase` subclass.
  - `create_async_engine(settings.database.url, pool_size=5, max_overflow=10, pool_pre_ping=True, echo=False)`.
  - `async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)`.
  - Async generator dependency `get_db()`.
- **Model Declarations (`app/models/`)**:
  - All models (`Tenant`, `User`, `Document`, `DocumentChunk`, `Model`, `ModelVersion`, `TenantSettings`, `Notification`, `RegulatoryStandard`, `ChatSession`, `ChatMessage`) use standard SQLAlchemy 2.0 `Mapped[...]` and `mapped_column(...)` typing.
  - Foreign keys, cascades, indices, and enum columns are consistently configured.
- **Alembic Configuration (`alembic/env.py`)**:
  - Sets `target_metadata = Base.metadata`.
  - Imports models module to register metadata.
  - Migration script `0e6c2385a516_add_model_centric_tables.py` covers all tables (`tenants`, `users`, `tenant_settings`, `models`, `model_versions`, `documents`, `document_chunks`, `notifications`, `regulatory_standards`, `chat_sessions`, `chat_messages`).

---

### 2.7 Pydantic v2 Compliance & Schema Validation

- **Compliance (`app/schemas/`)**:
  - Uses Pydantic v2 `BaseModel` and `ConfigDict`.
  - No deprecated Pydantic v1 patterns (`class Config:`, `@validator`, `schema_extra`).
  - Strict typing with `uuid.UUID`, `datetime`, `EmailStr`, and nested sub-models.

---

## 3. Discovered Bugs, Inconsistencies & Remediation Plan

### Issue 1 (High): Missing `tier` in `TokenPayload` Prevents Tiered Rate Limiting
- **Location**: `backend/app/schemas/auth.py:45-55`, `backend/app/middleware/rate_limiter.py:58-61`, `backend/app/api/deps.py:69-75`
- **Category**: Rate Limiting / Authentication Schema
- **Description**: In `rate_limiter.py:59`, the rate limiter inspects `tier = getattr(current_user, "tier", "FREE") or "FREE"`. However, `TokenPayload` in `schemas/auth.py` does not define a `tier` field. Consequently, `getattr` always defaults to `"FREE"`, meaning Enterprise and Professional tenant users are artificially throttled to the Free tier rate limits (10 burst capacity).
- **Remediation**:
  1. Add `tier: str = "FREE"` to `TokenPayload` in `backend/app/schemas/auth.py`.
  2. In `backend/app/api/deps.py:get_current_user`, load the user's tenant or tenant tier (`user.tenant.tier.value` or payload claims) and pass `tier=tier_val` into `TokenPayload`.
  3. Include `"tier": user.tenant.tier.value` in `create_access_token` in `backend/app/utils/security.py`.

---

### Issue 2 (High): Missing `model_config = ConfigDict(from_attributes=True)` Across Several Schemas
- **Location**: 
  - `backend/app/schemas/privacy.py:6-17` (`MaskRequest`, `MaskResponse`, `RedactionLogResponse`)
  - `backend/app/schemas/regulatory.py:27-29` (`RegulatoryStandardListResponse`)
  - `backend/app/schemas/system.py:20-28, 57-66` (`TenantSettingsUpdate`, `SearchResultItem`, `GlobalSearchResponse`)
- **Category**: Pydantic v2 Schema Compliance
- **Description**: Multiple schemas in `privacy.py`, `regulatory.py`, and `system.py` omit `model_config = ConfigDict(from_attributes=True)` or fail to import `ConfigDict`. While input request schemas without ORM serialization work, omitting `model_config` violates consistency and prevents ORM object validation.
- **Remediation**: Add `model_config = ConfigDict(from_attributes=True)` to all remaining schemas in `schemas/privacy.py`, `schemas/regulatory.py`, and `schemas/system.py`.

---

### Issue 3 (Medium): Incomplete Schema Index in `backend/app/schemas/__init__.py`
- **Location**: `backend/app/schemas/__init__.py:1-111`
- **Category**: Module Architecture / Broken Index
- **Description**: `app/schemas/__init__.py` fails to import and export schemas from `app/schemas/models.py` (`ModelSummary`, `ModelVersionDTO`, `ModelCreate`, `ModelExportData`) and `app/schemas/privacy.py` (`MaskRequest`, `MaskResponse`, `RedactionLogResponse`).
- **Remediation**: Add all model schemas and privacy schemas to `app/schemas/__init__.py` and include them in `__all__`.

---

### Issue 4 (Medium): Missing Return Type Annotations on API Route Handlers
- **Location**:
  - `backend/app/api/auth.py:18, 44, 67` (`register`, `login`, `refresh`)
  - `backend/app/api/health.py:13` (`health_check`)
  - `backend/app/api/models.py:20, 48, 84, 113, 134` (`list_models`, `create_model`, `get_model`, `get_model_versions`, `export_model_data`)
  - `backend/app/api/compare.py:25` (`compare_documents`)
  - `backend/app/api/gap_analysis.py:22` (`analyze_gaps`)
  - `backend/app/api/regulatory.py:32, 81` (`regulatory_search`, `get_regulatory_standards`)
  - `backend/app/api/system.py:33, 68, 88, 112, 131, 188` (`get_dashboard_metrics`, `get_tenant_settings`, `update_tenant_settings`, `get_notifications`, `global_search`, `get_user_profile`)
  - `backend/app/api/query.py:28` (`conversational_query`)
- **Category**: Type Safety / Python 3.12 Compliance
- **Description**: Although FastAPI supports route typing via `response_model`, Python 3.12 type checker and project coding standards require explicit function return annotations (`-> ReturnType`) for all public handlers.
- **Remediation**: Add precise return type annotations (e.g. `-> TokenResponse`, `-> list[ModelSummary]`, `-> StreamingResponse`, etc.) to all route functions.

---

### Issue 5 (Medium): RSA PEM Key String Newline Unescaping Safeguard
- **Location**: `backend/app/utils/security.py:39-51`
- **Category**: Security / Config Robustness
- **Description**: In production environments (Docker, AWS ECS, Kubernetes), RSA private and public keys stored in environment variables frequently contain escaped newline literals (`\n`). If loaded directly without `.replace("\\n", "\n")`, `cryptography` / `PyJWT` may fail to parse the PEM header.
- **Remediation**: Update `_get_private_key()` and `_get_public_key()` to unescape newlines:
  ```python
  def _get_private_key() -> str:
      if settings.jwt.private_key and settings.jwt.private_key.strip():
          return settings.jwt.private_key.replace("\\n", "\n")
      return _DEFAULT_PRIVATE_KEY_PEM
  ```

---

### Issue 6 (Low / Optimization): In-Route LLMRouter Resource Cleanup
- **Location**: `backend/app/api/compare.py:101-125`, `backend/app/api/gap_analysis.py:72-96`, `backend/app/api/regulatory.py:38-72`
- **Category**: Resource Management
- **Description**: In `app/api/documents.py`, `llm_router = LLMRouter()` is properly enclosed in a `try...finally: await llm_router.aclose()` block to cleanly close underlying HTTP connection pools. However, in `compare.py`, `gap_analysis.py`, and `regulatory.py`, `llm_router.aclose()` is not explicitly called after generation.
- **Remediation**: Wrap router generation calls in `try...finally: await llm_router.aclose()` or use an async context manager.

---

## 4. Verification & Validation Summary

| Check | Expected | Actual | Result |
|:---|:---|:---|:---:|
| Tenant ID Filtering on All DB Queries | Enforced | Enforced on 100% of endpoints | **PASS** |
| PyJWT RS256 Verification & Bcrypt Hashing | Direct bcrypt, RS256 decode | Implemented in `security.py` & `deps.py` | **PASS** |
| 1MB Upload Chunking & 50MB Max Limit | Spooled stream, 50MB check, sanitized filename | Implemented in `documents.py` | **PASS** |
| SSE Streaming Headers | `X-Accel-Buffering: no`, `Cache-Control: no-cache` | Implemented in `streaming.py` | **PASS** |
| Upstash Redis Lua Rate Limiting | Dynamic loading from `backend/lua/` | Path resolved, token bucket script verified | **PASS** |
| SQLAlchemy 2.0 Async Base & `Mapped[]` | `DeclarativeBase`, `Mapped[]`, `pool_pre_ping` | Implemented across all models & `database.py` | **PASS** |
| Pydantic v2 Schema Compliance | `ConfigDict(from_attributes=True)` | Compliant across majority; 5 schemas need `ConfigDict` | **NEEDS FIX** |

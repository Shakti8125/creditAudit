# ModelAudit AI — Backend Code Audit Report (Explorer M4)

## Target Scope: API Endpoints, Middleware & Server Entrypoint

- **Auditor**: Explorer M4
- **Working Directory**: `.agents/explorer_m4/`
- **Scope**: `backend/app/api/*`, `backend/app/middleware/*`, `backend/app/main.py`, `backend/app/__init__.py`
- **Target Files**:
  1. `backend/app/main.py`
  2. `backend/app/__init__.py`
  3. `backend/app/api/__init__.py`
  4. `backend/app/api/deps.py`
  5. `backend/app/api/auth.py`
  6. `backend/app/api/documents.py`
  7. `backend/app/api/query.py`
  8. `backend/app/api/compare.py`
  9. `backend/app/api/gap_analysis.py`
  10. `backend/app/api/health.py`
  11. `backend/app/api/regulatory.py`
  12. `backend/app/middleware/__init__.py`
  13. `backend/app/middleware/auth_middleware.py`
  14. `backend/app/middleware/rate_limiter.py`

---

## 1. Executive Summary

A comprehensive static analysis and code audit of the ModelAudit AI backend API endpoints, middleware layer, and server entrypoint was performed. The audit identified **35 distinct issues** across the 14 target files and related security/cryptographic modules.

### Severity Summary Table

| Severity | Count | Primary Impact Areas |
| :--- | :---: | :--- |
| **Critical** | **7** | Runtime `AttributeError` crashes on `current_user.get(...)` across 5 endpoints/middleware; Cross-tenant document isolation breach via unverified `document_id` in RAG retrieval; Dual conflicting authentication dependencies; Cryptographic RS256 single symmetric key misconfiguration. |
| **High** | **11** | Unbounded memory allocation / Denial of Service in file upload; Privacy pipeline bypass (unmasked user prompts sent to external LLMs); Broken CORS defaults disabling frontend access; Missing inactive user checks allowing disabled accounts to log in/refresh; Lua script path failure in containers; Silent fake fallback in gap analysis; Missing token type check allowing refresh tokens on data endpoints. |
| **Medium** | **8** | Database transaction inconsistency on upload error; Swallowed HTTPExceptions in auth middleware; Missing response models on endpoints; Dead GCRA Lua scripts in Redis; Hardcoded regulatory checklist instead of dynamic RAG; Silent JSON parsing error fallbacks. |
| **Low** | **9** | Deprecated `datetime.utcnow()` usage in Python 3.12; Misleading 200 OK on DB disconnect in health check; Unused imports; Hardcoded chunk counts; Mid-file imports; Arbitrary character truncation. |
| **Total** | **35** | **All identified findings with line numbers and exact remediation patterns.** |

### Category Breakdown

| Category (R1) | Count |
| :--- | :---: |
| **Security Issues & Multi-Tenancy** | 12 |
| **Type Annotation Correctness & Runtime Type Errors** | 7 |
| **Incorrect API Usage vs. Latest Library Docs** | 7 |
| **Privacy Pipeline Logic** | 3 |
| **Async/await & Transaction Correctness** | 2 |
| **Broken Imports, Missing Dependencies & Code Layout** | 4 |

---

## 2. Detailed Findings by Module & File

### Module: Middleware (`backend/app/middleware/`)

#### File: `backend/app/middleware/rate_limiter.py`

- **Finding ID**: M4-RL-01
- **File**: `backend/app/middleware/rate_limiter.py`
- **Line**: 38, 39, 98
- **Severity**: **Critical**
- **Category**: Type annotation correctness & Incorrect API usage vs. latest library docs
- **Description**: In `rate_limiter.py`, `get_rate_limiter` declares `current_user: dict = Depends(get_current_user)` (importing `get_current_user` from `app.middleware.auth_middleware`). `get_current_user` returns a Pydantic `TokenPayload` model (`TokenPayload(**payload_dict)`), NOT a Python `dict`. Inside `check_rate_limit`, lines 38 and 39 attempt dictionary lookups: `tenant_id = current_user.get('tenant_id')` and `tier = current_user.get('tier', 'FREE')`. In Python / Pydantic v2, `BaseModel` does not implement `.get()`. Calling `.get()` raises `AttributeError: 'TokenPayload' object has no attribute 'get'` on every request. Because lines 90-94 catch generic `Exception` and fail open (`return True`), the rate limiter crashes on every single request, logs an error, and fails open — completely disabling rate limiting across the entire application.
- **Correct Pattern / Fix**: Annotate `current_user: TokenPayload` and access attributes directly via standard dot notation (`current_user.tenant_id` and `getattr(current_user, 'tier', 'FREE')`).

---

- **Finding ID**: M4-RL-02
- **File**: `backend/app/middleware/rate_limiter.py`
- **Line**: 39
- **Severity**: **High**
- **Category**: Incorrect API usage vs. latest library docs
- **Description**: Line 39 attempts to extract `tier = current_user.get('tier', 'FREE')`. However, `TokenPayload` in `app/schemas/auth.py` and `create_access_token` in `app/utils/security.py` never include or serialize a `tier` field. Consequently, even if attribute access is fixed, `tier` is never present in the JWT claims, causing every tenant (including paid ENTERPRISE tier tenants with 1,000 capacity) to always default to the FREE tier limits (10 capacity, 1 refill/sec).
- **Correct Pattern / Fix**: Update `TokenPayload` schema in `app/schemas/auth.py` to include `tier: str = 'FREE'`, update `create_access_token` in `app/utils/security.py` to accept `tier: str` and encode `'tier': tier` into the JWT payload, and update `auth.py` to read `user.tenant.tier` during token generation.

---

- **Finding ID**: M4-RL-03
- **File**: `backend/app/middleware/rate_limiter.py`
- **Line**: 22, 26
- **Severity**: **High**
- **Category**: Incorrect API usage vs. latest library docs
- **Description**: `load_scripts()` attempts to open Lua scripts using hardcoded relative file paths: `open('backend/lua/token_bucket.lua', 'r')` and `open('backend/lua/gcra_leaky_bucket.lua', 'r')`. When Uvicorn is executed from within the `backend/` directory (e.g., `uvicorn app.main:app`) or in containerized environments (where `WORKDIR` is `/app`), this path fails with `FileNotFoundError`. When `load_scripts` fails at startup (or on request), `self.token_bucket_sha` remains `None`, causing `evalsha` to fail.
- **Correct Pattern / Fix**: Resolve script paths relative to the module file using `pathlib.Path`: `LUA_DIR = Path(__file__).resolve().parent.parent.parent / 'lua'`; `with open(LUA_DIR / 'token_bucket.lua', 'r', encoding='utf-8') as f:`.

---

- **Finding ID**: M4-RL-04
- **File**: `backend/app/middleware/rate_limiter.py`
- **Line**: 14, 26-28
- **Severity**: **Medium**
- **Category**: Incorrect API usage vs. latest library docs
- **Description**: `load_scripts` loads `backend/lua/gcra_leaky_bucket.lua` into Redis and stores `self.gcra_sha = await self.redis.script_load(gcra_script)`. However, `self.gcra_sha` is never referenced or executed anywhere in `check_rate_limit` (only token bucket is used). This creates unused dead code loaded into Redis memory.
- **Correct Pattern / Fix**: Remove unused GCRA script loading or provide a configuration setting in `Settings` (`rate_limit_algorithm: str = 'token_bucket'`) to choose between token bucket and GCRA.

---

- **Finding ID**: M4-RL-05
- **File**: `backend/lua/token_bucket.lua`
- **Line**: 28
- **Severity**: **Low**
- **Category**: Security issues
- **Description**: In `token_bucket.lua`, line 28 calculates key expiration TTL: `local ttl = math.ceil(capacity / refill_rate) * 2`. If `refill_rate` is 0 (or configured as 0 for an absolute quota), a division by zero error occurs in Lua, terminating script execution with a Redis error.
- **Correct Pattern / Fix**: Guard against zero refill rates in Lua: `local ttl = (refill_rate > 0) and (math.ceil(capacity / refill_rate) * 2) or 3600`.

---

#### File: `backend/app/middleware/auth_middleware.py`

- **Finding ID**: M4-AM-01
- **File**: `backend/app/middleware/auth_middleware.py`
- **Line**: 17-29
- **Severity**: **Medium**
- **Category**: Incorrect API usage & Error handling
- **Description**: In `get_current_user`, line 17 explicitly raises `HTTPException(status_code=401, detail='Invalid token type')` when `payload_dict.get('type') != 'access'`. However, line 24 defines a blanket `except Exception as e:` block that catches all exceptions — including `HTTPException`. As a result, the specific 401 error is swallowed and replaced with the generic `detail='Could not validate credentials'`.
- **Correct Pattern / Fix**: Catch `HTTPException` explicitly and re-raise (`except HTTPException: raise`), logging general exceptions separately.

---

- **Finding ID**: M4-AM-02
- **File**: `backend/app/middleware/auth_middleware.py`
- **Line**: 22-24
- **Severity**: **High**
- **Category**: Security issues & Multi-tenancy enforcement
- **Description**: `TokenPayload` schema in `app/schemas/auth.py` defines `tenant_id: uuid.UUID | None = None`. If an access token is issued without a `tenant_id` claim, `get_current_user` returns `TokenPayload` with `tenant_id=None`. When downstream endpoints and rate limiters use `current_user.tenant_id`, multi-tenant isolation is compromised or crashes with `None` tenant keys.
- **Correct Pattern / Fix**: Validate that `token_payload.tenant_id is not None` in `get_current_user`, raising `HTTPException(status_code=401, detail='Missing tenant context in access token')` if None.

---

- **Finding ID**: M4-AM-03
- **File**: `backend/app/middleware/auth_middleware.py`
- **Line**: 24
- **Severity**: **Low**
- **Category**: Code conventions & Error handling
- **Description**: Line 24 uses a bare `except Exception as e:` without logging the exception with `logging.getLogger(__name__)`, violating project convention rule 5: 'Never use bare except:. Always catch specific exceptions. Log with logging.getLogger(__name__)'.
- **Correct Pattern / Fix**: Initialize `logger = logging.getLogger(__name__)` and log authentication failures with `logger.warning(f'Authentication error: {e}')`.

---

### Module: API Dependencies (`backend/app/api/deps.py`)

#### File: `backend/app/api/deps.py`

- **Finding ID**: M4-DEP-01
- **File**: `backend/app/api/deps.py` & `backend/app/middleware/auth_middleware.py`
- **Line**: `deps.py:17-42` vs `auth_middleware.py:12-30`
- **Severity**: **Critical**
- **Category**: Broken imports / Architecture & Incorrect API usage vs. latest library docs
- **Description**: The backend contains two conflicting, duplicate implementations of `get_current_user`: (1) `app.middleware.auth_middleware.get_current_user` uses `HTTPBearer()` and returns `TokenPayload` (Pydantic model); (2) `app.api.deps.get_current_user` uses `OAuth2PasswordBearer(tokenUrl='auth/login')`, queries the database `SELECT * FROM users WHERE id = :user_id`, and returns `User` (SQLAlchemy model). In `main.py`, `get_rate_limiter` is attached to `documents.router`, causing every request to `/documents/*` to execute BOTH authentication dependencies with different security schemes on every request.
- **Correct Pattern / Fix**: Consolidate `get_current_user` into a single canonical dependency module (`app.api.deps`), standardize return type (e.g. `User` or `CurrentUserContext`), and use consistent security schemes (`HTTPBearer`).

---

- **Finding ID**: M4-DEP-02
- **File**: `backend/app/api/deps.py`
- **Line**: 27-31
- **Severity**: **High**
- **Category**: Security issues & Authentication
- **Description**: `deps.py:get_current_user` decodes the token and extracts `payload.get('sub')`, but NEVER checks `payload.get('type') == 'access'`. As a consequence, long-lived (7-day) refresh tokens can be used as authorization tokens against `/documents/upload`, `/documents/`, and any endpoint depending on `deps.get_current_user`.
- **Correct Pattern / Fix**: Add `if payload.get('type') != 'access': raise credentials_exception` before database user lookup.

---

- **Finding ID**: M4-DEP-03
- **File**: `backend/app/api/deps.py`
- **Line**: 38-40
- **Severity**: **High**
- **Category**: Security issues & Authentication
- **Description**: In `models/user.py`, `User` has `is_active: Mapped[bool] = mapped_column(Boolean, default=True)`. In `deps.py`, `get_current_user` checks `if user is None: raise credentials_exception` but never checks `if not user.is_active:`. Deactivated or disabled user accounts remain authorized to upload, delete, and read documents as long as their JWT has not expired.
- **Correct Pattern / Fix**: Add `if not user.is_active: raise HTTPException(status_code=401, detail='Inactive user account')`.

---

- **Finding ID**: M4-DEP-04
- **File**: `backend/app/api/deps.py`
- **Line**: 35
- **Severity**: **Medium**
- **Category**: Incorrect API usage vs. latest library docs (SQLAlchemy 2.0 async)
- **Description**: `select(User).filter(User.id == user_id)` does not eagerly load the `tenant` relationship (`selectinload(User.tenant)`). In SQLAlchemy 2.0 async sessions, accessing `user.tenant` outside of an eager load triggers a lazy-load attempt that fails with `MissingGreenlet`.
- **Correct Pattern / Fix**: Query with `select(User).options(selectinload(User.tenant)).where(User.id == user_id)`.

---

### Module: Authentication Endpoints (`backend/app/api/auth.py`)

#### File: `backend/app/api/auth.py`

- **Finding ID**: M4-AUTH-01
- **File**: `backend/app/api/auth.py`
- **Line**: 49, 77
- **Severity**: **High**
- **Category**: Security issues & Authentication
- **Description**: In `auth.py`, neither `login` (line 49) nor `refresh` (line 77) checks `if not user.is_active:`. Deactivated users can still authenticate with their password or refresh token and obtain new access tokens.
- **Correct Pattern / Fix**: Add `if not user.is_active: raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='User account is deactivated')` in both handlers.

---

- **Finding ID**: M4-AUTH-02
- **File**: `backend/app/api/auth.py`
- **Line**: 17
- **Severity**: **Medium**
- **Category**: Incorrect API usage vs. latest library docs (FastAPI / REST standards)
- **Description**: `@router.post('/register', response_model=TokenResponse)` defaults to HTTP 200 OK. Standard REST API conventions and OpenAPI documentation require resource creation endpoints to return HTTP 201 Created.
- **Correct Pattern / Fix**: Specify `status_code=status.HTTP_201_CREATED` on `@router.post('/register', ...) `.

---

- **Finding ID**: M4-AUTH-03
- **File**: `backend/app/api/auth.py`
- **Line**: 38, 52, 80
- **Severity**: **Medium**
- **Category**: Incorrect API usage vs. latest library docs
- **Description**: `create_access_token(user.id, user.tenant_id, user.role.value)` is invoked without providing tenant tier information. Because `tier` is stored on `Tenant` in the database, omitting tier in token claims prevents stateless downstream rate limiting based on subscription tiers.
- **Correct Pattern / Fix**: Include tenant tier claim in `create_access_token(user.id, user.tenant_id, user.role.value, tier=user.tenant.tier.value)`.

---

### Module: Document Management (`backend/app/api/documents.py`)

#### File: `backend/app/api/documents.py`

- **Finding ID**: M4-DOC-01
- **File**: `backend/app/api/documents.py`
- **Line**: 35
- **Severity**: **High**
- **Category**: Security issues (Denial of Service / Memory Exhaustion)
- **Description**: Line 35 executes `file_bytes = await file.read()` before verifying the file size. FastAPI reads the entire uploaded file directly into server RAM. If an attacker sends a multi-gigabyte file (e.g. 5GB), server memory is exhausted, causing an Out-of-Memory (OOM) crash before reaching line 36 (`if len(file_bytes) > MAX_FILE_SIZE:`).
- **Correct Pattern / Fix**: Stream and count chunks up to `MAX_FILE_SIZE` using a buffer (e.g. 1MB chunk reading), raising HTTP 413 immediately when limit is exceeded.

---

- **Finding ID**: M4-DOC-02
- **File**: `backend/app/api/documents.py`
- **Line**: 39, 49
- **Severity**: **High**
- **Category**: Security issues & Type annotation correctness
- **Description**: Line 39 executes `ext = file.filename.split('.')[-1].lower()`. If `file.filename` is `None` (valid per Starlette `UploadFile` types if omitted by client), it raises `AttributeError: 'NoneType' object has no attribute 'split'`, resulting in an unhandled 500 server error. Additionally, `file.filename` is stored directly into the database at line 49 (`filename=file.filename`) and passed to extractors without sanitizing directory traversal characters (`..`, `/`, `\`).
- **Correct Pattern / Fix**: Guard `if not file.filename: raise HTTPException(400, 'Filename must not be empty')`, sanitize with `Path(file.filename).name`, and extract extension with `Path(safe_name).suffix.lstrip('.').lower()`.

---

- **Finding ID**: M4-DOC-03
- **File**: `backend/app/api/documents.py`
- **Line**: 115
- **Severity**: **High**
- **Category**: Privacy pipeline logic & Data Leakage
- **Description**: Line 115 returns `masking_report=registry.get_mapping()` in `UploadResponse`. `registry.get_mapping()` contains the full entity mapping dictionary from anonymized tokens (`[BANK_1]`, `[PERSON_1]`) to original sensitive entity values (`First Abu Dhabi Bank`, `John Doe`). Returning the raw entity unmasking map in the API response creates a data exposure risk if API responses are logged or cached.
- **Correct Pattern / Fix**: Return token counts / summary statistics rather than the raw dictionary mapping sensitive values.

---

- **Finding ID**: M4-DOC-04
- **File**: `backend/app/api/documents.py`
- **Line**: 119-127
- **Severity**: **Medium**
- **Category**: Async/await correctness & SQLAlchemy 2.0 Transaction Handling
- **Description**: In `upload_document`, if an exception occurs during chunk generation (lines 95-102 where `db.add(db_chunk)` is called), the exception handlers at lines 119-127 execute: `db_doc.status = DocumentStatus.ERROR; await db.commit()`. Calling `await db.commit()` without rolling back the dirty session commits any partially-added `DocumentChunk` objects into the database in an inconsistent state.
- **Correct Pattern / Fix**: Call `await db.rollback()` before updating document status to `ERROR`.

---

- **Finding ID**: M4-DOC-05
- **File**: `backend/app/api/documents.py`
- **Line**: 147
- **Severity**: **Low**
- **Category**: Correctness & API completeness
- **Description**: In `list_documents`, `chunk_count=0` is hardcoded for all documents. The endpoint never queries or populates actual chunk counts.
- **Correct Pattern / Fix**: Query chunk count using a subquery or join with `func.count(DocumentChunk.id)`.

---

- **Finding ID**: M4-DOC-06
- **File**: `backend/app/api/documents.py`
- **Line**: 153
- **Severity**: **Medium**
- **Category**: FastAPI 0.112+ API usage
- **Description**: `@router.get('/{document_id}')` does not specify a `response_model`, returning a raw untyped Python dictionary. This bypasses Pydantic schema validation and generates incomplete OpenAPI schema documentation.
- **Correct Pattern / Fix**: Create `DocumentDetailResponse` schema and add `response_model=DocumentDetailResponse` to `@router.get('/{document_id}', response_model=DocumentDetailResponse)`.

---

### Module: Conversational Query & SSE Streaming (`backend/app/api/query.py`)

#### File: `backend/app/api/query.py`

- **Finding ID**: M4-QRY-01
- **File**: `backend/app/api/query.py`
- **Line**: 19, 26
- **Severity**: **Critical**
- **Category**: Type annotation correctness & Incorrect API usage vs. latest library docs
- **Description**: `conversational_query` imports `get_current_user` from `app.middleware.auth_middleware` and types `current_user: dict = Depends(get_current_user)`. `get_current_user` returns a `TokenPayload` Pydantic instance. Line 26 calls `tenant_id = current_user.get('tenant_id')`, which crashes immediately with `AttributeError: 'TokenPayload' object has no attribute 'get'` on every request.
- **Correct Pattern / Fix**: Use `current_user: TokenPayload = Depends(get_current_user)` and access `current_user.tenant_id`.

---

- **Finding ID**: M4-QRY-02
- **File**: `backend/app/api/query.py`
- **Line**: 28-34
- **Severity**: **Critical**
- **Category**: Security issues & Multi-tenancy enforcement
- **Description**: `conversational_query` accepts `request.document_id` and directly passes it to `retriever.retrieve(query=request.question, tenant_id=tenant_id, document_id=request.document_id, db=db)`. In `HybridRetriever._fetch_chunks_for_document`, the query executed is: `select(DocumentChunk).where(DocumentChunk.document_id == document_id)`. `DocumentChunk` has no `tenant_id` column and the query does NOT join with `Document` or filter by `current_user.tenant_id`. If an attacker from Tenant A supplies the UUID of a document belonging to Tenant B, BM25 retrieval pulls Tenant B's document chunks, passes them to neural reranking and LLM synthesis, leaking Tenant B's private data to Tenant A.
- **Correct Pattern / Fix**: Verify document ownership against the current tenant before retrieval: `select(Document.id).where(Document.id == request.document_id, Document.tenant_id == current_user.tenant_id)`.

---

- **Finding ID**: M4-QRY-03
- **File**: `backend/app/api/query.py`
- **Line**: 47, 56
- **Severity**: **High**
- **Category**: Privacy pipeline logic & Security issues
- **Description**: `request.question` is placed directly into `prompt = f'Context:\n{context_text}\n\nQuestion: {request.question}'` and sent to `llm_router.generate_stream(prompt, system_prompt)`. No privacy masking (`MaskingPipeline`) or egress validation (`EgressValidator`) is performed on user queries. If a user asks a question containing real bank or institution names, unmasked sensitive entities are sent directly to third-party LLM providers (NVIDIA / Google), violating the zero-trust privacy rule.
- **Correct Pattern / Fix**: Mask and validate query text using `MaskingPipeline` and `EgressValidator` before sending to the LLM router.

---

- **Finding ID**: M4-QRY-04
- **File**: `backend/app/api/query.py`
- **Line**: 16, 50-60
- **Severity**: **Medium**
- **Category**: Async/await correctness & FastAPI 0.112+ API usage
- **Description**: `conversational_query` does not specify `response_class=StreamingResponse` or describe the SSE streaming response in OpenAPI metadata. If an error occurs prior to or during generator execution (e.g. `AllProvidersUnavailableError`), headers are already sent as HTTP 200 text/event-stream with error payload formatted in data events rather than standard HTTP error status codes.
- **Correct Pattern / Fix**: Declare `response_class=StreamingResponse` on the route and handle pre-stream failures prior to yielding.

---

### Module: Document Comparison (`backend/app/api/compare.py`)

#### File: `backend/app/api/compare.py`

- **Finding ID**: M4-CMP-01
- **File**: `backend/app/api/compare.py`
- **Line**: 18, 21
- **Severity**: **Critical**
- **Category**: Type annotation correctness & Incorrect API usage vs. latest library docs
- **Description**: `compare_documents` declares `current_user: dict = Depends(get_current_user)`. Line 21 calls `tenant_id = current_user.get('tenant_id')`, which crashes with `AttributeError: 'TokenPayload' object has no attribute 'get'`.
- **Correct Pattern / Fix**: Annotate `current_user: TokenPayload = Depends(get_current_user)` and access `current_user.tenant_id`.

---

- **Finding ID**: M4-CMP-02
- **File**: `backend/app/api/compare.py`
- **Line**: 55, 60, 86
- **Severity**: **High**
- **Category**: Privacy pipeline logic & Security issues
- **Description**: `request.focus_areas` user input is formatted into `prompt` without running through `EgressValidator`. Unmasked entity names in focus areas can leak to external LLM providers.
- **Correct Pattern / Fix**: Run `EgressValidator().validate(prompt, registry=None)` before calling `llm_router.generate`.

---

- **Finding ID**: M4-CMP-03
- **File**: `backend/app/api/compare.py`
- **Line**: 91-96
- **Severity**: **Medium**
- **Category**: Incorrect API usage vs. latest library docs & Error Handling
- **Description**: Lines 91-96 catch all exceptions with `except Exception as e:` without logging. When JSON parsing fails, it silently returns an empty differences list `differences=[]` with raw text in `summary`.
- **Correct Pattern / Fix**: Log the error with `logger.warning(f'Failed to parse structured comparison: {e}')` and catch specific `json.JSONDecodeError` / `pydantic.ValidationError`.

---

- **Finding ID**: M4-CMP-04
- **File**: `backend/app/api/compare.py`
- **Line**: 46-48
- **Severity**: **Low**
- **Category**: Incorrect API usage vs. latest library docs
- **Description**: Lines 46-48 truncate document text at arbitrary character offset: `text_a = text_a[:20000]`. This slices words mid-character and ignores 80%+ of typical validation documents without warning the user.
- **Correct Pattern / Fix**: Use token-based chunking with tiktoken or section-by-section comparison.

---

### Module: Regulatory Gap Analysis (`backend/app/api/gap_analysis.py`)

#### File: `backend/app/api/gap_analysis.py`

- **Finding ID**: M4-GAP-01
- **File**: `backend/app/api/gap_analysis.py`
- **Line**: 17, 20
- **Severity**: **Critical**
- **Category**: Type annotation correctness & Incorrect API usage vs. latest library docs
- **Description**: `analyze_gaps` declares `current_user: dict = Depends(get_current_user)`. Line 20 executes `tenant_id = current_user.get('tenant_id')`, which crashes with `AttributeError` on `TokenPayload`.
- **Correct Pattern / Fix**: Annotate `current_user: TokenPayload = Depends(get_current_user)` and access `current_user.tenant_id`.

---

- **Finding ID**: M4-GAP-02
- **File**: `backend/app/api/gap_analysis.py`
- **Line**: 82-83
- **Severity**: **High**
- **Category**: Incorrect API usage vs. latest library docs & Error Handling
- **Description**: Lines 82-83 catch `except Exception:` and silently return `GapAnalysisResponse(gaps=[], coverage_score=0.0)`. If the LLM generates non-JSON output or if generation fails, the user is misled into believing the document has 0 gaps and 0.0 coverage rather than receiving an error indicating that the analysis failed.
- **Correct Pattern / Fix**: Log the error with `logger.error` and raise an `HTTPException(status_code=502, detail='Failed to generate structured gap analysis from LLM')`.

---

- **Finding ID**: M4-GAP-03
- **File**: `backend/app/api/gap_analysis.py`
- **Line**: 40-45
- **Severity**: **Medium**
- **Category**: Incorrect API usage vs. latest library docs
- **Description**: `checklist` is hardcoded to 4 static items rather than querying CBUAE MMG regulatory rules or using RAG against the regulatory knowledge base.
- **Correct Pattern / Fix**: Retrieve relevant regulatory requirements dynamically using `HybridRetriever` against the CBUAE corpus.

---

### Module: Regulatory Search (`backend/app/api/regulatory.py`)

#### File: `backend/app/api/regulatory.py`

- **Finding ID**: M4-REG-01
- **File**: `backend/app/api/regulatory.py`
- **Line**: 17, 24
- **Severity**: **Critical**
- **Category**: Type annotation correctness & Incorrect API usage vs. latest library docs
- **Description**: `regulatory_search` declares `current_user: dict = Depends(get_current_user)`. Line 24 executes `tenant_id = current_user.get('tenant_id')`, raising `AttributeError` on `TokenPayload`.
- **Correct Pattern / Fix**: Annotate `current_user: TokenPayload = Depends(get_current_user)` and access `current_user.tenant_id`.

---

- **Finding ID**: M4-REG-02
- **File**: `backend/app/api/regulatory.py`
- **Line**: 46, 48
- **Severity**: **High**
- **Category**: Privacy pipeline logic & Security issues
- **Description**: `request.question` is concatenated into `prompt` and passed directly to `llm_router.generate(prompt, ...)` without egress validation.
- **Correct Pattern / Fix**: Run `EgressValidator().validate(prompt)` before calling LLM generation.

---

- **Finding ID**: M4-REG-03
- **File**: `backend/app/api/regulatory.py`
- **Line**: 3
- **Severity**: **Low**
- **Category**: Broken imports and missing dependencies
- **Description**: Line 3 imports `import uuid` which is never used in `regulatory.py`.
- **Correct Pattern / Fix**: Remove unused `import uuid`.

---

### Module: Health & Diagnostics (`backend/app/api/health.py`)

#### File: `backend/app/api/health.py`

- **Finding ID**: M4-HLT-01
- **File**: `backend/app/api/health.py`
- **Line**: 24
- **Severity**: **Low**
- **Category**: Incorrect API usage vs. latest library docs (Python 3.12)
- **Description**: Line 24 calls `datetime.utcnow().isoformat()`. In Python 3.12, `datetime.utcnow()` is officially deprecated and produces `DeprecationWarning`.
- **Correct Pattern / Fix**: Use timezone-aware UTC datetime: `from datetime import datetime, timezone; datetime.now(timezone.utc).isoformat()`.

---

- **Finding ID**: M4-HLT-02
- **File**: `backend/app/api/health.py`
- **Line**: 18-25
- **Severity**: **Low**
- **Category**: API design & Monitoring
- **Description**: When the database connection fails, `health_check` catches `except Exception:` and returns HTTP 200 with `{'status': 'ok', 'db': 'disconnected'}`. Health check probes will report healthy when the database is unavailable.
- **Correct Pattern / Fix**: Return HTTP 503 Service Unavailable or implement dedicated liveness (`/health/live`) and readiness (`/health/ready`) endpoints.

---

### Module: Server Entrypoint & CORS (`backend/app/main.py`)

#### File: `backend/app/main.py`

- **Finding ID**: M4-MAIN-01
- **File**: `backend/app/main.py`
- **Line**: 35-43
- **Severity**: **High**
- **Category**: Security issues & FastAPI Configuration
- **Description**: `main.py` conditionally attaches `CORSMiddleware` only if `settings.allowed_origins` is non-empty (`if settings.allowed_origins:`). Because `Settings.allowed_origins` defaults to `''` in `config.py`, by default NO CORS middleware is registered at all. Browser requests from the frontend (e.g. `http://localhost:5173`) fail CORS preflight checks completely. Additionally, if `allowed_origins` is set to `*`, `allow_credentials=True` violates browser CORS standards.
- **Correct Pattern / Fix**: Always configure `CORSMiddleware` with safe defaults (`['http://localhost:5173', 'http://localhost:3000']`).

---

- **Finding ID**: M4-MAIN-02
- **File**: `backend/app/main.py`
- **Line**: 48-50
- **Severity**: **Low**
- **Category**: Code conventions & PEP 8
- **Description**: `from app.api import documents, query, compare, gap_analysis, regulatory` and `from fastapi import Depends` are placed midway down the file after app instantiation.
- **Correct Pattern / Fix**: Move all module imports to top of file per PEP 8.

---

### Module: Security, Cryptography & Dependencies (`backend/app/utils/security.py`, `backend/requirements.txt`)

#### File: `backend/app/utils/security.py` & `backend/requirements.txt`

- **Finding ID**: M4-SEC-01
- **File**: `backend/app/utils/security.py`, `backend/app/config.py`, `backend/requirements.txt`
- **Line**: `security.py:32, 42, 47` & `config.py:46, 47`
- **Severity**: **Critical**
- **Category**: Security issues & Cryptography
- **Description**: `config.py` specifies `jwt_algorithm: str = 'RS256'` and `jwt_secret_key: str = ''`. In `security.py`, `jwt.encode` and `jwt.decode` pass `settings.jwt.secret_key` (a single string symmetric secret) for both signing and verifying with `algorithm='RS256'`. RS256 is an asymmetric algorithm requiring an RSA Private Key (PEM format) for signing and an RSA Public Key (PEM format) for verification. Passing a symmetric string secret under RS256 causes cryptographic libraries (`python-jose` and `PyJWT`) to raise `JOSEError: Key must be a valid RSA key`. Furthermore, `AGENTS.md` mandates `PyJWT`, but `requirements.txt` includes `python-jose[cryptography]` and omits `pyjwt`.
- **Correct Pattern / Fix**: For RS256, define separate `jwt_private_key_pem` and `jwt_public_key_pem` in `Settings`, and use `PyJWT`.

---

- **Finding ID**: M4-SEC-02
- **File**: `backend/app/utils/security.py`
- **Line**: 24, 36
- **Severity**: **Low**
- **Category**: Incorrect API usage vs. latest library docs (Python 3.12)
- **Description**: `create_access_token` and `create_refresh_token` use `datetime.utcnow()`, which is deprecated in Python 3.12.
- **Correct Pattern / Fix**: Use `datetime.now(timezone.utc)`.

---

## 3. Cross-Cutting Verification & Architectural Synthesis

### Multi-Tenancy Enforcement Audit Matrix

| Endpoint | Method | Path | Tenant Filter Applied | Issues Identified |
| :--- | :--- | :--- | :---: | :--- |
| `auth.register` | POST | `/auth/register` | N/A (Tenant Created) | None |
| `auth.login` | POST | `/auth/login` | N/A (User Lookup) | Missing `is_active` check |
| `auth.refresh` | POST | `/auth/refresh` | N/A (User Lookup) | Missing `is_active` check |
| `documents.upload` | POST | `/documents/upload` | **YES** (`current_user.tenant_id`) | Memory DoS on read; filename unsanitized |
| `documents.list` | GET | `/documents` | **YES** (`current_user.tenant_id`) | Hardcoded chunk count |
| `documents.get` | GET | `/documents/{id}` | **YES** (`current_user.tenant_id`) | Missing response model |
| `documents.delete` | DELETE | `/documents/{id}` | **YES** (`current_user.tenant_id`) | None |
| `query.conversational` | POST | `/query` | **PARTIAL** (Vulnerable) | **Critical**: `AttributeError` on `current_user.get()`; `request.document_id` not verified against tenant in HybridRetriever |
| `compare.documents` | POST | `/compare` | **YES** (Doc A & B verified) | **Critical**: `AttributeError` on `current_user.get()` |
| `gap_analysis.analyze` | POST | `/gap-analysis` | **YES** (`Document.tenant_id`) | **Critical**: `AttributeError` on `current_user.get()` |
| `regulatory.search` | POST | `/regulatory/search` | N/A (CBUAE Corpus) | **Critical**: `AttributeError` on `current_user.get()` |
| `health.check` | GET | `/health` | N/A (Global) | Deprecated utcnow |

---

## 4. Remediation Priority Roadmap

1. **Immediate P0 Blockers (Crashes & Security Exploits)**:
   - Fix `AttributeError: 'TokenPayload' object has no attribute 'get'` in `rate_limiter.py`, `query.py`, `compare.py`, `gap_analysis.py`, and `regulatory.py` by switching to `current_user.tenant_id`.
   - Add tenant ownership check for `request.document_id` in `query.py` before passing to `HybridRetriever`.
   - Fix RS256 private/public key configuration in `config.py` and `security.py`.
   - Consolidate duplicate `get_current_user` dependencies between `deps.py` and `auth_middleware.py`.
2. **High Priority P1 Fixes (Stability & Privacy)**:
   - Add chunked streaming read with 413 check in `documents.py:upload_document`.
   - Sanitize filenames and guard against NoneType in `documents.py`.
   - Enforce `EgressValidator` and `MaskingPipeline` on user inputs in `query.py`, `compare.py`, and `regulatory.py`.
   - Check `is_active` in `deps.py:get_current_user`, `auth.py:login`, and `auth.py:refresh`.
   - Enforce `token_type == 'access'` in `deps.py:get_current_user`.
   - Add default local development origins to CORS middleware in `main.py`.
   - Fix Lua script loading path using `Path(__file__)` in `rate_limiter.py`.
3. **Medium/Low P2 Fixes (Refinements & Modernization)**:
   - Replace deprecated `datetime.utcnow()` with `datetime.now(timezone.utc)`.
   - Add `status_code=201` to `/auth/register` and `response_model` to `GET /documents/{document_id}`.
   - Replace silent JSON parse fallbacks in `gap_analysis.py` and `compare.py` with structured error logging and HTTP 502 exceptions.

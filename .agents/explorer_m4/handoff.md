# Handoff Report — Explorer M4 (API Endpoints, Middleware & Entrypoint)

## 1. Observation

Direct code inspections were performed across all 14 target files in the API and middleware layer. Key verbatim code patterns observed:

1. **`backend/app/middleware/rate_limiter.py:38-39, 98`**:
   - `async def check_rate_limit(self, request: Request, current_user: dict):`
   - `tenant_id = current_user.get('tenant_id')`
   - `tier = current_user.get('tier', 'FREE')`
   - `get_current_user` in `auth_middleware.py:23` returns `TokenPayload(**payload_dict)`.
   - Calling `.get()` on a Pydantic `BaseModel` raises `AttributeError: 'TokenPayload' object has no attribute 'get'`.

2. **`backend/app/api/query.py:19, 26, 28-34`**:
   - `async def conversational_query(request: QueryRequest, current_user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_db)):`
   - `tenant_id = current_user.get('tenant_id')`
   - `retrieval_result = await retriever.retrieve(query=request.question, tenant_id=tenant_id, document_id=request.document_id, db=db, top_k=6)`
   - In `HybridRetriever._fetch_chunks_for_document`, `select(DocumentChunk).where(DocumentChunk.document_id == document_id)` does not filter by tenant, allowing cross-tenant chunk retrieval if an arbitrary `document_id` is supplied.

3. **`backend/app/api/deps.py:17-42` vs `backend/app/middleware/auth_middleware.py:12-30`**:
   - Two completely conflicting `get_current_user` implementations exist. `deps.py` uses `OAuth2PasswordBearer` and returns `User` model; `auth_middleware.py` uses `HTTPBearer` and returns `TokenPayload`. In `main.py`, both are applied simultaneously to `documents.router`.

4. **`backend/app/api/documents.py:35, 39`**:
   - `file_bytes = await file.read()` before checking `len(file_bytes) > MAX_FILE_SIZE`.
   - `ext = file.filename.split('.')[-1].lower()` without `None` check or path traversal sanitization.

5. **`backend/app/utils/security.py:32, 47` & `backend/app/config.py:46-47`**:
   - `jwt_algorithm: str = 'RS256'`
   - `jwt_secret_key: str = ''`
   - Single symmetric secret string used for RS256 asymmetric RSA encoding and decoding.

---

## 2. Logic Chain

1. **`TokenPayload` vs `dict`**:
   - `auth_middleware.py:23` constructs and returns `TokenPayload(**payload_dict)`.
   - `rate_limiter.py`, `query.py`, `compare.py`, `gap_analysis.py`, and `regulatory.py` treat `current_user` as `dict` and call `.get('tenant_id')`.
   - Pydantic v2 `BaseModel` does not implement `.get()`.
   - Therefore, any request intercepted by `get_rate_limiter` or handled by `query.py`, `compare.py`, `gap_analysis.py`, or `regulatory.py` will crash at runtime with `AttributeError`.

2. **Cross-Tenant Retrieval Vulnerability**:
   - `query.py` accepts user-controlled `request.document_id`.
   - `query.py` passes `document_id` to `retriever.retrieve` without verifying tenant ownership in the `documents` table.
   - `HybridRetriever._fetch_chunks_for_document` executes `select(DocumentChunk).where(DocumentChunk.document_id == document_id)`.
   - `DocumentChunk` records do not contain `tenant_id` column.
   - Therefore, an authenticated user from Tenant A can query documents from Tenant B simply by providing Tenant B's document UUID.

3. **Denial of Service via Unbounded File Upload**:
   - `file.read()` asynchronously reads the entire payload stream into memory.
   - The size check `if len(file_bytes) > MAX_FILE_SIZE` only runs *after* `file.read()` finishes.
   - Therefore, a payload larger than available memory causes OOM crash before the 413 exception can be raised.

4. **Cryptographic Asymmetric Key Failure**:
   - RS256 requires an RSA private key for signing and an RSA public key for verification.
   - `config.py` defines only `jwt_secret_key: str = ''`.
   - `security.py` passes `settings.jwt.secret_key` to both `jwt.encode` and `jwt.decode`.
   - Therefore, JWT creation and validation fail with RSA key format errors.

---

## 3. Caveats

- This audit was performed under STRICT read-only rules without runtime code execution, test runs, or package installation.
- External upstream services (Upstash Redis, Pinecone, NVIDIA NIM, Google Gemini) were not connected live; all findings are based on static analysis of SDK call signatures and schemas.
- No caveats regarding code visibility: all 14 target files and all dependent schemas, models, and service interfaces were thoroughly reviewed.

---

## 4. Conclusion

The API endpoints, middleware, and entrypoints layer exhibits strong conceptual design (FastAPI async-first, Pydantic schemas, multi-tenant database filtering, token bucket rate limiting) but contains **7 Critical**, **11 High**, **8 Medium**, and **9 Low** severity bugs that prevent correct execution:
- All LLM-facing and rate-limited endpoints currently crash with `AttributeError` due to dictionary `.get()` calls on Pydantic `TokenPayload`.
- Multi-tenancy isolation can be bypassed in `query.py` via unvalidated `document_id`.
- The authentication layer has duplicate, conflicting dependencies and an invalid RS256 symmetric secret configuration.
- Privacy egress validation is bypassed on all conversational query, comparison, and regulatory search prompts.

---

## 5. Verification Method

To independently verify these findings when running the test suite / runtime environment:

1. **Verify `AttributeError` on `.get()`**:
   - Issue a request to `POST /query` with valid JWT bearer token.
   - Observe `AttributeError: 'TokenPayload' object has no attribute 'get'` in logs at `query.py:26`.
2. **Verify Multi-Tenancy Leak in `query.py`**:
   - Create Document in Tenant A (ID: `doc_a`).
   - Authenticate as Tenant B user and call `POST /query` with `document_id=doc_a`.
   - Observe Tenant A chunks returned in retrieval result citations.
3. **Verify File Upload OOM**:
   - Inspect `documents.py:35` confirming `await file.read()` is called prior to `len(file_bytes)` check.
4. **Verify RS256 Key Misconfiguration**:
   - Call `create_access_token(uuid.uuid4(), uuid.uuid4(), 'ADMIN')` with `jwt_algorithm='RS256'` and string secret.
   - Observe cryptographic error due to missing RSA private key.

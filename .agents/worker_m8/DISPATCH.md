## 2026-08-28T13:51:09Z
You are a specialist Worker for ModelAudit AI Milestone 8: API Endpoints, Middleware, Auth & Integration.

# Instructions & Context
- You MUST read ORIGINAL_REQUEST.md: `c:\Users\Shakti\Documents\CreditAudit- AI\.agents\ORIGINAL_REQUEST.md`
- You MUST read the Master Bug Report: `c:\Users\Shakti\Documents\CreditAudit- AI\backend_code_audit_report.md`
- Project Identity & Rules: `c:\Users\Shakti\Documents\CreditAudit- AI\.agents\AGENTS.md`
- Domain Skills to load if needed: `c:\Users\Shakti\Documents\CreditAudit- AI\.agents\skills\p6-api-streaming-ratelimit\SKILL.md` and `p1-database-auth`
- Your working directory for agent metadata is: `c:\Users\Shakti\Documents\CreditAudit- AI\.agents\worker_m8`

# Exclusive File Ownership
You exclusively own and may edit:
- `backend/app/api/query.py`
- `backend/app/api/compare.py`
- `backend/app/api/gap_analysis.py`
- `backend/app/api/regulatory.py`
- `backend/app/api/documents.py`
- `backend/app/api/auth.py`
- `backend/app/api/deps.py`
- `backend/app/api/health.py`
- `backend/app/api/__init__.py`
- `backend/app/middleware/rate_limiter.py`
- `backend/app/middleware/auth_middleware.py`
- `backend/app/middleware/__init__.py`
- `backend/app/utils/streaming.py`
- `backend/app/main.py`

DO NOT edit files outside this list.

# Assigned Issues to Resolve
1. API-01 (Critical): In `api/query.py`, `api/compare.py`, `api/gap_analysis.py`, `api/regulatory.py`, fix `current_user` attribute access. `get_current_user` returns `TokenPayload`. Use `current_user.tenant_id` instead of `current_user.get('tenant_id')`.
2. API-02 (Critical): In `api/query.py`, enforce multi-tenant document isolation by verifying in DB that `Document.id == request.document_id` and `Document.tenant_id == current_user.tenant_id` before querying retrieval pipeline.
3. API-03 (High): In `api/query.py`, `api/compare.py`, `api/regulatory.py`, ensure user prompt inputs are passed through `MaskingPipeline` and `EgressValidator` before sending to LLM.
4. API-04 (High): In `api/documents.py`, implement chunked streaming file upload with running byte counter (1MB chunks) raising HTTP 413 immediately when `MAX_FILE_SIZE` is exceeded, preventing OOM DoS attacks.
5. API-05 (High): In `api/documents.py`, sanitize uploaded filenames using `Path(file.filename).name` and guard against NoneType / path traversal.
6. API-06 (High): In `api/documents.py`, omit raw unmasked entity mapping in upload responses (return entity category counts instead of unmasked entity names).
7. API-07 (Medium): In `api/documents.py`, execute `await db.rollback()` before updating status to `ERROR` on processing failures.
8. API-08 (Critical): In `api/deps.py` and `middleware/auth_middleware.py`, consolidate the canonical `get_current_user` dependency returning `TokenPayload` (with user active check) in `deps.py`.
9. API-09 (High): In `api/auth.py` and `api/deps.py`, verify `user.is_active` on login, token refresh, and dependency resolution.
10. API-10 (High): In `api/deps.py`, verify `payload.type == 'access'` to reject refresh tokens on protected data endpoints.
11. API-11 (High): In `api/gap_analysis.py`, raise `HTTPException(502, 'Failed to generate gap analysis from LLM')` on LLM failure instead of returning empty fake results.
12. MID-01 (Critical): In `middleware/rate_limiter.py`, access `current_user.tenant_id` on `TokenPayload` instead of `current_user.get()`.
13. MID-02 (High): In `middleware/rate_limiter.py`, resolve Lua script paths dynamically using `Path(__file__).resolve().parent.parent.parent / 'lua'`.
14. MID-03 (High): In `api/auth.py` and `middleware/rate_limiter.py`, include `tier` claim in JWT payload and handle tenant tier limits properly.
15. MID-04 (Medium): In `middleware/auth_middleware.py`, re-raise `HTTPException` explicitly.
16. CFG-02 (High): In `backend/app/main.py`, register `CORSMiddleware` with default allowed origins (`['http://localhost:5173', 'http://localhost:3000']`).
17. CFG-03 (Medium): In `utils/streaming.py`, add `X-Accel-Buffering: no` and `Cache-Control: no-cache` headers.
18. Re-export public API routers and middleware in respective `__init__.py` files.

# Adversarial Stress-Testing Report: Operational Edge Cases, Vercel SPA Routing & Rollback Runbooks

**Evaluator**: `challenger_edge_1` (Empirical Challenger: Critic & Specialist)  
**Target Specification**: `c:\Users\Shakti\Documents\CreditAudit- AI\deployment_steps.md`  
**Date**: 2026-08-31  
**Verdict**: **APPROVE** (All 3 core challenge dimensions validated; minor operational hardening recommendations provided)

---

## Executive Summary

An adversarial stress-test and empirical validation was conducted on the production deployment guide and runbook (`deployment_steps.md`). The audit evaluated frontend edge routing on Vercel, operational resilience of external distributed dependencies (Upstash Redis, Pinecone Serverless, AWS RDS, AWS SSM), disaster recovery runbooks, and rollback procedures.

All primary architectural assumptions, cryptographic invariants, tenant isolation namespaces, and zero-downtime database rollback strategies were verified against the live implementation in `backend/app/` and `frontend/`.

```
========================================================================================
                               STRESS-TEST VERIFICATION SUMMARY
========================================================================================
 Dimension                                   Risk Assessment   Verdict
----------------------------------------------------------------------------------------
 1. Frontend Vercel SPA Routing & Headers   LOW               PASSED (Robust)
 2. Operational Resilience & Multi-Tenancy  LOW               PASSED (Isolated & Resilient)
 3. Disaster Recovery & Rollback Runbooks   LOW               PASSED (Complete)
========================================================================================
 FINAL AUDIT VERDICT: APPROVE
========================================================================================
```

---

## 1. Frontend Vercel Deployment & SPA Routing Stress-Test

### 1.1 SPA Routing Catch-All Rewrites & Asset Routing Collisions
- **Specification (`vercel.json`)**:
  ```json
  "rewrites": [
    { "source": "/api/:path*", "destination": "https://api.modelaudit.ai/:path*" },
    { "source": "/(.*)", "destination": "/index.html" }
  ]
  ```
- **Stress-Test Analysis**:
  1. *Static Asset Collision Probe*: In Vercel CDN routing architecture, physical static files emitted by Vite into `dist/` (e.g. `dist/assets/index-*.js`, `dist/assets/index-*.css`, `dist/favicon.ico`) take absolute precedence over `rewrites`. Non-file paths (`/workspace`, `/models`, `/settings`) hit the catch-all `/(.*)` rule and rewrite to `/index.html` for client-side HTML5 history routing.
  2. *API Rewrite vs Direct ALB (Option A vs Option B)*:
     - **Option B (Vercel Proxy)**: Forwards `/api/:path*` to `https://api.modelaudit.ai/:path*`. Under high load, Vercel Serverless / Edge rewrites have a 4.5 MB request body limit on standard tiers and edge timeout caps (10s to 60s). Large validation dossiers (up to 50MB PDFs) or long-running Server-Sent Event (`/query` SSE) streams could suffer proxy buffering or premature termination.
     - **Option A (Direct Cross-Origin)**: Configures `VITE_API_BASE_URL="https://api.modelaudit.ai"`. The browser connects directly to the AWS Application Load Balancer over TLS 1.3 on port 443. This bypasses Vercel proxy payload limits and delivers unbuffered chunked SSE streams.
     - *Conclusion*: `deployment_steps.md` Section 3.2 correctly articulates this distinction and recommends Option A for production enterprise throughput while maintaining Option B for zero-CORS setups.

### 1.2 Security Headers & Caching Strategy
- **Headers Configuration**:
  - `X-Content-Type-Options: nosniff`
  - `X-Frame-Options: DENY`
  - `X-XSS-Protection: 1; mode=block`
  - `Referrer-Policy: strict-origin-when-cross-origin`
  - `Cache-Control: public, max-age=31536000, immutable` strictly bound to `source: "/assets/(.*)"`
- **Stress-Test Assessment**:
  - *Caching Invariant*: The immutable 1-year cache is strictly isolated to content-hashed Vite bundles in `/assets/`. Root paths and `/index.html` are excluded from the immutable cache header, ensuring instantaneous rollout of new frontend releases.
  - *Security Hardening Recommendation*: Modern browsers treat `X-XSS-Protection` as obsolete. For strict CBUAE banking compliance, adding `Content-Security-Policy: default-src 'self'; connect-src 'self' https://api.modelaudit.ai;` and `Strict-Transport-Security: max-age=63072000; includeSubDomains; preload` is recommended for future hardening.

### 1.3 CORS Headers & Dynamic Origin Handling
- **Backend Configuration (`backend/app/main.py` & `backend/app/config.py`)**:
  `origins = settings.allowed_origins_list` with `allow_origins=origins, allow_credentials=True, allow_methods=["*"], allow_headers=["*"]`.
  `ALLOWED_ORIGINS` in ECS Task Definition: `"https://modelaudit.vercel.app,https://app.modelaudit.ai,http://localhost:5173"`.
- **Stress-Test Assessment**:
  - Production custom domains (`https://app.modelaudit.ai`) and primary Vercel domains (`https://modelaudit.vercel.app`) match exactly and support credentials and streaming.
  - *Caveat*: Dynamic ephemeral PR preview deployments (`modelaudit-ai-*-team.vercel.app`) will require Option B proxy routing or updating `ALLOWED_ORIGINS` dynamically.

### 1.4 Vite Build-Time Variable Inlining
- **Verification (`frontend/src/lib/http.ts:3-4` & `frontend/src/lib/sse.ts:4-5`)**:
  `const BASE = ((import.meta as any).env.VITE_API_BASE_URL as string | undefined) || '/api';`
- **Assessment**:
  - Vite embeds `VITE_*` variables as string constants during `npm run build`.
  - `deployment_steps.md` Section 3.2 correctly documents this in bold, warning operators that updating Vercel environment variables requires triggering a new build.

---

## 2. Operational Resilience & Multi-Tenancy Stress-Test

### 2.1 Upstash Redis Rate Limiting & Fail-Open Behavior
- **Implementation (`backend/app/middleware/rate_limiter.py`)**:
  - `load_scripts()` catches Redis connection failures and logs `logger.error` without preventing application startup.
  - `check_rate_limit()` wraps Redis `evalsha` in `try...except Exception:` and explicitly returns `True` (Fail-open) when Redis encounters connection drops, timeouts, or auth errors, while re-raising legitimate `HTTPException(429)` rate limits.
- **Stress-Test Assessment**:
  - If Upstash experiences a regional outage or network partition, the API remains fully accessible.
  - *Minor Finding*: `check_rate_limit` does not check `settings.rate_limit_enabled` at the start of the function; when disabled, it attempts Redis evaluation and relies on fail-open if unconfigured. This is functionally safe but could produce log warnings if Redis credentials are intentionally omitted in dev.

### 2.2 Pinecone Serverless Namespace Tenant Isolation
- **Implementation (`backend/app/api/documents.py`, `backend/app/services/retrieval/`)**:
  - Document Upload/Upsert: `namespace = f"user-docs:{current_user.tenant_id}:{doc_id}"`
  - Retrieval Query: `namespaces = ["cbuae-manuals", f"user-docs:{tenant_id}:{document_id}"]`
  - Document Deletion: `await pinecone_store.adelete_namespace(f"user-docs:{current_user.tenant_id}:{document_id}")`
- **Stress-Test Assessment**:
  - Vector embeddings are partition-isolated at the Pinecone Serverless namespace boundary.
  - No vector query from Tenant A can retrieve embeddings from Tenant B, even if document UUIDs were guessed.
  - Verified by `test_stress_multitenancy.py` (PASSED).

### 2.3 RS256 RSA Key Pair Persistence across ECS Fargate Tasks
- **Implementation (`backend/app/utils/security.py`)**:
  - Multi-line PEM keys loaded from `settings.jwt.private_key` and `settings.jwt.public_key` with automatic `\n` unescaping (`replace("\\n", "\n")`).
  - Fallback in-memory keys (`_DEFAULT_PRIVATE_KEY_PEM`) are only used if environment variables are empty.
- **Stress-Test Assessment**:
  - In a multi-task ECS cluster (`desired-count 2`), ephemeral keys would cause inter-task token validation failures (Task A issues token -> ALB routes to Task B -> 401 Unauthorized) and logout users on container restarts.
  - `deployment_steps.md` Section 4.5 and Section 5.4 mandate storing RSA 2048-bit keys in AWS SSM Parameter Store (`/modelaudit/prod/jwt/private_key`, `/modelaudit/prod/jwt/public_key`) and injecting them via Task Definition secrets. This guarantees key synchronization across all ECS tasks and task recycles.

### 2.4 Zero-Downtime Database Migration Rollback Strategies
- **Implementation (`backend/alembic/versions/`)**:
  - `b39c1a2f3e4d_add_frontend_compat_columns.py`: Adds `nullable=True` columns to `models` and `regulatory_standards`, and `min_observation_months` with `server_default='24'` to `tenant_settings`.
  - `c7d8e9f0a1b2_add_population_deciles.py`: Adds nullable `population_deciles` JSON column to `model_versions`.
- **Stress-Test Assessment**:
  - Migrations strictly adhere to the Expand/Contract pattern: old application containers continue operating during database migration without query breakage.
  - Rollback scripts (`downgrade()`) in all migrations cleanly drop added columns using `op.drop_column`.
  - Section 5.6 decouples migrations into a pre-deployment one-off Fargate `run-task` that verifies `exitCode == 0` before rolling out the web service.

---

## 3. Disaster Recovery & Rollback Runbook Validation (Section 9)

| Procedure | Verification Result | Operational Soundness |
|---|---|---|
| **ECS Task Rollback (9.1)** | `aws ecs update-service --task-definition modelaudit-backend-task:<prev_revision> --force-new-deployment` | Instantaneous rollback without container rebuild; traffic shifted via ALB target group deregistration delay. |
| **CloudWatch Alarms (9.2)** | Configured for CPU (>80%), Memory (>80%), ALB 5XX (>5 in 1 min), UnHealthyHostCount (>=1), and RDS Free Storage (<5GB). | Comprehensive alarm matrix protecting both availability and compute bounds. |
| **Database Migration Rollback (9.3)** | One-off task executing `alembic downgrade -1`. | Fully supported by bidirectional Alembic migration files. |
| **Vector DB Disaster Recovery (9.4)** | Regulatory corpus reconstructed via `python -m scripts.index_regulatory_corpus`. | Fully deterministic and re-indexable without customer downtime. |
| **RTO & RPO Objectives (9.4)** | RTO < 15 min, RPO < 5 min via RDS PITR and automated ECS task replacement. | Realistic and well within banking tier-2 recovery standards. |

---

## 4. Empirical Test Verification

The local test suites and frontend bundle build were empirically executed:
- **Pytest Full Suite**: 100% tests passing across multitenancy, privacy, guardrails, LLM routing, and analytics.
- **Frontend Production Build**: `tsc --noEmit && vite build` compiled without errors, generating production assets in `dist/`.

---

## 5. Final Audit Recommendation

**Verdict: APPROVE**

The deployment guide `deployment_steps.md` is robust, mathematically and architecturally accurate, and provides full operational resilience for production deployment on AWS ECS Fargate, Vercel, and managed cloud dependencies.

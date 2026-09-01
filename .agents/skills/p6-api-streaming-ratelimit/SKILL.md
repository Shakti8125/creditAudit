---
name: p6-api-streaming-ratelimit
description: >-
  Use this skill when the user asks to build the API endpoints, SSE streaming, and rate limiting middleware for ModelAudit AI Phase 6.
---
# Phase 6: API Endpoints, SSE Streaming, and Rate Limiting

This skill instructs an agent to build the API endpoints, streaming integration, and Redis-based rate limiting logic for Phase 6.

## Step 1: Create SSE Streaming Helper
**Target File**: `backend/app/utils/streaming.py`
- **Function**: `sse_stream(generator: AsyncIterator[str]) -> StreamingResponse`
- **Format**:
  - Each token: `data: {"type": "token", "content": "..."}\n\n`
  - End: `data: {"type": "done"}\n\n`
  - Error: `data: {"type": "error", "content": "..."}\n\n`
- **Headers**: Content-Type: `text/event-stream`

## Step 2: Create Conversational Q&A Endpoint
**Target File**: `backend/app/api/query.py`
- **Route**: `POST /query`
- **Request**: `QueryRequest(document_id: UUID | None, question: str, session_id: UUID | None)`
- **Flow**:
  a. Load document chunks if `document_id` provided.
  b. Hybrid retrieval against CBUAE corpus + uploaded doc chunks.
  c. Build prompt with retrieved context (MMG and doc chunks).
  d. Stream LLM response via SSE.
  e. Return citations alongside streamed response.
- **Prompt**: System prompt instructs the LLM to cite sources using `[Source: ...]` format.
- **Fallback**: Provide non-streaming fallback for clients that don't support SSE.

## Step 3: Create Document Comparison Endpoint
**Target File**: `backend/app/api/compare.py`
- **Route**: `POST /compare`
- **Request**: `CompareRequest(document_id_a: UUID, document_id_b: UUID, focus_areas: list[str] | None)`
- **Flow**: Load chunks from both documents, build comparison prompt, and return structured `CompareResponse` with side-by-side analysis.

## Step 4: Create Automated Gap Analysis Endpoint
**Target File**: `backend/app/api/gap_analysis.py`
- **Route**: `POST /gap-analysis`
- **Request**: `GapAnalysisRequest(document_id: UUID)`
- **Flow**: Use predefined MMG checklist (20+ requirements from CBUAE MMG Parts 1-3). For each requirement, query document chunks to check coverage. Use LLM to assess compliance level.
- **Response**: `GapAnalysisResponse(gaps: list[ComplianceGap], coverage_score: float)`

## Step 5: Create Standalone Regulatory Lookup Endpoint
**Target File**: `backend/app/api/regulatory.py`
- **Route**: `POST /regulatory/search`
- **Request**: `RegulatoryQuery(question: str)`
- **Flow**: Pure RAG against CBUAE corpus (no document upload needed).
- **Response**: Return answer with citations.

## Step 6: Create Token Bucket Lua Script
**Target File**: `backend/lua/token_bucket.lua`
- **Action**: Copy the Atomic Token Bucket Lua script from architecture plan section 9.1.

## Step 7: Create GCRA Leaky Bucket Lua Script
**Target File**: `backend/lua/gcra_leaky_bucket.lua`
- **Action**: Copy the Atomic GCRA Lua script from architecture plan section 9.1.

## Step 8: Create Rate Limiter Middleware
**Target File**: `backend/app/middleware/rate_limiter.py`
- **Class**: `RateLimiter` (FastAPI middleware using Upstash Redis)
- **Logic**:
  - Loads Lua scripts at startup via `redis.script_load()`.
  - Executes via `redis.evalsha(sha, keys=[key], args=[capacity, refill_rate, cost])`.
  - Connection: `from upstash_redis.asyncio import Redis; redis = Redis(url=..., token=...)`.
  - Endpoint cost multipliers: `/query=1`, `/compare=5`, `/gap-analysis=3`, `/health=0`.
  - Tier config from user's JWT (FREE/PROFESSIONAL/ENTERPRISE).
  - Pre-validates cost <= capacity (returns `403` if cost > max burst).
  - Returns `429` with `Retry-After` header on rate limit.
- **Dependency**: `rate_limit = Depends(get_rate_limiter)`

## Verification
- Test SSE streaming with curl.
- Test rate limiting with burst requests.
- Test all API endpoints to ensure they return correct schemas.

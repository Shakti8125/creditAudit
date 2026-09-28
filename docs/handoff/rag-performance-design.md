> Archived design (Sept 2026). The implemented contract lives in `backend/app/schemas/rag_eval.py` / `frontend/src/lib/ragTypes.ts` — see ../../HANDOFF.md §3. Deviations made during implementation: nDCG uses target-coverage gain (commit 7db3072), the `suggestedActions` SSE event was removed, retrieval uses the masked question, and `/regulatory/search` runs input guardrails.

# RAG Performance: implementation plan (telemetry, feedback, offline evaluation)

The plan has two work packages that share no files. WP-BACKEND edits only files under `backend/`, and WP-FRONTEND edits only files under `frontend/`. The API contract in §2 is the only thing they share. `backend/app/schemas/rag_eval.py` and `frontend/src/lib/ragTypes.ts` must stay field-for-field identical.

---

## 0. What the codebase actually does (and what this design depends on)

| Fact | Where | Consequence for the design |
|---|---|---|
| `HybridRetriever.retrieve()` runs sequentially: dense (embed plus Pinecone, top 20), then BM25 (DB chunks if there is a `document_id`, otherwise the 10-item `CBUAE_REGULATORY_CORPUS`), then RRF (`rrf_fuse`, normalised to 0–1), then rerank (`Reranker`, which falls back to the fused top-n on failure). It only records total `latency_ms` and 4 counts. | `services/retrieval/hybrid_retriever.py:172-300` | Add per-stage timing, a `mode` (ablation) parameter and a typed `diagnostics` object. The default behaviour must not change. |
| Dense errors are swallowed and return `[]`. Rerank errors are swallowed and fall back silently. | `dense_retriever.py:47-51`, `reranker.py:45-58` | Expose `dense_empty` and `rerank_fallback` flags, because otherwise degradation cannot be seen. |
| `LLMRouter` does not expose which provider or model served a call, or whether failover happened. It is instantiated per request. | `services/llm/router.py:126-151, 171-216` | Add a per-instance `call_log`. This is safe because each request builds its own router. |
| NVIDIA returns rerank **logits** (unbounded). Gemini rerank gives 0–10. RRF gives 0–1. Dense gives cosine. | `nvidia_provider.py:245`, `gemini_provider.py:118-166` | Top scores cannot be averaged across kinds. Store `score_kind` and a normalised `top_score_norm`. |
| `/query` is an SSE stream with events `session_id`, `citations`, `token`*, `suggestedActions`, then `done`/`error` (`utils/streaming.py`). The assistant `ChatMessage` is saved inside the generator using `async_session_maker()`. | `api/query.py:164-220` | Emit a new `{"type":"trace"}` event right after `session_id`. Save the trace in the generator's `finally` using a fresh session. |
| `/regulatory/search` is plain JSON (`RegulatoryResponse{answer,citations}`). | `api/regulatory.py` | Add an optional `trace_id` field. This is backward compatible. |
| `/gap-analysis` and `/compare` do **not retrieve**. They put up to 30k (gap analysis) and 2×20k (compare) characters of document text straight into the prompt. | `api/gap_analysis.py`, `api/compare.py` | They are not instrumented in v1. They are not RAG, so retrieval metrics do not apply to them. `RagTraceRecorder` could record "generation-only" traces for them later. |
| Dense citations for regulatory content come from PDF chunks: `source` is the PDF filename and `section` is a heading path or `"Chunk i"`. BM25 regulatory citations use `"CBUAE-MMG-2022"` and `"Section N - …"`. Document BM25 uses `doc-{uuid}` and `chunk-{i}`, while dense uses the filename and header. | `scripts/index_regulatory_corpus.py`, `api/documents.py:216-224`, `hybrid_retriever.py:233-256` | Relevance judging cannot rely on exact source/section alone. Targets therefore also match on keywords (text contains the keywords) and on `chunk_index` (text fingerprint). |
| Tests use in-memory sqlite, `Base.metadata.create_all`, `app.dependency_overrides[get_db]`, and `patch("app.api.X.LLMRouter.generate", AsyncMock)`. CI uses `DATABASE_URL=sqlite+aiosqlite:///./ci_test.db`, a file with **no tables**. There are no API keys. | `tests/test_router_guardrails.py`, `.github/workflows/ci.yml` | Telemetry and runner DB writes use a module-level `async_session_maker` that tests monkeypatch. Telemetry must **never raise**. |
| `tests/test_router_guardrails.py::test_query_clean_question_passes_input_rail` patches `retrieve` to raise `RuntimeError` and expects it to propagate. | line 141 | The instrumentation must re-raise the original exception. |
| Some router tests build `LLMRouter(nvidia=MagicMock(), gemini=MagicMock())`. | `tests/test_stress_llm_routing.py` | `getattr(mock, "last_generation_model")` returns a MagicMock. Model resolution must check `isinstance(x, str)`. |
| The frontend calls `/api/...`, which Vite and Vercel rewrite to backend routes with no prefix. Timestamps are naive UTC with no `Z`. | `lib/http.ts`, `vite.config.ts`, `models/user.py:_utc_now` | New routes live under `/rag/...`. The frontend must parse timestamps as UTC. |

---

## 1. Architecture

```
ONLINE (every real RAG call)                          OFFLINE (golden set)
/query (SSE) ─┐                                       rag_eval_cases (tenant CRUD + 22 CBUAE defaults)
/regulatory/search ─┤ RagTraceRecorder                     │
              │  stage timers + RetrievalDiagnostics       ▼  POST /rag/eval/runs (modes × top_k × gen?)
              │  + LLMRouter.call_log                  BackgroundTasks → runner.execute_run_group
              │  + masked query (egress-checked)           │ per case: mask → egress → HybridRetriever(mode)
              ▼                                            │  → relevance (metrics.py) → [generate → judge]
         rag_traces ◄── rag_feedback (👍/👎 per user)      ▼
              │                                        rag_eval_runs (+aggregates) / rag_eval_results
              ▼
GET /rag/telemetry/dashboard, /rag/traces[/id]       GET /rag/eval/runs[/id][/results]
                    └───────────── RagPerformanceView (frontend) ─────────────┘
```

Pure maths lives in `services/evaluation/metrics.py` (IR metrics, text overlap, percentiles, score normalisation) and `services/evaluation/dashboard.py` (trace-row aggregation). Neither module does I/O.

---

## 2. Shared contract (frozen before either WP starts)

### 2.1 General rules
- Base path: backend `/rag/...`; frontend `apiFetch('/rag/...')`.
- Auth: Bearer JWT on everything. A missing or invalid token returns 401. Every query filters by `tenant_id`. A resource belonging to another tenant returns **404**.
- Errors use the FastAPI shape `{"detail": string | [...]}`. Status codes: 400 (business rule), 404, 409 (conflict), 422 (validation).
- Timestamps are **naive UTC ISO-8601 without a zone suffix**, e.g. `"2026-09-23T10:15:02.123456"`. The frontend must parse them with `new Date(ts.endsWith('Z') ? ts : ts + 'Z')`.
- Rates are fractions from 0 to 1. Latencies are milliseconds (float). Any metric may be `null` when there is no data.
- UUIDs are strings.
- Enumerations:
  - `RetrievalMode = "dense" | "bm25" | "hybrid" | "hybrid_rerank"` (`hybrid_rerank` is production)
  - `RagWindow = "24h" | "7d" | "30d" | "90d"`
  - `RagEndpoint = "query" | "regulatory_search"`
  - `TraceStatus = "ok" | "error" | "blocked" | "cancelled"`
  - `EvalRunStatus = "pending" | "running" | "completed" | "failed" | "cancelled"`
  - `JudgeMode = "auto" | "deterministic"`
  - `FeedbackTag = "irrelevant_sources" | "wrong_citation" | "hallucination" | "incomplete" | "outdated" | "too_slow" | "other"`
  - `StageName = "masking" | "dense" | "bm25" | "fusion" | "rerank" | "retrieval" | "generation" | "ttft" | "total"`
  - `ScoreKind = "rerank_nvidia" | "rerank_gemini" | "rerank" | "rrf" | "dense" | "bm25"`

### 2.2 Changes to existing endpoints
1. **`POST /query` (SSE)** gets a new event, emitted immediately after `session_id` and before `citations`:
   `data: {"type": "trace", "content": "<trace uuid>"}`
   Full order: `session_id` → `trace` → `citations` → `token`* → `suggestedActions` → `done`, or `error` at any point. The trace row is saved **before** `done` is sent (it is written in the generator's `finally`, which runs before `sse_stream` emits `done`).
2. **`POST /regulatory/search`** response gains `"trace_id": "<uuid>" | null`:
   `{"answer": "...", "citations": [...], "trace_id": "6f1c…"}`

### 2.3 Telemetry endpoints

| # | Method and path | Query / body | Response |
|---|---|---|---|
| T1 | `GET /rag/telemetry/dashboard` | `window: RagWindow = "7d"`, `endpoint: "all" \| RagEndpoint = "all"` | `RagDashboard` |
| T2 | `GET /rag/traces` | `window = "7d"`, `endpoint = "all"`, `status: "all" \| TraceStatus = "all"`, `mine: bool = false`, `limit: 1..100 = 25`, `offset: >=0 = 0` | `RagTraceList` (sorted `created_at` desc) |
| T3 | `GET /rag/traces/{trace_id}` | – | `RagTraceDetail` (404 if not in tenant) |
| T4 | `POST /rag/feedback` | `RagFeedbackInput` | 200 `RagFeedbackRecord`. Upserts one vote per (trace, user). 404 if the trace is not in the tenant. 422 on a bad rating or tag. |
| T5 | `DELETE /rag/feedback/{trace_id}` | – | 204. Removes **my** vote. 404 if I have not voted. |

Dashboard rules:
- `from_ts` is the aligned start of the first bucket. For `24h` that is the start of the hour 23 hours before the current hour, giving 24 hourly buckets. For N days it is midnight N−1 days ago, giving N daily buckets.
- KPIs and the timeseries use the same row set, so they always agree.
- Buckets are zero-filled.
- Latency percentiles only count `status == "ok"` traces.
- `sampled = true` if more than 20,000 traces fell in the window; only the newest 20,000 are aggregated.
- `stages` always has 9 entries in this order: masking, dense, bm25, fusion, rerank, retrieval, generation, ttft, total. `kind` is `"component"` for masking, dense, bm25, fusion, rerank and generation, and `"composite"` for the others.

### 2.4 Evaluation endpoints

| # | Method and path | Body / query | Response |
|---|---|---|---|
| E1 | `GET /rag/eval/cases` | `include_inactive: bool = true` | `EvalCaseList`. **Lazily seeds the 22 default CBUAE cases** when the tenant has no cases at all. Ordering: defaults by `default_key`, then custom cases by `created_at`. |
| E2 | `POST /rag/eval/cases` | `EvalCaseInput` | 201 `EvalCase`. Returns 400 if the input guardrails flag the question (jailbreak or injection). Returns 404 if `document_id` is not in the tenant. Returns 422 on validation errors. |
| E3 | `PATCH /rag/eval/cases/{case_id}` | partial `EvalCaseInput` (sending `document_id: null` clears it) | 200 `EvalCase` |
| E4 | `DELETE /rag/eval/cases/{case_id}` | – | 204 |
| E5 | `POST /rag/eval/cases/restore-defaults` | – | 200 `{"inserted": int, "total": int}`. Inserts only default keys that are missing. |
| E6 | `POST /rag/eval/runs` | `EvalRunCreateInput` | **202** `EvalRunCreateResponse`. Creates one run per mode (same `group_id`), run in sequence in the background. Returns 400 when there are no active cases, `case_ids` are unknown or inactive, or there are more than 200 cases. Returns 409 when the tenant already has a pending or running run. |
| E7 | `GET /rag/eval/runs` | `limit: 1..100 = 20`, `offset = 0` | `EvalRunList` (`created_at` desc) |
| E8 | `GET /rag/eval/runs/{run_id}` | – | `EvalRunDetail` |
| E9 | `GET /rag/eval/runs/{run_id}/results` | – | `EvalRunResults` (ordered by `position`) |
| E10 | `POST /rag/eval/runs/{run_id}/cancel` | – | 200 `EvalRunSummary`. Returns 409 if the run has already finished. |
| E11 | `DELETE /rag/eval/runs/{run_id}` | – | 204. Returns 409 while pending or running. |

E7, E8 and E6 first reconcile stale runs: any run that is pending or running and whose `heartbeat_at` is more than 10 minutes old is set to `failed` with `error_message = "Run interrupted (worker restart or timeout)"`.

### 2.5 TypeScript contract (`frontend/src/lib/ragTypes.ts` must match; backend Pydantic must match field-for-field)

```ts
/** Naive UTC ISO-8601 (no zone suffix). Parse with parseUtc(). */
export type UtcTimestamp = string;
export type RagWindow = '24h' | '7d' | '30d' | '90d';
export type RagEndpoint = 'query' | 'regulatory_search';
export type RagEndpointFilter = 'all' | RagEndpoint;
export type TraceStatus = 'ok' | 'error' | 'blocked' | 'cancelled';
export type TraceStatusFilter = 'all' | TraceStatus;
export type RetrievalMode = 'dense' | 'bm25' | 'hybrid' | 'hybrid_rerank';
export type JudgeMode = 'auto' | 'deterministic';
export type EvalRunStatus = 'pending' | 'running' | 'completed' | 'failed' | 'cancelled';
export type FeedbackTag = 'irrelevant_sources' | 'wrong_citation' | 'hallucination' | 'incomplete' | 'outdated' | 'too_slow' | 'other';
export type StageName = 'masking' | 'dense' | 'bm25' | 'fusion' | 'rerank' | 'retrieval' | 'generation' | 'ttft' | 'total';
export type ScoreKind = 'rerank_nvidia' | 'rerank_gemini' | 'rerank' | 'rrf' | 'dense' | 'bm25';

export interface RagKpis {
  total_requests: number; ok_count: number; error_count: number; blocked_count: number; cancelled_count: number;
  error_rate: number | null; blocked_rate: number | null;
  llm_fallback_rate: number | null; rerank_fallback_rate: number | null; dense_empty_rate: number | null;
  p50_total_ms: number | null; p95_total_ms: number | null; p50_ttft_ms: number | null; p95_ttft_ms: number | null;
  avg_top_score_norm: number | null; avg_groundedness: number | null;
  citation_rate: number | null; avg_citations: number | null;
  feedback_count: number; satisfaction_rate: number | null;
  est_prompt_tokens: number; est_completion_tokens: number;
}
export interface RagStageLatency { stage: StageName; kind: 'component' | 'composite'; count: number; p50_ms: number | null; p95_ms: number | null; avg_ms: number | null; }
export interface RagEndpointBreakdown { endpoint: RagEndpoint; count: number; error_rate: number | null; p50_total_ms: number | null; p95_total_ms: number | null; avg_groundedness: number | null; satisfaction_rate: number | null; }
export interface RagProviderShare { provider: string; model: string; count: number; share: number; }
export interface RagScoreKindStat { kind: ScoreKind; count: number; avg_top_score: number | null; avg_top_score_norm: number | null; }
export interface RagTimeseriesPoint {
  bucket_start: UtcTimestamp; count: number; ok_count: number; error_count: number; blocked_count: number; cancelled_count: number;
  fallback_count: number; p50_total_ms: number | null; p95_total_ms: number | null; avg_groundedness: number | null;
  thumbs_up: number; thumbs_down: number;
}
export interface RagFeedbackTagCount { tag: FeedbackTag; count: number; }
export interface RagFeedbackItem { id: string; trace_id: string; rating: 1 | -1; comment: string | null; tags: FeedbackTag[]; endpoint: RagEndpoint | null; query_masked: string | null; created_at: UtcTimestamp; }
export interface RagFeedbackSummary { total: number; thumbs_up: number; thumbs_down: number; satisfaction_rate: number | null; tag_counts: RagFeedbackTagCount[]; recent: RagFeedbackItem[]; /* max 10, newest first */ }
export interface RagDashboard {
  window: RagWindow; endpoint: RagEndpointFilter; from_ts: UtcTimestamp; to_ts: UtcTimestamp; bucket: 'hour' | 'day'; sampled: boolean;
  kpis: RagKpis; stages: RagStageLatency[]; by_endpoint: RagEndpointBreakdown[]; providers: RagProviderShare[];
  score_kinds: RagScoreKindStat[]; timeseries: RagTimeseriesPoint[]; feedback: RagFeedbackSummary;
}
export interface RagTraceListItem {
  id: string; created_at: UtcTimestamp; endpoint: RagEndpoint; status: TraceStatus; query_masked: string | null; document_id: string | null;
  retrieval_mode: RetrievalMode; total_ms: number | null; retrieval_ms: number | null; generation_ms: number | null; ttft_ms: number | null;
  citation_count: number; answer_citation_count: number; top_score: number | null; top_score_norm: number | null; score_kind: ScoreKind | null;
  groundedness: number | null; provider: string | null; model: string | null; llm_fallback_used: boolean;
  guardrail_reason: string | null; error_stage: string | null; feedback_up: number; feedback_down: number;
}
export interface RagTraceList { total: number; limit: number; offset: number; items: RagTraceListItem[]; }
export interface RagRetrievedScore { rank: number; source: string; section: string; score: number; retrieval_method: string; }
export interface RagLlmCall { method: 'generate' | 'generate_stream' | 'embed' | 'rerank'; provider: string; model: string; latency_ms: number; success: boolean; attempt: number; error_type: string | null; }
export interface RagTraceFeedbackEntry { id: string; rating: 1 | -1; comment: string | null; tags: FeedbackTag[]; created_at: UtcTimestamp; is_mine: boolean; }
export interface RagTraceDetail extends RagTraceListItem {
  session_id: string | null; chat_message_id: string | null; document_filename: string | null; top_k: number; query_chars: number;
  answer_preview: string | null;
  masking_ms: number | null; dense_ms: number | null; bm25_ms: number | null; fusion_ms: number | null; rerank_ms: number | null;
  dense_count: number; bm25_count: number; fused_count: number; reranked_count: number; mean_score: number | null;
  rerank_applied: boolean; rerank_fallback: boolean; dense_empty: boolean;
  scores: RagRetrievedScore[]; fused_scores: RagRetrievedScore[]; llm_calls: RagLlmCall[];
  est_prompt_tokens: number | null; est_completion_tokens: number | null;
  guardrail_blocked: boolean; output_guardrail_reason: string | null; error_type: string | null;
  feedback: RagTraceFeedbackEntry[]; my_rating: 1 | -1 | null;
}
export interface RagFeedbackInput { trace_id: string; rating: 1 | -1; comment?: string | null; tags?: FeedbackTag[]; }
export interface RagFeedbackRecord { id: string; trace_id: string; rating: 1 | -1; comment: string | null; tags: FeedbackTag[]; created_at: UtcTimestamp; updated_at: UtcTimestamp; }

export interface EvalExpectedRef { source: string | null; section: string | null; keywords: string[]; min_keyword_hits: number | null; chunk_index: number | null; }
export interface EvalCase {
  id: string; question: string; reference_answer: string | null; document_id: string | null; document_filename: string | null;
  expected_refs: EvalExpectedRef[]; origin: 'default' | 'custom'; default_key: string | null; is_active: boolean;
  created_at: UtcTimestamp; updated_at: UtcTimestamp;
}
export interface EvalCaseList { total: number; cases: EvalCase[]; }
export interface EvalCaseInput { question: string; reference_answer?: string | null; document_id?: string | null; expected_refs: Array<Partial<EvalExpectedRef>>; is_active?: boolean; }
export interface RestoreDefaultsResult { inserted: number; total: number; }
export interface EvalRunCreateInput { modes: RetrievalMode[]; top_k: number; include_generation: boolean; judge: JudgeMode; case_ids?: string[] | null; label?: string | null; }
export interface EvalRunMetrics {
  hit_rate: number | null; recall: number | null; precision: number | null; mrr: number | null; ndcg: number | null;
  faithfulness: number | null; answer_relevance: number | null; answer_correctness: number | null;
  p50_latency_ms: number | null; p95_latency_ms: number | null;
}
export interface EvalRunSummary {
  id: string; group_id: string; label: string | null; status: EvalRunStatus; mode: RetrievalMode; top_k: number;
  include_generation: boolean; judge: JudgeMode; total_cases: number; completed_cases: number; failed_cases: number;
  progress: number; metrics: EvalRunMetrics; error_message: string | null;
  created_at: UtcTimestamp; started_at: UtcTimestamp | null; finished_at: UtcTimestamp | null;
}
export interface EvalRunCreateResponse { group_id: string; estimated_llm_calls: number; runs: EvalRunSummary[]; }
export interface EvalRunList { total: number; runs: EvalRunSummary[]; }
export interface EvalMetricCurves { k: number[]; hit: number[]; recall: number[]; precision: number[]; ndcg: number[]; }
export interface EvalJudgeBreakdown { llm: number; deterministic: number; none: number; }
export interface EvalDegradedCounts { dense_empty: number; rerank_fallback: number; unresolved_chunk_targets: number; }
export interface EvalRunDetail extends EvalRunSummary {
  curves: EvalMetricCurves | null; judge_breakdown: EvalJudgeBreakdown; degraded: EvalDegradedCounts;
  case_ids: string[]; generation_temperature: number | null;
}
export interface EvalRetrievedItem { rank: number; source: string; section: string; score: number; retrieval_method: string; relevant: boolean; matched_targets: number[]; snippet: string; }
export interface EvalCaseDiagnostics {
  mode: RetrievalMode; dense_ms: number | null; bm25_ms: number | null; fusion_ms: number | null; rerank_ms: number | null;
  dense_count: number; bm25_count: number; fused_count: number; final_count: number;
  rerank_applied: boolean; rerank_fallback: boolean; dense_empty: boolean; unresolved_chunk_targets: number;
}
export interface EvalCaseResult {
  id: string; case_id: string; position: number; status: 'ok' | 'error'; question_masked: string | null; document_id: string | null;
  n_targets: number; targets_matched: number; hit: boolean | null; first_relevant_rank: number | null;
  recall: number | null; precision: number | null; reciprocal_rank: number | null; ndcg: number | null;
  retrieved: EvalRetrievedItem[]; answer: string | null;
  faithfulness: number | null; answer_relevance: number | null; answer_correctness: number | null;
  judge_method: 'llm' | 'deterministic' | 'none'; judge_rationale: string | null;
  retrieval_ms: number | null; generation_ms: number | null; judge_ms: number | null;
  diagnostics: EvalCaseDiagnostics | null; error_type: string | null; error_stage: string | null; created_at: UtcTimestamp;
}
export interface EvalRunResults { run_id: string; results: EvalCaseResult[]; }
```

Example request and response for E6:
```json
POST /rag/eval/runs
{"modes": ["bm25", "hybrid", "hybrid_rerank"], "top_k": 5, "include_generation": true, "judge": "auto", "case_ids": null, "label": "Baseline Sept"}
→ 202 {"group_id": "…", "estimated_llm_calls": 198, "runs": [{"id": "…", "group_id": "…", "status": "pending", "mode": "bm25", "top_k": 5, "total_cases": 22, "completed_cases": 0, "failed_cases": 0, "progress": 0.0, "metrics": {"hit_rate": null, …}, …}, …]}
```
`estimated_llm_calls` is the sum, over modes and cases, of:
- 1 embed call if the mode uses dense
- 1 rerank call if the mode is `hybrid_rerank`
- 1 generation call if `include_generation`
- 1 judge call if `include_generation` and `judge == "auto"`

---

## 3. WP-BACKEND

### 3.1 File map

**New files:**
- `backend/app/models/rag_eval.py`
- `backend/app/schemas/rag_eval.py`
- `backend/app/services/evaluation/__init__.py` (a module docstring only, no imports, to avoid import cycles)
- `backend/app/services/evaluation/metrics.py` (pure)
- `backend/app/services/evaluation/dashboard.py` (pure aggregation)
- `backend/app/services/evaluation/telemetry.py` (recorder, persistence, telemetry queries)
- `backend/app/services/evaluation/prompts.py` (shared prompt constants, context formatter, judge prompt)
- `backend/app/services/evaluation/judge.py` (LLM judge with deterministic fallback)
- `backend/app/services/evaluation/default_dataset.py`
- `backend/app/services/evaluation/runner.py`
- `backend/app/api/rag_eval.py`
- `backend/alembic/versions/d4e5f6a7b8c9_add_rag_telemetry_and_eval_tables.py`
- Tests (see §3.15)

**Edits to existing files:**
- `app/schemas/retrieval.py`
- `app/services/retrieval/hybrid_retriever.py`
- `app/services/retrieval/reranker.py`
- `app/services/llm/router.py`
- `app/services/llm/nvidia_provider.py`
- `app/api/query.py`
- `app/api/regulatory.py`
- `app/schemas/regulatory.py`
- `app/models/__init__.py`
- `app/main.py`
- `app/config.py`

Nothing else changes. `alembic/env.py` needs no change: it imports `app.models`, whose `__init__` will import `rag_eval`, so `Base.metadata` includes the new tables.

### 3.2 `app/schemas/retrieval.py` (additive)
```python
import enum

class RetrievalMode(str, enum.Enum):
    """Retrieval pipeline configuration (ablation modes)."""
    DENSE = "dense"
    BM25 = "bm25"
    HYBRID = "hybrid"
    HYBRID_RERANK = "hybrid_rerank"   # production default

class CandidatePreview(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    source: str
    section: str
    score: float
    retrieval_method: str

class RetrievalDiagnostics(BaseModel):
    """Per-stage timings, counts and degradation flags for one retrieval."""
    model_config = ConfigDict(from_attributes=True)
    mode: RetrievalMode
    dense_ms: float | None = None
    bm25_ms: float | None = None
    fusion_ms: float | None = None
    rerank_ms: float | None = None
    dense_count: int = 0
    bm25_count: int = 0
    fused_count: int = 0
    final_count: int = 0
    rerank_applied: bool = False
    rerank_fallback: bool = False
    dense_empty: bool = False
    fused_preview: list[CandidatePreview] = []   # top-10 pre-rerank, no text

# RetrievalResult: add one field (default keeps every existing caller and mock valid)
    diagnostics: RetrievalDiagnostics | None = None
```

### 3.3 Retrieval hooks

**`reranker.py`** adds `rerank_with_status`. It contains the current logic moved over unchanged, but returns `(candidates, fallback_used)`:
- Empty input returns `([], False)`.
- An API exception returns `(copies of candidates[:top_n], True)`.
- Empty results return `(…, True)`.
- If there are no valid indices, it returns `(…, True)`.
- On success it returns `(sorted[:top_n], False)`.

`rerank()` becomes `reranked, _ = await self.rerank_with_status(...); return reranked`. Its signature does not change.

**`hybrid_retriever.py`:**
- Move the BM25 block (lines 216-257) into `async def _bm25_candidates(self, query, tenant_id, document_id, db, top_n: int) -> list[RetrievalCandidate]`. It must behave identically.
- Use `time.perf_counter()` and a module helper `_elapsed_ms(t0) -> float`.
- New signature. Both new parameters have defaults, so existing callers are unchanged:
```python
async def retrieve(self, query: str, tenant_id: uuid.UUID, document_id: Optional[uuid.UUID], db: AsyncSession,
                   top_k: int = 6, mode: RetrievalMode = RetrievalMode.HYBRID_RERANK,
                   candidate_pool: int = 20) -> RetrievalResult:
    start = time.perf_counter()
    use_dense = mode in (RetrievalMode.DENSE, RetrievalMode.HYBRID, RetrievalMode.HYBRID_RERANK)
    use_bm25 = mode in (RetrievalMode.BM25, RetrievalMode.HYBRID, RetrievalMode.HYBRID_RERANK)
    namespaces = ["cbuae-manuals"] + ([f"user-docs:{tenant_id}:{document_id}"] if document_id else [])
    dense_candidates, dense_ms = [], None
    if use_dense:
        t0 = time.perf_counter()
        try:
            dense_candidates = await self.dense_retriever.retrieve(query=query, namespaces=namespaces, top_k=candidate_pool)
        except Exception as exc:
            logger.error(f"Dense retrieval failed: {exc}", exc_info=True)
        dense_ms = _elapsed_ms(t0)
    bm25_candidates, bm25_ms = [], None
    if use_bm25:
        t0 = time.perf_counter()
        bm25_candidates = await self._bm25_candidates(query, tenant_id, document_id, db, candidate_pool)
        bm25_ms = _elapsed_ms(t0)
    fusion_ms = None
    if mode in (RetrievalMode.HYBRID, RetrievalMode.HYBRID_RERANK):
        t0 = time.perf_counter()
        fused = rrf_fuse([dense_candidates, bm25_candidates]) if (dense_candidates and bm25_candidates) \
                else (dense_candidates or bm25_candidates)
        fusion_ms = _elapsed_ms(t0)
    elif mode == RetrievalMode.DENSE:
        fused = dense_candidates
    else:
        fused = bm25_candidates
    rerank_ms, rerank_fallback = None, False
    if mode == RetrievalMode.HYBRID_RERANK and fused:
        t0 = time.perf_counter()
        final, rerank_fallback = await self.reranker.rerank_with_status(query=query, candidates=fused, top_n=top_k)
        rerank_ms = _elapsed_ms(t0)
    else:
        final = [c.model_copy() for c in fused[:top_k]]
    citations = [Citation(source=c.source, section=c.section, text=c.chunk_text, score=c.score,
                          retrieval_method=c.retrieval_method) for c in final]
    diagnostics = RetrievalDiagnostics(mode=mode, dense_ms=dense_ms, bm25_ms=bm25_ms, fusion_ms=fusion_ms,
        rerank_ms=rerank_ms, dense_count=len(dense_candidates), bm25_count=len(bm25_candidates),
        fused_count=len(fused), final_count=len(final),
        rerank_applied=(mode == RetrievalMode.HYBRID_RERANK and bool(fused) and not rerank_fallback),
        rerank_fallback=rerank_fallback, dense_empty=(use_dense and not dense_candidates),
        fused_preview=[CandidatePreview(source=c.source, section=c.section, score=c.score,
                                        retrieval_method=c.retrieval_method) for c in fused[:10]])
    return RetrievalResult(citations=citations, latency_ms=_elapsed_ms(start),
        retrieval_metadata={"dense_count": len(dense_candidates), "bm25_count": len(bm25_candidates),
                            "fused_count": len(fused), "reranked_count": len(final),
                            "mode": mode.value, "rerank_fallback": rerank_fallback},
        diagnostics=diagnostics)
```
In `hybrid_rerank` mode the output is identical to today's.

### 3.4 LLM router call log (`services/llm/router.py`, `nvidia_provider.py`)
- `router.py`: import `NVIDIA_EMBEDDING_MODEL, NVIDIA_RERANKING_MODEL` from the nvidia provider and `GEMINI_EMBEDDING_MODEL` from gemini. Add `from dataclasses import dataclass, asdict`.
```python
@dataclass(frozen=True)
class ProviderCallRecord:
    """One provider attempt made by the router (success or failure)."""
    method: str; provider: str; model: str; latency_ms: float; success: bool; attempt: int; error_type: str | None = None
    def to_dict(self) -> dict[str, Any]: return asdict(self)

_DEFAULT_MODELS: dict[tuple[str, str], str] = {
    ("nvidia", "generate"): NVIDIA_GENERATION_MODEL, ("nvidia", "generate_stream"): NVIDIA_GENERATION_MODEL,
    ("nvidia", "embed"): NVIDIA_EMBEDDING_MODEL, ("nvidia", "rerank"): NVIDIA_RERANKING_MODEL,
    ("gemini", "generate"): GEMINI_GENERATION_MODEL, ("gemini", "generate_stream"): GEMINI_GENERATION_MODEL,
    ("gemini", "embed"): GEMINI_EMBEDDING_MODEL, ("gemini", "rerank"): GEMINI_GENERATION_MODEL,
}
MAX_CALL_LOG = 200
```
- In `__init__`: `self.call_log: list[ProviderCallRecord] = []`.
- `_resolve_model(provider, method)`: for generate and generate_stream, use `getattr(self.providers[provider], "last_generation_model", None)` **only if `isinstance(value, str) and value`**. Otherwise use `_DEFAULT_MODELS.get(..., "unknown")`. This keeps MagicMock providers from breaking tests.
- `_record_call(method, provider, latency_ms, success, attempt, error=None)` appends a record while `len < MAX_CALL_LOG`. `error_type=type(error).__name__`. This method must never raise.
- `_execute_routed`: loop becomes `for attempt, provider_name in enumerate(candidates):`. Record `success=True` after a successful call, and `success=False` with the error in `except`. `generate_stream` gets the same treatment with method `"generate_stream"`.
- `nvidia_provider.py`: set `self.last_generation_model: str | None = None` in `__init__`. Set `self.last_generation_model = model` just before `return` in `generate`, and before `break` in `generate_stream`.

### 3.5 `app/models/rag_eval.py` (full)
```python
"""ORM models for RAG telemetry, user feedback and offline evaluation."""
from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (JSON, Boolean, DateTime, Float, ForeignKey, Index, Integer, SmallInteger, String, Text,
                        UniqueConstraint, Uuid)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base
from app.models.user import _utc_now


class TraceEndpoint(str, enum.Enum):
    """RAG surface that produced a trace."""
    QUERY = "query"
    REGULATORY_SEARCH = "regulatory_search"


class TraceStatus(str, enum.Enum):
    """Terminal outcome of a traced RAG request."""
    OK = "ok"
    ERROR = "error"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"


class EvalRunStatus(str, enum.Enum):
    """Lifecycle of an offline evaluation run."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class EvalCaseOrigin(str, enum.Enum):
    """Whether a golden case was seeded by the system or authored by the tenant."""
    DEFAULT = "default"
    CUSTOM = "custom"


class RagTrace(Base):
    """One instrumented RAG request. Stores the MASKED query only - never raw user text."""

    __tablename__ = "rag_traces"
    __table_args__ = (Index("ix_rag_traces_tenant_created", "tenant_id", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), index=True, nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    endpoint: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default=TraceStatus.OK.value, nullable=False)
    session_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    chat_message_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    document_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)  # no FK: docs can be deleted
    query_masked: Mapped[str | None] = mapped_column(Text, nullable=True)
    query_chars: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    answer_preview: Mapped[str | None] = mapped_column(Text, nullable=True)  # first 2000 chars of LLM output
    retrieval_mode: Mapped[str] = mapped_column(String(24), default="hybrid_rerank", nullable=False)
    top_k: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    masking_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    dense_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    bm25_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    fusion_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    rerank_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    retrieval_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    generation_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    ttft_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    total_ms: Mapped[float | None] = mapped_column(Float, nullable=True)

    dense_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    bm25_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    fused_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    reranked_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    citation_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    answer_citation_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    top_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    mean_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    top_score_norm: Mapped[float | None] = mapped_column(Float, nullable=True)
    score_kind: Mapped[str | None] = mapped_column(String(24), nullable=True)
    scores_json: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)
    fused_scores_json: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)
    rerank_applied: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    rerank_fallback: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    dense_empty: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    provider: Mapped[str | None] = mapped_column(String(32), nullable=True)
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    llm_fallback_used: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    llm_calls_json: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)
    est_prompt_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    est_completion_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    groundedness: Mapped[float | None] = mapped_column(Float, nullable=True)

    guardrail_blocked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    guardrail_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    output_guardrail_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_type: Mapped[str | None] = mapped_column(String(128), nullable=True)   # class name only
    error_stage: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utc_now, index=True, nullable=False)


class RagFeedback(Base):
    """Thumbs up/down (+ optional masked comment and tags) on a trace; one vote per user per trace."""

    __tablename__ = "rag_feedback"
    __table_args__ = (UniqueConstraint("trace_id", "user_id", name="uq_rag_feedback_trace_user"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), index=True, nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    trace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("rag_traces.id", ondelete="CASCADE"), index=True, nullable=False)
    chat_message_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    rating: Mapped[int] = mapped_column(SmallInteger, nullable=False)  # +1 / -1
    comment_masked: Mapped[str | None] = mapped_column(Text, nullable=True)
    tags_json: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utc_now, index=True, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utc_now, onupdate=_utc_now, nullable=False)


class RagEvalCase(Base):
    """A golden evaluation case (question + relevance targets + optional reference answer)."""

    __tablename__ = "rag_eval_cases"
    __table_args__ = (UniqueConstraint("tenant_id", "default_key", name="uq_rag_eval_cases_tenant_default_key"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), index=True, nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    reference_answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    expected_refs_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    document_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    origin: Mapped[str] = mapped_column(String(16), default=EvalCaseOrigin.CUSTOM.value, nullable=False)
    default_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utc_now, onupdate=_utc_now, nullable=False)


class RagEvalRun(Base):
    """One offline evaluation run (a single retrieval mode over a case snapshot)."""

    __tablename__ = "rag_eval_runs"
    __table_args__ = (Index("ix_rag_eval_runs_tenant_created", "tenant_id", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), index=True, nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    group_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), index=True, nullable=False)
    label: Mapped[str | None] = mapped_column(String(120), nullable=True)
    status: Mapped[str] = mapped_column(String(16), index=True, default=EvalRunStatus.PENDING.value, nullable=False)
    mode: Mapped[str] = mapped_column(String(24), nullable=False)
    top_k: Mapped[int] = mapped_column(Integer, nullable=False)
    include_generation: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    judge: Mapped[str] = mapped_column(String(16), default="auto", nullable=False)
    case_ids_json: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    total_cases: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    completed_cases: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failed_cases: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    hit_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    mean_recall: Mapped[float | None] = mapped_column(Float, nullable=True)
    mean_precision: Mapped[float | None] = mapped_column(Float, nullable=True)
    mrr: Mapped[float | None] = mapped_column(Float, nullable=True)
    mean_ndcg: Mapped[float | None] = mapped_column(Float, nullable=True)
    mean_faithfulness: Mapped[float | None] = mapped_column(Float, nullable=True)
    mean_answer_relevance: Mapped[float | None] = mapped_column(Float, nullable=True)
    mean_answer_correctness: Mapped[float | None] = mapped_column(Float, nullable=True)
    p50_latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    p95_latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    metrics_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)  # curves, judge_breakdown, degraded, generation_temperature
    error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utc_now, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class RagEvalResult(Base):
    """Per-case outcome inside an evaluation run."""

    __tablename__ = "rag_eval_results"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("rag_eval_runs.id", ondelete="CASCADE"), index=True, nullable=False)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), index=True, nullable=False)
    case_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), index=True, nullable=False)  # no FK: cases may be deleted later
    position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="ok", nullable=False)
    question_masked: Mapped[str | None] = mapped_column(Text, nullable=True)
    document_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    n_targets: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    targets_matched: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    hit: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    first_relevant_rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    recall: Mapped[float | None] = mapped_column(Float, nullable=True)
    precision: Mapped[float | None] = mapped_column(Float, nullable=True)
    reciprocal_rank: Mapped[float | None] = mapped_column(Float, nullable=True)
    ndcg: Mapped[float | None] = mapped_column(Float, nullable=True)
    relevances_json: Mapped[list[int] | None] = mapped_column(JSON, nullable=True)
    retrieved_json: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)
    answer_masked: Mapped[str | None] = mapped_column(Text, nullable=True)
    faithfulness: Mapped[float | None] = mapped_column(Float, nullable=True)
    answer_relevance: Mapped[float | None] = mapped_column(Float, nullable=True)
    answer_correctness: Mapped[float | None] = mapped_column(Float, nullable=True)
    judge_method: Mapped[str] = mapped_column(String(16), default="none", nullable=False)
    judge_rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    retrieval_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    generation_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    judge_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    diagnostics_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    error_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    error_stage: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utc_now, nullable=False)
```
Design decisions:
- Status, mode and endpoint are stored as `String` values rather than `SAEnum`. This avoids creating Postgres enum types in migrations and keeps the sqlite and Postgres behaviour identical.
- SQLite in tests does not enforce `ON DELETE CASCADE`. The delete endpoints therefore delete child rows explicitly.

`app/models/__init__.py`: add
`from app.models.rag_eval import RagTrace, RagFeedback, RagEvalCase, RagEvalRun, RagEvalResult, TraceEndpoint, TraceStatus, EvalRunStatus, EvalCaseOrigin`, and add each name to `__all__`.
**This is what makes `Base.metadata.create_all` in tests create the tables.** It works because tests import `app.main`, which imports `app.api.rag_eval`, which imports the models. The `__init__` import also covers Alembic autogenerate.

### 3.6 Migration: `backend/alembic/versions/d4e5f6a7b8c9_add_rag_telemetry_and_eval_tables.py`
```python
"""Add RAG telemetry, feedback and evaluation tables

Revision ID: d4e5f6a7b8c9
Revises: c7d8e9f0a1b2
Create Date: 2026-09-23 00:00:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'd4e5f6a7b8c9'
down_revision: Union[str, None] = 'c7d8e9f0a1b2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TRACE_MS = ('masking_ms', 'dense_ms', 'bm25_ms', 'fusion_ms', 'rerank_ms', 'retrieval_ms', 'generation_ms', 'ttft_ms', 'total_ms')
_TRACE_COUNTS = ('dense_count', 'bm25_count', 'fused_count', 'reranked_count', 'citation_count', 'answer_citation_count')
_RUN_METRICS = ('hit_rate', 'mean_recall', 'mean_precision', 'mrr', 'mean_ndcg', 'mean_faithfulness',
                'mean_answer_relevance', 'mean_answer_correctness', 'p50_latency_ms', 'p95_latency_ms')

def upgrade() -> None:
    op.create_table('rag_traces',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('tenant_id', sa.Uuid(), nullable=False),
        sa.Column('user_id', sa.Uuid(), nullable=False),
        sa.Column('endpoint', sa.String(length=32), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('session_id', sa.Uuid(), nullable=True),
        sa.Column('chat_message_id', sa.Uuid(), nullable=True),
        sa.Column('document_id', sa.Uuid(), nullable=True),
        sa.Column('query_masked', sa.Text(), nullable=True),
        sa.Column('query_chars', sa.Integer(), nullable=False),
        sa.Column('answer_preview', sa.Text(), nullable=True),
        sa.Column('retrieval_mode', sa.String(length=24), nullable=False),
        sa.Column('top_k', sa.Integer(), nullable=False),
        *[sa.Column(c, sa.Float(), nullable=True) for c in _TRACE_MS],
        *[sa.Column(c, sa.Integer(), nullable=False) for c in _TRACE_COUNTS],
        sa.Column('top_score', sa.Float(), nullable=True),
        sa.Column('mean_score', sa.Float(), nullable=True),
        sa.Column('top_score_norm', sa.Float(), nullable=True),
        sa.Column('score_kind', sa.String(length=24), nullable=True),
        sa.Column('scores_json', sa.JSON(), nullable=True),
        sa.Column('fused_scores_json', sa.JSON(), nullable=True),
        sa.Column('rerank_applied', sa.Boolean(), nullable=False),
        sa.Column('rerank_fallback', sa.Boolean(), nullable=False),
        sa.Column('dense_empty', sa.Boolean(), nullable=False),
        sa.Column('provider', sa.String(length=32), nullable=True),
        sa.Column('model', sa.String(length=128), nullable=True),
        sa.Column('llm_fallback_used', sa.Boolean(), nullable=False),
        sa.Column('llm_calls_json', sa.JSON(), nullable=True),
        sa.Column('est_prompt_tokens', sa.Integer(), nullable=True),
        sa.Column('est_completion_tokens', sa.Integer(), nullable=True),
        sa.Column('groundedness', sa.Float(), nullable=True),
        sa.Column('guardrail_blocked', sa.Boolean(), nullable=False),
        sa.Column('guardrail_reason', sa.String(length=64), nullable=True),
        sa.Column('output_guardrail_reason', sa.String(length=64), nullable=True),
        sa.Column('error_type', sa.String(length=128), nullable=True),
        sa.Column('error_stage', sa.String(length=32), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id']),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'))
    op.create_index(op.f('ix_rag_traces_tenant_id'), 'rag_traces', ['tenant_id'])
    op.create_index(op.f('ix_rag_traces_user_id'), 'rag_traces', ['user_id'])
    op.create_index(op.f('ix_rag_traces_endpoint'), 'rag_traces', ['endpoint'])
    op.create_index(op.f('ix_rag_traces_created_at'), 'rag_traces', ['created_at'])
    op.create_index('ix_rag_traces_tenant_created', 'rag_traces', ['tenant_id', 'created_at'])

    op.create_table('rag_feedback',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('tenant_id', sa.Uuid(), nullable=False),
        sa.Column('user_id', sa.Uuid(), nullable=False),
        sa.Column('trace_id', sa.Uuid(), nullable=False),
        sa.Column('chat_message_id', sa.Uuid(), nullable=True),
        sa.Column('rating', sa.SmallInteger(), nullable=False),
        sa.Column('comment_masked', sa.Text(), nullable=True),
        sa.Column('tags_json', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id']),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.ForeignKeyConstraint(['trace_id'], ['rag_traces.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('trace_id', 'user_id', name='uq_rag_feedback_trace_user'))
    op.create_index(op.f('ix_rag_feedback_tenant_id'), 'rag_feedback', ['tenant_id'])
    op.create_index(op.f('ix_rag_feedback_user_id'), 'rag_feedback', ['user_id'])
    op.create_index(op.f('ix_rag_feedback_trace_id'), 'rag_feedback', ['trace_id'])
    op.create_index(op.f('ix_rag_feedback_created_at'), 'rag_feedback', ['created_at'])

    op.create_table('rag_eval_cases',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('tenant_id', sa.Uuid(), nullable=False),
        sa.Column('created_by', sa.Uuid(), nullable=True),
        sa.Column('question', sa.Text(), nullable=False),
        sa.Column('reference_answer', sa.Text(), nullable=True),
        sa.Column('expected_refs_json', sa.JSON(), nullable=False),
        sa.Column('document_id', sa.Uuid(), nullable=True),
        sa.Column('origin', sa.String(length=16), nullable=False),
        sa.Column('default_key', sa.String(length=64), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id']),
        sa.ForeignKeyConstraint(['created_by'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('tenant_id', 'default_key', name='uq_rag_eval_cases_tenant_default_key'))
    op.create_index(op.f('ix_rag_eval_cases_tenant_id'), 'rag_eval_cases', ['tenant_id'])

    op.create_table('rag_eval_runs',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('tenant_id', sa.Uuid(), nullable=False),
        sa.Column('user_id', sa.Uuid(), nullable=False),
        sa.Column('group_id', sa.Uuid(), nullable=False),
        sa.Column('label', sa.String(length=120), nullable=True),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('mode', sa.String(length=24), nullable=False),
        sa.Column('top_k', sa.Integer(), nullable=False),
        sa.Column('include_generation', sa.Boolean(), nullable=False),
        sa.Column('judge', sa.String(length=16), nullable=False),
        sa.Column('case_ids_json', sa.JSON(), nullable=False),
        sa.Column('total_cases', sa.Integer(), nullable=False),
        sa.Column('completed_cases', sa.Integer(), nullable=False),
        sa.Column('failed_cases', sa.Integer(), nullable=False),
        *[sa.Column(c, sa.Float(), nullable=True) for c in _RUN_METRICS],
        sa.Column('metrics_json', sa.JSON(), nullable=True),
        sa.Column('error_message', sa.String(length=500), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('started_at', sa.DateTime(), nullable=True),
        sa.Column('finished_at', sa.DateTime(), nullable=True),
        sa.Column('heartbeat_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id']),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'))
    op.create_index(op.f('ix_rag_eval_runs_tenant_id'), 'rag_eval_runs', ['tenant_id'])
    op.create_index(op.f('ix_rag_eval_runs_user_id'), 'rag_eval_runs', ['user_id'])
    op.create_index(op.f('ix_rag_eval_runs_group_id'), 'rag_eval_runs', ['group_id'])
    op.create_index(op.f('ix_rag_eval_runs_status'), 'rag_eval_runs', ['status'])
    op.create_index('ix_rag_eval_runs_tenant_created', 'rag_eval_runs', ['tenant_id', 'created_at'])

    op.create_table('rag_eval_results',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('run_id', sa.Uuid(), nullable=False),
        sa.Column('tenant_id', sa.Uuid(), nullable=False),
        sa.Column('case_id', sa.Uuid(), nullable=False),
        sa.Column('position', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('question_masked', sa.Text(), nullable=True),
        sa.Column('document_id', sa.Uuid(), nullable=True),
        sa.Column('n_targets', sa.Integer(), nullable=False),
        sa.Column('targets_matched', sa.Integer(), nullable=False),
        sa.Column('hit', sa.Boolean(), nullable=True),
        sa.Column('first_relevant_rank', sa.Integer(), nullable=True),
        sa.Column('recall', sa.Float(), nullable=True),
        sa.Column('precision', sa.Float(), nullable=True),
        sa.Column('reciprocal_rank', sa.Float(), nullable=True),
        sa.Column('ndcg', sa.Float(), nullable=True),
        sa.Column('relevances_json', sa.JSON(), nullable=True),
        sa.Column('retrieved_json', sa.JSON(), nullable=True),
        sa.Column('answer_masked', sa.Text(), nullable=True),
        sa.Column('faithfulness', sa.Float(), nullable=True),
        sa.Column('answer_relevance', sa.Float(), nullable=True),
        sa.Column('answer_correctness', sa.Float(), nullable=True),
        sa.Column('judge_method', sa.String(length=16), nullable=False),
        sa.Column('judge_rationale', sa.Text(), nullable=True),
        sa.Column('retrieval_ms', sa.Float(), nullable=True),
        sa.Column('generation_ms', sa.Float(), nullable=True),
        sa.Column('judge_ms', sa.Float(), nullable=True),
        sa.Column('diagnostics_json', sa.JSON(), nullable=True),
        sa.Column('error_type', sa.String(length=128), nullable=True),
        sa.Column('error_stage', sa.String(length=32), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['run_id'], ['rag_eval_runs.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id']),
        sa.PrimaryKeyConstraint('id'))
    op.create_index(op.f('ix_rag_eval_results_run_id'), 'rag_eval_results', ['run_id'])
    op.create_index(op.f('ix_rag_eval_results_tenant_id'), 'rag_eval_results', ['tenant_id'])
    op.create_index(op.f('ix_rag_eval_results_case_id'), 'rag_eval_results', ['case_id'])

def downgrade() -> None:
    for name, table in [('ix_rag_eval_results_case_id', 'rag_eval_results'), ('ix_rag_eval_results_tenant_id', 'rag_eval_results'),
                        ('ix_rag_eval_results_run_id', 'rag_eval_results')]:
        op.drop_index(name, table_name=table)
    op.drop_table('rag_eval_results')
    for name in ('ix_rag_eval_runs_tenant_created', 'ix_rag_eval_runs_status', 'ix_rag_eval_runs_group_id',
                 'ix_rag_eval_runs_user_id', 'ix_rag_eval_runs_tenant_id'):
        op.drop_index(name, table_name='rag_eval_runs')
    op.drop_table('rag_eval_runs')
    op.drop_index('ix_rag_eval_cases_tenant_id', table_name='rag_eval_cases')
    op.drop_table('rag_eval_cases')
    for name in ('ix_rag_feedback_created_at', 'ix_rag_feedback_trace_id', 'ix_rag_feedback_user_id', 'ix_rag_feedback_tenant_id'):
        op.drop_index(name, table_name='rag_feedback')
    op.drop_table('rag_feedback')
    for name in ('ix_rag_traces_tenant_created', 'ix_rag_traces_created_at', 'ix_rag_traces_endpoint',
                 'ix_rag_traces_user_id', 'ix_rag_traces_tenant_id'):
        op.drop_index(name, table_name='rag_traces')
    op.drop_table('rag_traces')
```
To verify: `alembic upgrade head` then `alembic downgrade c7d8e9f0a1b2` against the docker Postgres. `alembic check` should report no drift, because the model `index=True` names match the `op.f(...)` names.

### 3.7 `app/schemas/rag_eval.py` (full; all models use `model_config = ConfigDict(from_attributes=True)`)
```python
from __future__ import annotations
import uuid
from datetime import datetime
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from app.schemas.retrieval import RetrievalMode

RagWindow = Literal["24h", "7d", "30d", "90d"]
EndpointFilter = Literal["all", "query", "regulatory_search"]
TraceStatusFilter = Literal["all", "ok", "error", "blocked", "cancelled"]
FeedbackTag = Literal["irrelevant_sources", "wrong_citation", "hallucination", "incomplete", "outdated", "too_slow", "other"]
JudgeMode = Literal["auto", "deterministic"]
RunStatus = Literal["pending", "running", "completed", "failed", "cancelled"]
StageName = Literal["masking", "dense", "bm25", "fusion", "rerank", "retrieval", "generation", "ttft", "total"]

class _Base(BaseModel):
    model_config = ConfigDict(from_attributes=True)

# ---- telemetry
class TelemetryKpis(_Base):
    total_requests: int; ok_count: int; error_count: int; blocked_count: int; cancelled_count: int
    error_rate: float | None; blocked_rate: float | None
    llm_fallback_rate: float | None; rerank_fallback_rate: float | None; dense_empty_rate: float | None
    p50_total_ms: float | None; p95_total_ms: float | None; p50_ttft_ms: float | None; p95_ttft_ms: float | None
    avg_top_score_norm: float | None; avg_groundedness: float | None
    citation_rate: float | None; avg_citations: float | None
    feedback_count: int; satisfaction_rate: float | None
    est_prompt_tokens: int; est_completion_tokens: int
class StageLatency(_Base):
    stage: StageName; kind: Literal["component", "composite"]; count: int
    p50_ms: float | None; p95_ms: float | None; avg_ms: float | None
class EndpointBreakdown(_Base):
    endpoint: Literal["query", "regulatory_search"]; count: int; error_rate: float | None
    p50_total_ms: float | None; p95_total_ms: float | None; avg_groundedness: float | None; satisfaction_rate: float | None
class ProviderShare(_Base):
    provider: str; model: str; count: int; share: float
class ScoreKindStat(_Base):
    kind: str; count: int; avg_top_score: float | None; avg_top_score_norm: float | None
class TimeseriesPoint(_Base):
    bucket_start: datetime; count: int; ok_count: int; error_count: int; blocked_count: int; cancelled_count: int
    fallback_count: int; p50_total_ms: float | None; p95_total_ms: float | None; avg_groundedness: float | None
    thumbs_up: int; thumbs_down: int
class FeedbackTagCount(_Base):
    tag: str; count: int
class FeedbackItem(_Base):
    id: uuid.UUID; trace_id: uuid.UUID; rating: int; comment: str | None; tags: list[str]
    endpoint: str | None; query_masked: str | None; created_at: datetime
class FeedbackSummary(_Base):
    total: int; thumbs_up: int; thumbs_down: int; satisfaction_rate: float | None
    tag_counts: list[FeedbackTagCount]; recent: list[FeedbackItem]
class RagDashboardResponse(_Base):
    window: RagWindow; endpoint: EndpointFilter; from_ts: datetime; to_ts: datetime
    bucket: Literal["hour", "day"]; sampled: bool
    kpis: TelemetryKpis; stages: list[StageLatency]; by_endpoint: list[EndpointBreakdown]
    providers: list[ProviderShare]; score_kinds: list[ScoreKindStat]; timeseries: list[TimeseriesPoint]
    feedback: FeedbackSummary
class RetrievedScore(_Base):
    rank: int; source: str; section: str; score: float; retrieval_method: str
class LlmCallInfo(_Base):
    method: str; provider: str; model: str; latency_ms: float; success: bool; attempt: int; error_type: str | None = None
class TraceListItem(_Base):
    id: uuid.UUID; created_at: datetime; endpoint: str; status: str; query_masked: str | None
    document_id: uuid.UUID | None; retrieval_mode: str
    total_ms: float | None; retrieval_ms: float | None; generation_ms: float | None; ttft_ms: float | None
    citation_count: int; answer_citation_count: int; top_score: float | None; top_score_norm: float | None
    score_kind: str | None; groundedness: float | None; provider: str | None; model: str | None
    llm_fallback_used: bool; guardrail_reason: str | None; error_stage: str | None
    feedback_up: int = 0; feedback_down: int = 0
class TraceListResponse(_Base):
    total: int; limit: int; offset: int; items: list[TraceListItem]
class TraceFeedbackEntry(_Base):
    id: uuid.UUID; rating: int; comment: str | None; tags: list[str]; created_at: datetime; is_mine: bool
class TraceDetailResponse(TraceListItem):
    session_id: uuid.UUID | None; chat_message_id: uuid.UUID | None; document_filename: str | None
    top_k: int; query_chars: int; answer_preview: str | None
    masking_ms: float | None; dense_ms: float | None; bm25_ms: float | None; fusion_ms: float | None; rerank_ms: float | None
    dense_count: int; bm25_count: int; fused_count: int; reranked_count: int; mean_score: float | None
    rerank_applied: bool; rerank_fallback: bool; dense_empty: bool
    scores: list[RetrievedScore]; fused_scores: list[RetrievedScore]; llm_calls: list[LlmCallInfo]
    est_prompt_tokens: int | None; est_completion_tokens: int | None
    guardrail_blocked: bool; output_guardrail_reason: str | None; error_type: str | None
    feedback: list[TraceFeedbackEntry]; my_rating: int | None
class FeedbackCreate(_Base):
    trace_id: uuid.UUID
    rating: Literal[1, -1]
    comment: str | None = Field(default=None, max_length=1000)
    tags: list[FeedbackTag] = Field(default_factory=list, max_length=7)
    # validator: strip comment; "" -> None; dedupe tags preserving order
class FeedbackResponse(_Base):
    id: uuid.UUID; trace_id: uuid.UUID; rating: int; comment: str | None; tags: list[str]
    created_at: datetime; updated_at: datetime

# ---- eval dataset
class ExpectedRef(_Base):
    source: str | None = Field(default=None, max_length=200)
    section: str | None = Field(default=None, max_length=300)
    keywords: list[str] = Field(default_factory=list, max_length=12)
    min_keyword_hits: int | None = Field(default=None, ge=1, le=12)
    chunk_index: int | None = Field(default=None, ge=0)
    # field_validator(source, section): strip; "" -> None
    # field_validator(keywords): strip each, drop empties, each <= 80 chars else ValueError, dedupe case-insensitively
    # model_validator(after): at least one of source/section/keywords/chunk_index -> else ValueError
    #   "expected_ref needs a source, section, keywords or chunk_index"
    #   min_keyword_hits requires keywords and must be <= len(keywords)
class EvalCaseCreate(_Base):
    question: str = Field(min_length=5, max_length=1000)
    reference_answer: str | None = Field(default=None, max_length=4000)
    document_id: uuid.UUID | None = None
    expected_refs: list[ExpectedRef] = Field(min_length=1, max_length=10)
    is_active: bool = True
    # model_validator(after): any ref.chunk_index set while document_id is None -> ValueError
class EvalCaseUpdate(_Base):
    question: str | None = Field(default=None, min_length=5, max_length=1000)
    reference_answer: str | None = Field(default=None, max_length=4000)
    document_id: uuid.UUID | None = None
    expected_refs: list[ExpectedRef] | None = Field(default=None, min_length=1, max_length=10)
    is_active: bool | None = None
    # endpoint uses payload.model_fields_set to distinguish "omitted" from explicit null;
    # re-validate the chunk_index/document_id rule on the MERGED state (422 on violation)
class EvalCaseResponse(_Base):
    id: uuid.UUID; question: str; reference_answer: str | None; document_id: uuid.UUID | None
    document_filename: str | None; expected_refs: list[ExpectedRef]
    origin: Literal["default", "custom"]; default_key: str | None; is_active: bool
    created_at: datetime; updated_at: datetime
class EvalCaseListResponse(_Base):
    total: int; cases: list[EvalCaseResponse]
class RestoreDefaultsResponse(_Base):
    inserted: int; total: int

# ---- eval runs
class EvalRunCreate(_Base):
    modes: list[RetrievalMode] = Field(default_factory=lambda: [RetrievalMode.HYBRID_RERANK], min_length=1, max_length=4)
    top_k: int = Field(default=5, ge=1, le=20)
    include_generation: bool = False
    judge: JudgeMode = "auto"
    case_ids: list[uuid.UUID] | None = Field(default=None, max_length=200)
    label: str | None = Field(default=None, max_length=120)
    # field_validator(modes): dedupe preserving order
class EvalRunMetrics(_Base):
    hit_rate: float | None = None; recall: float | None = None; precision: float | None = None
    mrr: float | None = None; ndcg: float | None = None; faithfulness: float | None = None
    answer_relevance: float | None = None; answer_correctness: float | None = None
    p50_latency_ms: float | None = None; p95_latency_ms: float | None = None
class EvalRunSummary(_Base):
    id: uuid.UUID; group_id: uuid.UUID; label: str | None; status: RunStatus; mode: RetrievalMode; top_k: int
    include_generation: bool; judge: JudgeMode; total_cases: int; completed_cases: int; failed_cases: int
    progress: float; metrics: EvalRunMetrics; error_message: str | None
    created_at: datetime; started_at: datetime | None; finished_at: datetime | None
class EvalRunCreateResponse(_Base):
    group_id: uuid.UUID; estimated_llm_calls: int; runs: list[EvalRunSummary]
class EvalRunListResponse(_Base):
    total: int; runs: list[EvalRunSummary]
class MetricCurves(_Base):
    k: list[int]; hit: list[float]; recall: list[float]; precision: list[float]; ndcg: list[float]
class JudgeBreakdown(_Base):
    llm: int = 0; deterministic: int = 0; none: int = 0
class DegradedCounts(_Base):
    dense_empty: int = 0; rerank_fallback: int = 0; unresolved_chunk_targets: int = 0
class EvalRunDetail(EvalRunSummary):
    curves: MetricCurves | None; judge_breakdown: JudgeBreakdown; degraded: DegradedCounts
    case_ids: list[uuid.UUID]; generation_temperature: float | None
class RetrievedItemResult(_Base):
    rank: int; source: str; section: str; score: float; retrieval_method: str
    relevant: bool; matched_targets: list[int]; snippet: str
class EvalCaseDiagnostics(_Base):
    mode: RetrievalMode; dense_ms: float | None; bm25_ms: float | None; fusion_ms: float | None; rerank_ms: float | None
    dense_count: int; bm25_count: int; fused_count: int; final_count: int
    rerank_applied: bool; rerank_fallback: bool; dense_empty: bool; unresolved_chunk_targets: int = 0
class EvalCaseResultResponse(_Base):
    id: uuid.UUID; case_id: uuid.UUID; position: int; status: Literal["ok", "error"]
    question_masked: str | None; document_id: uuid.UUID | None; n_targets: int; targets_matched: int
    hit: bool | None; first_relevant_rank: int | None; recall: float | None; precision: float | None
    reciprocal_rank: float | None; ndcg: float | None; retrieved: list[RetrievedItemResult]
    answer: str | None; faithfulness: float | None; answer_relevance: float | None; answer_correctness: float | None
    judge_method: Literal["llm", "deterministic", "none"]; judge_rationale: str | None
    retrieval_ms: float | None; generation_ms: float | None; judge_ms: float | None
    diagnostics: EvalCaseDiagnostics | None; error_type: str | None; error_stage: str | None; created_at: datetime
class EvalRunResultsResponse(_Base):
    run_id: uuid.UUID; results: list[EvalCaseResultResponse]
```
Also edit `app/schemas/regulatory.py`: add `trace_id: uuid.UUID | None = None` to `RegulatoryResponse` (`uuid` is already imported there).

### 3.8 `services/evaluation/metrics.py` (pure; no I/O, no app imports except stdlib)
Exact definitions. These are the source of truth for the tests.
```python
STOPWORDS: frozenset[str]   # ~120 common English words (copy the list from guardrails/actions.ENGLISH_STOP_WORDS, do NOT import it - keeps module dependency-free)
_TOKEN_RE = re.compile(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?|[a-z][a-z0-9_\-]*")   # preserves 1,250,000 (AGENTS rule 10)
_DASHES = dict.fromkeys(map(ord, "‐‑‒–—―"), "-")
_CITATION_RE = re.compile(r"\[Source:\s*[^\]]+\]", re.IGNORECASE)

def normalize_text(text: str) -> str            # translate dashes, lowercase, collapse whitespace, strip
def text_fingerprint(text: str) -> str          # sha256 hex of normalize_text(text)
def section_matches(expected: str, actual: str) -> bool
    # e = normalize_text(expected); a = normalize_text(actual); True if a == e, or a.startswith(e) AND the char
    # right after the prefix is not alphanumeric (so "Section 1" does NOT match "Section 10 - ...")
def keyword_hits(text: str, keywords: Sequence[str]) -> int   # count of normalize_text(kw) substrings in normalize_text(text)
def required_keyword_hits(keywords: Sequence[str], min_hits: int | None) -> int
    # min(len(keywords), min_hits) if min_hits else max(1, ceil(0.6 * len(keywords)))
@dataclass(frozen=True)
class RelevanceTarget: source: str | None = None; section: str | None = None; keywords: tuple[str, ...] = ()
                       min_keyword_hits: int | None = None; text_hash: str | None = None
@dataclass(frozen=True)
class RetrievedItem: source: str; section: str; text: str
def target_matches(target: RelevanceTarget, item: RetrievedItem) -> bool
    # (1) text_hash and text_fingerprint(item.text) == text_hash
    # (2) ref match: (source or section set) and (source is None or normalize_text(source)==normalize_text(item.source))
    #     and (section is None or section_matches(section, item.section))
    # (3) keywords and keyword_hits(item.text, keywords) >= required_keyword_hits(...)
    # -> any of the three
def judge_relevance(items: Sequence[RetrievedItem], targets: Sequence[RelevanceTarget]) -> tuple[list[int], list[list[int]]]
    # relevances[i] = 1 if item i matches >=1 target; matched[i] = sorted target indices it matches
def _check_k(k: int) -> None       # ValueError if k < 1
def hit_at_k(relevances, k) -> float                 # 1.0 if any(relevances[:k]) else 0.0
def precision_at_k(relevances, k) -> float           # sum(relevances[:k]) / k   (denominator is k even if fewer items)
def recall_at_k(matched_per_rank, n_targets, k) -> float   # |union(matched[:k])| / n_targets ; 0.0 if n_targets == 0
def first_relevant_rank(relevances, k) -> int | None # 1-based
def reciprocal_rank_at_k(relevances, k) -> float     # 1/rank or 0.0
def dcg_at_k(relevances, k) -> float                 # sum(rel_i / log2(i + 1)) for i = 1..k (binary gains)
def ndcg_at_k(relevances, k, n_targets) -> float
    # R = min(k, max(n_targets, sum(relevances[:k]))); IDCG = sum(1/log2(i+1), i=1..R); 0.0 if R == 0; result <= 1.0
@dataclass(frozen=True)
class CaseRetrievalScores: hit: bool; first_relevant_rank: int | None; recall: float; precision: float
                           reciprocal_rank: float; ndcg: float; targets_matched: int
def score_case(relevances, matched_per_rank, n_targets, k) -> CaseRetrievalScores
def metric_curves(cases: Sequence[tuple[Sequence[int], Sequence[Sequence[int]], int]], k_max: int) -> dict[str, list[float]]
    # {"k":[1..k_max], "hit":[mean hit@k], "recall":[...], "precision":[...], "ndcg":[...]}; empty lists if no cases
def tokenize(text: str) -> list[str]                  # _TOKEN_RE.findall(normalize_text(text))
def content_tokens(text: str) -> list[str]            # tokenize minus STOPWORDS minus len-1 tokens
def groundedness(answer: str, contexts: Sequence[str]) -> float | None
    # A = set(content_tokens(answer)); C = set(content_tokens(" ".join(contexts))); None if not A; |A∩C|/|A|
def question_coverage(question: str, answer: str) -> float | None   # |Q∩A|/|Q| over content-token sets; None if not Q
def token_f1(prediction: str, reference: str) -> float | None       # SQuAD F1 over content-token multisets (Counter); None if reference empty; 0.0 if no overlap
def count_inline_citations(answer: str) -> int                      # len(_CITATION_RE.findall(answer))
def estimate_tokens(text: str) -> int                               # ceil(len(text) / 4)
def percentile(values: Sequence[float], q: float) -> float | None   # linear interpolation (numpy default / type 7); q in [0,100]; None if empty
def mean_or_none(values: Iterable[float | None]) -> float | None     # ignores None
def safe_rate(numerator: int, denominator: int) -> float | None      # None if denominator == 0
def classify_score_kind(retrieval_method: str | None, rerank_provider: str | None) -> str | None
    # None if no method; endswith "_reranked" -> "rerank_nvidia"/"rerank_gemini"/"rerank" by provider;
    # "hybrid_rrf" -> "rrf"; "dense" -> "dense"; "bm25" -> "bm25"; else None
def normalize_score(kind: str | None, score: float | None) -> float | None
    # rerank_nvidia: 1/(1+exp(-score)) (logit->prob); rerank_gemini: clamp(score/10); rrf, dense: clamp(score); bm25/None/unknown: None
```

### 3.9 `services/evaluation/dashboard.py` (pure)
```python
WINDOW_DELTAS = {"24h": timedelta(hours=24), "7d": timedelta(days=7), "30d": timedelta(days=30), "90d": timedelta(days=90)}
STAGE_ORDER: tuple[tuple[str, str, str], ...] = (   # (stage, TraceRow attribute, kind)
  ("masking","masking_ms","component"), ("dense","dense_ms","component"), ("bm25","bm25_ms","component"),
  ("fusion","fusion_ms","component"), ("rerank","rerank_ms","component"), ("retrieval","retrieval_ms","composite"),
  ("generation","generation_ms","component"), ("ttft","ttft_ms","composite"), ("total","total_ms","composite"))
@dataclass(frozen=True) class TraceRow: created_at; endpoint; status; masking_ms; dense_ms; bm25_ms; fusion_ms; rerank_ms;
    retrieval_ms; generation_ms; ttft_ms; total_ms; citation_count; answer_citation_count; top_score; top_score_norm;
    score_kind; groundedness; provider; model; llm_fallback_used; rerank_applied; rerank_fallback; dense_empty;
    retrieval_mode; fused_count; est_prompt_tokens; est_completion_tokens
@dataclass(frozen=True) class FeedbackRow: id; trace_id; rating; comment; tags; created_at; endpoint; query_masked
def bucket_kind(window: str) -> Literal["hour","day"]           # "24h" -> hour, else day
def bucket_starts(window: str, now: datetime) -> list[datetime] # 24 aligned hours, or N aligned days (oldest first)
def floor_bucket(ts: datetime, kind) -> datetime
def aggregate_dashboard(*, traces: Sequence[TraceRow], feedback: Sequence[FeedbackRow], window: str, endpoint: str,
                        now: datetime, sampled: bool) -> RagDashboardResponse
```
Rules for `aggregate_dashboard`:
- `ok = [t for t in traces if t.status == "ok"]`.
- Percentiles (p50 and p95) and averages use `ok` only.
- `error_rate = error/total` and `blocked_rate = blocked/total`.
- `llm_fallback_rate` is computed over traces that have a non-null `provider`.
- `rerank_fallback_rate` is computed over traces where `retrieval_mode == "hybrid_rerank"` and `fused_count > 0`.
- `dense_empty_rate` is computed over non-blocked traces.
- `citation_rate` is the share of `ok` traces with `answer_citation_count >= 1`.
- `avg_citations` is the mean of `citation_count` over `ok`.
- `avg_top_score_norm` is the mean of non-null `top_score_norm` over `ok`.
- `satisfaction_rate = up/(up+down)`.
- `providers` groups by (provider, model) over non-null provider, with `share = count/Σ`, sorted by count descending.
- `score_kinds` groups by non-null `score_kind`.
- `by_endpoint` has one entry per endpoint present, sorted by count descending.
- `timeseries` is zero-filled over `bucket_starts`. Traces are assigned to buckets by `floor_bucket(created_at)`. Feedback thumbs are counted by feedback `created_at`. `fallback_count` is the count of `llm_fallback_used`.
- `feedback.recent` holds the 10 newest items. `tag_counts` is sorted descending.
- `from_ts = bucket_starts[0]` and `to_ts = now`.

### 3.10 `services/evaluation/telemetry.py`
Module-level imports that tests patch: `from app.db.database import async_session_maker`, `from app.config import settings`.

```python
async def mask_for_telemetry(text: str) -> str | None:
    """Mask + egress-validate text for storage; returns None on ANY failure (never stores a possible leak)."""
    # MaskingPipeline().mask_document via run_in_threadpool -> EgressValidator().validate(masked, registry) via run_in_threadpool
    # except Exception (noqa: BLE001) -> log type name only -> None

class RagTraceRecorder:
    """Per-request accumulator for a RAG trace; persistence never raises."""
    def __init__(self, *, tenant_id: uuid.UUID, user_id: uuid.UUID, endpoint: TraceEndpoint, top_k: int,
                 document_id: uuid.UUID | None = None, session_id: uuid.UUID | None = None,
                 retrieval_mode: RetrievalMode = RetrievalMode.HYBRID_RERANK) -> None
        # self.trace_id = uuid.uuid4(); self._t0 = time.perf_counter(); self._persisted = False; fields dict
    trace_id: uuid.UUID; session_id: uuid.UUID | None; chat_message_id: uuid.UUID | None   # public, settable
    @contextmanager
    def stage(self, name: Literal["masking", "retrieval", "generation"]) -> Iterator[None]
        # ACCUMULATES f"{name}_ms" (masking is entered several times); on exception sets error_stage=name if unset, re-raises
    def record_retrieval(self, result: RetrievalResult) -> None
        # copies diagnostics (if None: counts from retrieval_metadata); citation_count; scores_json = [{rank,source,section,score,retrieval_method}]
        # fused_scores_json from diagnostics.fused_preview; top_score = citations[0].score; mean_score; top_method = citations[0].retrieval_method
    def set_masked_query(self, masked_query: str, raw_length: int) -> None   # CALL ONLY AFTER egress validation passed
    @property has_masked_query -> bool
    def record_prompt(self, prompt: str, system_prompt: str) -> None          # est_prompt_tokens = estimate_tokens(system_prompt + prompt)
    def mark_first_token(self) -> None                                         # ttft_ms = since request start; idempotent
    def record_answer(self, answer: str, contexts: Sequence[str]) -> None
        # answer_preview = answer[:2000]; answer_citation_count; groundedness(answer, contexts); est_completion_tokens
    def record_llm_calls(self, call_log: Sequence[ProviderCallRecord]) -> None
        # llm_calls_json = [r.to_dict()]; provider/model = LAST successful generate|generate_stream record;
        # llm_fallback_used = any(r.success and r.attempt > 0); rerank_provider = last successful "rerank" record's provider
    def mark_blocked(self, reason: str) -> None        # status blocked, guardrail_blocked True, guardrail_reason
    def mark_output_flag(self, reason: str) -> None    # output_guardrail_reason (status unchanged; /query rail is log-only)
    def mark_error(self, exc: BaseException, stage: str | None = None) -> None
        # EgressViolationError -> mark_blocked("egress_violation"); else status error, error_type=type(exc).__name__,
        # error_stage = stage or already-set stage or "unknown". NEVER store str(exc) (egress reports embed entity names)
    def mark_cancelled(self) -> None
    @property status -> str
    def build(self) -> RagTrace
        # total_ms = since t0 if unset; score_kind = classify_score_kind(top_method, rerank_provider); top_score_norm = normalize_score(...)
    async def persist(self) -> None
        # no-op if already persisted or not settings.rag_telemetry_enabled; set _persisted first;
        # async with async_session_maker() as s: s.add(self.build()); await s.commit()
        # except Exception as exc:  # noqa: BLE001 - telemetry must never break a user request
        #     logger.warning("Failed to persist RAG trace %s (%s)", self.trace_id, type(exc).__name__)

async def load_dashboard(db, tenant_id, window, endpoint, now: datetime | None = None) -> RagDashboardResponse
    # now = _utc_now(); from_ts = bucket_starts(window, now)[0]; SELECT explicit scalar columns only (no JSON),
    # WHERE tenant_id == tenant_id AND created_at >= from_ts [AND endpoint == endpoint]; ORDER BY created_at DESC LIMIT 20001;
    # sampled = len > 20000. Feedback: SELECT feedback cols + RagTrace.endpoint + RagTrace.query_masked JOIN RagTrace
    # ON trace_id WHERE RagFeedback.tenant_id == tenant AND RagTrace.tenant_id == tenant AND RagFeedback.created_at >= from_ts [endpoint]
    # -> aggregate_dashboard(...)
async def list_traces(db, tenant_id, user_id, *, window, endpoint, status, mine, limit, offset) -> TraceListResponse
    # same window start as dashboard; count(*) query + page query; then ONE grouped feedback query for the page ids:
    # select(trace_id, func.sum(case((rating == 1, 1), else_=0)), func.sum(case((rating == -1, 1), else_=0))) ... group_by(trace_id)
async def get_trace_detail(db, tenant_id, user_id, trace_id) -> TraceDetailResponse | None
    # tenant-filtered; document_filename via Document (id == document_id AND tenant_id == tenant); feedback list with is_mine
async def upsert_feedback(db, tenant_id, user_id, payload: FeedbackCreate) -> FeedbackResponse | None
    # None if trace not in tenant; comment -> mask_for_telemetry (if masking fails store None); update-or-insert on (trace_id, user_id);
    # chat_message_id copied from trace
async def delete_feedback(db, tenant_id, user_id, trace_id) -> bool
```

### 3.11 `prompts.py` and `judge.py`
`prompts.py` contains:
- `REGULATORY_SYSTEM_PROMPT` and `QUERY_SYSTEM_PROMPT`. These are **verbatim** copies of the current strings in `regulatory.py:65-69` and `query.py:150-154`.
- `def format_context(citations: Sequence[Citation]) -> str`, which returns exactly `"\n\n".join(f"Source: {c.source}\nSection: {c.section}\nContent: {c.text}" …)`.
- `JUDGE_SYSTEM_PROMPT`.
- `def build_judge_prompt(question: str, context: str, answer: str, reference: str | None) -> str`.
- `def judge_json_schema(with_reference: bool) -> dict`.

The judge schema uses plain `number` and `string` types with no nullable union, because Gemini's `response_schema` does not accept type arrays. `correctness` is included only when there is a reference answer.

Judge prompt text:
```
JUDGE_SYSTEM_PROMPT = ("You are a strict evaluator of retrieval-augmented answers about CBUAE model risk regulation. "
  "Tokens like [ORG_1] or [BANK_1] are privacy placeholders; treat them as opaque names. Respond only with JSON.")
Body: "Question:\n{q}\n\nRetrieved context:\n{context[:8000]}\n\nCandidate answer:\n{answer[:4000]}\n\n"
  + ("Reference answer:\n{reference[:4000]}\n\n" if reference else "")
  + "Score each criterion from 0.0 to 1.0:\n"
    "- faithfulness: fraction of the answer's factual claims directly supported by the retrieved context.\n"
    "- answer_relevance: how directly and completely the answer addresses the question (ignore correctness).\n"
  + ("- correctness: agreement with the reference answer's key facts.\n" if reference else "")
  + 'Return JSON with keys faithfulness, answer_relevance' + (', correctness' if reference else '') + ', rationale (<= 300 characters).'
```

`judge.py`:
```python
@dataclass(frozen=True)
class JudgeOutcome: method: Literal["llm","deterministic","none"]; faithfulness: float | None; answer_relevance: float | None
                    answer_correctness: float | None; rationale: str | None; latency_ms: float
class JudgeVerdict(BaseModel): faithfulness: float; answer_relevance: float; correctness: float | None = None; rationale: str = ""
def _coerce_unit(v: float | None) -> float | None    # 1 < v <= 10 -> v/10 ; then clamp [0,1]
def deterministic_judge(question, answer, contexts, reference) -> JudgeOutcome
    # faithfulness = groundedness(answer, contexts); relevance = question_coverage(question, answer);
    # correctness = token_f1(answer, reference) if reference else None; rationale="Deterministic token-overlap proxy."
async def judge_answer(*, llm_router, mode: str, question_masked: str, context: str, answer: str,
                       reference_masked: str | None, registry: EntityRegistry, egress: EgressValidator) -> JudgeOutcome
    # mode == "deterministic" -> deterministic_judge
    # else: prompt = build_judge_prompt(...); await run_in_threadpool(egress.validate, prompt, registry);
    #   raw = await llm_router.generate(prompt, system_prompt=JUDGE_SYSTEM_PROMPT, temperature=0.0, max_tokens=400,
    #                                   json_schema=judge_json_schema(bool(reference_masked)))
    #   strip ``` fences -> json.loads -> JudgeVerdict.model_validate -> coerce -> JudgeOutcome(method="llm", rationale[:300])
    #   except Exception as exc (noqa: BLE001; provider SDK errors are heterogeneous):
    #     out = deterministic_judge(...); rationale = f"LLM judge unavailable ({type(exc).__name__}); deterministic proxy used."
```

### 3.12 `default_dataset.py`: 22 default cases derived from `CBUAE_REGULATORY_CORPUS`
```python
from app.services.retrieval.hybrid_retriever import CBUAE_REGULATORY_CORPUS
@dataclass(frozen=True) class DefaultTargetSpec: section_index: int; keywords: tuple[str, ...]
@dataclass(frozen=True) class DefaultCaseSpec: key: str; question: str; reference_answer: str; targets: tuple[DefaultTargetSpec, ...]
DEFAULT_CASE_SPECS: tuple[DefaultCaseSpec, ...]
def build_expected_refs(spec) -> list[dict]:   # [{"source": corpus[i]["source"], "section": corpus[i]["section"],
                                               #   "keywords": list(kw), "min_keyword_hits": None, "chunk_index": None}]
async def ensure_default_cases(db, tenant_id, user_id) -> int   # insert all specs iff tenant has ZERO cases (any origin/state)
async def restore_default_cases(db, tenant_id, user_id) -> int  # insert specs whose key not present for tenant
```
The table below lists every case. The section index is 0-based. Every keyword was checked against the corpus text so that it meets the minimum hit count, which is ⌈0.6·n⌉, on its own section and on **no other** section.

| key | question | section idx : keywords | reference answer |
|---|---|---|---|
| cbuae-s01-q1 | Who must approve the model risk management framework? | 0: "Board of Directors", "risk appetite" | The Model Risk Management framework must be approved by the Board of Directors and define model risk appetite. |
| cbuae-s01-q2 | What must the model risk management framework define regarding lines of defense and responsibilities? | 0: "three lines of defense", "model owners" | The MRM framework must define model risk appetite, the three lines of defense, and the roles and responsibilities of model owners, developers and independent model validation units. |
| cbuae-s02-q1 | How must models be classified into tiers under the model inventory requirements? | 1: "Tier 1", "Tier 2", "Tier 3", "Materiality" | Models are tiered into Tier 1 (high), Tier 2 (medium) and Tier 3 (low materiality) based on financial exposure, regulatory capital impact, algorithmic complexity and decision autonomy, and recorded in a centralized model inventory. |
| cbuae-s02-q2 | How frequently must Tier 1 models be validated? | 1: "Tier 1", "annual validation" | Tier 1 (high materiality) models require annual validation. |
| cbuae-s03-q1 | How much historical data is required when developing a credit risk model? | 2: "economic cycle", "5-7 years" | Development data must be representative and cover at least one full economic cycle, a minimum of 5-7 years. |
| cbuae-s03-q2 | Which data quality treatments must be documented in the Model Development Document? | 2: "outlier treatment", "missing value imputation", "Model Development Document" | Completeness checks, outlier treatment, missing value imputation and sample selection rationale must be documented in the Model Development Document (MDD). |
| cbuae-s04-q1 | What is the minimum Gini coefficient required for credit scoring models? | 3: "Gini", "0.40" | Credit scoring and rating models must achieve a Gini coefficient of at least 0.40 (40%). |
| cbuae-s04-q2 | What AUC and KS thresholds must rating models meet? | 3: "AUC", "0.70", "Kolmogorov-Smirnov" | The minimum benchmarks are AUC-ROC of at least 0.70 and a Kolmogorov-Smirnov (KS) statistic of at least 30 (30%). |
| cbuae-s05-q1 | Which statistical tests are required for PD calibration? | 4: "binomial", "traffic light", "Hosmer-Lemeshow" | PD calibration requires binomial tests, traffic light tests, Hosmer-Lemeshow goodness-of-fit tests and Brier score evaluation. |
| cbuae-s05-q2 | What Brier score target applies to PD model calibration? | 4: "Brier", "0.15" | The Brier score target is 0.15 or lower. |
| cbuae-s06-q1 | At what PSI level is recalibration or rebuild mandatory? | 5: "PSI", "0.25", "recalibration" | A PSI of 0.25 or higher indicates a significant shift that triggers mandatory recalibration or rebuild. |
| cbuae-s06-q2 | Which indices are used to monitor population and characteristic drift? | 5: "Population Stability Index", "Characteristic Stability Index" | Drift is monitored with the Population Stability Index (PSI) and the Characteristic Stability Index (CSI). |
| cbuae-s07-q1 | What days-past-due backstop applies to SICR assessment under IFRS 9? | 6: "30 days past due", "SICR" | SICR criteria must include the mandatory 30 days past due (DPD) backstop alongside quantitative lifetime PD changes and qualitative watchlist flags. |
| cbuae-s07-q2 | Which macroeconomic scenarios must IFRS 9 ECL models incorporate? | 6: "baseline", "upside", "downside" | ECL models must incorporate probability-weighted forward-looking baseline, upside and downside macroeconomic scenarios. |
| cbuae-s08-q1 | Which macroeconomic shocks should credit risk stress tests cover? | 7: "real estate", "oil price", "interest rate" | Stress tests should cover severe but plausible shocks including real estate shocks, oil price volatility and interest rate fluctuations. |
| cbuae-s08-q2 | Which capital and provisioning metrics must stress testing evaluate? | 7: "risk-weighted assets", "impairment provisions", "capital adequacy" | Stress testing must evaluate the impact on risk-weighted assets (RWA), impairment provisions and capital adequacy ratios. |
| cbuae-s09-q1 | What independence requirements apply to the model validation unit? | 8: "Independent Model Validation", "independence" | Independent Model Validation units must maintain strict organizational and reporting independence from model development. |
| cbuae-s09-q2 | What activities does independent model validation encompass? | 8: "conceptual soundness", "replication", "benchmarking" | Validation covers conceptual soundness review, developmental evidence verification, replication, outcome analysis, benchmarking and implementation verification. |
| cbuae-s10-q1 | How often must ongoing monitoring reports be escalated to the Board Risk Committee? | 9: "quarterly", "Board Risk Committee" | Ongoing monitoring reports, override tracking, policy exception rates and validation findings must be reported quarterly to the Board Risk Committee. |
| cbuae-s10-q2 | What is the purpose of an Early Warning System for credit portfolios? | 9: "Early Warning Systems", "creditworthiness" | Early Warning Systems detect deteriorating borrower creditworthiness and emerging portfolio stress. |
| cbuae-multi-01 | For a Tier 1 credit scoring model, how often is validation required and what minimum Gini applies? | 1: "Tier 1", "annual validation" **and** 3: "Gini", "0.40" | Tier 1 models require annual validation and credit scoring models must reach a Gini coefficient of at least 0.40. |
| cbuae-multi-02 | Which calibration tests and stability indices should ongoing monitoring of a PD model include? | 4: "binomial", "Hosmer-Lemeshow" **and** 5: "Population Stability Index", "PSI" | Ongoing monitoring should include calibration tests such as binomial and Hosmer-Lemeshow tests plus stability tracking with the Population Stability Index (PSI). |

The two multi-target cases make Recall@k differ from Hit@k.

### 3.13 `runner.py`
Module-level names that tests patch: `async_session_maker`, `LLMRouter`, `PineconeStore`, `MaskingPipeline`, `EgressValidator`.
Constants: `STALE_RUN_SECONDS = 600`, `CASE_TIMEOUT_SECONDS = 120`, `MAX_CASES_PER_RUN = 200`, `GENERATION_TEMPERATURE = 0.0`, `SNIPPET_CHARS = 280`.

```python
async def execute_run_group(run_ids: list[uuid.UUID], tenant_id: uuid.UUID) -> None
    # sequentially: for run_id in run_ids: await execute_run(run_id, tenant_id); every exception is caught inside execute_run
async def execute_run(run_id, tenant_id) -> None
    # async with async_session_maker() as db:
    #   run = tenant-filtered load; return if None or status != pending
    #   status=running, started_at=heartbeat_at=now; commit
    #   cases = SELECT RagEvalCase WHERE tenant_id AND id IN run.case_ids_json (preserve snapshot order; missing ones skipped)
    #   llm_router = LLMRouter(); retriever = HybridRetriever(llm_router, PineconeStore()); masking = MaskingPipeline(); egress = EgressValidator()
    #   try:
    #     for pos, case in enumerate(cases):
    #       await db.refresh(run, attribute_names=["status"]); break if status == cancelled
    #       try: row = await asyncio.wait_for(evaluate_case(...), CASE_TIMEOUT_SECONDS)
    #       except TimeoutError: row = error row (error_type="TimeoutError", error_stage="timeout")
    #       db.add(row); completed_cases += 1 if row.status == "ok" else failed_cases += 1
    #       now = _utc_now(); run.heartbeat_at = now
    #       await db.execute(update(RagEvalRun).where(group_id == run.group_id, tenant_id == tenant_id, status == "pending").values(heartbeat_at=now))
    #       await db.commit()
    #     agg = aggregate_run_results(all result rows of run, run.top_k, run.include_generation) -> set metric columns + metrics_json
    #     await db.refresh(run, ["status"]); run.status = cancelled if cancelled else completed; finished_at; commit
    #   except Exception as exc (noqa: BLE001): rollback; status failed; error_message = f"Run failed ({type(exc).__name__})"; finished_at; commit
    #   finally: await llm_router.aclose()
async def evaluate_case(*, db, run, case, position, retriever, llm_router, masking, egress) -> RagEvalResult
```
`evaluate_case` never raises except on timeout. Its steps, with the error stage recorded for each failure:
1. **mask**: `masked_q, registry = run_in_threadpool(masking.mask_document, case.question)`, then `egress.validate(masked_q, registry)`. An `EgressViolationError` produces an error row with stage `"egress"` and `question_masked=None`.
2. **document**: if `case.document_id` is set, check the Document exists with `id == document_id AND tenant_id == run.tenant_id`. Otherwise produce an error row with stage `"document"` and `error_type="DocumentNotFound"`.
3. **targets**: build `RelevanceTarget`s from `expected_refs_json`. For each `chunk_index`, look up `DocumentChunk.masked_text`, joined to Document and filtered by tenant, and set `text_hash = text_fingerprint(masked_text)`. If the chunk is missing, increment `unresolved_chunk_targets`.
4. **retrieval**: `res = await retriever.retrieve(query=masked_q, tenant_id=run.tenant_id, document_id=case.document_id, db=db, top_k=run.top_k, mode=RetrievalMode(run.mode))`, timed to give `retrieval_ms`.
   This uses the **masked** question, which is privacy-correct. Production currently embeds the raw question; see §6.
5. **relevance**:
   - `items = [RetrievedItem(c.source, c.section, c.text) for c in res.citations]`
   - `relevances, matched = judge_relevance(items, targets)`
   - `scores = score_case(relevances, matched, len(targets), run.top_k)`
   - `retrieved_json` holds rank, source, section, score, method, relevant, matched_targets and `snippet = text[:280]`.
   - `diagnostics_json = res.diagnostics.model_dump(mode="json", exclude={"fused_preview"}) | {"unresolved_chunk_targets": n}`
6. **generation** (only if `run.include_generation`):
   - `context = format_context(res.citations)` and `prompt = f"Context:\n{context}\n\nQuestion: {masked_q}"`.
   - `egress.validate(prompt, registry)`.
   - `answer = await llm_router.generate(prompt, system_prompt=(QUERY_SYSTEM_PROMPT if case.document_id else REGULATORY_SYSTEM_PROMPT), temperature=0.0, max_tokens=700)`, timed.
   - Any failure gives an error row with stage `"generation"`, but the retrieval metrics are **kept**: the row's status is `"ok"` for the retrieval part and `error_stage="generation"`, and `judge_method="none"`.
7. **judge**: mask the reference answer with the same registry, then call `judge_answer(...)`.

`aggregate_run_results(results, top_k, include_generation) -> dict`:
- Uses results with `status == "ok"`.
- Each result column is the mean over non-null values. The results feed the run columns: `hit_rate` (mean of `hit` as 0/1), `mean_recall`, `mean_precision`, `mrr` (mean `reciprocal_rank`), `mean_ndcg`, `mean_faithfulness`, `mean_answer_relevance`, `mean_answer_correctness`.
- `p50_latency_ms` and `p95_latency_ms` are percentiles of `retrieval_ms + (generation_ms or 0)`.
- `metrics_json = {"curves": metric_curves(...), "judge_breakdown": {...}, "degraded": {dense_empty, rerank_fallback, unresolved_chunk_targets}, "generation_temperature": 0.0 if include_generation else None}`.

`reconcile_stale_runs(db, tenant_id, now=None) -> int`: an UPDATE that sets `status='failed'`, `error_message='Run interrupted (worker restart or timeout)'` and `finished_at=now` on runs where `tenant_id` matches, `status IN ('pending','running')`, and `COALESCE(heartbeat_at, created_at) < now - 600s`. It then commits.

### 3.14 `app/api/rag_eval.py`
`router = APIRouter(prefix="/rag", tags=["RAG Performance"])`. Every handler takes `current_user: TokenPayload = Depends(get_current_user)` and `db: AsyncSession = Depends(get_db)`.
- **T1–T5** delegate to the telemetry functions. T3 and T4 return 404 on `None`.
- **E1**: `await ensure_default_cases(db, tenant, user)`, then list the cases. Compute `document_filename` with one `SELECT Document.id, Document.filename WHERE tenant_id AND id IN (...)`.
- **E2**: `violation = await run_input_guardrails(payload.question, check_off_topic=False)` returns 400 with `violation.detail` if set. Check document ownership (404 if not owned). Insert with `origin="custom"` and `expected_refs_json=[r.model_dump() for r in payload.expected_refs]`.
- **E3**: tenant-filtered load (404). Apply only `model_fields_set`. Re-run guardrails if the question changed. Re-check document ownership. Re-validate the merged chunk_index/document rule, returning 422 via `HTTPException(422, detail=...)` if it fails.
- **E4**: tenant-filtered delete, returning 204.
- **E5**: call `restore_default_cases`.
- **E6**, signature `create_runs(payload: EvalRunCreate, background_tasks: BackgroundTasks, …)` with `status_code=202`:
  1. `reconcile_stale_runs`.
  2. Return 409 (`"An evaluation run is already in progress for this tenant"`) if any run for the tenant is pending or running.
  3. Call `ensure_default_cases`.
  4. Resolve cases. If `case_ids` is set, it must be a subset of the tenant's active cases, otherwise 400 `"Unknown or inactive case ids"`. Otherwise use all active cases. 0 cases returns 400 `"No active evaluation cases"`; more than 200 returns 400.
  5. Create one `RagEvalRun` per mode, all sharing `group_id=uuid4()`, `case_ids_json=[str(id)...]`, `total_cases=n` and `heartbeat_at=now`. **Commit.**
  6. Call `background_tasks.add_task(execute_run_group, [ids], tenant_id)`.
  7. Return summaries plus `estimated_llm_calls`.
- **E7 and E8** call `reconcile_stale_runs` first. Helpers `_run_summary(run)` and `_run_detail(run)` map `mean_recall` to `metrics.recall` and so on. `progress = (completed + failed) / total` (0 if total is 0). `curves`, `judge_breakdown` and `degraded` come from `metrics_json` with defaults.
- **E9**: tenant-filtered run (404), then results ordered by `position`.
- **E10**: a pending run becomes `cancelled` with `finished_at=now`. A running run becomes `cancelled` (the runner stops before the next case). A finished run returns 409.
- **E11**: a pending or running run returns 409. Otherwise explicitly `delete(RagEvalResult).where(run_id==…, tenant_id==…)`, then delete the run, and return 204.

Edits to `main.py`: add `rag_eval` to the `from app.api import …` line, and add `app.include_router(rag_eval.router, dependencies=[Depends(get_rate_limiter)])`. With FREE capacity 10 and 1 token/s refill, 3-second polling costs about 0.7 token/s, which is fine.

Edit to `config.py`: add `rag_telemetry_enabled: bool = True` to `Settings` (env var `RAG_TELEMETRY_ENABLED`).

### 3.15 Instrumenting `/regulatory/search` and `/query`
**`regulatory.py`** (full handler body):
```python
from app.models.rag_eval import TraceEndpoint
from app.services.evaluation.prompts import REGULATORY_SYSTEM_PROMPT, format_context
from app.services.evaluation.telemetry import RagTraceRecorder, mask_for_telemetry

recorder = RagTraceRecorder(tenant_id=current_user.tenant_id, user_id=current_user.sub,
                            endpoint=TraceEndpoint.REGULATORY_SEARCH, top_k=5)
llm_router = LLMRouter()
try:
    retriever = HybridRetriever(llm_router, PineconeStore())
    with recorder.stage("retrieval"):
        retrieval_result = await retriever.retrieve(query=request.question, tenant_id=current_user.tenant_id,
                                                    document_id=None, db=db, top_k=5)
    recorder.record_retrieval(retrieval_result)
    masking_pipeline, egress_validator = MaskingPipeline(), EgressValidator()
    with recorder.stage("masking"):
        masked_question, registry = await run_in_threadpool(masking_pipeline.mask_document, request.question)
        await run_in_threadpool(egress_validator.validate, masked_question, registry)
    recorder.set_masked_query(masked_question, raw_length=len(request.question))   # only after egress passed
    context_text = format_context(retrieval_result.citations)
    prompt = f"Context:\n{context_text}\n\nQuestion: {masked_question}"
    with recorder.stage("masking"):
        await run_in_threadpool(egress_validator.validate, prompt, registry)
    recorder.record_prompt(prompt, REGULATORY_SYSTEM_PROMPT)
    with recorder.stage("generation"):
        answer = await llm_router.generate(prompt, system_prompt=REGULATORY_SYSTEM_PROMPT)
    recorder.record_answer(answer, contexts=[context_text])
    return RegulatoryResponse(answer=answer, citations=retrieval_result.citations, trace_id=recorder.trace_id)
except Exception as exc:
    recorder.mark_error(exc)
    if not recorder.has_masked_query:
        masked = await mask_for_telemetry(request.question)
        if masked is not None:
            recorder.set_masked_query(masked, raw_length=len(request.question))
    raise
finally:
    recorder.record_llm_calls(llm_router.call_log)
    await recorder.persist()
    await llm_router.aclose()
```

**`query.py`** (changes in order):
- (a) At the top of the handler, after the document check: `recorder = RagTraceRecorder(tenant_id=…, user_id=current_user.sub, endpoint=TraceEndpoint.QUERY, top_k=6, document_id=request.document_id)`.
- (b) Guardrail block: before `raise HTTPException(400…)`, add `recorder.mark_blocked(violation.reason)`, then `masked = await mask_for_telemetry(request.question)` and `set_masked_query` if it is not None, then `await recorder.persist()`. No ChatSession is created, so the existing test still holds.
- (c) After the session is resolved: `recorder.session_id = session_id`.
- (d) Wrap `retriever.retrieve(...)` in `with recorder.stage("retrieval")`, then call `record_retrieval`.
- (e) Wrap question masking, egress, history masking and final-prompt egress in `with recorder.stage("masking")`. Call `recorder.set_masked_query(masked_question, …)` right after `egress_validator.validate(masked_question, registry)`.
- (f) Replace the inline `context_text` join and `system_prompt` with `format_context(...)` and `QUERY_SYSTEM_PROMPT`. Call `recorder.record_prompt(prompt, QUERY_SYSTEM_PROMPT)`. Set `ai_message_id = uuid.uuid4()` and `recorder.chat_message_id = ai_message_id`.
- (g) New generator (`import anyio`, `import time`):
```python
async def generator() -> AsyncIterator[Union[str, Dict[str, Any]]]:
    completed = False
    try:
        yield {"type": "session_id", "content": str(session_id)}
        yield {"type": "trace", "content": str(recorder.trace_id)}
        yield {"type": "citations", "content": [c.model_dump() for c in retrieval_result.citations]}
        full_response = ""
        with recorder.stage("generation"):
            async for chunk in llm_router.generate_stream(prompt, QUERY_SYSTEM_PROMPT):
                if not full_response:
                    recorder.mark_first_token()
                full_response += chunk
                yield chunk
        try:   # existing output-guardrail block, plus:
            out_violation = await run_output_guardrails(...)
            if out_violation:
                recorder.mark_output_flag(out_violation.reason)
                logger.warning(...)
        except Exception as e:
            logger.error(...)
        try:
            async with async_session_maker() as stream_db:
                stream_db.add(ChatMessage(id=ai_message_id, session_id=session_id, role=ChatRoleEnum.ASSISTANT,
                                          content=full_response,
                                          sources_json=[c.model_dump() for c in retrieval_result.citations]))
                await stream_db.commit()
        except Exception as e:
            logger.error(...)
        recorder.record_answer(full_response, contexts=[context_text])
        completed = True
        yield {"type": "suggestedActions", "content": [...unchanged...]}
    except Exception as exc:
        recorder.mark_error(exc, stage="generation")
        raise
    finally:
        if not completed and recorder.status == "ok":
            recorder.mark_cancelled()          # client disconnected mid-stream
        recorder.record_llm_calls(llm_router.call_log)
        with anyio.CancelScope(shield=True):   # Starlette cancels via anyio on disconnect; shield the writes
            await recorder.persist()
            await llm_router.aclose()
```
Note: a disconnect raises `CancelledError`, which is a `BaseException` and so is not caught by the `except Exception` above.
- (h) Outer `except Exception as exc:` gets `recorder.mark_error(exc)`. If there is no masked query yet, call `mask_for_telemetry`. Then `recorder.record_llm_calls(llm_router.call_log)`, `await recorder.persist()`, `await llm_router.aclose()`, `raise`. This re-raises the original exception, which keeps `test_query_clean_question_passes_input_rail` passing.

### 3.16 Test plan
All tests run offline. Each file declares its own in-memory engine, following the existing pattern (see `tests/test_router_guardrails.py`). Shared fixture shape:
```python
engine = create_async_engine("sqlite+aiosqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
TestingSessionLocal = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
@pytest_asyncio.fixture(autouse=True)
async def setup_db(monkeypatch):
    app.dependency_overrides[get_db] = override_get_db
    monkeypatch.setattr("app.services.evaluation.telemetry.async_session_maker", TestingSessionLocal)
    monkeypatch.setattr("app.services.evaluation.runner.async_session_maker", TestingSessionLocal)
    monkeypatch.setattr("app.api.query.async_session_maker", TestingSessionLocal)
    async with engine.begin() as conn: await conn.run_sync(Base.metadata.create_all)   # includes rag_* via app.models.__init__
    ... seed Tenant/User (two tenants for isolation tests) ...
```
`FakeRouter` for the runner is patched in with `monkeypatch.setattr("app.services.evaluation.runner.LLMRouter", FakeRouter)`. It has:
- `call_log = []`
- `embed` → raises `RuntimeError`, so dense is empty
- `rerank` → raises, so rerank falls back
- `generate(prompt, system_prompt=None, **kw)` → if `kw.get("json_schema")` it returns `'{"faithfulness":0.9,"answer_relevance":0.8,"correctness":0.7,"rationale":"ok"}'`, otherwise `"Gini must be at least 0.40 [Source: CBUAE-MMG-2022, Section: Section 4 - Quantitative Validation & Discriminatory Power]"`
- `aclose = AsyncMock()`

Also patch `runner.PineconeStore` with `MagicMock`. Patch `runner.MaskingPipeline` with an identity fake (`mask_document(t, registry=None) -> (t, EntityRegistry())`) and `runner.EgressValidator` with a no-op fake. Real masking is covered separately in the telemetry tests.

| File | Coverage |
|---|---|
| `tests/test_rag_metrics.py` | Worked example: relevances `[0,1,0,1]`, matched `[[],[0],[],[1]]`, 2 targets, k=4 gives hit 1.0, P 0.5, RR 0.5, recall 1.0 (0.5 at k=2), DCG 1.0616, nDCG **0.6509**. `[1,1,1]` with 1 target gives nDCG 1.0 (never above 1). k=0 raises `ValueError`. `section_matches("Section 1","Section 10 - Early…")` is False, and True for "Section 1 - Governance…". Case-insensitivity and unicode-dash normalisation. `required_keyword_hits` (4 keywords → 3). Text-hash target. `percentile([1,2,3,4],50)==2.5`, `percentile([10],95)==10`, empty returns None. Groundedness 1.0, 0.0 and None. Comma number `"1,250,000"` stays one token. `token_f1("gini","gini auc")≈0.667`. `normalize_score("rerank_nvidia",0)==0.5`, gemini 7.5 → 0.75, bm25 → None. `count_inline_citations`. `metric_curves` shapes. |
| `tests/test_rag_default_dataset.py` | 22 specs with unique keys. Every `section_index` is valid. Keywords meet the required hits on their own section text and not on any other section. `build_expected_refs` produces source "CBUAE-MMG-2022" with the exact section titles. `await run_input_guardrails(q, check_off_topic=False) is None` for every question. |
| `tests/test_rag_retriever_modes.py` | `HybridRetriever(MagicMock router, MagicMock store)` with a real sqlite session. **bm25**: `router.embed` not awaited, `dense_ms is None`, `rerank_ms is None`, at most `top_k` results, methods all `"bm25"`. **dense**: embed returns a vector, `store.query` returns `VectorResult`s, `bm25_count == 0`. **hybrid**: methods `"hybrid_rrf"`, rerank not awaited. **hybrid_rerank**: rerank raises → `rerank_fallback True`; rerank returns `[RerankResult(index=2,…)]` → order follows the rerank and `rerank_applied`. The default call (no `mode`) keeps the legacy `retrieval_metadata` keys. Offline sanity: bm25 over all 22 raw default questions at top_k=10 gives hit_rate 1.0 and recall 1.0 (guaranteed by structure). At top_k=5, MRR ≥ 0.7; set the floor just below the first observed value because the run is deterministic. |
| `tests/test_llm_router_call_log.py` | NVIDIA fails and Gemini succeeds on `generate` → 2 records (attempt 0 failed with `error_type="RuntimeError"`, attempt 1 succeeded). With MagicMock providers, `record.model` is a `str`. Stream success is recorded as `generate_stream`. The log stops at 200 entries. |
| `tests/test_rag_dashboard_aggregation.py` | Pure `aggregate_dashboard`: 24h window gives 24 hourly zero-filled buckets. 7d gives 7 buckets and `from_ts` at the aligned midnight. Percentiles use ok rows only. Rates are None when the denominator is 0. `satisfaction_rate`. Provider shares sum to 1. Stages come in canonical order with `kind`. |
| `tests/test_rag_telemetry_api.py` | **regulatory OK**: patch `app.api.regulatory.HybridRetriever.retrieve` (returns a `RetrievalResult` with diagnostics) and `LLMRouter.generate`/`aclose`. Response `trace_id` is not null. The row has `endpoint="regulatory_search"`, `status="ok"`, `answer_citation_count==1`, groundedness not null. **Privacy**: question "What Gini must Emirates NBD meet?" → stored `query_masked` contains `[BANK_` and not `"Emirates NBD"`. **Error**: retrieve raises `RuntimeError` → exception propagates, row has `status="error"`, `error_type="RuntimeError"`, `error_stage="retrieval"`, and no message text stored. **/query stream**: patch retrieve and `LLMRouter.generate_stream` with an async generator. The SSE events come in order `session_id, trace, citations, token…, suggestedActions, done`. The trace row's `chat_message_id` equals the saved assistant `ChatMessage.id` and `ttft_ms` is not None. **Blocked**: a jailbreak gives 400, a trace with `status="blocked"` and `guardrail_reason="jailbreak"`, and no ChatSession. **Dashboard, list and detail**: seed traces for 2 tenants and check tenant isolation, filters, pagination, and a 404 for another tenant's trace. **Feedback**: create, then update (upsert keeps 1 row), then DELETE (204), then DELETE again (404). Another tenant's trace gives 404. A rating of 0 gives 422. A comment with a bank name is stored masked. **Telemetry DB down**: point `telemetry.async_session_maker` at a sessionmaker whose engine has no tables; the request still succeeds. |
| `tests/test_rag_eval_api.py` | First E1 seeds 22 cases; a second E1 adds none. Delete 2 cases, then restore → `inserted == 2`. CRUD for a custom case. 422s (no refs; empty ref; `chunk_index` without a document). 400 for a jailbreak question. 404 for a document from another tenant. **Run flow**: E6 with `modes=["bm25","hybrid_rerank"]`, `include_generation=true`, `judge="auto"` → 202 with 2 runs and one group. httpx `ASGITransport` completes BackgroundTasks before returning, so E7 then shows both runs `completed` and `progress == 1.0`. `hit_rate` is not null, E9 returns 22 results, `judge_method == "llm"`, faithfulness is 0.9, and `degraded.dense_empty == 22` for hybrid_rerank. **Judge fallback**: FakeRouter's judge call raises → `judge_method == "deterministic"` and faithfulness is not null. **409** when a running run with a fresh heartbeat exists. **Stale**: running with a heartbeat 20 minutes old → E7 shows it `failed`. Cancel a pending run → `cancelled`. DELETE a completed run removes its results; DELETE while running → 409. Another tenant's run → 404 on E8, E9, E10 and E11. |
| `tests/test_rag_runner.py` | Unit tests of `evaluate_case`: an egress violation (fake raises `EgressViolationError`) gives error stage `"egress"` with `question_masked` None. A missing document gives stage `"document"`. `chunk_index` target resolution matches by text fingerprint. Generation failure keeps the retrieval metrics and sets `error_stage="generation"`. `aggregate_run_results` computes means and curves. |

Run with `cd backend && python -m ruff check app --select E9,F63,F7,F82 && python -m compileall app && DATABASE_URL=sqlite+aiosqlite:///./ci_test.db python -m pytest -q`.

### 3.17 Backend sequencing
1. Retrieval schemas, retriever and reranker, plus their tests.
2. Router call log and nvidia change, plus tests.
3. `metrics.py` and tests.
4. Models, migration and `models/__init__`.
5. `schemas/rag_eval.py`, including the regulatory `trace_id`.
6. `dashboard.py` and `telemetry.py` plus tests.
7. `prompts.py`, then instrument `regulatory.py` and `query.py`, plus API telemetry tests.
8. `default_dataset.py`, `judge.py`, `runner.py` plus tests.
9. `api/rag_eval.py`, `main.py`, `config.py`, plus eval API tests.

---

## 4. WP-FRONTEND

### 4.1 File map
**New files:**
- `frontend/src/lib/ragTypes.ts` (the §2.5 contract, copied verbatim)
- `frontend/src/lib/ragFormat.ts`
- `frontend/src/components/RagPerformanceView.tsx`
- `frontend/src/components/rag/palette.ts`
- `frontend/src/components/rag/charts.tsx`
- `frontend/src/components/rag/KpiTile.tsx`
- `frontend/src/components/rag/TelemetryPanel.tsx`
- `frontend/src/components/rag/TraceDetailDrawer.tsx`
- `frontend/src/components/rag/EvaluationPanel.tsx`
- `frontend/src/components/rag/EvalRunLauncher.tsx`
- `frontend/src/components/rag/EvalRunsTable.tsx`
- `frontend/src/components/rag/EvalRunComparison.tsx`
- `frontend/src/components/rag/EvalRunResultsDrawer.tsx`
- `frontend/src/components/rag/EvalDatasetPanel.tsx`
- `frontend/src/components/rag/EvalCaseEditorModal.tsx`
- `frontend/src/components/rag/FeedbackControl.tsx`

**Edits:** `src/types.ts`, `src/components/SideNav.tsx`, `src/App.tsx`, `src/lib/api.ts`, `src/lib/sse.ts`, `src/components/WorkspaceView.tsx`, `src/components/RegulatoryLibraryView.tsx`.

No new dependencies. All charts are inline SVG. Use `motion` only for drawers and modals, as the existing code does.

### 4.2 Types, API and formatting
- `types.ts`: `export type NavItem = 'overview' | 'workspace' | 'compare' | 'library' | 'rag' | 'settings';`. Add `traceId?: string;` to `ChatMessage`.
- `lib/api.ts`: add typed functions. The DTOs use snake_case exactly as sent by the backend, with no adapter layer. Query values must be strings.
```ts
import type { RagDashboard, RagWindow, RagEndpointFilter, TraceStatusFilter, RagTraceList, RagTraceDetail, RagFeedbackInput,
  RagFeedbackRecord, EvalCaseList, EvalCase, EvalCaseInput, RestoreDefaultsResult, EvalRunCreateInput, EvalRunCreateResponse,
  EvalRunList, EvalRunDetail, EvalRunResults, EvalRunSummary } from '@/lib/ragTypes';
export const getRagDashboard = (window: RagWindow, endpoint: RagEndpointFilter) =>
  apiFetch<RagDashboard>('/rag/telemetry/dashboard', { query: { window, endpoint } });
export const listRagTraces = (p: { window: RagWindow; endpoint: RagEndpointFilter; status: TraceStatusFilter; mine: boolean; limit: number; offset: number }) =>
  apiFetch<RagTraceList>('/rag/traces', { query: { window: p.window, endpoint: p.endpoint, status: p.status, mine: String(p.mine), limit: String(p.limit), offset: String(p.offset) } });
export const getRagTrace = (id: string) => apiFetch<RagTraceDetail>(`/rag/traces/${id}`);
export const submitRagFeedback = (input: RagFeedbackInput) => apiFetch<RagFeedbackRecord>('/rag/feedback', { method: 'POST', body: input });
export const deleteRagFeedback = (traceId: string) => apiFetch<void>(`/rag/feedback/${traceId}`, { method: 'DELETE' });
export const listEvalCases = (includeInactive = true) => apiFetch<EvalCaseList>('/rag/eval/cases', { query: { include_inactive: String(includeInactive) } });
export const createEvalCase = (input: EvalCaseInput) => apiFetch<EvalCase>('/rag/eval/cases', { method: 'POST', body: input });
export const updateEvalCase = (id: string, input: Partial<EvalCaseInput>) => apiFetch<EvalCase>(`/rag/eval/cases/${id}`, { method: 'PATCH', body: input });
export const deleteEvalCase = (id: string) => apiFetch<void>(`/rag/eval/cases/${id}`, { method: 'DELETE' });
export const restoreDefaultEvalCases = () => apiFetch<RestoreDefaultsResult>('/rag/eval/cases/restore-defaults', { method: 'POST' });
export const createEvalRuns = (input: EvalRunCreateInput) => apiFetch<EvalRunCreateResponse>('/rag/eval/runs', { method: 'POST', body: input });
export const listEvalRuns = (limit = 20, offset = 0) => apiFetch<EvalRunList>('/rag/eval/runs', { query: { limit: String(limit), offset: String(offset) } });
export const getEvalRun = (id: string) => apiFetch<EvalRunDetail>(`/rag/eval/runs/${id}`);
export const getEvalRunResults = (id: string) => apiFetch<EvalRunResults>(`/rag/eval/runs/${id}/results`);
export const cancelEvalRun = (id: string) => apiFetch<EvalRunSummary>(`/rag/eval/runs/${id}/cancel`, { method: 'POST' });
export const deleteEvalRun = (id: string) => apiFetch<void>(`/rag/eval/runs/${id}`, { method: 'DELETE' });
```
- `lib/ragFormat.ts`:
  - `parseUtc(ts)` appends `'Z'` if there is no zone suffix.
  - `fmtMs(ms|null)`: "—", "850 ms", or "2.3 s" at 1000 ms and above.
  - `fmtPct(x|null, digits=0)`.
  - `fmtScore(x|null, 2)`.
  - `fmtCompact(n)` (1,284 / 12.9K).
  - `fmtRelative(ts)`, e.g. "5 min ago".
  - `fmtDateTime(ts)`.
  - Label maps:
    - `MODE_LABEL`: dense "Dense only", bm25 "BM25 only", hybrid "Hybrid (RRF)", hybrid_rerank "Hybrid + rerank (production)".
    - `STAGE_LABEL`: masking "Privacy masking", dense "Dense (embed + Pinecone)", bm25 "BM25", fusion "RRF fusion", rerank "Rerank", retrieval "Retrieval total", generation "Generation", ttft "Time to first token", total "End-to-end".
    - `ENDPOINT_LABEL`: query "AI Analyst chat", regulatory_search "Regulatory Q&A".
    - `TAG_LABEL`, `SCORE_KIND_LABEL`.

### 4.3 Navigation wiring
- `SideNav.tsx`: import `Activity` from lucide-react. Insert `{ key: 'rag', label: 'RAG Performance', icon: Activity }` between `library` and `settings`.
- `App.tsx`: add `rag: 'RAG Performance'` to `NAV_LABELS`, between `library` and `settings`, so the mobile menu keeps the same order. Import `RagPerformanceView`. Render `{!loading && activeNav === 'rag' && <RagPerformanceView />}` after the library block. The view needs no current model.

### 4.4 Page layout (`RagPerformanceView.tsx`)
- Header, matching `OverviewView` style: kicker `text-xs font-bold text-indigo-600 uppercase tracking-wider` reading "Retrieval quality", h1 "RAG Performance", subtitle "Live telemetry from every retrieval-augmented answer, plus offline evaluation against a golden dataset."
- Top-level segmented control: `Live telemetry` | `Offline evaluation`. Pill buttons: active `bg-indigo-50 text-indigo-700`, inactive `text-slate-600 hover:bg-slate-100`. Local state holds the tab.
- `<TelemetryPanel/>` or `<EvaluationPanel/>`.

**TelemetryPanel**
- **Filter row**, one row above all charts: window segmented control (24h / 7d / 30d / 90d, default 7d), endpoint `<select>` (All / AI Analyst chat / Regulatory Q&A), and a "Refresh" button with the `RefreshCw` icon. Changing a filter refetches the dashboard and resets traces to page 0. While a refetch is in flight, keep the previous render at `opacity-60`, with no skeleton and no layout jump. Show `sampled` as a small note: "Showing newest 20,000 requests".
- **Empty state** when `kpis.total_requests === 0`: a sleek card saying "No RAG traffic in this window yet — ask the AI Analyst or Regulatory Q&A a question to generate traces."
- **Degradation banner**, amber with the `AlertTriangle` icon, when `dense_empty_rate > 0.5`: "Dense retrieval returned no candidates for most requests — check Pinecone/embedding configuration. Results are BM25-only." If `rerank_fallback_rate > 0.2`, add "Reranker fell back to fusion order in N% of requests."
- **KPI row**: `grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-6` with 8 `KpiTile`s.
  1. **Requests**: the accent tile (indigo-600 background, like Overview's first card). Value `total_requests`; caption "{ok_count} answered · {blocked_count} blocked"; sparkline of `timeseries[].count`.
  2. **p95 latency**: `fmtMs(p95_total_ms)`; caption "p50 {p50_total_ms}".
  3. **Time to first token**: `p50_ttft_ms`; caption "p95 {p95_ttft_ms} · chat streaming".
  4. **Error rate**: `fmtPct(error_rate,1)`; caption "{error_count} errors". Status icon plus label: critical if above 5%, warning if above 1%.
  5. **Groundedness**: `fmtPct(avg_groundedness)`; caption "Answer tokens found in retrieved context".
  6. **Citation rate**: `fmtPct(citation_rate)`; caption "Answers with ≥1 inline [Source: …] · avg {avg_citations} retrieved".
  7. **Satisfaction**: `fmtPct(satisfaction_rate)`; caption "{thumbs_up} of {feedback_count} rated helpful".
  8. **LLM failover**: `fmtPct(llm_fallback_rate)`; caption "Rerank fallback {…} · Dense empty {…}".

  `KpiTile` props: `{ label: string; value: string; caption?: string; tone?: 'default' | 'accent' | 'good' | 'warning' | 'critical'; icon: LucideIcon; spark?: number[] }`. Label is sentence case; value is `text-3xl font-bold`. Status tones show an icon and a label, never colour alone.
- **Row 2** (`lg:grid-cols-2`):
  - **"Latency by stage"**: `HBarPairChart` of the 6 component stages plus a hairline divider plus the 3 composite stages. Series are p50 and p95. Legend present. The p95 value label sits at the bar tip. Tooltip shows stage, p50, p95, avg, n.
  - **"Request volume"**: `StackedColumnChart` over `timeseries` with stacks ok / blocked / error / cancelled. Legend and tooltip. X labels show the hour ("14:00") for the hour bucket or the date ("Sep 21") for the day bucket, thinned to at most about 8 labels.
- **Row 3** (`lg:grid-cols-2`):
  - **"Latency trend"**: `LineChart` with 2 series, p50 total and p95 total (ms). One y-axis. The line ends are labelled directly and there is a crosshair tooltip.
  - **"Feedback"** card: satisfaction `Meter`; up and down counts with `ThumbsUp`/`ThumbsDown` icons; tag counts as horizontal bars (single hue); list of `feedback.recent` (masked query, comment, tags, relative time). Clicking an item opens `TraceDetailDrawer(trace_id)`.
- **Row 4** (`lg:grid-cols-3`):
  - **"By endpoint"** table: endpoint, requests, error rate, p50, p95, groundedness, satisfaction.
  - **"Providers"** table: provider/model, count, share bar.
  - **"Top-score by scorer"** table: kind label, n, avg raw, avg normalised. Footnote: "NVIDIA rerank scores are logits (normalised via sigmoid); Gemini 0–10; RRF 0–1; BM25 is unbounded and not normalised."
- **Recent traces** card:
  - Filter row: status select (All / OK / Error / Blocked / Cancelled) and a "Only mine" checkbox.
  - Table columns:
    - Time (`fmtRelative`, full time in `title`)
    - Surface (endpoint label)
    - Query (masked, truncated to 80 characters, `font-mono text-xs` for placeholders)
    - Status badge: ok is emerald `CheckCircle2` "OK"; error is rose `XCircle` "Error"; blocked is amber `ShieldAlert` "Blocked" with the reason in `title`; cancelled is slate `MinusCircle` "Cancelled"
    - Total, Retrieval, Gen (`fmtMs`)
    - Citations ("6 · 2 cited")
    - Top relevance (`top_score_norm`)
    - Groundedness
    - Provider (with a `Shuffle` icon if `llm_fallback_used`)
    - Feedback (↑n ↓m)
  - Use `tabular-nums` in number cells. Pagination has Prev and Next buttons and "x–y of total" (limit 25). Clicking a row opens the drawer.

**TraceDetailDrawer** is a `glass-drawer` with `motion` slide-in, `sm:w-[560px]`, and an `isOpen`/`traceId` prop. It fetches `getRagTrace` and shows:
- Header: masked query, endpoint, time, and status badge.
- **Waterfall**: an SVG horizontal timeline in sequential order, each segment starting where the previous one ends: dense, bm25, fusion, rerank (retrieval), then masking, then generation. Add "other" = total − Σ, and draw the TTFT marker as a vertical hairline. Each segment has a tooltip. Colours: retrieval stages in the sequential blue ramp, masking in slate, generation in orange.
- Counts grid: dense/bm25/fused/final, `top_k`, flags shown as chips (Rerank applied / Rerank fallback / Dense empty).
- "Retrieved (final)" list: rank, source, section, score; plus a collapsible "Before rerank" list (`fused_scores`).
- Answer preview, in a `whitespace-pre-line` box.
- LLM calls table: method, provider/model, latency, attempt, ✓/✗ with error type.
- Guardrails and errors: `guardrail_reason`, `output_guardrail_reason`, `error_type` and `error_stage`.
- Token estimates, labelled "≈".
- Feedback entries, plus a `FeedbackControl` pre-set to `my_rating`.

**EvaluationPanel** has sub-tabs `Runs` | `Golden dataset`.

- **EvalRunLauncher** (sleek card):
  - Mode checkboxes (4, default only `hybrid_rerank`) plus a "Compare all modes" shortcut that selects all 4.
  - `top_k` number input (1–20, default 5).
  - "Also evaluate generated answers" toggle. When on, a judge radio appears: "LLM judge with deterministic fallback" (`auto`) or "Deterministic only".
  - Optional label input.
  - Case scope: "All active cases (N)", or "Selected cases" using the selection from the dataset tab via lifted state in `EvaluationPanel`.
  - A pre-run estimate computed on the client from the §2.4 formula: "≈ X LLM calls".
  - "Run evaluation" button calls `createEvalRuns`. On 409 show "Another evaluation is already running." Any other `ApiError` shows its `detail`.
- **EvalRunsTable**: runs from `listEvalRuns(50)`, grouped by `group_id` with a group header row ("Batch · {label || 'unlabelled'} · {fmtDateTime(created_at)}").
  - Columns: compare checkbox, Mode, k, Gen, Status (a badge; running shows a progress bar with `progress` and "{completed+failed}/{total}"), Hit@k, Recall@k, MRR, nDCG@k, Faithfulness, p95 latency, actions (View results / Cancel if pending or running / Delete if finished).
  - `error_message` shows under failed rows.
- **Polling**: in `EvaluationPanel`, if any run is pending or running, `setInterval(refresh, 3000)`, cleared on unmount or when none are active. Also refetch the detail of selected runs.
- **EvalRunComparison**: up to 4 runs selected. The default selection is the latest group whose runs are all finished.
  - Series slots are assigned **at selection time** and kept stable (`Map<runId, slot>`); removing a run does not recolour the others. Legend label: `MODE_LABEL[mode]` plus `label`.
  - `GroupedBarChart` "Retrieval metrics @k": categories Hit, Recall, Precision, MRR, nDCG; domain 0–1.
  - `GroupedBarChart` "Answer quality", shown only if any selected run has `include_generation`: Faithfulness, Relevance, Correctness. Each bar tooltip shows the judge breakdown.
  - `LineChart` "Hit@k curve" and "Recall@k curve" from `getEvalRun(id).curves`, with x = k.
  - `HBarPairChart` "Latency p50/p95 per run". This is a separate chart; never use a dual axis.
  - Delta table (which also serves as the accessible table view): Metric | run A (baseline = first selected) | run B (Δ) … Δ is formatted as "+0.12" and shown as text with an ▲/▼ icon; do not colour the numbers.
  - Degraded banner if any selected run has `degraded.dense_empty > 0`: "Dense retrieval unavailable for N cases — dense/hybrid numbers reflect BM25 only (Pinecone or embedding provider unreachable)."
  - **Case matrix**: fetch `getEvalRunResults` for each selected run and join rows by `case_id`. Columns are one per run. Each cell shows `first_relevant_rank`: "#1" (good), "#2–#k" (warning), "miss" (critical), or "error". Every cell has an icon and text, not colour alone. A toggle "Only cases where runs disagree" filters the rows. Clicking a row opens `EvalRunResultsDrawer` for that case.
- **EvalRunResultsDrawer** (`sm:w-[680px]`): for one run, lists results with the filter "Only misses / errors".
  - Each item shows the masked question, hit icon, rank, recall, nDCG, faithfulness, relevance, correctness and a judge badge ("LLM judge" / "Proxy" / "—").
  - Expanding an item shows the retrieved list. Each entry has rank, source, section, score, a relevance marker (`CheckCircle2` plus "matches target #i") and the snippet. It also shows the answer, `judge_rationale`, diagnostics chips (per-stage ms, dense empty, rerank fallback), and error type and stage.

**EvalDatasetPanel**:
- Toolbar: search box (question text), filter (All / Active / Inactive), "Add case" (opens the modal), "Restore defaults" (calls `restoreDefaultEvalCases`, then shows a toast "{inserted} default cases restored").
- Table columns: select checkbox (feeds the launcher's "Selected cases"), Question, Scope ("Regulatory corpus" or `document_filename`), Targets (chips: the section title, or "kw: a, b, c", or "chunk #12"), Ref answer (✓ / —), Origin badge (Default / Custom), Active toggle (`updateEvalCase(id, {is_active})`), and Actions (edit, delete with `confirm()`).

**EvalCaseEditorModal**, which follows the `ExportReportModal` idiom (`sleek-card`, centred, motion):
- Fields: question (textarea); scope `<select>` with "Regulatory corpus (no document)" plus documents from `listDocuments()` → `toDocumentMeta`, READY ones only.
- Target list editor, where each row has:
  - source input (optional)
  - section input (optional; placeholder "Section 4 - Quantitative Validation…")
  - keywords (comma-separated, shown as chips)
  - min hits (number, optional)
  - chunk index (number, enabled only when a document scope is chosen; hint "0-based chunk number from the Documents tab")
  - remove button
- "Add target" (maximum 10), reference answer textarea, active checkbox.
- Client validation mirrors the backend: question 5–1000 characters; at least 1 target; each target needs at least one field. Server 422 or 400 `detail` is shown inline.
- Submit calls `createEvalCase` or `updateEvalCase`.

### 4.5 Chart specification (`charts.tsx`, `palette.ts`), following the dataviz method
- `palette.ts`:
  - `SERIES = ['#2a78d6', '#eb6834', '#1baf7a', '#eda100']`. Categorical slots 1–4 in this fixed order, never cycled. This is the validated reference palette, adjacent-pair CVD-safe.
  - `SEQ = { s250: '#86b6ef', s450: '#2a78d6', s600: '#184f95' }`.
  - `STATUS = { good: '#0ca30c', warning: '#fab219', serious: '#ec835a', critical: '#d03b3b' }`.
  - `NEUTRAL = '#94a3b8'`, `GRID = '#e2e8f0'`, `AXIS = '#64748b'`, `INK = '#0f172a'`.
- Colour roles:
  - Stage latency: p50 = `SEQ.s450`, p95 = `SEQ.s250` (one hue, ordinal steps).
  - Volume stacks: ok = `SERIES[0]`, blocked = `STATUS.warning`, error = `STATUS.critical`, cancelled = `NEUTRAL`.
  - Latency trend: p50 = `SERIES[0]`, p95 = `SERIES[1]`.
  - Run comparison: slots `SERIES[0..3]`.
  - Text never takes the series colour. Labels and values use slate text classes.
- Components. All are SVG with `viewBox` and `width="100%"`, and wrapped in a `relative` container with an absolutely positioned tooltip div. Each takes an `ariaLabel` (`role="img"`) and renders a `<details><summary>View data table</summary><table>…</table></details>` beneath it for accessibility.
  - `Sparkline({ values, color? })`
  - `Meter({ value, label })`: fill `SEQ.s450` on a track of `#cde2fb`.
  - `LineChart({ xLabels, series: {key,label,color,values:(number|null)[]}[], yMax?, yFormat, height=220, ariaLabel })`
  - `StackedColumnChart({ xLabels, stacks, yFormat, height=220, ariaLabel })`
  - `GroupedBarChart({ categories, series, yMax=1, yFormat, height=240, ariaLabel })`
  - `HBarPairChart({ rows: {label, a, b, divider?}[], aLabel, bLabel, aColor, bColor, format, ariaLabel })`
- Mark specs:
  - Bars at most 24px thick, with a 4px rounded data end and a square baseline. Use helper paths `columnPath(x,y,w,h,r=4)` and `hbarPath(x,y,w,h,r=4)`.
  - 2px surface gap between stacked segments and adjacent bars.
  - Lines 2px with `strokeLinecap/Linejoin="round"`. End markers r=4 with a 2px white ring.
  - 1px solid `GRID` gridlines (never dashed). Y ticks at clean values: 0/0.25/0.5/0.75/1 for rates, rounded ms otherwise. Axis text is 10–11px `AXIS`.
  - At most one y-axis per chart.
- Interaction:
  - Line charts: a crosshair that snaps to the nearest x, with an invisible full-height hit rect per x band. The tooltip lists every series at that x: value in bold, series name secondary, keyed by a short line stroke.
  - Bars: each full band is the hit target (larger than the bar), and the hovered bar lightens.
  - The same tooltip also appears on keyboard focus (`tabIndex=0` on bands, `onFocus`).
  - A legend is always present for 2 or more series (a rect key for bars, a line key for lines). With 4 run series, direct-label the bar values at the tips when they fit.
- Build the tooltip DOM as React text nodes. Never use `dangerouslySetInnerHTML`, because labels such as masked queries and section names are untrusted.

### 4.6 Feedback in the existing chat and regulatory UIs
- **`lib/sse.ts`**: add `onTrace?: (traceId: string) => void;` to `QueryStreamHandlers`, and `case 'trace': handlers.onTrace?.(payload.content); break;` in `dispatch`.
- **`FeedbackControl.tsx`**: props `{ traceId: string; initialRating?: 1 | -1 | null; compact?: boolean }`.
  - Renders two icon buttons, `ThumbsUp` and `ThumbsDown`, with `aria-pressed`, a `title`, and the caption "Was this helpful?" (hidden when `compact`).
  - Clicking the current rating again calls `deleteRagFeedback`, which clears it.
  - 👍 calls `submitRagFeedback({trace_id, rating: 1})`.
  - 👎 immediately submits `rating: -1` and then expands an inline panel. The panel has tag chips (7 `FeedbackTag`s, multi-select) and a comment textarea (max 1000 characters, with a counter). "Send" re-submits with tags and comment; "Skip" closes the panel.
  - Updates are optimistic with rollback on error, and a small rose error line. Controls are disabled while a request is in flight. After a detailed submit, show "Thanks — feedback recorded."
  - Styling: `px-2 py-1 rounded-full border border-slate-200 bg-white text-slate-500 hover:border-indigo-300`. Active 👍 is `text-indigo-700 bg-indigo-50 border-indigo-200`; active 👎 is `text-rose-700 bg-rose-50 border-rose-200`.
- **`WorkspaceView.tsx`**. This is the exact place `/query` answers are rendered: `messages.map` at lines 681-755, where the AI bubble closes at line 732 and `suggestedActions` starts at 734.
  - In `handleSend`, declare `let pendingTraceId: string | undefined;` before `pushError` (next to `pendingSources`, lines 192-193).
  - Add `onTrace: (id) => { pendingTraceId = id; },` after `onSessionId` (line 215).
  - In `onDone`'s map (lines 232-243) add `traceId: pendingTraceId`.
  - In `pushError`'s map add `traceId: m.traceId ?? pendingTraceId`.
  - Render, inside the `max-w-[85%] space-y-2` container between the bubble `</div>` (line 732) and the suggested-actions block:
    `{msg.sender === 'ai' && msg.traceId && msg.timestamp && (<div className="pl-1"><FeedbackControl traceId={msg.traceId} compact /></div>)}`
    `timestamp` is only set after `done` or an error, so the control appears only once the trace has been saved.
- **`RegulatoryLibraryView.tsx`**:
  - Add `traceId?: string` to the `SearchResult` interface (lines 26-29).
  - In `handleSearch` (line 96) use `setSearchResult({ answer: dto.answer ?? '', citations, traceId: dto.trace_id ?? undefined })`.
  - Render `{searchResult.traceId && <FeedbackControl traceId={searchResult.traceId} />}` right after the answer box (after line 284).

### 4.7 Frontend verification
- `cd frontend && npm run lint && npm run build`. Both run `tsc --noEmit` under strict mode, so there must be no implicit `any` in new files.
- Manual checks against the backend at `localhost:8001` via the Vite proxy:
  1. Nav to RAG Performance shows the empty state.
  2. Ask 2 Regulatory Q&A questions, then 👍 one. The dashboard updates and the trace drawer shows the waterfall.
  3. Run an evaluation of all modes with 22 default cases. Progress polls, the comparison renders, and the case matrix opens the drawer.
  4. Add a custom case, run with "Selected cases", then delete the case. Historical results remain.

---

## 5. Parallelisation and integration checklist
- **No shared files**: the backend only touches `backend/**` and the frontend only touches `frontend/**`.
- **Contract freeze**: §2 is final. Any change must update both `schemas/rag_eval.py` and `lib/ragTypes.ts` in the same PR.
- The frontend can run before the backend exists: every call goes through `apiFetch`. Until the backend merges, the UI shows `ApiError` detail or empty states. `FeedbackControl` only renders when a `trace` id exists, and old backends never send one, so the chat UI is safe to merge first.
- Integration smoke test after both merge: `alembic upgrade head`, then the manual checks in §4.7, then the backend `pytest -q`.

---

## 6. Findings outside this scope, verified in code (recommend separate tickets)
1. **Privacy gap in production RAG.**
   - What: `/query` (`api/query.py:119-125`) and `/regulatory/search` (`api/regulatory.py:45-51`) call `retriever.retrieve(query=request.question)` **before** masking.
   - Why it matters: the raw question goes to NVIDIA/Gemini **embedding** (`dense_retriever.py:48`) and **rerank** (`nvidia_provider.py:229`, and the Gemini LLM-based rerank), with no egress validation. That breaks the AGENTS.md rules "no real entity names to LLMs" and "egress validator before any LLM call".
   - The evaluation runner in this plan deliberately retrieves with the masked question. The fix is to retrieve with `masked_question`.
   - Before shipping that fix, the new offline evaluation can measure its quality impact: run `hybrid_rerank` before and after.
2. BM25 returns **every** corpus item, including zero-score ones (`bm25.py:104-129` appends all indices). As a result `bm25_count` is always 10 for regulatory search, and the reranker scores irrelevant passages. Consider filtering `score > 0`; the new telemetry will make this visible.
3. Citation identity is inconsistent for document chunks. BM25 uses `doc-{uuid}` / `chunk-{i}`, while dense uses the filename and header (`hybrid_retriever.py:233-234` vs `documents.py:224`). The evaluation works around this with keyword and `chunk_index` targets, but users see two naming schemes.
4. `/regulatory/search` runs no input guardrails, unlike `/query`.
5. There is no per-endpoint rate-limit cost for `POST /rag/eval/runs`. The per-tenant single-run 409 and the 200-case cap bound the cost. Adding `cost = 5` in `middleware/rate_limiter.py` for `POST /rag/eval/runs` is optional hardening.
6. Real token usage is not available: providers return only strings. The traces store **estimates** (chars/4). The v2 path is to have providers stash `usage` (OpenAI `response.usage`, stream `stream_options={"include_usage": True}`, Gemini `usage_metadata`).

### Critical Files for Implementation
- /home/user/creditAudit/backend/app/services/retrieval/hybrid_retriever.py
- /home/user/creditAudit/backend/app/api/query.py
- /home/user/creditAudit/backend/app/services/llm/router.py
- /home/user/creditAudit/backend/app/api/regulatory.py
- /home/user/creditAudit/frontend/src/components/WorkspaceView.tsx
- /home/user/creditAudit/frontend/src/lib/sse.ts
- /home/user/creditAudit/frontend/src/App.tsx

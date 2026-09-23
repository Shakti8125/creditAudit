/**
 * RAG telemetry, feedback and offline-evaluation API contract.
 *
 * FROZEN: copied verbatim from the shared contract (rag_plan.md section 2.5). It must stay
 * field-for-field identical to backend/app/schemas/rag_eval.py; change both together.
 * DTOs are snake_case exactly as sent by the backend (no adapter layer).
 */

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

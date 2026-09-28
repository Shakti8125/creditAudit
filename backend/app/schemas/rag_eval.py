"""Pydantic schemas for RAG telemetry, feedback and offline evaluation.

These models are the backend half of the frozen API contract; they must stay
field-for-field identical to ``frontend/src/lib/ragTypes.ts``.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.retrieval import RetrievalMode

RagWindow = Literal["24h", "7d", "30d", "90d"]
EndpointFilter = Literal["all", "query", "regulatory_search"]
TraceStatusFilter = Literal["all", "ok", "error", "blocked", "cancelled"]
FeedbackTag = Literal[
    "irrelevant_sources", "wrong_citation", "hallucination", "incomplete", "outdated", "too_slow", "other"
]
JudgeMode = Literal["auto", "deterministic"]
RunStatus = Literal["pending", "running", "completed", "failed", "cancelled"]
StageName = Literal["masking", "dense", "bm25", "fusion", "rerank", "retrieval", "generation", "ttft", "total"]

MAX_KEYWORD_CHARS = 80


def _strip_or_none(value: Any) -> Any:
    """Strip strings and turn blank strings into None; pass anything else through."""
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return value


class _Base(BaseModel):
    """Common config for every RAG schema."""

    model_config = ConfigDict(from_attributes=True)


# --------------------------------------------------------------------------- telemetry


class TelemetryKpis(_Base):
    """Headline KPIs of the telemetry dashboard (RagKpis)."""

    total_requests: int
    ok_count: int
    error_count: int
    blocked_count: int
    cancelled_count: int
    error_rate: float | None
    blocked_rate: float | None
    llm_fallback_rate: float | None
    rerank_fallback_rate: float | None
    dense_empty_rate: float | None
    p50_total_ms: float | None
    p95_total_ms: float | None
    p50_ttft_ms: float | None
    p95_ttft_ms: float | None
    avg_top_score_norm: float | None
    avg_groundedness: float | None
    citation_rate: float | None
    avg_citations: float | None
    feedback_count: int
    satisfaction_rate: float | None
    est_prompt_tokens: int
    est_completion_tokens: int


class StageLatency(_Base):
    """Latency distribution of one pipeline stage (RagStageLatency)."""

    stage: StageName
    kind: Literal["component", "composite"]
    count: int
    p50_ms: float | None
    p95_ms: float | None
    avg_ms: float | None


class EndpointBreakdown(_Base):
    """Per-endpoint summary (RagEndpointBreakdown)."""

    endpoint: Literal["query", "regulatory_search"]
    count: int
    error_rate: float | None
    p50_total_ms: float | None
    p95_total_ms: float | None
    avg_groundedness: float | None
    satisfaction_rate: float | None


class ProviderShare(_Base):
    """Share of generation calls served by a provider/model (RagProviderShare)."""

    provider: str
    model: str
    count: int
    share: float


class ScoreKindStat(_Base):
    """Top-score statistics per scorer kind (RagScoreKindStat)."""

    kind: str
    count: int
    avg_top_score: float | None
    avg_top_score_norm: float | None


class TimeseriesPoint(_Base):
    """One zero-filled time bucket (RagTimeseriesPoint)."""

    bucket_start: datetime
    count: int
    ok_count: int
    error_count: int
    blocked_count: int
    cancelled_count: int
    fallback_count: int
    p50_total_ms: float | None
    p95_total_ms: float | None
    avg_groundedness: float | None
    thumbs_up: int
    thumbs_down: int


class FeedbackTagCount(_Base):
    """Count of one feedback tag (RagFeedbackTagCount)."""

    tag: str
    count: int


class FeedbackItem(_Base):
    """A recent feedback entry (RagFeedbackItem)."""

    id: uuid.UUID
    trace_id: uuid.UUID
    rating: int
    comment: str | None
    tags: list[str]
    endpoint: str | None
    query_masked: str | None
    created_at: datetime


class FeedbackSummary(_Base):
    """Feedback aggregate for the dashboard window (RagFeedbackSummary)."""

    total: int
    thumbs_up: int
    thumbs_down: int
    satisfaction_rate: float | None
    tag_counts: list[FeedbackTagCount]
    recent: list[FeedbackItem]


class RagDashboardResponse(_Base):
    """GET /rag/telemetry/dashboard (RagDashboard)."""

    window: RagWindow
    endpoint: EndpointFilter
    from_ts: datetime
    to_ts: datetime
    bucket: Literal["hour", "day"]
    sampled: bool
    kpis: TelemetryKpis
    stages: list[StageLatency]
    by_endpoint: list[EndpointBreakdown]
    providers: list[ProviderShare]
    score_kinds: list[ScoreKindStat]
    timeseries: list[TimeseriesPoint]
    feedback: FeedbackSummary


class RetrievedScore(_Base):
    """A retrieved (or pre-rerank) passage score without text (RagRetrievedScore)."""

    rank: int
    source: str
    section: str
    score: float
    retrieval_method: str


class LlmCallInfo(_Base):
    """One provider attempt (RagLlmCall)."""

    method: str
    provider: str
    model: str
    latency_ms: float
    success: bool
    attempt: int
    error_type: str | None = None


class TraceListItem(_Base):
    """Row of GET /rag/traces (RagTraceListItem)."""

    id: uuid.UUID
    created_at: datetime
    endpoint: str
    status: str
    query_masked: str | None
    document_id: uuid.UUID | None
    retrieval_mode: str
    total_ms: float | None
    retrieval_ms: float | None
    generation_ms: float | None
    ttft_ms: float | None
    citation_count: int
    answer_citation_count: int
    top_score: float | None
    top_score_norm: float | None
    score_kind: str | None
    groundedness: float | None
    provider: str | None
    model: str | None
    llm_fallback_used: bool
    guardrail_reason: str | None
    error_stage: str | None
    feedback_up: int = 0
    feedback_down: int = 0


class TraceListResponse(_Base):
    """GET /rag/traces (RagTraceList)."""

    total: int
    limit: int
    offset: int
    items: list[TraceListItem]


class TraceFeedbackEntry(_Base):
    """Feedback attached to a trace (RagTraceFeedbackEntry)."""

    id: uuid.UUID
    rating: int
    comment: str | None
    tags: list[str]
    created_at: datetime
    is_mine: bool


class TraceDetailResponse(TraceListItem):
    """GET /rag/traces/{id} (RagTraceDetail)."""

    session_id: uuid.UUID | None
    chat_message_id: uuid.UUID | None
    document_filename: str | None
    top_k: int
    query_chars: int
    answer_preview: str | None
    masking_ms: float | None
    dense_ms: float | None
    bm25_ms: float | None
    fusion_ms: float | None
    rerank_ms: float | None
    dense_count: int
    bm25_count: int
    fused_count: int
    reranked_count: int
    mean_score: float | None
    rerank_applied: bool
    rerank_fallback: bool
    dense_empty: bool
    scores: list[RetrievedScore]
    fused_scores: list[RetrievedScore]
    llm_calls: list[LlmCallInfo]
    est_prompt_tokens: int | None
    est_completion_tokens: int | None
    guardrail_blocked: bool
    output_guardrail_reason: str | None
    error_type: str | None
    feedback: list[TraceFeedbackEntry]
    my_rating: int | None


class FeedbackCreate(_Base):
    """POST /rag/feedback body (RagFeedbackInput)."""

    trace_id: uuid.UUID
    rating: Literal[1, -1]
    comment: str | None = Field(default=None, max_length=1000)
    tags: list[FeedbackTag] = Field(default_factory=list, max_length=7)

    @field_validator("comment", mode="before")
    @classmethod
    def _clean_comment(cls, value: Any) -> Any:
        """Strip the comment; blank becomes None."""
        return _strip_or_none(value)

    @field_validator("tags")
    @classmethod
    def _dedupe_tags(cls, value: list[str]) -> list[str]:
        """Remove duplicate tags preserving order."""
        return list(dict.fromkeys(value))


class FeedbackResponse(_Base):
    """POST /rag/feedback response (RagFeedbackRecord)."""

    id: uuid.UUID
    trace_id: uuid.UUID
    rating: int
    comment: str | None
    tags: list[str]
    created_at: datetime
    updated_at: datetime


# --------------------------------------------------------------------------- eval dataset


class ExpectedRef(_Base):
    """One relevance target of a golden case (EvalExpectedRef)."""

    source: str | None = Field(default=None, max_length=200)
    section: str | None = Field(default=None, max_length=300)
    keywords: list[str] = Field(default_factory=list, max_length=12)
    min_keyword_hits: int | None = Field(default=None, ge=1, le=12)
    chunk_index: int | None = Field(default=None, ge=0)

    @field_validator("source", "section", mode="before")
    @classmethod
    def _clean_label(cls, value: Any) -> Any:
        """Strip labels; blank becomes None."""
        return _strip_or_none(value)

    @field_validator("keywords")
    @classmethod
    def _clean_keywords(cls, value: list[str]) -> list[str]:
        """Strip, drop empties, cap length and dedupe case-insensitively."""
        cleaned: list[str] = []
        seen: set[str] = set()
        for raw in value:
            keyword = raw.strip()
            if not keyword:
                continue
            if len(keyword) > MAX_KEYWORD_CHARS:
                raise ValueError(f"keywords must be at most {MAX_KEYWORD_CHARS} characters")
            key = keyword.casefold()
            if key in seen:
                continue
            seen.add(key)
            cleaned.append(keyword)
        return cleaned

    @model_validator(mode="after")
    def _check_target(self) -> ExpectedRef:
        """Require at least one matching criterion and a consistent keyword threshold."""
        if not (self.source or self.section or self.keywords or self.chunk_index is not None):
            raise ValueError("expected_ref needs a source, section, keywords or chunk_index")
        if self.min_keyword_hits is not None:
            if not self.keywords:
                raise ValueError("min_keyword_hits requires keywords")
            if self.min_keyword_hits > len(self.keywords):
                raise ValueError("min_keyword_hits cannot exceed the number of keywords")
        return self


def _clean_question(value: Any) -> Any:
    """Strip surrounding whitespace from a question (validation happens afterwards)."""
    return value.strip() if isinstance(value, str) else value


class EvalCaseCreate(_Base):
    """POST /rag/eval/cases body (EvalCaseInput)."""

    question: str = Field(min_length=5, max_length=1000)
    reference_answer: str | None = Field(default=None, max_length=4000)
    document_id: uuid.UUID | None = None
    expected_refs: list[ExpectedRef] = Field(min_length=1, max_length=10)
    is_active: bool = True

    @field_validator("question", mode="before")
    @classmethod
    def _strip_question(cls, value: Any) -> Any:
        """Strip the question."""
        return _clean_question(value)

    @field_validator("reference_answer", mode="before")
    @classmethod
    def _clean_reference(cls, value: Any) -> Any:
        """Strip the reference answer; blank becomes None."""
        return _strip_or_none(value)

    @model_validator(mode="after")
    def _chunk_targets_need_document(self) -> EvalCaseCreate:
        """chunk_index targets only make sense for a document-scoped case."""
        if self.document_id is None and any(ref.chunk_index is not None for ref in self.expected_refs):
            raise ValueError("chunk_index targets require a document_id")
        return self


class EvalCaseUpdate(_Base):
    """PATCH /rag/eval/cases/{id} body (partial EvalCaseInput).

    The endpoint uses ``model_fields_set`` to distinguish omitted fields from an
    explicit null (``document_id: null`` clears the document scope).
    """

    question: str | None = Field(default=None, min_length=5, max_length=1000)
    reference_answer: str | None = Field(default=None, max_length=4000)
    document_id: uuid.UUID | None = None
    expected_refs: list[ExpectedRef] | None = Field(default=None, min_length=1, max_length=10)
    is_active: bool | None = None

    @field_validator("question", mode="before")
    @classmethod
    def _strip_question(cls, value: Any) -> Any:
        """Strip the question."""
        return _clean_question(value)

    @field_validator("reference_answer", mode="before")
    @classmethod
    def _clean_reference(cls, value: Any) -> Any:
        """Strip the reference answer; blank becomes None."""
        return _strip_or_none(value)


class EvalCaseResponse(_Base):
    """A golden case (EvalCase)."""

    id: uuid.UUID
    question: str
    reference_answer: str | None
    document_id: uuid.UUID | None
    document_filename: str | None
    expected_refs: list[ExpectedRef]
    origin: Literal["default", "custom"]
    default_key: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class EvalCaseListResponse(_Base):
    """GET /rag/eval/cases (EvalCaseList)."""

    total: int
    cases: list[EvalCaseResponse]


class RestoreDefaultsResponse(_Base):
    """POST /rag/eval/cases/restore-defaults (RestoreDefaultsResult)."""

    inserted: int
    total: int


# --------------------------------------------------------------------------- eval runs


class EvalRunCreate(_Base):
    """POST /rag/eval/runs body (EvalRunCreateInput)."""

    modes: list[RetrievalMode] = Field(
        default_factory=lambda: [RetrievalMode.HYBRID_RERANK], min_length=1, max_length=4
    )
    top_k: int = Field(default=5, ge=1, le=20)
    include_generation: bool = False
    judge: JudgeMode = "auto"
    case_ids: list[uuid.UUID] | None = Field(default=None, max_length=200)
    label: str | None = Field(default=None, max_length=120)

    @field_validator("modes")
    @classmethod
    def _dedupe_modes(cls, value: list[RetrievalMode]) -> list[RetrievalMode]:
        """Remove duplicate modes preserving order."""
        return list(dict.fromkeys(value))

    @field_validator("label", mode="before")
    @classmethod
    def _clean_label(cls, value: Any) -> Any:
        """Strip the label; blank becomes None."""
        return _strip_or_none(value)


class EvalRunMetrics(_Base):
    """Aggregate metrics of a run (EvalRunMetrics)."""

    hit_rate: float | None = None
    recall: float | None = None
    precision: float | None = None
    mrr: float | None = None
    ndcg: float | None = None
    faithfulness: float | None = None
    answer_relevance: float | None = None
    answer_correctness: float | None = None
    p50_latency_ms: float | None = None
    p95_latency_ms: float | None = None


class EvalRunSummary(_Base):
    """A run in lists and create responses (EvalRunSummary)."""

    id: uuid.UUID
    group_id: uuid.UUID
    label: str | None
    status: RunStatus
    mode: RetrievalMode
    top_k: int
    include_generation: bool
    judge: JudgeMode
    total_cases: int
    completed_cases: int
    failed_cases: int
    progress: float
    metrics: EvalRunMetrics
    error_message: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class EvalRunCreateResponse(_Base):
    """POST /rag/eval/runs response (EvalRunCreateResponse)."""

    group_id: uuid.UUID
    estimated_llm_calls: int
    runs: list[EvalRunSummary]


class EvalRunListResponse(_Base):
    """GET /rag/eval/runs (EvalRunList)."""

    total: int
    runs: list[EvalRunSummary]


class MetricCurves(_Base):
    """Mean metric@k curves (EvalMetricCurves)."""

    k: list[int]
    hit: list[float]
    recall: list[float]
    precision: list[float]
    ndcg: list[float]


class JudgeBreakdown(_Base):
    """How answers were judged (EvalJudgeBreakdown)."""

    llm: int = 0
    deterministic: int = 0
    none: int = 0


class DegradedCounts(_Base):
    """Cases evaluated under degraded retrieval (EvalDegradedCounts)."""

    dense_empty: int = 0
    rerank_fallback: int = 0
    unresolved_chunk_targets: int = 0


class EvalRunDetail(EvalRunSummary):
    """GET /rag/eval/runs/{id} (EvalRunDetail)."""

    curves: MetricCurves | None
    judge_breakdown: JudgeBreakdown
    degraded: DegradedCounts
    case_ids: list[uuid.UUID]
    generation_temperature: float | None


class RetrievedItemResult(_Base):
    """A retrieved passage with its relevance verdict (EvalRetrievedItem)."""

    rank: int
    source: str
    section: str
    score: float
    retrieval_method: str
    relevant: bool
    matched_targets: list[int]
    snippet: str


class EvalCaseDiagnostics(_Base):
    """Retrieval diagnostics of one evaluated case (EvalCaseDiagnostics)."""

    mode: RetrievalMode
    dense_ms: float | None
    bm25_ms: float | None
    fusion_ms: float | None
    rerank_ms: float | None
    dense_count: int
    bm25_count: int
    fused_count: int
    final_count: int
    rerank_applied: bool
    rerank_fallback: bool
    dense_empty: bool
    unresolved_chunk_targets: int = 0


class EvalCaseResultResponse(_Base):
    """Per-case result (EvalCaseResult)."""

    id: uuid.UUID
    case_id: uuid.UUID
    position: int
    status: Literal["ok", "error"]
    question_masked: str | None
    document_id: uuid.UUID | None
    n_targets: int
    targets_matched: int
    hit: bool | None
    first_relevant_rank: int | None
    recall: float | None
    precision: float | None
    reciprocal_rank: float | None
    ndcg: float | None
    retrieved: list[RetrievedItemResult]
    answer: str | None
    faithfulness: float | None
    answer_relevance: float | None
    answer_correctness: float | None
    judge_method: Literal["llm", "deterministic", "none"]
    judge_rationale: str | None
    retrieval_ms: float | None
    generation_ms: float | None
    judge_ms: float | None
    diagnostics: EvalCaseDiagnostics | None
    error_type: str | None
    error_stage: str | None
    created_at: datetime


class EvalRunResultsResponse(_Base):
    """GET /rag/eval/runs/{id}/results (EvalRunResults)."""

    run_id: uuid.UUID
    results: list[EvalCaseResultResponse]

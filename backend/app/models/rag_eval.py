"""ORM models for RAG telemetry, user feedback and offline evaluation."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
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
    # No FK: documents can be deleted while their traces are retained.
    document_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
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
    error_type: Mapped[str | None] = mapped_column(String(128), nullable=True)  # class name only
    error_stage: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utc_now, index=True, nullable=False)


class RagFeedback(Base):
    """Thumbs up/down (+ optional masked comment and tags) on a trace; one vote per user per trace."""

    __tablename__ = "rag_feedback"
    __table_args__ = (UniqueConstraint("trace_id", "user_id", name="uq_rag_feedback_trace_user"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), index=True, nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    trace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("rag_traces.id", ondelete="CASCADE"), index=True, nullable=False
    )
    chat_message_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    rating: Mapped[int] = mapped_column(SmallInteger, nullable=False)  # +1 / -1
    comment_masked: Mapped[str | None] = mapped_column(Text, nullable=True)
    tags_json: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utc_now, index=True, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utc_now, onupdate=_utc_now, nullable=False)


class RagEvalCase(Base):
    """A golden evaluation case (question + relevance targets + optional reference answer)."""

    __tablename__ = "rag_eval_cases"
    __table_args__ = (
        UniqueConstraint("tenant_id", "default_key", name="uq_rag_eval_cases_tenant_default_key"),
    )

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
    status: Mapped[str] = mapped_column(
        String(16), index=True, default=EvalRunStatus.PENDING.value, nullable=False
    )
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
    # curves, judge_breakdown, degraded, generation_temperature
    metrics_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utc_now, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class RagEvalResult(Base):
    """Per-case outcome inside an evaluation run."""

    __tablename__ = "rag_eval_results"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("rag_eval_runs.id", ondelete="CASCADE"), index=True, nullable=False
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), index=True, nullable=False)
    # No FK: cases may be deleted later while historical results are kept.
    case_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), index=True, nullable=False)
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

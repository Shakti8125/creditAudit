"""RAG request telemetry: per-request trace recorder, persistence and read queries.

``RagTraceRecorder`` accumulates stage timings, retrieval diagnostics, LLM call
records and answer-quality proxies for one ``/query`` or ``/regulatory/search``
request, then persists a single ``RagTrace`` row. Persistence never raises: a
telemetry failure is logged and the user request carries on.

Privacy: only MASKED query text is ever stored. ``set_masked_query`` must be called
only after the egress validator passed; failure paths use ``mask_for_telemetry``,
which returns None (store nothing) whenever masking or egress validation fails.
"""

from __future__ import annotations

import logging
import time
import uuid
from contextlib import contextmanager
from datetime import datetime
from typing import Any, AsyncIterator, Iterator, Literal, Sequence

import anyio
from sqlalchemy import case, delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.config import settings
from app.db.database import async_session_maker
from app.models.document import Document
from app.models.rag_eval import RagFeedback, RagTrace, TraceEndpoint, TraceStatus
from app.models.user import _utc_now
from app.schemas.rag_eval import (
    FeedbackCreate,
    FeedbackResponse,
    LlmCallInfo,
    RagDashboardResponse,
    RetrievedScore,
    TraceDetailResponse,
    TraceFeedbackEntry,
    TraceListItem,
    TraceListResponse,
)
from app.schemas.retrieval import RetrievalMode, RetrievalResult
from app.services.evaluation.dashboard import FeedbackRow, TraceRow, aggregate_dashboard, bucket_starts
from app.services.evaluation.metrics import (
    classify_score_kind,
    count_inline_citations,
    estimate_tokens,
    groundedness,
    mean_or_none,
    normalize_score,
)
from app.services.privacy.egress_validator import EgressValidator, EgressViolationError
from app.services.privacy.masking_pipeline import MaskingPipeline

logger = logging.getLogger(__name__)

ANSWER_PREVIEW_CHARS = 2000
DASHBOARD_MAX_TRACES = 20000
DASHBOARD_MAX_FEEDBACK = 20000
StageKey = Literal["masking", "retrieval", "generation"]


def _elapsed_ms(t0: float) -> float:
    """Milliseconds since a ``time.perf_counter()`` reading."""
    return (time.perf_counter() - t0) * 1000.0


async def mask_for_telemetry(text: str) -> str | None:
    """Mask and egress-validate text for storage.

    Args:
        text: Raw user text (query or feedback comment).

    Returns:
        The masked text, or None on ANY failure so a possible leak is never stored.
    """
    if not text:
        return None
    try:
        masked, registry = await run_in_threadpool(MaskingPipeline().mask_document, text)
        await run_in_threadpool(EgressValidator().validate, masked, registry)
        return masked
    except Exception as exc:  # noqa: BLE001 - masking/egress failures must never store raw text
        logger.warning("Telemetry masking failed (%s); text not stored", type(exc).__name__)
        return None


class RagTraceRecorder:
    """Per-request accumulator for a RAG trace; persistence never raises.

    Attributes:
        trace_id: UUID of the trace row (sent to the client before persistence).
        session_id: Chat session of a ``/query`` request, if any.
        chat_message_id: Assistant ChatMessage the trace belongs to, if persisted.
    """

    def __init__(
        self,
        *,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        endpoint: TraceEndpoint,
        top_k: int,
        document_id: uuid.UUID | None = None,
        session_id: uuid.UUID | None = None,
        retrieval_mode: RetrievalMode = RetrievalMode.HYBRID_RERANK,
    ) -> None:
        """Start the request clock and initialise the trace fields.

        Args:
            tenant_id: Tenant of the authenticated user.
            user_id: Authenticated user.
            endpoint: RAG surface being traced.
            top_k: Requested number of citations.
            document_id: Optional document scope.
            session_id: Optional chat session.
            retrieval_mode: Retrieval pipeline configuration.
        """
        self.trace_id: uuid.UUID = uuid.uuid4()
        self.session_id: uuid.UUID | None = session_id
        self.chat_message_id: uuid.UUID | None = None
        self._t0 = time.perf_counter()
        self._persisted = False
        self._answered = False
        self._top_method: str | None = None
        self._rerank_provider: str | None = None
        self._fields: dict[str, Any] = {
            "tenant_id": tenant_id,
            "user_id": user_id,
            "endpoint": endpoint.value,
            "status": TraceStatus.OK.value,
            "document_id": document_id,
            "retrieval_mode": retrieval_mode.value,
            "top_k": top_k,
            "query_masked": None,
            "query_chars": 0,
        }

    # ------------------------------------------------------------------ state

    @property
    def status(self) -> str:
        """Current trace status (``ok``, ``error``, ``blocked`` or ``cancelled``)."""
        return str(self._fields["status"])

    @property
    def has_masked_query(self) -> bool:
        """Whether an egress-validated masked query has been recorded."""
        return self._fields.get("query_masked") is not None

    def trace_event(self) -> dict[str, str]:
        """SSE event announcing the trace id (sent right after ``session_id``)."""
        return {"type": "trace", "content": str(self.trace_id)}

    @contextmanager
    def stage(self, name: StageKey) -> Iterator[None]:
        """Time a pipeline stage, accumulating into ``{name}_ms``.

        Masking is entered several times per request, so durations add up. An
        exception escaping the block records ``error_stage`` (if unset) and is re-raised.

        Args:
            name: Stage name.

        Yields:
            None.
        """
        key = f"{name}_ms"
        t0 = time.perf_counter()
        try:
            yield
        except Exception:
            self._fields.setdefault("error_stage", name)
            raise
        finally:
            self._fields[key] = (self._fields.get(key) or 0.0) + _elapsed_ms(t0)

    # ------------------------------------------------------------------ recording

    def set_masked_query(self, masked_query: str, raw_length: int) -> None:
        """Record the masked query. Call ONLY after egress validation passed.

        Args:
            masked_query: Egress-validated masked text.
            raw_length: Length of the raw question (characters, not stored text).
        """
        self._fields["query_masked"] = masked_query
        self._fields["query_chars"] = raw_length

    def record_retrieval(self, result: RetrievalResult) -> None:
        """Copy retrieval diagnostics, counts and score summaries.

        Args:
            result: Output of ``HybridRetriever.retrieve``.
        """
        try:
            citations = result.citations
            diag = result.diagnostics
            if diag is not None:
                self._fields.update(
                    retrieval_mode=diag.mode.value,
                    dense_ms=diag.dense_ms,
                    bm25_ms=diag.bm25_ms,
                    fusion_ms=diag.fusion_ms,
                    rerank_ms=diag.rerank_ms,
                    dense_count=diag.dense_count,
                    bm25_count=diag.bm25_count,
                    fused_count=diag.fused_count,
                    reranked_count=diag.final_count,
                    rerank_applied=diag.rerank_applied,
                    rerank_fallback=diag.rerank_fallback,
                    dense_empty=diag.dense_empty,
                    fused_scores_json=[
                        {
                            "rank": i + 1,
                            "source": p.source,
                            "section": p.section,
                            "score": p.score,
                            "retrieval_method": p.retrieval_method,
                        }
                        for i, p in enumerate(diag.fused_preview)
                    ],
                )
            else:
                meta = result.retrieval_metadata or {}
                self._fields.update(
                    dense_count=int(meta.get("dense_count", 0) or 0),
                    bm25_count=int(meta.get("bm25_count", 0) or 0),
                    fused_count=int(meta.get("fused_count", 0) or 0),
                    reranked_count=int(meta.get("reranked_count", len(citations)) or 0),
                )
            self._fields["citation_count"] = len(citations)
            self._fields["scores_json"] = [
                {
                    "rank": i + 1,
                    "source": c.source,
                    "section": c.section,
                    "score": c.score,
                    "retrieval_method": c.retrieval_method,
                }
                for i, c in enumerate(citations)
            ]
            if citations:
                self._fields["top_score"] = citations[0].score
                self._fields["mean_score"] = mean_or_none(c.score for c in citations)
                self._top_method = citations[0].retrieval_method
        except Exception as exc:  # noqa: BLE001 - telemetry must never break a user request
            logger.warning("Failed to record retrieval telemetry (%s)", type(exc).__name__)

    def record_prompt(self, prompt: str, system_prompt: str) -> None:
        """Record the estimated prompt size.

        Args:
            prompt: Final (masked, egress-validated) user prompt.
            system_prompt: System prompt.
        """
        self._fields["est_prompt_tokens"] = estimate_tokens((system_prompt or "") + (prompt or ""))

    def mark_first_token(self) -> None:
        """Record time-to-first-token since request start (idempotent)."""
        if self._fields.get("ttft_ms") is None:
            self._fields["ttft_ms"] = _elapsed_ms(self._t0)

    async def track_stream(self, stream: AsyncIterator[str]) -> AsyncIterator[str]:
        """Pass a token stream through, timing generation and time-to-first-token.

        A provider exception marks the trace as errored at stage ``generation``
        and is re-raised unchanged.

        Args:
            stream: Token stream from ``LLMRouter.generate_stream``.

        Yields:
            The stream's chunks, unchanged.
        """
        with self.stage("generation"):
            try:
                async for chunk in stream:
                    self.mark_first_token()
                    yield chunk
            except Exception as exc:
                self.mark_error(exc, stage="generation")
                raise

    def record_answer(self, answer: str, contexts: Sequence[str]) -> None:
        """Record the answer preview and quality proxies.

        Args:
            answer: Generated answer (produced from masked input).
            contexts: Retrieved context strings shown to the model.
        """
        self._answered = True
        try:
            self._fields["answer_preview"] = (answer or "")[:ANSWER_PREVIEW_CHARS]
            self._fields["answer_citation_count"] = count_inline_citations(answer or "")
            self._fields["groundedness"] = groundedness(answer or "", contexts)
            self._fields["est_completion_tokens"] = estimate_tokens(answer or "")
        except Exception as exc:  # noqa: BLE001 - telemetry must never break a user request
            logger.warning("Failed to record answer telemetry (%s)", type(exc).__name__)

    def record_llm_calls(self, call_log: Sequence[Any]) -> None:
        """Copy the router's provider call log and derive provider/model/failover.

        Args:
            call_log: ``LLMRouter.call_log`` (ProviderCallRecord items).
        """
        try:
            if not isinstance(call_log, (list, tuple)):
                return
            records = list(call_log)
            self._fields["llm_calls_json"] = [r.to_dict() for r in records]
            generation = [
                r for r in records if r.success and r.method in ("generate", "generate_stream")
            ]
            if generation:
                self._fields["provider"] = generation[-1].provider
                self._fields["model"] = generation[-1].model
            self._fields["llm_fallback_used"] = any(r.success and r.attempt > 0 for r in records)
            reranks = [r for r in records if r.success and r.method == "rerank"]
            if reranks:
                self._rerank_provider = reranks[-1].provider
        except Exception as exc:  # noqa: BLE001 - telemetry must never break a user request
            logger.warning("Failed to record LLM call telemetry (%s)", type(exc).__name__)

    def mark_blocked(self, reason: str) -> None:
        """Mark the request as blocked by a guardrail.

        Args:
            reason: Stable guardrail reason slug.
        """
        self._fields["status"] = TraceStatus.BLOCKED.value
        self._fields["guardrail_blocked"] = True
        self._fields["guardrail_reason"] = (reason or "")[:64] or None

    def mark_output_flag(self, reason: str) -> None:
        """Record an output-guardrail flag (status unchanged: the /query rail is log-only).

        Args:
            reason: Stable guardrail reason slug.
        """
        self._fields["output_guardrail_reason"] = (reason or "")[:64] or None

    def mark_error(self, exc: BaseException, stage: str | None = None) -> None:
        """Mark the request as failed. Stores the exception CLASS name only.

        Egress reports embed entity names, so ``str(exc)`` is never stored; an
        egress violation is recorded as a ``blocked`` trace instead.

        Args:
            exc: The exception.
            stage: Stage where it happened (defaults to the stage already recorded).
        """
        if isinstance(exc, EgressViolationError):
            self.mark_blocked("egress_violation")
            return
        self._fields["status"] = TraceStatus.ERROR.value
        self._fields["error_type"] = type(exc).__name__[:128]
        self._fields["error_stage"] = stage or self._fields.get("error_stage") or "unknown"

    def mark_cancelled(self) -> None:
        """Mark the request as cancelled (client disconnected mid-stream)."""
        self._fields["status"] = TraceStatus.CANCELLED.value

    # ------------------------------------------------------------------ hooks

    async def _ensure_masked_query(self, raw_query: str) -> None:
        """Mask the raw query for storage when no validated masked query exists yet."""
        if self.has_masked_query or not raw_query:
            return
        masked = await mask_for_telemetry(raw_query)
        if masked is not None:
            self.set_masked_query(masked, raw_length=len(raw_query))

    async def record_blocked(self, reason: str, raw_query: str) -> None:
        """Record and persist an input-guardrail block (the request raises 400 next).

        Args:
            reason: Guardrail reason slug.
            raw_query: Raw question (masked before storage, never stored raw).
        """
        self.mark_blocked(reason)
        await self._ensure_masked_query(raw_query)
        await self.persist()

    async def record_failure(self, exc: BaseException, raw_query: str, stage: str | None = None) -> None:
        """Mark an error and make sure a masked query is attached (does not persist).

        Args:
            exc: The exception that aborted the request.
            raw_query: Raw question (masked before storage, never stored raw).
            stage: Optional stage override.
        """
        self.mark_error(exc, stage)
        await self._ensure_masked_query(raw_query)

    async def finish(self, llm_router: Any | None = None) -> None:
        """Terminal hook: finalise, persist the trace and close the router.

        A request that never recorded an answer while still ``ok`` was cancelled
        (client disconnect). Persistence and ``aclose`` are shielded from anyio
        cancellation, which Starlette uses on disconnect.

        Args:
            llm_router: The request's LLMRouter (its call log is captured, then it is closed).
        """
        if not self._answered and self.status == TraceStatus.OK.value:
            self.mark_cancelled()
        if llm_router is not None:
            self.record_llm_calls(getattr(llm_router, "call_log", []))
        with anyio.CancelScope(shield=True):
            await self.persist()
            if llm_router is not None:
                await llm_router.aclose()

    # ------------------------------------------------------------------ persistence

    def build(self) -> RagTrace:
        """Build the ORM row from the accumulated fields.

        Returns:
            An unsaved RagTrace.
        """
        fields = dict(self._fields)
        if fields.get("total_ms") is None:
            fields["total_ms"] = _elapsed_ms(self._t0)
        score_kind = classify_score_kind(self._top_method, self._rerank_provider)
        fields["score_kind"] = score_kind
        fields["top_score_norm"] = normalize_score(score_kind, fields.get("top_score"))
        return RagTrace(
            id=self.trace_id,
            session_id=self.session_id,
            chat_message_id=self.chat_message_id,
            created_at=_utc_now(),
            **fields,
        )

    async def persist(self) -> None:
        """Save the trace once. Never raises; failures are logged by class name only."""
        if self._persisted or not settings.rag_telemetry_enabled:
            return
        self._persisted = True
        try:
            async with async_session_maker() as session:
                session.add(self.build())
                await session.commit()
        except Exception as exc:  # noqa: BLE001 - telemetry must never break a user request
            logger.warning("Failed to persist RAG trace %s (%s)", self.trace_id, type(exc).__name__)


# ---------------------------------------------------------------------- read queries

_TRACE_ROW_COLUMNS = (
    RagTrace.created_at,
    RagTrace.endpoint,
    RagTrace.status,
    RagTrace.masking_ms,
    RagTrace.dense_ms,
    RagTrace.bm25_ms,
    RagTrace.fusion_ms,
    RagTrace.rerank_ms,
    RagTrace.retrieval_ms,
    RagTrace.generation_ms,
    RagTrace.ttft_ms,
    RagTrace.total_ms,
    RagTrace.citation_count,
    RagTrace.answer_citation_count,
    RagTrace.top_score,
    RagTrace.top_score_norm,
    RagTrace.score_kind,
    RagTrace.groundedness,
    RagTrace.provider,
    RagTrace.model,
    RagTrace.llm_fallback_used,
    RagTrace.rerank_applied,
    RagTrace.rerank_fallback,
    RagTrace.dense_empty,
    RagTrace.retrieval_mode,
    RagTrace.fused_count,
    RagTrace.est_prompt_tokens,
    RagTrace.est_completion_tokens,
)


def _window_start(window: str, now: datetime) -> datetime:
    """Aligned start of the first dashboard bucket for a window."""
    return bucket_starts(window, now)[0]


async def load_dashboard(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    window: str,
    endpoint: str,
    now: datetime | None = None,
) -> RagDashboardResponse:
    """Load tenant trace/feedback rows for the window and aggregate them.

    Args:
        db: Async session.
        tenant_id: Tenant from the JWT.
        window: ``24h``, ``7d``, ``30d`` or ``90d``.
        endpoint: ``all`` or a RagEndpoint.
        now: Override of the current naive-UTC time (tests).

    Returns:
        RagDashboardResponse.
    """
    now = now or _utc_now()
    from_ts = _window_start(window, now)

    trace_stmt = select(*_TRACE_ROW_COLUMNS).where(
        RagTrace.tenant_id == tenant_id, RagTrace.created_at >= from_ts
    )
    if endpoint != "all":
        trace_stmt = trace_stmt.where(RagTrace.endpoint == endpoint)
    trace_stmt = trace_stmt.order_by(RagTrace.created_at.desc()).limit(DASHBOARD_MAX_TRACES + 1)
    trace_rows = (await db.execute(trace_stmt)).all()
    sampled = len(trace_rows) > DASHBOARD_MAX_TRACES
    traces = [TraceRow(**row._asdict()) for row in trace_rows[:DASHBOARD_MAX_TRACES]]

    feedback_stmt = (
        select(
            RagFeedback.id,
            RagFeedback.trace_id,
            RagFeedback.rating,
            RagFeedback.comment_masked,
            RagFeedback.tags_json,
            RagFeedback.created_at,
            RagTrace.endpoint,
            RagTrace.query_masked,
        )
        .join(RagTrace, RagFeedback.trace_id == RagTrace.id)
        .where(
            RagFeedback.tenant_id == tenant_id,
            RagTrace.tenant_id == tenant_id,
            RagFeedback.created_at >= from_ts,
        )
    )
    if endpoint != "all":
        feedback_stmt = feedback_stmt.where(RagTrace.endpoint == endpoint)
    feedback_stmt = feedback_stmt.order_by(RagFeedback.created_at.desc()).limit(DASHBOARD_MAX_FEEDBACK)
    feedback = [
        FeedbackRow(
            id=row.id,
            trace_id=row.trace_id,
            rating=int(row.rating),
            comment=row.comment_masked,
            tags=list(row.tags_json or []),
            created_at=row.created_at,
            endpoint=row.endpoint,
            query_masked=row.query_masked,
        )
        for row in (await db.execute(feedback_stmt)).all()
    ]
    return aggregate_dashboard(
        traces=traces, feedback=feedback, window=window, endpoint=endpoint, now=now, sampled=sampled
    )


async def _feedback_counts_for(
    db: AsyncSession, tenant_id: uuid.UUID, trace_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, tuple[int, int]]:
    """Thumbs up/down per trace id in one grouped query."""
    if not trace_ids:
        return {}
    stmt = (
        select(
            RagFeedback.trace_id,
            func.sum(case((RagFeedback.rating == 1, 1), else_=0)),
            func.sum(case((RagFeedback.rating == -1, 1), else_=0)),
        )
        .where(RagFeedback.tenant_id == tenant_id, RagFeedback.trace_id.in_(list(trace_ids)))
        .group_by(RagFeedback.trace_id)
    )
    return {row[0]: (int(row[1] or 0), int(row[2] or 0)) for row in (await db.execute(stmt)).all()}


def _list_item_fields(trace: RagTrace, up: int, down: int) -> dict[str, Any]:
    """Fields shared by TraceListItem and TraceDetailResponse."""
    return {
        "id": trace.id,
        "created_at": trace.created_at,
        "endpoint": trace.endpoint,
        "status": trace.status,
        "query_masked": trace.query_masked,
        "document_id": trace.document_id,
        "retrieval_mode": trace.retrieval_mode,
        "total_ms": trace.total_ms,
        "retrieval_ms": trace.retrieval_ms,
        "generation_ms": trace.generation_ms,
        "ttft_ms": trace.ttft_ms,
        "citation_count": trace.citation_count,
        "answer_citation_count": trace.answer_citation_count,
        "top_score": trace.top_score,
        "top_score_norm": trace.top_score_norm,
        "score_kind": trace.score_kind,
        "groundedness": trace.groundedness,
        "provider": trace.provider,
        "model": trace.model,
        "llm_fallback_used": trace.llm_fallback_used,
        "guardrail_reason": trace.guardrail_reason,
        "error_stage": trace.error_stage,
        "feedback_up": up,
        "feedback_down": down,
    }


async def list_traces(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    *,
    window: str,
    endpoint: str,
    status: str,
    mine: bool,
    limit: int,
    offset: int,
    now: datetime | None = None,
) -> TraceListResponse:
    """Page through the tenant's traces (newest first).

    Args:
        db: Async session.
        tenant_id: Tenant from the JWT.
        user_id: Current user (for ``mine``).
        window: Dashboard window.
        endpoint: ``all`` or a RagEndpoint.
        status: ``all`` or a TraceStatus.
        mine: Only the current user's traces.
        limit: Page size.
        offset: Page offset.
        now: Override of the current time (tests).

    Returns:
        TraceListResponse.
    """
    now = now or _utc_now()
    conditions = [RagTrace.tenant_id == tenant_id, RagTrace.created_at >= _window_start(window, now)]
    if endpoint != "all":
        conditions.append(RagTrace.endpoint == endpoint)
    if status != "all":
        conditions.append(RagTrace.status == status)
    if mine:
        conditions.append(RagTrace.user_id == user_id)

    total = int((await db.execute(select(func.count()).select_from(RagTrace).where(*conditions))).scalar_one())
    page = (
        await db.execute(
            select(RagTrace)
            .where(*conditions)
            .order_by(RagTrace.created_at.desc(), RagTrace.id)
            .limit(limit)
            .offset(offset)
        )
    ).scalars().all()
    counts = await _feedback_counts_for(db, tenant_id, [t.id for t in page])
    items = [TraceListItem(**_list_item_fields(t, *counts.get(t.id, (0, 0)))) for t in page]
    return TraceListResponse(total=total, limit=limit, offset=offset, items=items)


def _scores(raw: Any) -> list[RetrievedScore]:
    """Parse stored score rows, skipping malformed entries."""
    result: list[RetrievedScore] = []
    for entry in raw or []:
        try:
            result.append(RetrievedScore.model_validate(entry))
        except ValueError:
            continue
    return result


def _llm_calls(raw: Any) -> list[LlmCallInfo]:
    """Parse stored LLM call records, skipping malformed entries."""
    result: list[LlmCallInfo] = []
    for entry in raw or []:
        try:
            result.append(LlmCallInfo.model_validate(entry))
        except ValueError:
            continue
    return result


async def get_trace_detail(
    db: AsyncSession, tenant_id: uuid.UUID, user_id: uuid.UUID, trace_id: uuid.UUID
) -> TraceDetailResponse | None:
    """Full trace detail with feedback, or None when the trace is not in the tenant.

    Args:
        db: Async session.
        tenant_id: Tenant from the JWT.
        user_id: Current user (for ``is_mine``/``my_rating``).
        trace_id: Trace to load.

    Returns:
        TraceDetailResponse or None.
    """
    trace = (
        await db.execute(select(RagTrace).where(RagTrace.id == trace_id, RagTrace.tenant_id == tenant_id))
    ).scalar_one_or_none()
    if trace is None:
        return None

    document_filename: str | None = None
    if trace.document_id is not None:
        document_filename = (
            await db.execute(
                select(Document.filename).where(
                    Document.id == trace.document_id, Document.tenant_id == tenant_id
                )
            )
        ).scalar_one_or_none()

    votes = (
        await db.execute(
            select(RagFeedback)
            .where(RagFeedback.trace_id == trace.id, RagFeedback.tenant_id == tenant_id)
            .order_by(RagFeedback.created_at.desc())
        )
    ).scalars().all()
    up = sum(1 for v in votes if v.rating == 1)
    down = sum(1 for v in votes if v.rating == -1)
    my_rating = next((int(v.rating) for v in votes if v.user_id == user_id), None)

    return TraceDetailResponse(
        **_list_item_fields(trace, up, down),
        session_id=trace.session_id,
        chat_message_id=trace.chat_message_id,
        document_filename=document_filename,
        top_k=trace.top_k,
        query_chars=trace.query_chars,
        answer_preview=trace.answer_preview,
        masking_ms=trace.masking_ms,
        dense_ms=trace.dense_ms,
        bm25_ms=trace.bm25_ms,
        fusion_ms=trace.fusion_ms,
        rerank_ms=trace.rerank_ms,
        dense_count=trace.dense_count,
        bm25_count=trace.bm25_count,
        fused_count=trace.fused_count,
        reranked_count=trace.reranked_count,
        mean_score=trace.mean_score,
        rerank_applied=trace.rerank_applied,
        rerank_fallback=trace.rerank_fallback,
        dense_empty=trace.dense_empty,
        scores=_scores(trace.scores_json),
        fused_scores=_scores(trace.fused_scores_json),
        llm_calls=_llm_calls(trace.llm_calls_json),
        est_prompt_tokens=trace.est_prompt_tokens,
        est_completion_tokens=trace.est_completion_tokens,
        guardrail_blocked=trace.guardrail_blocked,
        output_guardrail_reason=trace.output_guardrail_reason,
        error_type=trace.error_type,
        feedback=[
            TraceFeedbackEntry(
                id=v.id,
                rating=int(v.rating),
                comment=v.comment_masked,
                tags=list(v.tags_json or []),
                created_at=v.created_at,
                is_mine=v.user_id == user_id,
            )
            for v in votes
        ],
        my_rating=my_rating,
    )


def _feedback_response(row: RagFeedback) -> FeedbackResponse:
    """Map a feedback row to its API shape."""
    return FeedbackResponse(
        id=row.id,
        trace_id=row.trace_id,
        rating=int(row.rating),
        comment=row.comment_masked,
        tags=list(row.tags_json or []),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


async def _my_feedback(
    db: AsyncSession, tenant_id: uuid.UUID, user_id: uuid.UUID, trace_id: uuid.UUID
) -> RagFeedback | None:
    """The current user's vote on a trace, if any."""
    return (
        await db.execute(
            select(RagFeedback).where(
                RagFeedback.trace_id == trace_id,
                RagFeedback.user_id == user_id,
                RagFeedback.tenant_id == tenant_id,
            )
        )
    ).scalar_one_or_none()


async def upsert_feedback(
    db: AsyncSession, tenant_id: uuid.UUID, user_id: uuid.UUID, payload: FeedbackCreate
) -> FeedbackResponse | None:
    """Create or update the current user's vote on a trace.

    Args:
        db: Async session.
        tenant_id: Tenant from the JWT.
        user_id: Current user.
        payload: Validated feedback.

    Returns:
        The stored feedback, or None when the trace is not in the tenant.
    """
    trace = (
        await db.execute(
            select(RagTrace.id, RagTrace.chat_message_id).where(
                RagTrace.id == payload.trace_id, RagTrace.tenant_id == tenant_id
            )
        )
    ).one_or_none()
    if trace is None:
        return None

    comment_masked = await mask_for_telemetry(payload.comment) if payload.comment else None
    tags = list(payload.tags)

    for attempt in range(2):
        existing = await _my_feedback(db, tenant_id, user_id, payload.trace_id)
        if existing is not None:
            existing.rating = payload.rating
            existing.comment_masked = comment_masked
            existing.tags_json = tags
            existing.updated_at = _utc_now()
            await db.commit()
            return _feedback_response(existing)
        now = _utc_now()
        row = RagFeedback(
            tenant_id=tenant_id,
            user_id=user_id,
            trace_id=payload.trace_id,
            chat_message_id=trace.chat_message_id,
            rating=payload.rating,
            comment_masked=comment_masked,
            tags_json=tags,
            created_at=now,
            updated_at=now,
        )
        db.add(row)
        try:
            await db.commit()
        except IntegrityError:
            # A concurrent vote by the same user won the insert; retry as an update.
            await db.rollback()
            if attempt == 1:
                raise
            continue
        return _feedback_response(row)
    return None


async def delete_feedback(
    db: AsyncSession, tenant_id: uuid.UUID, user_id: uuid.UUID, trace_id: uuid.UUID
) -> bool:
    """Remove the current user's vote on a trace.

    Args:
        db: Async session.
        tenant_id: Tenant from the JWT.
        user_id: Current user.
        trace_id: Trace whose vote to remove.

    Returns:
        True when a vote was deleted.
    """
    result = await db.execute(
        delete(RagFeedback).where(
            RagFeedback.trace_id == trace_id,
            RagFeedback.user_id == user_id,
            RagFeedback.tenant_id == tenant_id,
        )
    )
    await db.commit()
    return bool(result.rowcount)

"""Pure aggregation of RAG trace and feedback rows into the telemetry dashboard.

No I/O: ``telemetry.load_dashboard`` selects the rows and hands them here, which
keeps every rule of the dashboard contract unit-testable without a database.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Literal, Sequence

from app.schemas.rag_eval import (
    EndpointBreakdown,
    FeedbackItem,
    FeedbackSummary,
    FeedbackTagCount,
    ProviderShare,
    RagDashboardResponse,
    ScoreKindStat,
    StageLatency,
    TelemetryKpis,
    TimeseriesPoint,
)
from app.services.evaluation.metrics import mean_or_none, percentile, safe_rate

BucketKind = Literal["hour", "day"]

WINDOW_DELTAS: dict[str, timedelta] = {
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
    "30d": timedelta(days=30),
    "90d": timedelta(days=90),
}
_WINDOW_DAYS: dict[str, int] = {"7d": 7, "30d": 30, "90d": 90}

# (stage, TraceRow attribute, kind) in canonical display order.
STAGE_ORDER: tuple[tuple[str, str, str], ...] = (
    ("masking", "masking_ms", "component"),
    ("dense", "dense_ms", "component"),
    ("bm25", "bm25_ms", "component"),
    ("fusion", "fusion_ms", "component"),
    ("rerank", "rerank_ms", "component"),
    ("retrieval", "retrieval_ms", "composite"),
    ("generation", "generation_ms", "component"),
    ("ttft", "ttft_ms", "composite"),
    ("total", "total_ms", "composite"),
)
RECENT_FEEDBACK_LIMIT = 10


@dataclass(frozen=True)
class TraceRow:
    """Scalar columns of one RagTrace needed for aggregation (no JSON payloads)."""

    created_at: datetime
    endpoint: str
    status: str
    masking_ms: float | None = None
    dense_ms: float | None = None
    bm25_ms: float | None = None
    fusion_ms: float | None = None
    rerank_ms: float | None = None
    retrieval_ms: float | None = None
    generation_ms: float | None = None
    ttft_ms: float | None = None
    total_ms: float | None = None
    citation_count: int = 0
    answer_citation_count: int = 0
    top_score: float | None = None
    top_score_norm: float | None = None
    score_kind: str | None = None
    groundedness: float | None = None
    provider: str | None = None
    model: str | None = None
    llm_fallback_used: bool = False
    rerank_applied: bool = False
    rerank_fallback: bool = False
    dense_empty: bool = False
    retrieval_mode: str = "hybrid_rerank"
    fused_count: int = 0
    est_prompt_tokens: int | None = None
    est_completion_tokens: int | None = None


@dataclass(frozen=True)
class FeedbackRow:
    """One feedback vote joined with its trace's endpoint and masked query."""

    id: Any
    trace_id: Any
    rating: int
    comment: str | None
    tags: Sequence[str]
    created_at: datetime
    endpoint: str | None
    query_masked: str | None


def bucket_kind(window: str) -> BucketKind:
    """Bucket granularity for a window: hourly for 24h, daily otherwise."""
    return "hour" if window == "24h" else "day"


def floor_bucket(ts: datetime, kind: BucketKind) -> datetime:
    """Floor a timestamp to the start of its hour or day."""
    if kind == "hour":
        return ts.replace(minute=0, second=0, microsecond=0)
    return ts.replace(hour=0, minute=0, second=0, microsecond=0)


def bucket_starts(window: str, now: datetime) -> list[datetime]:
    """Aligned bucket starts (oldest first) covering the window and ending at ``now``'s bucket.

    Args:
        window: One of ``24h``, ``7d``, ``30d``, ``90d``.
        now: Current naive-UTC time.

    Returns:
        24 hourly starts for ``24h``; N daily starts (midnight N-1 days ago .. today) otherwise.

    Raises:
        ValueError: For an unknown window.
    """
    if window == "24h":
        last = floor_bucket(now, "hour")
        return [last - timedelta(hours=offset) for offset in range(23, -1, -1)]
    if window not in _WINDOW_DAYS:
        raise ValueError(f"Unknown window: {window}")
    days = _WINDOW_DAYS[window]
    last = floor_bucket(now, "day")
    return [last - timedelta(days=offset) for offset in range(days - 1, -1, -1)]


def _bucket_index(ts: datetime, starts: Sequence[datetime], kind: BucketKind, index: dict[datetime, int]) -> int:
    """Bucket position of a timestamp, clamped to the window's first/last bucket."""
    floored = floor_bucket(ts, kind)
    if floored in index:
        return index[floored]
    return 0 if floored < starts[0] else len(starts) - 1


def _p(values: Sequence[float], q: float) -> float | None:
    """Percentile shortcut."""
    return percentile(values, q)


def _present(values: Sequence[float | None]) -> list[float]:
    """Drop None values."""
    return [float(v) for v in values if v is not None]


def _feedback_counts(rows: Sequence[FeedbackRow]) -> tuple[int, int]:
    """(thumbs_up, thumbs_down)."""
    up = sum(1 for r in rows if r.rating > 0)
    down = sum(1 for r in rows if r.rating < 0)
    return up, down


def aggregate_dashboard(
    *,
    traces: Sequence[TraceRow],
    feedback: Sequence[FeedbackRow],
    window: str,
    endpoint: str,
    now: datetime,
    sampled: bool,
) -> RagDashboardResponse:
    """Aggregate trace and feedback rows into the dashboard response.

    Latency percentiles and quality averages use ``ok`` traces only; KPIs and the
    timeseries are computed from the same rows so they always agree.

    Args:
        traces: Trace rows inside the window (already endpoint-filtered).
        feedback: Feedback rows inside the window (already endpoint-filtered).
        window: Dashboard window.
        endpoint: Endpoint filter echoed back (``all`` or an endpoint).
        now: Current naive-UTC time (``to_ts``).
        sampled: Whether the trace rows were truncated to the newest N.

    Returns:
        RagDashboardResponse.
    """
    kind = bucket_kind(window)
    starts = bucket_starts(window, now)
    ok = [t for t in traces if t.status == "ok"]
    total = len(traces)
    counts = Counter(t.status for t in traces)
    up, down = _feedback_counts(feedback)

    with_provider = [t for t in traces if t.provider]
    rerank_eligible = [t for t in traces if t.retrieval_mode == "hybrid_rerank" and t.fused_count > 0]
    non_blocked = [t for t in traces if t.status != "blocked"]
    ok_total_ms = _present([t.total_ms for t in ok])
    ok_ttft_ms = _present([t.ttft_ms for t in ok])

    kpis = TelemetryKpis(
        total_requests=total,
        ok_count=counts.get("ok", 0),
        error_count=counts.get("error", 0),
        blocked_count=counts.get("blocked", 0),
        cancelled_count=counts.get("cancelled", 0),
        error_rate=safe_rate(counts.get("error", 0), total),
        blocked_rate=safe_rate(counts.get("blocked", 0), total),
        llm_fallback_rate=safe_rate(sum(1 for t in with_provider if t.llm_fallback_used), len(with_provider)),
        rerank_fallback_rate=safe_rate(sum(1 for t in rerank_eligible if t.rerank_fallback), len(rerank_eligible)),
        dense_empty_rate=safe_rate(sum(1 for t in non_blocked if t.dense_empty), len(non_blocked)),
        p50_total_ms=_p(ok_total_ms, 50),
        p95_total_ms=_p(ok_total_ms, 95),
        p50_ttft_ms=_p(ok_ttft_ms, 50),
        p95_ttft_ms=_p(ok_ttft_ms, 95),
        avg_top_score_norm=mean_or_none(t.top_score_norm for t in ok),
        avg_groundedness=mean_or_none(t.groundedness for t in ok),
        citation_rate=safe_rate(sum(1 for t in ok if t.answer_citation_count >= 1), len(ok)),
        avg_citations=mean_or_none(float(t.citation_count) for t in ok),
        feedback_count=len(feedback),
        satisfaction_rate=safe_rate(up, up + down),
        est_prompt_tokens=sum(t.est_prompt_tokens or 0 for t in traces),
        est_completion_tokens=sum(t.est_completion_tokens or 0 for t in traces),
    )

    stages: list[StageLatency] = []
    for stage, attr, stage_kind in STAGE_ORDER:
        values = _present([getattr(t, attr) for t in ok])
        stages.append(
            StageLatency(
                stage=stage,  # type: ignore[arg-type]
                kind=stage_kind,  # type: ignore[arg-type]
                count=len(values),
                p50_ms=_p(values, 50),
                p95_ms=_p(values, 95),
                avg_ms=mean_or_none(values),
            )
        )

    by_endpoint = _endpoint_breakdown(traces, feedback)
    providers = _provider_shares(with_provider)
    score_kinds = _score_kind_stats(traces)
    timeseries = _timeseries(traces, feedback, starts, kind)

    tag_counter: Counter[str] = Counter(tag for row in feedback for tag in row.tags)
    recent = sorted(feedback, key=lambda r: r.created_at, reverse=True)[:RECENT_FEEDBACK_LIMIT]
    feedback_summary = FeedbackSummary(
        total=len(feedback),
        thumbs_up=up,
        thumbs_down=down,
        satisfaction_rate=safe_rate(up, up + down),
        tag_counts=[
            FeedbackTagCount(tag=tag, count=count)
            for tag, count in sorted(tag_counter.items(), key=lambda kv: (-kv[1], kv[0]))
        ],
        recent=[
            FeedbackItem(
                id=r.id,
                trace_id=r.trace_id,
                rating=r.rating,
                comment=r.comment,
                tags=list(r.tags),
                endpoint=r.endpoint,
                query_masked=r.query_masked,
                created_at=r.created_at,
            )
            for r in recent
        ],
    )

    return RagDashboardResponse(
        window=window,  # type: ignore[arg-type]
        endpoint=endpoint,  # type: ignore[arg-type]
        from_ts=starts[0],
        to_ts=now,
        bucket=kind,
        sampled=sampled,
        kpis=kpis,
        stages=stages,
        by_endpoint=by_endpoint,
        providers=providers,
        score_kinds=score_kinds,
        timeseries=timeseries,
        feedback=feedback_summary,
    )


def _endpoint_breakdown(traces: Sequence[TraceRow], feedback: Sequence[FeedbackRow]) -> list[EndpointBreakdown]:
    """One entry per endpoint present, sorted by request count descending."""
    grouped: dict[str, list[TraceRow]] = defaultdict(list)
    for t in traces:
        grouped[t.endpoint].append(t)
    feedback_by_endpoint: dict[str, list[FeedbackRow]] = defaultdict(list)
    for row in feedback:
        if row.endpoint:
            feedback_by_endpoint[row.endpoint].append(row)

    result: list[EndpointBreakdown] = []
    for name, rows in grouped.items():
        if name not in ("query", "regulatory_search"):
            continue
        ok = [t for t in rows if t.status == "ok"]
        totals = _present([t.total_ms for t in ok])
        up, down = _feedback_counts(feedback_by_endpoint.get(name, []))
        result.append(
            EndpointBreakdown(
                endpoint=name,  # type: ignore[arg-type]
                count=len(rows),
                error_rate=safe_rate(sum(1 for t in rows if t.status == "error"), len(rows)),
                p50_total_ms=_p(totals, 50),
                p95_total_ms=_p(totals, 95),
                avg_groundedness=mean_or_none(t.groundedness for t in ok),
                satisfaction_rate=safe_rate(up, up + down),
            )
        )
    result.sort(key=lambda e: (-e.count, e.endpoint))
    return result


def _provider_shares(with_provider: Sequence[TraceRow]) -> list[ProviderShare]:
    """(provider, model) shares over traces that have a provider, sorted by count descending."""
    counter: Counter[tuple[str, str]] = Counter(
        (t.provider or "", t.model or "unknown") for t in with_provider
    )
    total = sum(counter.values())
    shares = [
        ProviderShare(provider=provider, model=model, count=count, share=count / total)
        for (provider, model), count in counter.items()
    ]
    shares.sort(key=lambda s: (-s.count, s.provider, s.model))
    return shares


def _score_kind_stats(traces: Sequence[TraceRow]) -> list[ScoreKindStat]:
    """Top-score averages grouped by non-null score kind (count descending)."""
    grouped: dict[str, list[TraceRow]] = defaultdict(list)
    for t in traces:
        if t.score_kind:
            grouped[t.score_kind].append(t)
    stats = [
        ScoreKindStat(
            kind=name,
            count=len(rows),
            avg_top_score=mean_or_none(t.top_score for t in rows),
            avg_top_score_norm=mean_or_none(t.top_score_norm for t in rows),
        )
        for name, rows in grouped.items()
    ]
    stats.sort(key=lambda s: (-s.count, s.kind))
    return stats


def _timeseries(
    traces: Sequence[TraceRow],
    feedback: Sequence[FeedbackRow],
    starts: Sequence[datetime],
    kind: BucketKind,
) -> list[TimeseriesPoint]:
    """Zero-filled per-bucket counts, latency percentiles and thumbs."""
    index = {start: i for i, start in enumerate(starts)}
    trace_buckets: list[list[TraceRow]] = [[] for _ in starts]
    for t in traces:
        trace_buckets[_bucket_index(t.created_at, starts, kind, index)].append(t)
    thumbs: list[list[int]] = [[0, 0] for _ in starts]
    for row in feedback:
        slot = thumbs[_bucket_index(row.created_at, starts, kind, index)]
        if row.rating > 0:
            slot[0] += 1
        elif row.rating < 0:
            slot[1] += 1

    points: list[TimeseriesPoint] = []
    for i, start in enumerate(starts):
        rows = trace_buckets[i]
        status_counts = Counter(t.status for t in rows)
        ok = [t for t in rows if t.status == "ok"]
        totals = _present([t.total_ms for t in ok])
        points.append(
            TimeseriesPoint(
                bucket_start=start,
                count=len(rows),
                ok_count=status_counts.get("ok", 0),
                error_count=status_counts.get("error", 0),
                blocked_count=status_counts.get("blocked", 0),
                cancelled_count=status_counts.get("cancelled", 0),
                fallback_count=sum(1 for t in rows if t.llm_fallback_used),
                p50_total_ms=_p(totals, 50),
                p95_total_ms=_p(totals, 95),
                avg_groundedness=mean_or_none(t.groundedness for t in ok),
                thumbs_up=thumbs[i][0],
                thumbs_down=thumbs[i][1],
            )
        )
    return points

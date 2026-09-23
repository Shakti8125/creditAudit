from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import pytest

from app.services.evaluation.dashboard import (
    STAGE_ORDER,
    FeedbackRow,
    TraceRow,
    aggregate_dashboard,
    bucket_starts,
)

NOW = datetime(2026, 9, 23, 14, 37, 12)


def _trace(**kw) -> TraceRow:
    base = {"created_at": NOW - timedelta(minutes=5), "endpoint": "query", "status": "ok"}
    base.update(kw)
    return TraceRow(**base)


def _feedback(rating: int, tags=(), minutes: int = 3, endpoint: str = "query") -> FeedbackRow:
    return FeedbackRow(
        id=uuid.uuid4(),
        trace_id=uuid.uuid4(),
        rating=rating,
        comment=None,
        tags=list(tags),
        created_at=NOW - timedelta(minutes=minutes),
        endpoint=endpoint,
        query_masked="q",
    )


def test_24h_window_has_24_hourly_zero_filled_buckets() -> None:
    dash = aggregate_dashboard(traces=[], feedback=[], window="24h", endpoint="all", now=NOW, sampled=False)
    assert dash.bucket == "hour"
    assert len(dash.timeseries) == 24
    assert dash.timeseries[-1].bucket_start == datetime(2026, 9, 23, 14)
    assert dash.from_ts == datetime(2026, 9, 22, 15)
    assert dash.to_ts == NOW
    assert all(p.count == 0 and p.p50_total_ms is None for p in dash.timeseries)


def test_7d_window_aligned_to_midnight() -> None:
    starts = bucket_starts("7d", NOW)
    assert len(starts) == 7
    assert starts[0] == datetime(2026, 9, 17)
    assert starts[-1] == datetime(2026, 9, 23)
    dash = aggregate_dashboard(traces=[], feedback=[], window="7d", endpoint="all", now=NOW, sampled=True)
    assert dash.bucket == "day" and dash.from_ts == datetime(2026, 9, 17) and dash.sampled is True


def test_percentiles_use_ok_rows_only_and_rates() -> None:
    traces = [
        _trace(total_ms=100.0, ttft_ms=10.0, groundedness=0.8, answer_citation_count=1, citation_count=5),
        _trace(total_ms=300.0, ttft_ms=30.0, groundedness=0.6, answer_citation_count=0, citation_count=3),
        _trace(status="error", total_ms=99999.0),
        _trace(status="blocked", total_ms=5.0),
    ]
    dash = aggregate_dashboard(traces=traces, feedback=[], window="24h", endpoint="all", now=NOW, sampled=False)
    k = dash.kpis
    assert k.total_requests == 4 and k.ok_count == 2 and k.error_count == 1 and k.blocked_count == 1
    assert k.p50_total_ms == 200.0
    assert k.p95_total_ms == pytest.approx(290.0)
    assert k.error_rate == 0.25 and k.blocked_rate == 0.25
    assert k.avg_groundedness == pytest.approx(0.7)
    assert k.citation_rate == 0.5
    assert k.avg_citations == 4.0
    assert k.llm_fallback_rate is None
    assert k.rerank_fallback_rate is None
    assert k.satisfaction_rate is None
    total_point = dash.timeseries[-1]
    assert total_point.count == 4 and total_point.ok_count == 2 and total_point.p50_total_ms == 200.0


def test_empty_window_rates_are_none() -> None:
    k = aggregate_dashboard(traces=[], feedback=[], window="30d", endpoint="all", now=NOW, sampled=False).kpis
    assert k.error_rate is None and k.dense_empty_rate is None and k.p50_total_ms is None
    assert k.est_prompt_tokens == 0


def test_satisfaction_and_feedback_summary() -> None:
    feedback = [
        _feedback(1),
        _feedback(1, minutes=1),
        _feedback(-1, tags=["hallucination", "too_slow"]),
        _feedback(-1, tags=["hallucination"], endpoint="regulatory_search"),
    ]
    traces = [_trace(), _trace(endpoint="regulatory_search")]
    dash = aggregate_dashboard(traces=traces, feedback=feedback, window="24h", endpoint="all", now=NOW, sampled=False)
    assert dash.kpis.feedback_count == 4
    assert dash.kpis.satisfaction_rate == 0.5
    assert dash.feedback.thumbs_up == 2 and dash.feedback.thumbs_down == 2
    assert [t.tag for t in dash.feedback.tag_counts] == ["hallucination", "too_slow"]
    assert dash.feedback.tag_counts[0].count == 2
    assert dash.feedback.recent[0].created_at == NOW - timedelta(minutes=1)
    assert sum(p.thumbs_up for p in dash.timeseries) == 2
    by_endpoint = {e.endpoint: e for e in dash.by_endpoint}
    assert by_endpoint["regulatory_search"].satisfaction_rate == 0.0
    assert by_endpoint["query"].satisfaction_rate == pytest.approx(2 / 3)


def test_provider_shares_sum_to_one_and_fallback_rate() -> None:
    traces = [
        _trace(provider="nvidia", model="m1"),
        _trace(provider="nvidia", model="m1"),
        _trace(provider="gemini", model="g", llm_fallback_used=True),
        _trace(provider=None),
    ]
    dash = aggregate_dashboard(traces=traces, feedback=[], window="24h", endpoint="all", now=NOW, sampled=False)
    assert sum(p.share for p in dash.providers) == pytest.approx(1.0)
    assert dash.providers[0].provider == "nvidia" and dash.providers[0].count == 2
    assert dash.kpis.llm_fallback_rate == pytest.approx(1 / 3)
    assert dash.timeseries[-1].fallback_count == 1


def test_rerank_and_dense_rates_and_score_kinds() -> None:
    traces = [
        _trace(fused_count=10, rerank_fallback=True, dense_empty=True, score_kind="rrf", top_score=0.9, top_score_norm=0.9),
        _trace(fused_count=10, rerank_applied=True, score_kind="rerank_nvidia", top_score=2.0, top_score_norm=0.88),
        _trace(fused_count=0),
        _trace(status="blocked", dense_empty=False),
    ]
    dash = aggregate_dashboard(traces=traces, feedback=[], window="24h", endpoint="all", now=NOW, sampled=False)
    assert dash.kpis.rerank_fallback_rate == 0.5
    assert dash.kpis.dense_empty_rate == pytest.approx(1 / 3)
    assert {s.kind for s in dash.score_kinds} == {"rrf", "rerank_nvidia"}


def test_stages_in_canonical_order_with_kind() -> None:
    dash = aggregate_dashboard(
        traces=[_trace(masking_ms=3.0, total_ms=50.0)], feedback=[], window="24h", endpoint="all", now=NOW, sampled=False
    )
    assert [s.stage for s in dash.stages] == [name for name, _, _ in STAGE_ORDER]
    assert len(dash.stages) == 9
    kinds = {s.stage: s.kind for s in dash.stages}
    assert kinds["masking"] == "component" and kinds["generation"] == "component"
    assert kinds["retrieval"] == "composite" and kinds["ttft"] == "composite" and kinds["total"] == "composite"
    masking = dash.stages[0]
    assert masking.count == 1 and masking.p50_ms == 3.0
    assert dash.stages[1].count == 0 and dash.stages[1].avg_ms is None

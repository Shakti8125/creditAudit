"""Offline RAG evaluation runner (executed as a FastAPI background task).

Each run evaluates one retrieval mode over a snapshot of golden cases. Per case:
mask the question and egress-validate it, retrieve with the MASKED question, judge
relevance against the case targets, optionally generate an answer and judge it.
Everything is persisted incrementally with a heartbeat so a crashed worker's runs
can be reconciled as failed.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections import Counter
from datetime import datetime, timedelta
from typing import Any, Sequence

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.db.database import async_session_maker
from app.models.document import Document, DocumentChunk
from app.models.rag_eval import EvalRunStatus, RagEvalCase, RagEvalResult, RagEvalRun
from app.models.user import _utc_now
from app.schemas.retrieval import RetrievalMode
from app.services.evaluation.judge import judge_answer
from app.services.evaluation.metrics import (
    RelevanceTarget,
    RetrievedItem,
    judge_relevance,
    mean_or_none,
    metric_curves,
    percentile,
    score_case,
    text_fingerprint,
)
from app.services.evaluation.prompts import QUERY_SYSTEM_PROMPT, REGULATORY_SYSTEM_PROMPT, format_context
from app.services.llm.router import LLMRouter
from app.services.privacy.egress_validator import EgressValidator, EgressViolationError
from app.services.privacy.masking_pipeline import MaskingPipeline
from app.services.retrieval.hybrid_retriever import HybridRetriever
from app.services.retrieval.pinecone_store import PineconeStore

logger = logging.getLogger(__name__)

STALE_RUN_SECONDS = 600
CASE_TIMEOUT_SECONDS = 120
MAX_CASES_PER_RUN = 200
GENERATION_TEMPERATURE = 0.0
GENERATION_MAX_TOKENS = 700
SNIPPET_CHARS = 280
STALE_RUN_MESSAGE = "Run interrupted (worker restart or timeout)"
ACTIVE_RUN_STATUSES = (EvalRunStatus.PENDING.value, EvalRunStatus.RUNNING.value)


def estimate_llm_calls(modes: Sequence[RetrievalMode], n_cases: int, include_generation: bool, judge: str) -> int:
    """Upper-bound provider calls for a run group (contract formula).

    Per mode and case: 1 embed if the mode uses dense, 1 rerank for ``hybrid_rerank``,
    1 generation if enabled, 1 judge call if generation is enabled and judge is ``auto``.

    Args:
        modes: Retrieval modes of the group.
        n_cases: Cases per run.
        include_generation: Whether answers are generated.
        judge: ``auto`` or ``deterministic``.

    Returns:
        Estimated number of LLM calls.
    """
    per_case_common = (1 if include_generation else 0) + (1 if include_generation and judge == "auto" else 0)
    total = 0
    for mode in modes:
        per_case = per_case_common
        if mode in (RetrievalMode.DENSE, RetrievalMode.HYBRID, RetrievalMode.HYBRID_RERANK):
            per_case += 1
        if mode == RetrievalMode.HYBRID_RERANK:
            per_case += 1
        total += per_case * n_cases
    return total


async def reconcile_stale_runs(db: AsyncSession, tenant_id: uuid.UUID, now: datetime | None = None) -> int:
    """Fail the tenant's pending/running runs whose heartbeat is older than 10 minutes.

    Args:
        db: Async session.
        tenant_id: Tenant from the JWT.
        now: Override of the current naive-UTC time (tests).

    Returns:
        Number of runs marked failed.
    """
    now = now or _utc_now()
    cutoff = now - timedelta(seconds=STALE_RUN_SECONDS)
    result = await db.execute(
        update(RagEvalRun)
        .where(
            RagEvalRun.tenant_id == tenant_id,
            RagEvalRun.status.in_(ACTIVE_RUN_STATUSES),
            func.coalesce(RagEvalRun.heartbeat_at, RagEvalRun.created_at) < cutoff,
        )
        .values(status=EvalRunStatus.FAILED.value, error_message=STALE_RUN_MESSAGE, finished_at=now)
        .execution_options(synchronize_session=False)
    )
    await db.commit()
    return int(result.rowcount or 0)


async def execute_run_group(run_ids: list[uuid.UUID], tenant_id: uuid.UUID) -> None:
    """Execute the runs of a group sequentially (background task entry point).

    Args:
        run_ids: Runs to execute, in order.
        tenant_id: Tenant owning the runs.
    """
    for run_id in run_ids:
        await execute_run(run_id, tenant_id)


async def execute_run(run_id: uuid.UUID, tenant_id: uuid.UUID) -> None:
    """Execute one run; every failure is recorded on the run, never raised.

    Args:
        run_id: Run to execute.
        tenant_id: Tenant owning the run.
    """
    try:
        async with async_session_maker() as db:
            await _execute_run(db, run_id, tenant_id)
    except Exception as exc:  # noqa: BLE001 - a background task must never raise
        logger.error("Evaluation run %s crashed (%s)", run_id, type(exc).__name__)


async def _execute_run(db: AsyncSession, run_id: uuid.UUID, tenant_id: uuid.UUID) -> None:
    """Body of ``execute_run`` using the given session."""
    run = (
        await db.execute(select(RagEvalRun).where(RagEvalRun.id == run_id, RagEvalRun.tenant_id == tenant_id))
    ).scalar_one_or_none()
    if run is None or run.status != EvalRunStatus.PENDING.value:
        return

    now = _utc_now()
    run.status = EvalRunStatus.RUNNING.value
    run.started_at = now
    run.heartbeat_at = now
    await db.commit()

    llm_router: Any | None = None
    try:
        case_ids = [uuid.UUID(str(cid)) for cid in run.case_ids_json or []]
        loaded = (
            await db.execute(
                select(RagEvalCase).where(RagEvalCase.tenant_id == tenant_id, RagEvalCase.id.in_(case_ids))
            )
        ).scalars().all()
        by_id = {case.id: case for case in loaded}
        cases = [by_id[cid] for cid in case_ids if cid in by_id]

        llm_router = LLMRouter()
        retriever = HybridRetriever(llm_router, PineconeStore())
        masking = MaskingPipeline()
        egress = EgressValidator()

        for position, case in enumerate(cases):
            await db.refresh(run, attribute_names=["status"])
            if run.status == EvalRunStatus.CANCELLED.value:
                break
            try:
                row = await asyncio.wait_for(
                    evaluate_case(
                        db=db,
                        run=run,
                        case=case,
                        position=position,
                        retriever=retriever,
                        llm_router=llm_router,
                        masking=masking,
                        egress=egress,
                    ),
                    CASE_TIMEOUT_SECONDS,
                )
            except asyncio.TimeoutError:
                row = _error_row(run, case, position, error_type="TimeoutError", error_stage="timeout")
            db.add(row)
            if row.status == "ok":
                run.completed_cases += 1
            else:
                run.failed_cases += 1
            now = _utc_now()
            run.heartbeat_at = now
            # Keep the group's queued runs from being reconciled as stale while we work.
            await db.execute(
                update(RagEvalRun)
                .where(
                    RagEvalRun.group_id == run.group_id,
                    RagEvalRun.tenant_id == tenant_id,
                    RagEvalRun.status == EvalRunStatus.PENDING.value,
                )
                .values(heartbeat_at=now)
                .execution_options(synchronize_session=False)
            )
            await db.commit()

        results = (
            await db.execute(
                select(RagEvalResult).where(RagEvalResult.run_id == run.id, RagEvalResult.tenant_id == tenant_id)
            )
        ).scalars().all()
        for key, value in aggregate_run_results(results, run.top_k, run.include_generation).items():
            setattr(run, key, value)
        await db.refresh(run, attribute_names=["status"])
        if run.status != EvalRunStatus.CANCELLED.value:
            run.status = EvalRunStatus.COMPLETED.value
        run.finished_at = _utc_now()
        await db.commit()
    except Exception as exc:  # noqa: BLE001 - record any failure on the run instead of raising
        logger.error("Evaluation run %s failed (%s)", run_id, type(exc).__name__)
        await db.rollback()
        await db.execute(
            update(RagEvalRun)
            .where(RagEvalRun.id == run_id, RagEvalRun.tenant_id == tenant_id)
            .values(
                status=EvalRunStatus.FAILED.value,
                error_message=f"Run failed ({type(exc).__name__})",
                finished_at=_utc_now(),
            )
            .execution_options(synchronize_session=False)
        )
        await db.commit()
    finally:
        if llm_router is not None:
            await llm_router.aclose()


def _elapsed_ms(t0: float) -> float:
    """Milliseconds since a ``time.perf_counter()`` reading."""
    return (time.perf_counter() - t0) * 1000.0


def _error_row(
    run: RagEvalRun,
    case: RagEvalCase,
    position: int,
    *,
    error_type: str,
    error_stage: str,
    question_masked: str | None = None,
) -> RagEvalResult:
    """A failed result row (retrieval metrics unavailable)."""
    return RagEvalResult(
        id=uuid.uuid4(),
        run_id=run.id,
        tenant_id=run.tenant_id,
        case_id=case.id,
        position=position,
        status="error",
        question_masked=question_masked,
        document_id=case.document_id,
        n_targets=len(case.expected_refs_json or []),
        targets_matched=0,
        judge_method="none",
        error_type=error_type[:128],
        error_stage=error_stage,
        created_at=_utc_now(),
    )


async def _build_targets(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    document_id: uuid.UUID | None,
    refs: Sequence[dict[str, Any]],
) -> tuple[list[RelevanceTarget], int]:
    """Turn stored expected refs into RelevanceTargets, resolving chunk_index to text hashes.

    Returns:
        ``(targets, unresolved_chunk_targets)``.
    """
    targets: list[RelevanceTarget] = []
    unresolved = 0
    for ref in refs:
        text_hash: str | None = None
        chunk_index = ref.get("chunk_index")
        if chunk_index is not None:
            chunk_text: str | None = None
            if document_id is not None:
                chunk_text = (
                    await db.execute(
                        select(DocumentChunk.masked_text)
                        .join(Document, DocumentChunk.document_id == Document.id)
                        .where(
                            Document.id == document_id,
                            Document.tenant_id == tenant_id,
                            DocumentChunk.chunk_index == int(chunk_index),
                        )
                        .limit(1)
                    )
                ).scalar_one_or_none()
            if chunk_text:
                text_hash = text_fingerprint(chunk_text)
            else:
                unresolved += 1
        targets.append(
            RelevanceTarget(
                source=ref.get("source"),
                section=ref.get("section"),
                keywords=tuple(ref.get("keywords") or ()),
                min_keyword_hits=ref.get("min_keyword_hits"),
                text_hash=text_hash,
            )
        )
    return targets, unresolved


async def evaluate_case(
    *,
    db: AsyncSession,
    run: RagEvalRun,
    case: RagEvalCase,
    position: int,
    retriever: HybridRetriever,
    llm_router: Any,
    masking: Any,
    egress: Any,
) -> RagEvalResult:
    """Evaluate one golden case. Never raises (failures become error rows).

    Args:
        db: Async session.
        run: The run being executed.
        case: Golden case.
        position: 0-based position in the run.
        retriever: Retriever bound to the run's router.
        llm_router: LLMRouter used for generation and judging.
        masking: MaskingPipeline.
        egress: EgressValidator.

    Returns:
        An unsaved RagEvalResult.
    """
    # 1. Mask + egress-validate the question (only masked text is sent anywhere or stored).
    try:
        masked_q, registry = await run_in_threadpool(masking.mask_document, case.question)
        await run_in_threadpool(egress.validate, masked_q, registry)
    except EgressViolationError:
        return _error_row(run, case, position, error_type="EgressViolationError", error_stage="egress")
    except Exception as exc:  # noqa: BLE001 - one bad case must not abort the run
        return _error_row(run, case, position, error_type=type(exc).__name__, error_stage="mask")

    try:
        # 2. Document scope must still exist in the tenant.
        if case.document_id is not None:
            found = (
                await db.execute(
                    select(Document.id).where(Document.id == case.document_id, Document.tenant_id == run.tenant_id)
                )
            ).scalar_one_or_none()
            if found is None:
                return _error_row(
                    run, case, position, error_type="DocumentNotFound", error_stage="document", question_masked=masked_q
                )

        # 3. Relevance targets.
        targets, unresolved = await _build_targets(db, run.tenant_id, case.document_id, case.expected_refs_json or [])
    except Exception as exc:  # noqa: BLE001 - one bad case must not abort the run
        return _error_row(run, case, position, error_type=type(exc).__name__, error_stage="targets", question_masked=masked_q)

    # 4. Retrieval with the MASKED question.
    t0 = time.perf_counter()
    try:
        res = await retriever.retrieve(
            query=masked_q,
            tenant_id=run.tenant_id,
            document_id=case.document_id,
            db=db,
            top_k=run.top_k,
            mode=RetrievalMode(run.mode),
        )
    except Exception as exc:  # noqa: BLE001 - one bad case must not abort the run
        return _error_row(
            run, case, position, error_type=type(exc).__name__, error_stage="retrieval", question_masked=masked_q
        )
    retrieval_ms = _elapsed_ms(t0)

    # 5. Relevance and IR metrics.
    items = [RetrievedItem(source=c.source, section=c.section, text=c.text) for c in res.citations]
    relevances, matched = judge_relevance(items, targets)
    scores = score_case(relevances, matched, len(targets), run.top_k)
    retrieved_json = [
        {
            "rank": i + 1,
            "source": c.source,
            "section": c.section,
            "score": c.score,
            "retrieval_method": c.retrieval_method,
            "relevant": bool(relevances[i]),
            "matched_targets": matched[i],
            "snippet": c.text[:SNIPPET_CHARS],
        }
        for i, c in enumerate(res.citations)
    ]
    diagnostics_json: dict[str, Any] = {"unresolved_chunk_targets": unresolved}
    if res.diagnostics is not None:
        diagnostics_json = res.diagnostics.model_dump(mode="json", exclude={"fused_preview"}) | diagnostics_json

    row = RagEvalResult(
        id=uuid.uuid4(),
        run_id=run.id,
        tenant_id=run.tenant_id,
        case_id=case.id,
        position=position,
        status="ok",
        question_masked=masked_q,
        document_id=case.document_id,
        n_targets=len(targets),
        targets_matched=scores.targets_matched,
        hit=scores.hit,
        first_relevant_rank=scores.first_relevant_rank,
        recall=scores.recall,
        precision=scores.precision,
        reciprocal_rank=scores.reciprocal_rank,
        ndcg=scores.ndcg,
        relevances_json=relevances,
        retrieved_json=retrieved_json,
        judge_method="none",
        retrieval_ms=retrieval_ms,
        diagnostics_json=diagnostics_json,
        created_at=_utc_now(),
    )
    if not run.include_generation:
        return row

    # 6. Generation (failure keeps the retrieval metrics).
    context = format_context(res.citations)
    prompt = f"Context:\n{context}\n\nQuestion: {masked_q}"
    system_prompt = QUERY_SYSTEM_PROMPT if case.document_id else REGULATORY_SYSTEM_PROMPT
    t1 = time.perf_counter()
    try:
        await run_in_threadpool(egress.validate, prompt, registry)
        answer = await llm_router.generate(
            prompt,
            system_prompt=system_prompt,
            temperature=GENERATION_TEMPERATURE,
            max_tokens=GENERATION_MAX_TOKENS,
        )
    except Exception as exc:  # noqa: BLE001 - provider SDK errors are heterogeneous
        row.generation_ms = _elapsed_ms(t1)
        row.error_type = type(exc).__name__[:128]
        row.error_stage = "generation"
        return row
    row.generation_ms = _elapsed_ms(t1)
    row.answer_masked = answer

    # 7. Judge (reference answer masked with the same registry; skipped if masking fails).
    reference_masked: str | None = None
    if case.reference_answer:
        try:
            reference_masked, _ = await run_in_threadpool(
                masking.mask_document, case.reference_answer, registry=registry
            )
        except Exception as exc:  # noqa: BLE001 - never send an unmasked reference
            logger.info("Reference masking failed (%s); judging without reference", type(exc).__name__)
            reference_masked = None
    outcome = await judge_answer(
        llm_router=llm_router,
        mode=run.judge,
        question_masked=masked_q,
        context=context,
        answer=answer,
        reference_masked=reference_masked,
        registry=registry,
        egress=egress,
    )
    row.faithfulness = outcome.faithfulness
    row.answer_relevance = outcome.answer_relevance
    row.answer_correctness = outcome.answer_correctness
    row.judge_method = outcome.method
    row.judge_rationale = outcome.rationale
    row.judge_ms = outcome.latency_ms
    return row


def aggregate_run_results(
    results: Sequence[RagEvalResult], top_k: int, include_generation: bool
) -> dict[str, Any]:
    """Aggregate per-case results into run columns and ``metrics_json``.

    Args:
        results: All result rows of the run (only ``ok`` rows are aggregated).
        top_k: The run's k (length of the metric curves).
        include_generation: Whether answers were generated.

    Returns:
        Mapping of RagEvalRun attribute name to value.
    """
    ok = [r for r in results if r.status == "ok"]
    latencies = [
        float(r.retrieval_ms) + float(r.generation_ms or 0.0) for r in ok if r.retrieval_ms is not None
    ]
    curve_cases = [
        (
            list(r.relevances_json or []),
            [list(item.get("matched_targets") or []) for item in (r.retrieved_json or [])],
            int(r.n_targets or 0),
        )
        for r in ok
    ]
    curves = metric_curves(curve_cases, top_k) if top_k >= 1 else {"k": []}
    judge_counts: Counter[str] = Counter(r.judge_method or "none" for r in ok)
    diagnostics = [r.diagnostics_json or {} for r in ok]
    return {
        "hit_rate": mean_or_none((1.0 if r.hit else 0.0) for r in ok if r.hit is not None),
        "mean_recall": mean_or_none(r.recall for r in ok),
        "mean_precision": mean_or_none(r.precision for r in ok),
        "mrr": mean_or_none(r.reciprocal_rank for r in ok),
        "mean_ndcg": mean_or_none(r.ndcg for r in ok),
        "mean_faithfulness": mean_or_none(r.faithfulness for r in ok),
        "mean_answer_relevance": mean_or_none(r.answer_relevance for r in ok),
        "mean_answer_correctness": mean_or_none(r.answer_correctness for r in ok),
        "p50_latency_ms": percentile(latencies, 50),
        "p95_latency_ms": percentile(latencies, 95),
        "metrics_json": {
            "curves": curves if curves.get("k") else None,
            "judge_breakdown": {
                "llm": judge_counts.get("llm", 0),
                "deterministic": judge_counts.get("deterministic", 0),
                "none": judge_counts.get("none", 0),
            },
            "degraded": {
                "dense_empty": sum(1 for d in diagnostics if d.get("dense_empty")),
                "rerank_fallback": sum(1 for d in diagnostics if d.get("rerank_fallback")),
                "unresolved_chunk_targets": sum(int(d.get("unresolved_chunk_targets") or 0) for d in diagnostics),
            },
            "generation_temperature": GENERATION_TEMPERATURE if include_generation else None,
        },
    }

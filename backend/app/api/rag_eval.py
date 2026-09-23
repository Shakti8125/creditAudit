"""RAG performance API: live telemetry, user feedback and offline evaluation (``/rag/...``)."""

from __future__ import annotations

import logging
import uuid
from typing import Any, Sequence

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Response, status
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.database import get_db
from app.models.document import Document
from app.models.rag_eval import EvalCaseOrigin, EvalRunStatus, RagEvalCase, RagEvalResult, RagEvalRun
from app.models.user import _utc_now
from app.schemas.auth import TokenPayload
from app.schemas.rag_eval import (
    DegradedCounts,
    EndpointFilter,
    EvalCaseCreate,
    EvalCaseDiagnostics,
    EvalCaseListResponse,
    EvalCaseResponse,
    EvalCaseResultResponse,
    EvalCaseUpdate,
    EvalRunCreate,
    EvalRunCreateResponse,
    EvalRunDetail,
    EvalRunListResponse,
    EvalRunMetrics,
    EvalRunResultsResponse,
    EvalRunSummary,
    ExpectedRef,
    FeedbackCreate,
    FeedbackResponse,
    JudgeBreakdown,
    MetricCurves,
    RagDashboardResponse,
    RagWindow,
    RestoreDefaultsResponse,
    RetrievedItemResult,
    TraceDetailResponse,
    TraceListResponse,
    TraceStatusFilter,
)
from app.schemas.retrieval import RetrievalMode
from app.services.evaluation import telemetry
from app.services.evaluation.default_dataset import ensure_default_cases, restore_default_cases
from app.services.evaluation.runner import (
    ACTIVE_RUN_STATUSES,
    MAX_CASES_PER_RUN,
    estimate_llm_calls,
    execute_run_group,
    reconcile_stale_runs,
)
from app.services.guardrails.checks import run_input_guardrails

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/rag", tags=["RAG Performance"])

_DOCUMENT_NOT_FOUND = "Document not found or does not belong to this tenant"
_TRACE_NOT_FOUND = "Trace not found"
_CASE_NOT_FOUND = "Evaluation case not found"
_RUN_NOT_FOUND = "Evaluation run not found"
# Literal code: Starlette renamed the 422 constant, and both names are not available across versions.
_HTTP_422 = 422


# ============================================================================ telemetry


@router.get("/telemetry/dashboard", response_model=RagDashboardResponse)
async def get_dashboard(
    window: RagWindow = Query("7d"),
    endpoint: EndpointFilter = Query("all"),
    current_user: TokenPayload = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> RagDashboardResponse:
    """T1: KPIs, stage latencies, breakdowns, timeseries and feedback for the window."""
    return await telemetry.load_dashboard(db, current_user.tenant_id, window, endpoint)


@router.get("/traces", response_model=TraceListResponse)
async def list_traces(
    window: RagWindow = Query("7d"),
    endpoint: EndpointFilter = Query("all"),
    status_filter: TraceStatusFilter = Query("all", alias="status"),
    mine: bool = Query(False),
    limit: int = Query(25, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: TokenPayload = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TraceListResponse:
    """T2: page through traces (newest first)."""
    return await telemetry.list_traces(
        db,
        current_user.tenant_id,
        current_user.sub,
        window=window,
        endpoint=endpoint,
        status=status_filter,
        mine=mine,
        limit=limit,
        offset=offset,
    )


@router.get("/traces/{trace_id}", response_model=TraceDetailResponse)
async def get_trace(
    trace_id: uuid.UUID,
    current_user: TokenPayload = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TraceDetailResponse:
    """T3: full trace detail (404 outside the tenant)."""
    detail = await telemetry.get_trace_detail(db, current_user.tenant_id, current_user.sub, trace_id)
    if detail is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_TRACE_NOT_FOUND)
    return detail


@router.post("/feedback", response_model=FeedbackResponse)
async def submit_feedback(
    payload: FeedbackCreate,
    current_user: TokenPayload = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> FeedbackResponse:
    """T4: upsert the current user's vote on a trace."""
    record = await telemetry.upsert_feedback(db, current_user.tenant_id, current_user.sub, payload)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_TRACE_NOT_FOUND)
    return record


@router.delete("/feedback/{trace_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_feedback(
    trace_id: uuid.UUID,
    current_user: TokenPayload = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """T5: remove the current user's vote (404 if there is none)."""
    if not await telemetry.delete_feedback(db, current_user.tenant_id, current_user.sub, trace_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Feedback not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ============================================================================ eval cases


async def _document_filenames(
    db: AsyncSession, tenant_id: uuid.UUID, document_ids: Sequence[uuid.UUID | None]
) -> dict[uuid.UUID, str]:
    """Filenames of the tenant's documents among the given ids (one query)."""
    ids = {doc_id for doc_id in document_ids if doc_id is not None}
    if not ids:
        return {}
    rows = await db.execute(
        select(Document.id, Document.filename).where(Document.tenant_id == tenant_id, Document.id.in_(ids))
    )
    return {row[0]: row[1] for row in rows.all()}


async def _ensure_document(db: AsyncSession, tenant_id: uuid.UUID, document_id: uuid.UUID) -> None:
    """404 unless the document belongs to the tenant."""
    found = (
        await db.execute(select(Document.id).where(Document.id == document_id, Document.tenant_id == tenant_id))
    ).scalar_one_or_none()
    if found is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_DOCUMENT_NOT_FOUND)


async def _check_question(question: str) -> None:
    """400 when the input guardrails flag the question (jailbreak / injection)."""
    violation = await run_input_guardrails(question, check_off_topic=False)
    if violation:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=violation.detail)


def _expected_refs(raw: Any) -> list[ExpectedRef]:
    """Parse stored expected refs, skipping malformed entries."""
    refs: list[ExpectedRef] = []
    for entry in raw or []:
        try:
            refs.append(ExpectedRef.model_validate(entry))
        except ValueError:
            continue
    return refs


def _case_response(case: RagEvalCase, filenames: dict[uuid.UUID, str]) -> EvalCaseResponse:
    """Map a case row to its API shape."""
    return EvalCaseResponse(
        id=case.id,
        question=case.question,
        reference_answer=case.reference_answer,
        document_id=case.document_id,
        document_filename=filenames.get(case.document_id) if case.document_id else None,
        expected_refs=_expected_refs(case.expected_refs_json),
        origin=case.origin,  # type: ignore[arg-type]
        default_key=case.default_key,
        is_active=case.is_active,
        created_at=case.created_at,
        updated_at=case.updated_at,
    )


async def _load_case(db: AsyncSession, tenant_id: uuid.UUID, case_id: uuid.UUID) -> RagEvalCase:
    """Tenant-filtered case load (404 when missing)."""
    case = (
        await db.execute(select(RagEvalCase).where(RagEvalCase.id == case_id, RagEvalCase.tenant_id == tenant_id))
    ).scalar_one_or_none()
    if case is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_CASE_NOT_FOUND)
    return case


@router.get("/eval/cases", response_model=EvalCaseListResponse)
async def list_eval_cases(
    include_inactive: bool = Query(True),
    current_user: TokenPayload = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> EvalCaseListResponse:
    """E1: list golden cases, lazily seeding the 22 defaults for a tenant with none."""
    await ensure_default_cases(db, current_user.tenant_id, current_user.sub)
    stmt = select(RagEvalCase).where(RagEvalCase.tenant_id == current_user.tenant_id)
    if not include_inactive:
        stmt = stmt.where(RagEvalCase.is_active.is_(True))
    cases = list((await db.execute(stmt)).scalars().all())
    cases.sort(
        key=lambda c: (
            0 if c.origin == EvalCaseOrigin.DEFAULT.value else 1,
            c.default_key or "" if c.origin == EvalCaseOrigin.DEFAULT.value else "",
            c.created_at,
        )
    )
    filenames = await _document_filenames(db, current_user.tenant_id, [c.document_id for c in cases])
    return EvalCaseListResponse(total=len(cases), cases=[_case_response(c, filenames) for c in cases])


@router.post("/eval/cases", response_model=EvalCaseResponse, status_code=status.HTTP_201_CREATED)
async def create_eval_case(
    payload: EvalCaseCreate,
    current_user: TokenPayload = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> EvalCaseResponse:
    """E2: create a custom golden case."""
    await _check_question(payload.question)
    if payload.document_id is not None:
        await _ensure_document(db, current_user.tenant_id, payload.document_id)
    now = _utc_now()
    case = RagEvalCase(
        tenant_id=current_user.tenant_id,
        created_by=current_user.sub,
        question=payload.question,
        reference_answer=payload.reference_answer,
        expected_refs_json=[ref.model_dump() for ref in payload.expected_refs],
        document_id=payload.document_id,
        origin=EvalCaseOrigin.CUSTOM.value,
        default_key=None,
        is_active=payload.is_active,
        created_at=now,
        updated_at=now,
    )
    db.add(case)
    await db.commit()
    filenames = await _document_filenames(db, current_user.tenant_id, [case.document_id])
    return _case_response(case, filenames)


@router.patch("/eval/cases/{case_id}", response_model=EvalCaseResponse)
async def update_eval_case(
    case_id: uuid.UUID,
    payload: EvalCaseUpdate,
    current_user: TokenPayload = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> EvalCaseResponse:
    """E3: partially update a case (explicit ``document_id: null`` clears the scope)."""
    case = await _load_case(db, current_user.tenant_id, case_id)
    fields = payload.model_fields_set
    for name in ("question", "expected_refs", "is_active"):
        if name in fields and getattr(payload, name) is None:
            raise HTTPException(status_code=_HTTP_422, detail=f"{name} cannot be null")

    if "question" in fields and payload.question is not None and payload.question != case.question:
        await _check_question(payload.question)
    if "document_id" in fields and payload.document_id is not None:
        await _ensure_document(db, current_user.tenant_id, payload.document_id)

    merged_document_id = payload.document_id if "document_id" in fields else case.document_id
    merged_refs = (
        [ref.model_dump() for ref in payload.expected_refs]
        if "expected_refs" in fields and payload.expected_refs is not None
        else list(case.expected_refs_json or [])
    )
    if merged_document_id is None and any(ref.get("chunk_index") is not None for ref in merged_refs):
        raise HTTPException(
            status_code=_HTTP_422,
            detail="chunk_index targets require a document_id",
        )

    if "question" in fields and payload.question is not None:
        case.question = payload.question
    if "reference_answer" in fields:
        case.reference_answer = payload.reference_answer
    if "document_id" in fields:
        case.document_id = payload.document_id
    if "expected_refs" in fields:
        case.expected_refs_json = merged_refs
    if "is_active" in fields and payload.is_active is not None:
        case.is_active = payload.is_active
    case.updated_at = _utc_now()
    await db.commit()
    filenames = await _document_filenames(db, current_user.tenant_id, [case.document_id])
    return _case_response(case, filenames)


@router.delete("/eval/cases/{case_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_eval_case(
    case_id: uuid.UUID,
    current_user: TokenPayload = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """E4: delete a case (historical results keep their case_id)."""
    result = await db.execute(
        delete(RagEvalCase).where(RagEvalCase.id == case_id, RagEvalCase.tenant_id == current_user.tenant_id)
    )
    await db.commit()
    if not result.rowcount:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_CASE_NOT_FOUND)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/eval/cases/restore-defaults", response_model=RestoreDefaultsResponse)
async def restore_defaults(
    current_user: TokenPayload = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> RestoreDefaultsResponse:
    """E5: re-insert missing default cases."""
    inserted = await restore_default_cases(db, current_user.tenant_id, current_user.sub)
    total = (
        await db.execute(
            select(func.count()).select_from(RagEvalCase).where(RagEvalCase.tenant_id == current_user.tenant_id)
        )
    ).scalar_one()
    return RestoreDefaultsResponse(inserted=inserted, total=int(total))


# ============================================================================ eval runs


def _run_summary_fields(run: RagEvalRun) -> dict[str, Any]:
    """Fields shared by EvalRunSummary and EvalRunDetail."""
    done = (run.completed_cases or 0) + (run.failed_cases or 0)
    progress = min(1.0, done / run.total_cases) if run.total_cases else 0.0
    return {
        "id": run.id,
        "group_id": run.group_id,
        "label": run.label,
        "status": run.status,
        "mode": RetrievalMode(run.mode),
        "top_k": run.top_k,
        "include_generation": run.include_generation,
        "judge": run.judge,
        "total_cases": run.total_cases,
        "completed_cases": run.completed_cases,
        "failed_cases": run.failed_cases,
        "progress": progress,
        "metrics": EvalRunMetrics(
            hit_rate=run.hit_rate,
            recall=run.mean_recall,
            precision=run.mean_precision,
            mrr=run.mrr,
            ndcg=run.mean_ndcg,
            faithfulness=run.mean_faithfulness,
            answer_relevance=run.mean_answer_relevance,
            answer_correctness=run.mean_answer_correctness,
            p50_latency_ms=run.p50_latency_ms,
            p95_latency_ms=run.p95_latency_ms,
        ),
        "error_message": run.error_message,
        "created_at": run.created_at,
        "started_at": run.started_at,
        "finished_at": run.finished_at,
    }


def _run_summary(run: RagEvalRun) -> EvalRunSummary:
    """Map a run row to EvalRunSummary."""
    return EvalRunSummary(**_run_summary_fields(run))


def _run_detail(run: RagEvalRun) -> EvalRunDetail:
    """Map a run row to EvalRunDetail (curves/breakdowns from metrics_json)."""
    metrics = run.metrics_json or {}
    curves_raw = metrics.get("curves")
    curves = MetricCurves.model_validate(curves_raw) if curves_raw and curves_raw.get("k") else None
    case_ids: list[uuid.UUID] = []
    for raw in run.case_ids_json or []:
        try:
            case_ids.append(uuid.UUID(str(raw)))
        except ValueError:
            continue
    return EvalRunDetail(
        **_run_summary_fields(run),
        curves=curves,
        judge_breakdown=JudgeBreakdown.model_validate(metrics.get("judge_breakdown") or {}),
        degraded=DegradedCounts.model_validate(metrics.get("degraded") or {}),
        case_ids=case_ids,
        generation_temperature=metrics.get("generation_temperature"),
    )


async def _load_run(db: AsyncSession, tenant_id: uuid.UUID, run_id: uuid.UUID) -> RagEvalRun:
    """Tenant-filtered run load (404 when missing)."""
    run = (
        await db.execute(select(RagEvalRun).where(RagEvalRun.id == run_id, RagEvalRun.tenant_id == tenant_id))
    ).scalar_one_or_none()
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_RUN_NOT_FOUND)
    return run


@router.post("/eval/runs", response_model=EvalRunCreateResponse, status_code=status.HTTP_202_ACCEPTED)
async def create_runs(
    payload: EvalRunCreate,
    background_tasks: BackgroundTasks,
    current_user: TokenPayload = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> EvalRunCreateResponse:
    """E6: create one run per mode (shared group) and execute them in the background."""
    tenant_id = current_user.tenant_id
    await reconcile_stale_runs(db, tenant_id)
    active = (
        await db.execute(
            select(func.count())
            .select_from(RagEvalRun)
            .where(RagEvalRun.tenant_id == tenant_id, RagEvalRun.status.in_(ACTIVE_RUN_STATUSES))
        )
    ).scalar_one()
    if active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An evaluation run is already in progress for this tenant",
        )

    await ensure_default_cases(db, tenant_id, current_user.sub)
    active_cases = list(
        (
            await db.execute(
                select(RagEvalCase).where(RagEvalCase.tenant_id == tenant_id, RagEvalCase.is_active.is_(True))
            )
        ).scalars().all()
    )
    if payload.case_ids is not None:
        by_id = {case.id: case for case in active_cases}
        requested = list(dict.fromkeys(payload.case_ids))
        if not requested or any(case_id not in by_id for case_id in requested):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown or inactive case ids")
        selected = [by_id[case_id] for case_id in requested]
    else:
        active_cases.sort(
            key=lambda c: (
                0 if c.origin == EvalCaseOrigin.DEFAULT.value else 1,
                c.default_key or "" if c.origin == EvalCaseOrigin.DEFAULT.value else "",
                c.created_at,
            )
        )
        selected = active_cases
    if not selected:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No active evaluation cases")
    if len(selected) > MAX_CASES_PER_RUN:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"An evaluation run is limited to {MAX_CASES_PER_RUN} cases",
        )

    group_id = uuid.uuid4()
    now = _utc_now()
    case_ids = [str(case.id) for case in selected]
    runs = [
        RagEvalRun(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            user_id=current_user.sub,
            group_id=group_id,
            label=payload.label,
            status=EvalRunStatus.PENDING.value,
            mode=mode.value,
            top_k=payload.top_k,
            include_generation=payload.include_generation,
            judge=payload.judge,
            case_ids_json=case_ids,
            total_cases=len(case_ids),
            completed_cases=0,
            failed_cases=0,
            created_at=now,
            heartbeat_at=now,
        )
        for mode in payload.modes
    ]
    db.add_all(runs)
    await db.commit()
    summaries = [_run_summary(run) for run in runs]
    background_tasks.add_task(execute_run_group, [run.id for run in runs], tenant_id)
    return EvalRunCreateResponse(
        group_id=group_id,
        estimated_llm_calls=estimate_llm_calls(
            payload.modes, len(case_ids), payload.include_generation, payload.judge
        ),
        runs=summaries,
    )


@router.get("/eval/runs", response_model=EvalRunListResponse)
async def list_runs(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: TokenPayload = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> EvalRunListResponse:
    """E7: list runs, newest first."""
    tenant_id = current_user.tenant_id
    await reconcile_stale_runs(db, tenant_id)
    total = (
        await db.execute(select(func.count()).select_from(RagEvalRun).where(RagEvalRun.tenant_id == tenant_id))
    ).scalar_one()
    runs = (
        await db.execute(
            select(RagEvalRun)
            .where(RagEvalRun.tenant_id == tenant_id)
            .order_by(RagEvalRun.created_at.desc(), RagEvalRun.id)
            .limit(limit)
            .offset(offset)
            .execution_options(populate_existing=True)
        )
    ).scalars().all()
    return EvalRunListResponse(total=int(total), runs=[_run_summary(run) for run in runs])


@router.get("/eval/runs/{run_id}", response_model=EvalRunDetail)
async def get_run(
    run_id: uuid.UUID,
    current_user: TokenPayload = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> EvalRunDetail:
    """E8: run detail with curves, judge breakdown and degradation counts."""
    await reconcile_stale_runs(db, current_user.tenant_id)
    return _run_detail(await _load_run(db, current_user.tenant_id, run_id))


def _result_response(row: RagEvalResult) -> EvalCaseResultResponse:
    """Map a result row to its API shape."""
    retrieved: list[RetrievedItemResult] = []
    for entry in row.retrieved_json or []:
        try:
            retrieved.append(RetrievedItemResult.model_validate(entry))
        except ValueError:
            continue
    diagnostics: EvalCaseDiagnostics | None = None
    if row.diagnostics_json and row.diagnostics_json.get("mode"):
        try:
            diagnostics = EvalCaseDiagnostics.model_validate(row.diagnostics_json)
        except ValueError:
            diagnostics = None
    return EvalCaseResultResponse(
        id=row.id,
        case_id=row.case_id,
        position=row.position,
        status="ok" if row.status == "ok" else "error",
        question_masked=row.question_masked,
        document_id=row.document_id,
        n_targets=row.n_targets,
        targets_matched=row.targets_matched,
        hit=row.hit,
        first_relevant_rank=row.first_relevant_rank,
        recall=row.recall,
        precision=row.precision,
        reciprocal_rank=row.reciprocal_rank,
        ndcg=row.ndcg,
        retrieved=retrieved,
        answer=row.answer_masked,
        faithfulness=row.faithfulness,
        answer_relevance=row.answer_relevance,
        answer_correctness=row.answer_correctness,
        judge_method=row.judge_method if row.judge_method in ("llm", "deterministic") else "none",  # type: ignore[arg-type]
        judge_rationale=row.judge_rationale,
        retrieval_ms=row.retrieval_ms,
        generation_ms=row.generation_ms,
        judge_ms=row.judge_ms,
        diagnostics=diagnostics,
        error_type=row.error_type,
        error_stage=row.error_stage,
        created_at=row.created_at,
    )


@router.get("/eval/runs/{run_id}/results", response_model=EvalRunResultsResponse)
async def get_run_results(
    run_id: uuid.UUID,
    current_user: TokenPayload = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> EvalRunResultsResponse:
    """E9: per-case results ordered by position."""
    run = await _load_run(db, current_user.tenant_id, run_id)
    rows = (
        await db.execute(
            select(RagEvalResult)
            .where(RagEvalResult.run_id == run.id, RagEvalResult.tenant_id == current_user.tenant_id)
            .order_by(RagEvalResult.position)
        )
    ).scalars().all()
    return EvalRunResultsResponse(run_id=run.id, results=[_result_response(row) for row in rows])


@router.post("/eval/runs/{run_id}/cancel", response_model=EvalRunSummary)
async def cancel_run(
    run_id: uuid.UUID,
    current_user: TokenPayload = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> EvalRunSummary:
    """E10: cancel a pending or running run (a running run stops before its next case)."""
    run = await _load_run(db, current_user.tenant_id, run_id)
    if run.status not in ACTIVE_RUN_STATUSES:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Run has already finished")
    if run.status == EvalRunStatus.PENDING.value:
        run.finished_at = _utc_now()
    run.status = EvalRunStatus.CANCELLED.value
    await db.commit()
    return _run_summary(run)


@router.delete("/eval/runs/{run_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_run(
    run_id: uuid.UUID,
    current_user: TokenPayload = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """E11: delete a finished run and its results (409 while pending or running)."""
    tenant_id = current_user.tenant_id
    run = await _load_run(db, tenant_id, run_id)
    if run.status in ACTIVE_RUN_STATUSES:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Cannot delete a run that is in progress")
    # SQLite does not enforce ON DELETE CASCADE, so delete the children explicitly.
    await db.execute(delete(RagEvalResult).where(RagEvalResult.run_id == run.id, RagEvalResult.tenant_id == tenant_id))
    await db.execute(delete(RagEvalRun).where(RagEvalRun.id == run.id, RagEvalRun.tenant_id == tenant_id))
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)

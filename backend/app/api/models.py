from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Iterable, List, Literal, Sequence

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_current_user
from app.db.database import get_db
from app.models.audit import Model, ModelVersion
from app.models.chat import ChatMessage, ChatRoleEnum, ChatSession
from app.models.document import Document, DocumentStatus
from app.schemas.auth import TokenPayload
from app.schemas.models import (
    ExportedChatCitation,
    ExportedDocument,
    ModelCreate,
    ModelExportData,
    ModelSummary,
    ModelVersionCreate,
    ModelVersionDTO,
)
from app.schemas.metrics import MetricValue, PopulationDecilesResponse, PopulationDecile
from app.schemas.compare import (
    ModelCompareRequest,
    ModelCompareResponse,
    ComparisonModelDTO,
    ComparisonMetric,
    ComparisonDiff,
    ComparisonFindings,
)
from app.services.analytics.policy_checker import to_fraction_scale, to_percentage_scale

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/models", tags=["Models"])


def _find_current_version(model: Model) -> ModelVersion | None:
    """Return the version flagged ``is_current`` (no fallback)."""
    for version in model.versions:
        if version.is_current:
            return version
    return None


async def _last_analyzed_by_version(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    version_ids: Iterable[uuid.UUID],
) -> dict[uuid.UUID, datetime]:
    """Map each model version to the upload time of its newest READY document.

    Args:
        db: Active database session.
        tenant_id: Tenant scope for the documents.
        version_ids: Model versions to look up.

    Returns:
        ``{model_version_id: max(upload_time)}``; versions without READY documents are absent.
    """
    ids = list(version_ids)
    if not ids:
        return {}
    result = await db.execute(
        select(Document.model_version_id, func.max(Document.upload_time))
        .where(
            Document.tenant_id == tenant_id,
            Document.status == DocumentStatus.READY,
            Document.model_version_id.in_(ids),
        )
        .group_by(Document.model_version_id)
    )
    return {version_id: last for version_id, last in result.all()}


async def _build_summaries(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    models: Sequence[Model],
) -> list[ModelSummary]:
    """Build ``ModelSummary`` DTOs (current version + last analyzed time) for loaded models.

    Args:
        db: Active database session.
        tenant_id: Tenant that owns the models.
        models: Models loaded with ``selectinload(Model.versions)``.

    Returns:
        One summary per model, in input order.
    """
    current_versions = {model.id: _find_current_version(model) for model in models}
    last_analyzed = await _last_analyzed_by_version(
        db, tenant_id, (v.id for v in current_versions.values() if v is not None)
    )
    summaries: list[ModelSummary] = []
    for model in models:
        summary = ModelSummary.model_validate(model)
        current_version = current_versions[model.id]
        if current_version:
            summary.current_version = ModelVersionDTO.model_validate(current_version)
            summary.last_analyzed_at = last_analyzed.get(current_version.id)
        summaries.append(summary)
    return summaries


@router.get("", response_model=List[ModelSummary])
async def list_models(
    db: AsyncSession = Depends(get_db),
    current_user: TokenPayload = Depends(get_current_user),
):
    """List tenant-scoped models."""
    result = await db.execute(
        select(Model)
        .where(Model.tenant_id == current_user.tenant_id)
        .options(selectinload(Model.versions))
    )
    models = result.scalars().all()
    return await _build_summaries(db, current_user.tenant_id, models)

@router.post("", response_model=ModelSummary, status_code=status.HTTP_201_CREATED)
async def create_model(
    request: ModelCreate,
    db: AsyncSession = Depends(get_db),
    current_user: TokenPayload = Depends(get_current_user),
):
    """Create a new Model and an initial ModelVersion."""
    new_model = Model(
        tenant_id=current_user.tenant_id,
        user_id=current_user.sub,
        name=request.name,
        type=request.type,
        description=request.description,
        portfolio=request.portfolio,
        algorithm=request.algorithm,
    )
    db.add(new_model)
    await db.flush()
    
    new_version = ModelVersion(
        model_id=new_model.id,
        version=request.initial_version,
        is_current=True,
    )
    db.add(new_version)
    await db.commit()
    
    result = await db.execute(
        select(Model)
        .where(Model.id == new_model.id)
        .options(selectinload(Model.versions))
    )
    model = result.scalars().first()
    
    summary = ModelSummary.model_validate(model)
    summary.current_version = ModelVersionDTO.model_validate(new_version)
    return summary

@router.get("/{model_id}", response_model=ModelSummary)
async def get_model(
    model_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: TokenPayload = Depends(get_current_user),
):
    """Get full summary including metrics and gap analysis."""
    result = await db.execute(
        select(Model)
        .where(Model.id == model_id, Model.tenant_id == current_user.tenant_id)
        .options(selectinload(Model.versions))
    )
    model = result.scalars().first()
    
    if not model:
        raise HTTPException(status_code=404, detail="Model not found")

    summaries = await _build_summaries(db, current_user.tenant_id, [model])
    return summaries[0]

@router.get("/{model_id}/versions", response_model=List[ModelVersionDTO])
async def get_model_versions(
    model_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: TokenPayload = Depends(get_current_user),
):
    """Get model lineage history."""
    model_res = await db.execute(
        select(Model.id)
        .where(Model.id == model_id, Model.tenant_id == current_user.tenant_id)
    )
    if not model_res.scalars().first():
        raise HTTPException(status_code=404, detail="Model not found")
        
    result = await db.execute(
        select(ModelVersion)
        .where(ModelVersion.model_id == model_id)
        .order_by(ModelVersion.created_at.desc())
    )
    return result.scalars().all()

@router.post(
    "/{model_id}/versions",
    response_model=ModelVersionDTO,
    status_code=status.HTTP_201_CREATED,
)
async def create_model_version(
    model_id: uuid.UUID,
    request: ModelVersionCreate,
    db: AsyncSession = Depends(get_db),
    current_user: TokenPayload = Depends(get_current_user),
):
    """Create a new version of a model and make it the current one.

    The previous current version becomes the parent and is flagged
    ``is_current=False``. The new version starts without metrics, gap analysis
    or population deciles, so the model status is reset to ``None`` (pending)
    until a document is analysed against it.

    Raises:
        HTTPException: 404 if the model is not in the caller's tenant; 409 if
            the version label already exists for this model.
    """
    result = await db.execute(
        select(Model)
        .where(Model.id == model_id, Model.tenant_id == current_user.tenant_id)
        .options(selectinload(Model.versions))
    )
    model = result.scalars().first()
    if not model:
        raise HTTPException(status_code=404, detail="Model not found")

    if any(v.version == request.version for v in model.versions):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Version '{request.version}' already exists for this model",
        )

    previous = _find_current_version(model)
    if previous is None and model.versions:
        previous = max(model.versions, key=lambda v: v.created_at)
    for version in model.versions:
        version.is_current = False

    new_version = ModelVersion(
        model_id=model.id,
        version=request.version,
        is_current=True,
        parent_version_id=previous.id if previous else None,
    )
    db.add(new_version)
    model.status = None
    await db.commit()
    await db.refresh(new_version)
    logger.info(
        f"Created version {new_version.version} ({new_version.id}) for model {model.id} "
        f"in tenant {current_user.tenant_id}"
    )
    return new_version

@router.get("/{model_id}/export-data", response_model=ModelExportData)
async def export_model_data(
    model_id: uuid.UUID,
    include_citations: bool = False,
    include_audit_trail: bool = False,
    db: AsyncSession = Depends(get_db),
    current_user: TokenPayload = Depends(get_current_user),
):
    """Comprehensive JSON payload of the model's data.

    Args:
        include_citations: Add ``chat_citations`` — sources cited by the caller's
            AI Analyst answers in sessions scoped to any version of this model.
        include_audit_trail: Add ``documents`` — every document uploaded against
            any version of this model.
    """
    result = await db.execute(
        select(Model)
        .where(Model.id == model_id, Model.tenant_id == current_user.tenant_id)
        .options(selectinload(Model.versions))
    )
    model = result.scalars().first()
    
    if not model:
        raise HTTPException(status_code=404, detail="Model not found")

    summary = (await _build_summaries(db, current_user.tenant_id, [model]))[0]
        
    versions_result = await db.execute(
        select(ModelVersion)
        .where(ModelVersion.model_id == model_id)
        .order_by(ModelVersion.created_at.desc())
    )
    history = versions_result.scalars().all()
    version_ids = [v.id for v in history]

    documents = (
        await _export_documents(db, current_user.tenant_id, version_ids)
        if include_audit_trail
        else None
    )
    chat_citations = (
        await _export_chat_citations(db, current_user, version_ids)
        if include_citations
        else None
    )
    
    return ModelExportData(
        model_info=summary,
        history=[ModelVersionDTO.model_validate(v) for v in history],
        documents=documents,
        chat_citations=chat_citations,
    )


async def _export_documents(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    version_ids: list[uuid.UUID],
) -> list[ExportedDocument]:
    """List the tenant's documents attached to any of the given model versions, oldest first."""
    if not version_ids:
        return []
    result = await db.execute(
        select(Document)
        .where(
            Document.tenant_id == tenant_id,
            Document.model_version_id.in_(version_ids),
        )
        .order_by(Document.upload_time)
    )
    return [ExportedDocument.model_validate(d) for d in result.scalars().all()]


async def _export_chat_citations(
    db: AsyncSession,
    current_user: TokenPayload,
    version_ids: list[uuid.UUID],
) -> list[ExportedChatCitation]:
    """Collect the sources of the caller's assistant answers in chats scoped to the given versions.

    Chat sessions are private to their owner, so only the caller's own
    sessions are exported.
    """
    if not version_ids:
        return []
    result = await db.execute(
        select(ChatMessage)
        .join(ChatSession, ChatMessage.session_id == ChatSession.id)
        .where(
            ChatSession.tenant_id == current_user.tenant_id,
            ChatSession.user_id == current_user.sub,
            ChatSession.model_version_id.in_(version_ids),
            ChatMessage.role == ChatRoleEnum.ASSISTANT,
        )
        .order_by(ChatMessage.created_at)
    )
    return [
        ExportedChatCitation(
            session_id=message.session_id,
            message_id=message.id,
            created_at=message.created_at,
            sources=message.sources_json or [],
        )
        for message in result.scalars().all()
    ]

@router.get("/{model_id}/metrics/population-deciles", response_model=PopulationDecilesResponse)
async def get_population_deciles(
    model_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: TokenPayload = Depends(get_current_user),
):
    """Return population deciles for the current model version."""
    result = await db.execute(
        select(Model)
        .where(Model.id == model_id, Model.tenant_id == current_user.tenant_id)
        .options(selectinload(Model.versions))
    )
    model = result.scalars().first()

    if not model:
        raise HTTPException(status_code=404, detail="Model not found")

    current_version = None
    for version in model.versions:
        if version.is_current:
            current_version = version
            break
    if current_version is None and model.versions:
        current_version = model.versions[0]

    if current_version is None or current_version.population_deciles is None:
        return PopulationDecilesResponse(deciles=[])

    return PopulationDecilesResponse(
        deciles=[PopulationDecile(**d) for d in current_version.population_deciles]
    )


def _resolve_current_version(model: Model) -> ModelVersion | None:
    """Return the current version, falling back to the first loaded version."""
    current = _find_current_version(model)
    if current is None and model.versions:
        return model.versions[0]
    return current


MetricScale = Literal["percent", "fraction"]

# (profile key, display label, scale) — scales mirror the policy checker so the
# comparison shows the same numbers the compliance rules were evaluated on.
_COMPARED_METRICS: tuple[tuple[str, str, MetricScale], ...] = (
    ("gini", "Gini Coefficient", "percent"),
    ("auc", "AUC", "fraction"),
    ("ks", "KS Statistic", "percent"),
    ("psi", "PSI", "fraction"),
)


def _num(version_metrics: dict | None, key: str, scale: MetricScale) -> float | None:
    """Read a stored metric and normalise it to its display scale.

    Args:
        version_metrics: ``ModelVersion.metrics`` (a ``ModelValidationProfile`` dump).
        key: Profile field name, e.g. ``"gini"``.
        scale: ``"percent"`` (0-100) or ``"fraction"`` (0-1).

    Returns:
        The normalised value, or ``None`` when missing or malformed.
    """
    if not version_metrics:
        return None
    metric = version_metrics.get(key)
    if not isinstance(metric, dict):
        return None
    try:
        value = float(metric.get("value"))
    except (TypeError, ValueError):
        return None
    normalisable = MetricValue(
        value=value,
        unit=str(metric.get("unit") or ""),
        raw_text=str(metric.get("raw_text") or ""),
        context=str(metric.get("context") or ""),
    )
    if scale == "percent":
        return to_percentage_scale(normalisable)
    return to_fraction_scale(normalisable)


def _fmt(scale: MetricScale, value: float | None) -> str:
    """Format a normalised metric value for display (``""`` when missing)."""
    if value is None:
        return ""
    if scale == "percent":
        return f"{round(value, 2):g}%"
    return f"{round(value, 3):g}"


def _open_findings(version: ModelVersion | None) -> int:
    if version is None or not version.gap_analysis:
        return 0
    results = version.gap_analysis.get("results", [])
    return sum(
        1
        for r in results
        if isinstance(r, dict) and r.get("status") in ("BREACH", "WARNING")
    )


@router.post("/compare", response_model=ModelCompareResponse)
async def compare_models(
    request: ModelCompareRequest,
    db: AsyncSession = Depends(get_db),
    current_user: TokenPayload = Depends(get_current_user),
):
    """Compare two tenant models across metrics, methodology, and findings."""
    baseline_result = await db.execute(
        select(Model)
        .where(Model.id == request.model_id_a, Model.tenant_id == current_user.tenant_id)
        .options(selectinload(Model.versions))
    )
    baseline_model = baseline_result.scalars().first()
    if not baseline_model:
        raise HTTPException(status_code=404, detail="Baseline model not found")

    challenger_result = await db.execute(
        select(Model)
        .where(Model.id == request.model_id_b, Model.tenant_id == current_user.tenant_id)
        .options(selectinload(Model.versions))
    )
    challenger_model = challenger_result.scalars().first()
    if not challenger_model:
        raise HTTPException(status_code=404, detail="Challenger model not found")

    baseline_version = _resolve_current_version(baseline_model)
    challenger_version = _resolve_current_version(challenger_model)

    baseline_version_str = baseline_version.version if baseline_version else "1.0"
    challenger_version_str = challenger_version.version if challenger_version else "1.0"

    baseline_raw_metrics = baseline_version.metrics if baseline_version else None
    challenger_raw_metrics = challenger_version.metrics if challenger_version else None

    # The baseline card shows its own values; only the challenger card carries
    # the old -> new diff against the baseline.
    baseline_metrics: list[ComparisonMetric] = []
    challenger_metrics: list[ComparisonMetric] = []
    for key, label, scale in _COMPARED_METRICS:
        baseline_str = _fmt(scale, _num(baseline_raw_metrics, key, scale))
        challenger_str = _fmt(scale, _num(challenger_raw_metrics, key, scale))
        baseline_metrics.append(ComparisonMetric(name=label, value=baseline_str))
        challenger_metrics.append(
            ComparisonMetric(
                name=label,
                value=challenger_str,
                old_value=baseline_str or None,
                new_value=challenger_str or None,
                is_diff=bool(baseline_str and challenger_str and baseline_str != challenger_str),
            )
        )

    baseline_methodology = baseline_model.description or f"{baseline_model.name} implementation"
    challenger_methodology = challenger_model.description or f"{challenger_model.name} implementation"

    methodology_diff = None
    if (
        baseline_model.algorithm
        and challenger_model.algorithm
        and baseline_model.algorithm != challenger_model.algorithm
    ):
        methodology_diff = ComparisonDiff(
            type="changed",
            text=f"Algorithm changed from {baseline_model.algorithm} to {challenger_model.algorithm}",
            old_val=baseline_model.algorithm,
            new_val=challenger_model.algorithm,
        )

    # No per-model data configuration is captured yet; the UI hides empty values.
    data_config = ""

    baseline_open = _open_findings(baseline_version)
    challenger_open = _open_findings(challenger_version)

    baseline_findings = ComparisonFindings(open_count=baseline_open)
    if baseline_open > challenger_open:
        resolved = baseline_open - challenger_open
        challenger_findings = ComparisonFindings(
            open_count=challenger_open,
            resolved_count=resolved,
            diff_note=f"{resolved} findings resolved",
        )
    else:
        challenger_findings = ComparisonFindings(open_count=challenger_open)

    baseline = ComparisonModelDTO(
        title=baseline_model.name,
        role="baseline",
        version=baseline_version_str,
        methodology=baseline_methodology,
        methodology_diff=None,
        data_config=data_config,
        data_config_diff=None,
        metrics=baseline_metrics,
        findings=baseline_findings,
    )

    challenger = ComparisonModelDTO(
        title=challenger_model.name,
        role="challenger",
        version=challenger_version_str,
        methodology=challenger_methodology,
        methodology_diff=methodology_diff,
        data_config=data_config,
        data_config_diff=None,
        metrics=challenger_metrics,
        findings=challenger_findings,
    )

    return ModelCompareResponse(baseline=baseline, challenger=challenger)

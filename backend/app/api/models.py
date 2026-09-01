from __future__ import annotations

import uuid
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_current_user
from app.db.database import get_db
from app.models.audit import Model, ModelVersion
from app.models.system import TenantSettings
from app.schemas.auth import TokenPayload
from app.schemas.models import ModelCreate, ModelSummary, ModelVersionDTO, ModelExportData
from app.schemas.metrics import PopulationDecilesResponse, PopulationDecile
from app.schemas.compare import (
    ModelCompareRequest,
    ModelCompareResponse,
    ComparisonModelDTO,
    ComparisonMetric,
    ComparisonDiff,
    ComparisonFindings,
)

router = APIRouter(prefix="/models", tags=["Models"])

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
    
    summaries = []
    for model in models:
        current_version = None
        for version in model.versions:
            if version.is_current:
                current_version = version
                break
        
        summary = ModelSummary.model_validate(model)
        if current_version:
            summary.current_version = ModelVersionDTO.model_validate(current_version)
        summaries.append(summary)
        
    return summaries

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
        
    current_version = None
    for version in model.versions:
        if version.is_current:
            current_version = version
            break
            
    summary = ModelSummary.model_validate(model)
    if current_version:
        summary.current_version = ModelVersionDTO.model_validate(current_version)
        
    return summary

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

@router.get("/{model_id}/export-data", response_model=ModelExportData)
async def export_model_data(
    model_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: TokenPayload = Depends(get_current_user),
):
    """Comprehensive JSON payload of the model's data."""
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
            
    summary = ModelSummary.model_validate(model)
    if current_version:
        summary.current_version = ModelVersionDTO.model_validate(current_version)
        
    versions_result = await db.execute(
        select(ModelVersion)
        .where(ModelVersion.model_id == model_id)
        .order_by(ModelVersion.created_at.desc())
    )
    history = versions_result.scalars().all()
    
    return ModelExportData(
        model_info=summary,
        history=[ModelVersionDTO.model_validate(v) for v in history]
    )

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
    for version in model.versions:
        if version.is_current:
            return version
    if model.versions:
        return model.versions[0]
    return None


def _num(version_metrics: dict | None, key: str) -> float | None:
    if not version_metrics:
        return None
    metric = version_metrics.get(key)
    if not isinstance(metric, dict):
        return None
    value = metric.get("value")
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _fmt(key: str, value: float | None) -> str:
    if value is None:
        return ""
    if key == "gini":
        return f"{value}%"
    return f"{round(value, 3)}"


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

    baseline_metrics = baseline_version.metrics if baseline_version else None
    challenger_metrics = challenger_version.metrics if challenger_version else None

    metrics = []
    for key, label in (
        ("gini", "Gini Coefficient"),
        ("auc", "AUC"),
        ("ks", "KS Statistic"),
        ("psi", "PSI"),
    ):
        baseline_val = _num(baseline_metrics, key)
        challenger_val = _num(challenger_metrics, key)
        metrics.append(
            ComparisonMetric(
                name=label,
                value=_fmt(key, challenger_val),
                old_value=_fmt(key, baseline_val) if baseline_val is not None else None,
                new_value=_fmt(key, challenger_val) if challenger_val is not None else None,
                is_diff=(
                    baseline_val is not None
                    and challenger_val is not None
                    and baseline_val != challenger_val
                ),
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

    settings_res = await db.execute(
        select(TenantSettings).where(TenantSettings.tenant_id == current_user.tenant_id)
    )
    settings = settings_res.scalars().first()
    window_months = settings.min_observation_months if settings else 24
    data_config = f"{window_months}-month observation window"

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
        metrics=metrics,
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
        metrics=metrics,
        findings=challenger_findings,
    )

    return ModelCompareResponse(baseline=baseline, challenger=challenger)

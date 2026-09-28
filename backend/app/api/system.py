from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import ValidationError
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_current_user
from app.db.database import get_db
from app.models.audit import Model, ModelStatusEnum, ModelVersion
from app.models.chat import ChatMessage, ChatRoleEnum, ChatSession
from app.models.document import Document, DocumentStatus
from app.models.system import Notification, RegulatoryStandard, TenantSettings
from app.models.user import User
from app.schemas.auth import TokenPayload
from app.schemas.metrics import ModelValidationProfile
from app.schemas.system import (
    DashboardMetricsResponse,
    GlobalSearchResponse,
    NotificationResponse,
    SearchResultItem,
    TenantSettingsResponse,
    TenantSettingsUpdate,
    UserProfileResponse,
    UserProfileUpdate,
)
from app.services.analytics.policy_checker import PolicyChecker, compute_model_status

logger = logging.getLogger(__name__)

router = APIRouter(tags=["System"])


@router.get("/dashboard/metrics", response_model=DashboardMetricsResponse)
async def get_dashboard_metrics(
    current_user: TokenPayload = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Calculate aggregated stats across the tenant's models."""
    
    # Active Models Count
    models_query = select(func.count()).select_from(Model).where(Model.tenant_id == current_user.tenant_id)
    models_result = await db.execute(models_query)
    active_models = models_result.scalar() or 0

    # Documents Analyzed Count
    docs_query = select(func.count()).select_from(Document).where(
        Document.tenant_id == current_user.tenant_id,
        Document.status == DocumentStatus.READY
    )
    docs_result = await db.execute(docs_query)
    documents_analyzed = docs_result.scalar() or 0

    # Compliance Issues Count (Models with BREACH or WARNING)
    issues_query = select(func.count()).select_from(Model).where(
        Model.tenant_id == current_user.tenant_id,
        Model.status.in_([ModelStatusEnum.BREACH, ModelStatusEnum.WARNING])
    )
    issues_result = await db.execute(issues_query)
    compliance_issues = issues_result.scalar() or 0

    # AI Reviews Count (assistant answers produced by the AI Analyst in this tenant)
    reviews_query = (
        select(func.count(ChatMessage.id))
        .join(ChatSession, ChatMessage.session_id == ChatSession.id)
        .where(
            ChatSession.tenant_id == current_user.tenant_id,
            ChatMessage.role == ChatRoleEnum.ASSISTANT,
        )
    )
    reviews_result = await db.execute(reviews_query)
    ai_reviews = reviews_result.scalar() or 0

    return DashboardMetricsResponse(
        active_models=active_models,
        documents_analyzed=documents_analyzed,
        compliance_issues=compliance_issues,
        ai_reviews=ai_reviews,
    )


@router.get("/settings", response_model=TenantSettingsResponse)
async def get_tenant_settings(
    current_user: TokenPayload = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get the current tenant's settings."""
    query = select(TenantSettings).where(TenantSettings.tenant_id == current_user.tenant_id)
    result = await db.execute(query)
    settings = result.scalar_one_or_none()

    if not settings:
        # Create default settings if not exists
        settings = TenantSettings(tenant_id=current_user.tenant_id)
        db.add(settings)
        await db.commit()
        await db.refresh(settings)

    return settings


@router.put("/settings", response_model=TenantSettingsResponse)
async def update_tenant_settings(
    settings_update: TenantSettingsUpdate,
    current_user: TokenPayload = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update the current tenant's settings."""
    query = select(TenantSettings).where(TenantSettings.tenant_id == current_user.tenant_id)
    result = await db.execute(query)
    settings = result.scalar_one_or_none()

    if not settings:
        settings = TenantSettings(tenant_id=current_user.tenant_id)
        db.add(settings)

    update_data = settings_update.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(settings, key, value)

    # Flush + refresh so column defaults of a freshly created row are populated
    # before the thresholds are read by the policy checker.
    await db.flush()
    await db.refresh(settings)
    reevaluated = await _reevaluate_tenant_models(db, current_user.tenant_id, settings)
    logger.info(
        f"Tenant {current_user.tenant_id} settings updated; re-evaluated {reevaluated} model(s)"
    )

    await db.commit()
    await db.refresh(settings)
    return settings


async def _reevaluate_tenant_models(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    settings: TenantSettings,
) -> int:
    """Re-run the policy checker for every model's current version under new thresholds.

    Updates ``ModelVersion.gap_analysis`` and ``Model.status`` in the session
    without committing. Current versions without stored metrics (e.g. a fresh
    version awaiting its first document) are left untouched.

    Args:
        db: Active session; the caller commits.
        tenant_id: Tenant whose models are re-evaluated.
        settings: Tenant settings carrying the new thresholds.

    Returns:
        Number of models whose current version was re-evaluated.
    """
    result = await db.execute(
        select(Model)
        .where(Model.tenant_id == tenant_id)
        .options(selectinload(Model.versions))
    )
    checker = PolicyChecker()
    reevaluated = 0
    for model in result.scalars().all():
        current_version = next((v for v in model.versions if v.is_current), None)
        if current_version is None or not current_version.metrics:
            continue
        try:
            profile = ModelValidationProfile.model_validate(current_version.metrics)
        except ValidationError as exc:
            logger.warning(
                f"Skipping re-evaluation of model {model.id}: stored metrics are invalid ({exc})"
            )
            continue
        report = checker.check(profile, settings)
        # Reassign (not mutate) the JSON column so SQLAlchemy detects the change.
        current_version.gap_analysis = report.model_dump()
        model.status = compute_model_status(report)
        reevaluated += 1
    return reevaluated


@router.get("/notifications", response_model=list[NotificationResponse])
async def get_notifications(
    current_user: TokenPayload = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Fetch user alerts from the Notification table."""
    query = (
        select(Notification)
        .where(
            Notification.tenant_id == current_user.tenant_id,
            Notification.user_id == current_user.sub
        )
        .order_by(Notification.created_at.desc())
        .limit(50)
    )
    result = await db.execute(query)
    return list(result.scalars().all())


@router.post("/notifications/{notification_id}/read", response_model=NotificationResponse)
async def mark_notification_read(
    notification_id: uuid.UUID,
    current_user: TokenPayload = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Mark a notification as read (tenant + user scoped)."""
    query = select(Notification).where(
        Notification.id == notification_id,
        Notification.tenant_id == current_user.tenant_id,
        Notification.user_id == current_user.sub,
    )
    result = await db.execute(query)
    notification = result.scalars().first()
    if not notification:
        raise HTTPException(status_code=404, detail="Notification not found")
    notification.is_read = True
    await db.commit()
    await db.refresh(notification)
    return notification


def _like_pattern(q: str) -> str:
    """Build a substring ILIKE pattern, escaping LIKE wildcards in the user's input."""
    escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


@router.get("/search", response_model=GlobalSearchResponse)
async def global_search(
    q: str,
    current_user: TokenPayload = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """ILIKE search over models, regulatory standards and the tenant's documents.

    Matches ``Model.name``/``description`` (tenant-scoped), ``RegulatoryStandard``
    ``title``/``code``/``description`` (shared catalogue) and ``Document.filename``
    (tenant-scoped; each hit carries the owning model id when resolvable).
    """
    search_term = _like_pattern(q)
    
    # Search Models
    models_query = (
        select(Model)
        .where(
            Model.tenant_id == current_user.tenant_id,
            or_(
                Model.name.ilike(search_term, escape="\\"),
                Model.description.ilike(search_term, escape="\\"),
            )
        )
        .limit(20)
    )
    models_result = await db.execute(models_query)
    models = models_result.scalars().all()

    # Search Regulatory Standards (global reference catalogue, not tenant data)
    reg_query = (
        select(RegulatoryStandard)
        .where(
            or_(
                RegulatoryStandard.title.ilike(search_term, escape="\\"),
                RegulatoryStandard.code.ilike(search_term, escape="\\"),
                RegulatoryStandard.description.ilike(search_term, escape="\\"),
            )
        )
        .limit(20)
    )
    reg_result = await db.execute(reg_query)
    standards = reg_result.scalars().all()

    # Search Documents by filename; resolve the owning model within the same tenant
    docs_query = (
        select(Document.id, Document.filename, Model.id)
        .outerjoin(ModelVersion, Document.model_version_id == ModelVersion.id)
        .outerjoin(
            Model,
            and_(
                Model.id == ModelVersion.model_id,
                Model.tenant_id == current_user.tenant_id,
            ),
        )
        .where(
            Document.tenant_id == current_user.tenant_id,
            Document.filename.ilike(search_term, escape="\\"),
        )
        .order_by(Document.upload_time.desc())
        .limit(20)
    )
    docs_result = await db.execute(docs_query)
    documents = docs_result.all()

    results: list[SearchResultItem] = []
    for model in models:
        results.append(
            SearchResultItem(
                id=model.id,
                type="model",
                title=model.name,
                description=model.description,
                model_id=model.id,
            )
        )

    for standard in standards:
        results.append(
            SearchResultItem(
                id=standard.id,
                type="regulatory_standard",
                title=standard.title,
                description=standard.code,
                model_id=None,
            )
        )

    for doc_id, filename, owning_model_id in documents:
        results.append(
            SearchResultItem(
                id=doc_id,
                type="document",
                title=filename,
                description="Document",
                model_id=owning_model_id,
            )
        )

    return GlobalSearchResponse(results=results)


@router.get("/users/me", response_model=UserProfileResponse)
async def get_user_profile(
    current_user: TokenPayload = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return extended user profile fields."""
    user = await _get_current_user_row(db, current_user)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    return user


@router.patch("/users/me", response_model=UserProfileResponse)
async def update_user_profile(
    profile_update: UserProfileUpdate,
    current_user: TokenPayload = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update the caller's own profile (``full_name``, ``title``, ``division``).

    Only fields present in the request body are applied; ``role`` and
    ``security_clearance`` cannot be changed through this endpoint.
    """
    user = await _get_current_user_row(db, current_user)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    for key, value in profile_update.model_dump(exclude_unset=True).items():
        setattr(user, key, value)

    await db.commit()
    await db.refresh(user)
    return user


async def _get_current_user_row(db: AsyncSession, current_user: TokenPayload) -> User | None:
    """Load the authenticated user's row, scoped to their tenant."""
    result = await db.execute(
        select(User).where(
            User.id == current_user.sub,
            User.tenant_id == current_user.tenant_id,
        )
    )
    return result.scalar_one_or_none()

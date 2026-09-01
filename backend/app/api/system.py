from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.database import get_db
from app.models.audit import Model, ModelStatusEnum
from app.models.document import Document, DocumentStatus
from app.models.system import Notification, RegulatoryStandard, TenantSettings
from app.models.user import User
from app.schemas.auth import TokenPayload
from app.schemas.system import (
    DashboardMetricsResponse,
    GlobalSearchResponse,
    NotificationResponse,
    SearchResultItem,
    TenantSettingsResponse,
    TenantSettingsUpdate,
    UserProfileResponse,
)

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

    return DashboardMetricsResponse(
        active_models=active_models,
        documents_analyzed=documents_analyzed,
        compliance_issues=compliance_issues
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

    await db.commit()
    await db.refresh(settings)
    return settings


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


@router.get("/search", response_model=GlobalSearchResponse)
async def global_search(
    q: str,
    current_user: TokenPayload = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Basic ILIKE search over Model.name, Model.description, and RegulatoryStandard.title."""
    search_term = f"%{q}%"
    
    # Search Models
    models_query = (
        select(Model)
        .where(
            Model.tenant_id == current_user.tenant_id,
            or_(
                Model.name.ilike(search_term),
                Model.description.ilike(search_term)
            )
        )
        .limit(20)
    )
    models_result = await db.execute(models_query)
    models = models_result.scalars().all()

    # Search Regulatory Standards
    reg_query = (
        select(RegulatoryStandard)
        .where(RegulatoryStandard.title.ilike(search_term))
        .limit(20)
    )
    reg_result = await db.execute(reg_query)
    standards = reg_result.scalars().all()

    results = []
    for model in models:
        results.append(
            SearchResultItem(
                id=model.id,
                type="model",
                title=model.name,
                description=model.description
            )
        )

    for standard in standards:
        results.append(
            SearchResultItem(
                id=standard.id,
                type="regulatory_standard",
                title=standard.title,
                description=None
            )
        )

    return GlobalSearchResponse(results=results)


@router.get("/users/me", response_model=UserProfileResponse)
async def get_user_profile(
    current_user: TokenPayload = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return extended user profile fields."""
    query = select(User).where(User.id == current_user.sub)
    result = await db.execute(query)
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    return user

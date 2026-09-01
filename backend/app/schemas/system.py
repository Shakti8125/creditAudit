from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.system import NotificationTypeEnum
from app.models.user import RoleEnum


class DashboardMetricsResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    
    active_models: int
    documents_analyzed: int
    compliance_issues: int


class TenantSettingsUpdate(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    gini_tolerance: float | None = None
    psi_warning_threshold: float | None = None
    psi_breach_threshold: float | None = None
    auto_mask_bank: bool | None = None
    auto_mask_borrower: bool | None = None
    auto_mask_location: bool | None = None
    strict_zero_trust: bool | None = None
    min_observation_months: int | None = None


class TenantSettingsResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    
    id: uuid.UUID
    tenant_id: uuid.UUID
    gini_tolerance: float
    psi_warning_threshold: float
    psi_breach_threshold: float
    auto_mask_bank: bool
    auto_mask_borrower: bool
    auto_mask_location: bool
    strict_zero_trust: bool
    min_observation_months: int
    updated_at: datetime


class NotificationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    
    id: uuid.UUID
    title: str
    description: str | None = None
    type: NotificationTypeEnum
    is_read: bool
    created_at: datetime
    model_id: uuid.UUID | None = None


class SearchResultItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    type: str  # 'model' or 'regulatory_standard'
    title: str
    description: str | None = None


class GlobalSearchResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    results: list[SearchResultItem]


class UserProfileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    
    id: uuid.UUID
    email: str
    full_name: str | None = None
    title: str | None = None
    division: str | None = None
    security_clearance: str | None = None
    role: RoleEnum
    is_active: bool
    created_at: datetime

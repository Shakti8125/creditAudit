from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.system import NotificationTypeEnum
from app.models.user import RoleEnum


class DashboardMetricsResponse(BaseModel):
    """Tenant-wide KPI counters for the overview dashboard."""

    model_config = ConfigDict(from_attributes=True)
    
    active_models: int
    documents_analyzed: int
    compliance_issues: int
    ai_reviews: int = 0


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


SearchResultType = Literal["model", "regulatory_standard", "document"]


class SearchResultItem(BaseModel):
    """A single global-search hit.

    Attributes:
        id: Model, regulatory standard or document id (depending on ``type``).
        type: Kind of entity matched.
        title: Model name, standard title or document filename.
        description: Model description, standard code, or ``"Document"``.
        model_id: Owning model for models (their own id) and documents; ``None`` for standards.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    type: SearchResultType
    title: str
    description: str | None = None
    model_id: uuid.UUID | None = None


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


class UserProfileUpdate(BaseModel):
    """Self-service profile edit payload for ``PATCH /users/me``.

    Only the fields sent are applied. ``role`` and ``security_clearance`` are
    administrator-managed and deliberately absent (unknown fields are ignored).
    Blank strings are stored as ``None``.
    """

    model_config = ConfigDict(from_attributes=True, str_strip_whitespace=True)

    full_name: str | None = Field(default=None, max_length=120)
    title: str | None = Field(default=None, max_length=120)
    division: str | None = Field(default=None, max_length=120)

    @field_validator("full_name", "title", "division")
    @classmethod
    def _blank_to_none(cls, value: str | None) -> str | None:
        """Normalise empty strings to ``None`` so cleared fields read as unset."""
        return value or None

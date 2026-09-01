from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, List, Optional
from pydantic import BaseModel, ConfigDict

from app.models.audit import ModelTypeEnum, ModelStatusEnum


class ModelVersionDTO(BaseModel):
    """Schema for a specific version of a model."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    model_id: uuid.UUID
    version: str
    is_current: bool
    parent_version_id: uuid.UUID | None = None
    metrics: dict[str, Any] | None = None
    gap_analysis: dict[str, Any] | None = None
    population_deciles: list[dict] | None = None
    created_at: datetime


class ModelSummary(BaseModel):
    """Schema for returning a summary of a Model."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    user_id: uuid.UUID
    name: str
    type: ModelTypeEnum
    description: str | None = None
    portfolio: str | None = None
    algorithm: str | None = None
    status: ModelStatusEnum | None = None
    created_at: datetime
    current_version: ModelVersionDTO | None = None


class ModelCreate(BaseModel):
    """Schema for creating a new Model."""
    
    model_config = ConfigDict(from_attributes=True)
    
    name: str
    type: ModelTypeEnum
    description: str | None = None
    portfolio: str | None = None
    algorithm: str | None = None
    initial_version: str = "1.0"


class ModelExportData(BaseModel):
    """Schema for comprehensive model export."""

    model_config = ConfigDict(from_attributes=True)

    model_info: ModelSummary
    history: List[ModelVersionDTO]

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, List, Optional
from pydantic import BaseModel, ConfigDict, Field

from app.models.audit import ModelTypeEnum, ModelStatusEnum
from app.models.document import DocumentStatus


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
    # Upload time of the newest READY document attached to the current version.
    last_analyzed_at: datetime | None = None


class ModelCreate(BaseModel):
    """Schema for creating a new Model."""
    
    model_config = ConfigDict(from_attributes=True)
    
    name: str
    type: ModelTypeEnum
    description: str | None = None
    portfolio: str | None = None
    algorithm: str | None = None
    initial_version: str = "1.0"


class ModelVersionCreate(BaseModel):
    """Schema for creating a new version of an existing Model.

    Attributes:
        version: Version label, unique per model (surrounding whitespace is stripped).
    """

    model_config = ConfigDict(from_attributes=True, str_strip_whitespace=True)

    version: str = Field(..., min_length=1, max_length=32)


class ExportedDocument(BaseModel):
    """Document entry in the audit trail of a model export."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    filename: str
    file_type: str
    upload_time: datetime
    status: DocumentStatus
    model_version_id: uuid.UUID | None = None


class ExportedChatCitation(BaseModel):
    """Sources cited by one AI Analyst answer, included in a model export.

    Attributes:
        session_id: Chat session the answer belongs to.
        message_id: Assistant message id.
        created_at: Time the answer was persisted (UTC).
        sources: Citation dicts (``source``, ``section``, ``text``, ``score``,
            ``retrieval_method``) exactly as stored with the message.
    """

    model_config = ConfigDict(from_attributes=True)

    session_id: uuid.UUID
    message_id: uuid.UUID
    created_at: datetime
    sources: List[dict[str, Any]] = Field(default_factory=list)


class ModelExportData(BaseModel):
    """Schema for comprehensive model export.

    ``documents`` is only populated when the audit trail is requested and
    ``chat_citations`` only when citations are requested; otherwise both are ``None``.
    """

    model_config = ConfigDict(from_attributes=True)

    model_info: ModelSummary
    history: List[ModelVersionDTO]
    documents: Optional[List[ExportedDocument]] = None
    chat_citations: Optional[List[ExportedChatCitation]] = None

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.models.document import DocumentStatus


class UploadResponse(BaseModel):
    """Schema for document upload response."""

    model_config = ConfigDict(from_attributes=True)

    document_id: uuid.UUID
    filename: str
    file_type: str
    page_count: int
    chunk_count: int
    masking_report: dict[str, Any]
    metrics_summary: dict[str, Any]


class DocumentMetadata(BaseModel):
    """Schema for document metadata."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    filename: str
    file_type: str
    upload_time: datetime
    status: DocumentStatus
    chunk_count: int = 0
    model_version_id: uuid.UUID | None = None


class DocumentListResponse(BaseModel):
    """Schema for list of documents response."""

    model_config = ConfigDict(from_attributes=True)

    documents: list[DocumentMetadata]

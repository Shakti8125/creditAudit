from __future__ import annotations

from typing import Any
from pydantic import BaseModel, ConfigDict


class ChunkData(BaseModel):
    """Schema for document chunk data."""

    model_config = ConfigDict(from_attributes=True)

    source: str
    section: str
    text: str
    page: int | None = None


class VectorResult(BaseModel):
    """Schema for vector similarity search result."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    score: float
    metadata: dict[str, Any]


class RetrievalCandidate(BaseModel):
    """Schema for an intermediate retrieval candidate."""

    model_config = ConfigDict(from_attributes=True)

    chunk_text: str
    source: str
    section: str
    score: float
    retrieval_method: str


class Citation(BaseModel):
    """Schema for a retrieved source citation."""

    model_config = ConfigDict(from_attributes=True)

    source: str
    section: str
    text: str
    score: float
    retrieval_method: str


class RetrievalResult(BaseModel):
    """Schema for aggregated retrieval result."""

    model_config = ConfigDict(from_attributes=True)

    citations: list[Citation]
    latency_ms: float
    retrieval_metadata: dict[str, Any]

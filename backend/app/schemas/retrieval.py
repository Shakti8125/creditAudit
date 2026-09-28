from __future__ import annotations

import enum
from typing import Any
from pydantic import BaseModel, ConfigDict, Field


class RetrievalMode(str, enum.Enum):
    """Retrieval pipeline configuration (ablation modes).

    ``HYBRID_RERANK`` is the production pipeline; the other modes exist so the
    offline evaluation can measure the contribution of each stage.
    """

    DENSE = "dense"
    BM25 = "bm25"
    HYBRID = "hybrid"
    HYBRID_RERANK = "hybrid_rerank"


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


class CandidatePreview(BaseModel):
    """Text-free preview of a pre-rerank candidate (used by telemetry)."""

    model_config = ConfigDict(from_attributes=True)

    source: str
    section: str
    score: float
    retrieval_method: str


class RetrievalDiagnostics(BaseModel):
    """Per-stage timings, counts and degradation flags for one retrieval."""

    model_config = ConfigDict(from_attributes=True)

    mode: RetrievalMode
    dense_ms: float | None = None
    bm25_ms: float | None = None
    fusion_ms: float | None = None
    rerank_ms: float | None = None
    dense_count: int = 0
    bm25_count: int = 0
    fused_count: int = 0
    final_count: int = 0
    rerank_applied: bool = False
    rerank_fallback: bool = False
    dense_empty: bool = False
    fused_preview: list[CandidatePreview] = Field(default_factory=list)


class RetrievalResult(BaseModel):
    """Schema for aggregated retrieval result."""

    model_config = ConfigDict(from_attributes=True)

    citations: list[Citation]
    latency_ms: float
    retrieval_metadata: dict[str, Any]
    diagnostics: RetrievalDiagnostics | None = None

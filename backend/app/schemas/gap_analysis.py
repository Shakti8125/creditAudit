from __future__ import annotations

from uuid import UUID
from pydantic import BaseModel, ConfigDict


class ComplianceGap(BaseModel):
    """Schema for a compliance gap item.

    Numbers are accepted as strings (a model that writes 0.25 for a text field is not a failure).
    """

    model_config = ConfigDict(from_attributes=True, coerce_numbers_to_str=True)

    requirement: str
    status: str
    description: str
    recommendation: str


class GapAnalysisRequest(BaseModel):
    """Schema for gap analysis request."""

    model_config = ConfigDict(from_attributes=True)

    document_id: UUID


class GapAnalysisResponse(BaseModel):
    """Schema for gap analysis response."""

    model_config = ConfigDict(from_attributes=True)

    gaps: list[ComplianceGap]
    coverage_score: float

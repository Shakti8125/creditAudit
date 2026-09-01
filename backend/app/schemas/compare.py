from __future__ import annotations

from uuid import UUID
from pydantic import BaseModel, ConfigDict


class CompareRequest(BaseModel):
    """Schema for document comparison request."""

    model_config = ConfigDict(from_attributes=True)

    document_id_a: UUID
    document_id_b: UUID
    focus_areas: list[str] | None = None


class ComparisonDifference(BaseModel):
    """Schema for an individual difference between two documents."""

    model_config = ConfigDict(from_attributes=True)

    category: str
    description: str
    doc_a_value: str
    doc_b_value: str


class CompareResponse(BaseModel):
    """Schema for document comparison response."""

    model_config = ConfigDict(from_attributes=True)

    differences: list[ComparisonDifference]
    summary: str


class ComparisonMetric(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    name: str
    value: str
    old_value: str | None = None
    new_value: str | None = None
    is_diff: bool = False


class ComparisonDiff(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    type: str  # 'added' | 'changed' | 'removed'
    text: str
    old_val: str | None = None
    new_val: str | None = None


class ComparisonFindings(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    label: str = "Open Findings"
    open_count: int = 0
    resolved_count: int | None = None
    diff_note: str | None = None


class ComparisonModelDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    title: str
    role: str  # 'baseline' | 'challenger'
    version: str
    methodology: str
    methodology_diff: ComparisonDiff | None = None
    data_config: str
    data_config_diff: ComparisonDiff | None = None
    metrics: list[ComparisonMetric]
    findings: ComparisonFindings


class ModelCompareRequest(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    model_id_a: UUID
    model_id_b: UUID


class ModelCompareResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    baseline: ComparisonModelDTO
    challenger: ComparisonModelDTO

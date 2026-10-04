from __future__ import annotations
import uuid
from datetime import datetime
from pydantic import BaseModel, ConfigDict
from typing import List
from app.schemas.retrieval import Citation

class RegulatoryQuery(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    question: str

class RegulatoryResponse(BaseModel):
    """Answer to a regulatory question.

    Attributes:
        answer: The generated answer.
        citations: Sources the answer is grounded in.
        trace_id: RAG trace id, for feedback.
        truncated: True when the answer was cut off at the token budget, so it is incomplete.
    """

    model_config = ConfigDict(from_attributes=True)
    answer: str
    citations: List[Citation]
    trace_id: uuid.UUID | None = None
    truncated: bool = False

class RegulatoryStandardResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    code: str
    title: str
    authority: str
    jurisdiction: str
    effective_date: str | None = None
    category: str | None = None
    description: str | None = None
    clauses_json: list[dict]
    created_at: datetime

class RegulatoryStandardListResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    standards: List[RegulatoryStandardResponse]

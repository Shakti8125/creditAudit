from __future__ import annotations
from pydantic import BaseModel, ConfigDict
from typing import Optional, List
from uuid import UUID
from app.schemas.retrieval import Citation

class QueryRequest(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    document_id: Optional[UUID] = None
    question: str
    session_id: Optional[UUID] = None

class QueryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    answer: str
    citations: List[Citation]

from __future__ import annotations

import uuid
from pydantic import BaseModel, ConfigDict


class MaskRequest(BaseModel):
    """Request schema for live privacy masking."""

    # Pydantic v2 configuration for ORM attribute compatibility
    model_config = ConfigDict(from_attributes=True)

    text: str
    session_id: uuid.UUID | None = None


class MaskResponse(BaseModel):
    """Response schema containing masked text and the redaction mapping."""

    # Pydantic v2 configuration for ORM attribute compatibility
    model_config = ConfigDict(from_attributes=True)

    masked_text: str
    redactions: dict[str, str]


class RedactionLogResponse(BaseModel):
    """Response schema containing session redaction log mapping."""

    # Pydantic v2 configuration for ORM attribute compatibility
    model_config = ConfigDict(from_attributes=True)

    session_id: uuid.UUID
    redactions: dict[str, str]

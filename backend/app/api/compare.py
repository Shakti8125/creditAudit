from __future__ import annotations

import json
import logging
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.database import get_db
from app.models.document import Document, DocumentChunk
from app.schemas.auth import TokenPayload
from app.schemas.compare import CompareRequest, CompareResponse
from app.services.llm.router import LLMRouter
from app.services.privacy.egress_validator import EgressValidator
from app.services.privacy.masking_pipeline import MaskingPipeline

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/compare", tags=["Compare"])


@router.post("", response_model=CompareResponse)
async def compare_documents(
    request: CompareRequest,
    current_user: TokenPayload = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Compare two credit risk model documents for discrepancies and methodological drift."""
    # Verify ownership and get chunks for document A
    doc_a_res = await db.execute(
        select(Document).where(
            Document.id == request.document_id_a,
            Document.tenant_id == current_user.tenant_id,
        )
    )
    doc_a = doc_a_res.scalar_one_or_none()
    if not doc_a:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document A not found or does not belong to this tenant",
        )

    chunks_a_res = await db.execute(
        select(DocumentChunk)
        .where(DocumentChunk.document_id == request.document_id_a)
        .order_by(DocumentChunk.chunk_index)
    )
    chunks_a = chunks_a_res.scalars().all()

    # Verify ownership and get chunks for document B
    doc_b_res = await db.execute(
        select(Document).where(
            Document.id == request.document_id_b,
            Document.tenant_id == current_user.tenant_id,
        )
    )
    doc_b = doc_b_res.scalar_one_or_none()
    if not doc_b:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document B not found or does not belong to this tenant",
        )

    chunks_b_res = await db.execute(
        select(DocumentChunk)
        .where(DocumentChunk.document_id == request.document_id_b)
        .order_by(DocumentChunk.chunk_index)
    )
    chunks_b = chunks_b_res.scalars().all()

    text_a = "\n\n".join([chunk.masked_text for chunk in chunks_a])
    text_b = "\n\n".join([chunk.masked_text for chunk in chunks_b])

    max_length = 20000
    text_a = text_a[:max_length]
    text_b = text_b[:max_length]

    system_prompt = (
        "You are ModelAudit AI, a credit risk expert. Compare the two provided model validation documents. "
        "Extract key differences in Methodology, Assumptions, Validation Results, and Metrics."
    )

    focus = ", ".join(request.focus_areas) if request.focus_areas else "all relevant credit risk areas"

    # Privacy masking & egress validation on user focus areas (API-03)
    masking_pipeline = MaskingPipeline()
    egress_validator = EgressValidator()

    masked_focus, registry = masking_pipeline.mask_document(focus)
    egress_validator.validate(masked_focus, registry)

    prompt = (
        f"Document A:\n{text_a}\n\n"
        f"Document B:\n{text_b}\n\n"
        f"Please compare Document A and Document B focusing on: {masked_focus}."
    )
    egress_validator.validate(prompt, registry)

    llm_router = LLMRouter()

    schema = {
        "type": "object",
        "properties": {
            "differences": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "category": {"type": "string"},
                        "description": {"type": "string"},
                        "doc_a_value": {"type": "string"},
                        "doc_b_value": {"type": "string"},
                    },
                    "required": ["category", "description", "doc_a_value", "doc_b_value"],
                },
            },
            "summary": {"type": "string"},
        },
        "required": ["differences", "summary"],
    }

    result_str = await llm_router.generate(prompt, system_prompt=system_prompt, json_schema=schema)

    try:
        result_json = json.loads(result_str)
        return CompareResponse(**result_json)
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"Failed to parse LLM comparison JSON: {e}")
        # Fallback if json parsing fails
        return CompareResponse(
            differences=[],
            summary=result_str,
        )


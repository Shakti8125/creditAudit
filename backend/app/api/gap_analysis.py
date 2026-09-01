from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.database import get_db
from app.models.document import Document, DocumentChunk
from app.schemas.auth import TokenPayload
from app.schemas.gap_analysis import GapAnalysisRequest, GapAnalysisResponse
from app.services.llm.router import LLMRouter
from app.services.privacy.egress_validator import EgressValidator, EgressViolationError
from starlette.concurrency import run_in_threadpool

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/gap-analysis", tags=["Gap Analysis"])


@router.post("", response_model=GapAnalysisResponse)
async def analyze_gaps(
    request: GapAnalysisRequest,
    current_user: TokenPayload = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Assess document against CBUAE Model Management Guidelines checklist."""
    # Verify ownership
    doc_res = await db.execute(
        select(Document).where(
            Document.id == request.document_id,
            Document.tenant_id == current_user.tenant_id,
        )
    )
    doc = doc_res.scalar_one_or_none()
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found or does not belong to this tenant",
        )

    # Load chunks
    chunks_res = await db.execute(
        select(DocumentChunk)
        .where(DocumentChunk.document_id == request.document_id)
        .order_by(DocumentChunk.chunk_index)
    )
    chunks = chunks_res.scalars().all()

    text = "\n\n".join([chunk.masked_text for chunk in chunks])
    max_length = 30000
    text = text[:max_length]

    system_prompt = (
        "You are ModelAudit AI, checking a model document for compliance against CBUAE Model Management Guidelines."
    )

    checklist = [
        "Discrimination testing via Gini coefficient (Target >= 40%)",
        "Population Stability Index (PSI) (Target <= 0.25)",
        "Documentation of qualitative assumptions",
        "Backtesting results over a 12-month period",
    ]

    prompt = (
        f"Document Content:\n{text}\n\n"
        f"Assess the document against the following CBUAE MMG requirements:\n"
        f"{json.dumps(checklist)}\n"
        "Return the gaps found."
    )

    # Privacy Rule 2: Strictly validate egress text through EgressValidator before dispatching to LLM
    validator = EgressValidator()
    try:
        await run_in_threadpool(validator.validate, prompt)
    except EgressViolationError as e:
        logger.warning(f"Privacy egress violation in gap analysis for doc {request.document_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Privacy validation failed: {str(e)}",
        ) from e

    llm_router = LLMRouter()

    schema = {
        "type": "object",
        "properties": {
            "gaps": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "requirement": {"type": "string"},
                        "status": {"type": "string", "enum": ["PASS", "WARNING", "BREACH", "MISSING"]},
                        "description": {"type": "string"},
                        "recommendation": {"type": "string"},
                    },
                    "required": ["requirement", "status", "description", "recommendation"],
                },
            },
            "coverage_score": {"type": "number"},
        },
        "required": ["gaps", "coverage_score"],
    }

    try:
        result_str = await llm_router.generate(prompt, system_prompt=system_prompt, json_schema=schema)
        result_json = json.loads(result_str)
        return GapAnalysisResponse(**result_json)
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Failed to generate gap analysis from LLM: {exc}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to generate gap analysis from LLM",
        ) from exc
    finally:
        # Prevent connection pool leaks by closing LLMRouter client
        await llm_router.aclose()


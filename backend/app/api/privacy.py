from __future__ import annotations

import logging
import uuid
from fastapi import APIRouter, Depends, HTTPException, status
from starlette.concurrency import run_in_threadpool

from app.api.deps import get_current_user
from app.schemas.auth import TokenPayload
from app.schemas.privacy import MaskRequest, MaskResponse, RedactionLogResponse
from app.services.privacy.masking_pipeline import MaskingPipeline
from app.services.privacy.registry_store import get_registry

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/privacy", tags=["Privacy"])


@router.get("/redactions", response_model=RedactionLogResponse)
async def get_redactions(
    session_id: uuid.UUID,
    current_user: TokenPayload = Depends(get_current_user),
):
    """Return the redaction log from the *in-memory* EntityRegistry for the given session."""
    registry = get_registry(session_id)
    return RedactionLogResponse(
        session_id=session_id,
        redactions=registry.get_mapping(),
    )


@router.post("/mask", response_model=MaskResponse)
async def mask_text(
    request: MaskRequest,
    current_user: TokenPayload = Depends(get_current_user),
):
    """Live redaction simulator endpoint that runs text through the MaskingPipeline."""
    registry = None
    if request.session_id:
        registry = get_registry(request.session_id)
        
    masking_pipeline = MaskingPipeline()
    # Offload CPU-bound synchronous masking (spaCy / Presidio) to threadpool to prevent blocking the async event loop
    masked_text, result_registry = await run_in_threadpool(
        masking_pipeline.mask_document,
        request.text,
        registry=registry,
    )
    
    return MaskResponse(
        masked_text=masked_text,
        redactions=result_registry.get_mapping(),
    )

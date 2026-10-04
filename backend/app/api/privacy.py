from __future__ import annotations

import logging
import uuid
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.api.deps import get_current_user
from app.db.database import get_db
from app.models.chat import ChatSession
from app.schemas.auth import TokenPayload
from app.schemas.privacy import MaskRequest, MaskResponse, RedactionLogResponse
from app.services.privacy.entity_registry import EntityRegistry
from app.services.privacy.masking_pipeline import MaskingPipeline
from app.services.privacy.session_registry import (
    MAX_SESSION_MESSAGES,
    build_session_state,
    load_session_messages,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/privacy", tags=["Privacy"])


async def _require_owned_session(
    db: AsyncSession,
    session_id: uuid.UUID,
    current_user: TokenPayload,
) -> None:
    """Ensure a chat session belongs to the caller (same tenant and same user).

    Args:
        db: Active database session.
        session_id: Chat session whose entity registry is being accessed.
        current_user: Authenticated caller.

    Raises:
        HTTPException: 404 when the session does not exist or belongs to someone
            else, without revealing which of the two applies.
    """
    owned = await db.execute(
        select(ChatSession.id).where(
            ChatSession.id == session_id,
            ChatSession.tenant_id == current_user.tenant_id,
            ChatSession.user_id == current_user.sub,
        )
    )
    if owned.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chat session not found",
        )


async def _derive_session_registry(
    db: AsyncSession,
    session_id: uuid.UUID,
    current_user: TokenPayload,
) -> EntityRegistry:
    """Derive a session's registry from its persisted messages (QA-011).

    The same rebuild ``POST /query`` uses, so every worker returns the same map.
    At most the first ``MAX_SESSION_MESSAGES`` messages are masked.

    Args:
        db: Active database session.
        session_id: Chat session (ownership already checked).
        current_user: Authenticated caller.

    Returns:
        A registry private to the caller (safe to mutate).
    """
    messages = await load_session_messages(db, session_id, current_user.tenant_id)
    state = await run_in_threadpool(
        build_session_state, session_id, messages[:MAX_SESSION_MESSAGES], MaskingPipeline()
    )
    return state.registry


@router.get("/redactions", response_model=RedactionLogResponse)
async def get_redactions(
    session_id: uuid.UUID,
    current_user: TokenPayload = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the redaction log of the given session.

    The registry is derived deterministically from the session's persisted
    messages (never stored), so the log is the same on every worker. It maps raw
    entities to their masking tokens, so it is only served to the user who owns
    the chat session (same tenant and same user); any other caller gets a 404
    that does not reveal whether the session exists.
    """
    await _require_owned_session(db, session_id, current_user)
    registry = await _derive_session_registry(db, session_id, current_user)
    return RedactionLogResponse(
        session_id=session_id,
        redactions=registry.get_mapping(),
    )


@router.post("/mask", response_model=MaskResponse)
async def mask_text(
    request: MaskRequest,
    current_user: TokenPayload = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Live redaction simulator endpoint that runs text through the MaskingPipeline.

    When ``session_id`` is given the session's registry is used (and its full
    mapping returned), so the same ownership rule as ``/privacy/redactions`` applies.
    The simulator works on a private copy: it never changes what the chat masks.
    """
    registry = None
    if request.session_id:
        await _require_owned_session(db, request.session_id, current_user)
        registry = await _derive_session_registry(db, request.session_id, current_user)

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

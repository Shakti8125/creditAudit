from __future__ import annotations

import logging
import uuid
from typing import Any, AsyncIterator, Dict, List, Optional, Union

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.database import async_session_maker, get_db
from app.models.audit import Model, ModelVersion
from app.models.chat import ChatMessage, ChatRoleEnum, ChatSession
from app.models.document import Document, DocumentStatus
from starlette.concurrency import run_in_threadpool
from app.schemas.auth import TokenPayload
from app.schemas.query import ChatMessageResponse, ChatSessionSummary, QueryRequest, QueryResponse
from app.schemas.retrieval import Citation
from app.services.guardrails.checks import run_input_guardrails, run_output_guardrails
from app.services.llm.router import LLMRouter
from app.services.privacy.egress_validator import EgressValidator
from app.services.privacy.masking_pipeline import MaskingPipeline
from app.services.retrieval.hybrid_retriever import HybridRetriever
from app.services.retrieval.pinecone_store import PineconeStore
from app.utils.streaming import sse_stream

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/query", tags=["Query"])

# Maximum length of ``last_message_preview`` in the session listing.
SESSION_PREVIEW_CHARS = 160


async def _get_tenant_document(
    db: AsyncSession,
    document_id: uuid.UUID,
    current_user: TokenPayload,
) -> Document:
    """Load a document owned by the caller's tenant.

    Raises:
        HTTPException: 404 when the document is missing or belongs to another tenant.
    """
    doc_res = await db.execute(
        select(Document).where(
            Document.id == document_id,
            Document.tenant_id == current_user.tenant_id,
        )
    )
    doc = doc_res.scalar_one_or_none()
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found or does not belong to this tenant",
        )
    return doc


async def _require_tenant_model_version(
    db: AsyncSession,
    model_version_id: uuid.UUID,
    current_user: TokenPayload,
) -> None:
    """Ensure a model version belongs to a model of the caller's tenant.

    Raises:
        HTTPException: 404 when the version is missing or belongs to another tenant.
    """
    mv_res = await db.execute(
        select(ModelVersion.id)
        .join(Model, ModelVersion.model_id == Model.id)
        .where(
            ModelVersion.id == model_version_id,
            Model.tenant_id == current_user.tenant_id,
        )
    )
    if mv_res.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Model version not found",
        )


async def _latest_ready_document(
    db: AsyncSession,
    model_version_id: uuid.UUID,
    tenant_id: uuid.UUID,
) -> Optional[Document]:
    """Return the most recently uploaded READY document of a model version, if any."""
    doc_res = await db.execute(
        select(Document)
        .where(
            Document.model_version_id == model_version_id,
            Document.tenant_id == tenant_id,
            Document.status == DocumentStatus.READY,
        )
        .order_by(Document.upload_time.desc())
        .limit(1)
    )
    return doc_res.scalars().first()


async def _get_owned_chat_session(
    db: AsyncSession,
    session_id: uuid.UUID,
    current_user: TokenPayload,
) -> ChatSession:
    """Load a chat session owned by the caller (same tenant and same user).

    Raises:
        HTTPException: 404 when the session is missing or belongs to someone else.
    """
    session_res = await db.execute(
        select(ChatSession).where(
            ChatSession.id == session_id,
            ChatSession.tenant_id == current_user.tenant_id,
            ChatSession.user_id == current_user.sub,
        )
    )
    chat_session = session_res.scalar_one_or_none()
    if not chat_session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chat session not found",
        )
    return chat_session


async def _resolve_query_scope(
    db: AsyncSession,
    request: QueryRequest,
    current_user: TokenPayload,
) -> tuple[Optional[uuid.UUID], Optional[uuid.UUID]]:
    """Resolve which document grounds the answer and which model version scopes the chat.

    An explicit ``document_id`` always wins for retrieval. Otherwise, when a
    ``model_version_id`` is given, the latest READY document of that version is
    used; with neither (or a version without documents) retrieval falls back
    to the regulatory corpus only.

    Args:
        db: Active database session.
        request: Incoming query request.
        current_user: Authenticated caller.

    Returns:
        ``(document_id, model_version_id)`` for retrieval and the chat session;
        either may be ``None``.

    Raises:
        HTTPException: 404 for a document or model version outside the tenant.
    """
    doc = None
    if request.document_id:
        doc = await _get_tenant_document(db, request.document_id, current_user)

    if request.model_version_id:
        await _require_tenant_model_version(db, request.model_version_id, current_user)
        if doc is None:
            doc = await _latest_ready_document(db, request.model_version_id, current_user.tenant_id)
        return (doc.id if doc else None), request.model_version_id

    if doc is None:
        return None, None
    return doc.id, doc.model_version_id


@router.get("/sessions", response_model=List[ChatSessionSummary])
async def list_chat_sessions(
    model_version_id: Optional[uuid.UUID] = None,
    current_user: TokenPayload = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List the caller's own chat sessions in their tenant, newest first.

    Args:
        model_version_id: Optional filter to sessions scoped to this model version.
    """
    message_count = (
        select(func.count(ChatMessage.id))
        .where(ChatMessage.session_id == ChatSession.id)
        .correlate(ChatSession)
        .scalar_subquery()
    )
    last_message = (
        select(ChatMessage.content)
        .where(ChatMessage.session_id == ChatSession.id)
        .order_by(ChatMessage.created_at.desc())
        .limit(1)
        .correlate(ChatSession)
        .scalar_subquery()
    )
    query = (
        select(ChatSession, message_count, last_message)
        .where(
            ChatSession.tenant_id == current_user.tenant_id,
            ChatSession.user_id == current_user.sub,
        )
        .order_by(ChatSession.created_at.desc())
        .limit(100)
    )
    if model_version_id is not None:
        query = query.where(ChatSession.model_version_id == model_version_id)

    rows = (await db.execute(query)).all()
    return [
        ChatSessionSummary(
            id=chat_session.id,
            model_version_id=chat_session.model_version_id,
            created_at=chat_session.created_at,
            message_count=count or 0,
            last_message_preview=(
                last_content[:SESSION_PREVIEW_CHARS] if last_content is not None else None
            ),
        )
        for chat_session, count, last_content in rows
    ]


@router.get("/sessions/{session_id}/messages", response_model=List[ChatMessageResponse])
async def list_chat_messages(
    session_id: uuid.UUID,
    current_user: TokenPayload = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the messages of one of the caller's chat sessions, oldest first.

    Raises:
        HTTPException: 404 when the session is not the caller's.
    """
    await _get_owned_chat_session(db, session_id, current_user)
    result = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.created_at, ChatMessage.id)
    )
    return list(result.scalars().all())


@router.post("")
async def conversational_query(
    request: QueryRequest,
    current_user: TokenPayload = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Conversational Q&A endpoint against document chunks and CBUAE regulatory corpus."""
    from app.services.privacy.registry_store import get_registry

    retrieval_document_id, scope_version_id = await _resolve_query_scope(db, request, current_user)

    # 0. Input guardrails — run before any session/message is persisted so a
    # blocked request leaves no trace in the chat history.
    violation = await run_input_guardrails(request.question)
    if violation:
        logger.warning(
            f"Input guardrail '{violation.reason}' blocked a /query request "
            f"for tenant {current_user.tenant_id}"
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=violation.detail,
        )

    # 1. Manage ChatSession
    session_id = request.session_id
    chat_session = None
    if session_id:
        chat_session = await _get_owned_chat_session(db, session_id, current_user)
    else:
        chat_session = ChatSession(
            id=uuid.uuid4(),
            tenant_id=current_user.tenant_id,
            user_id=current_user.sub,
            model_version_id=scope_version_id,
        )
        db.add(chat_session)
        await db.commit()
        await db.refresh(chat_session)
        session_id = chat_session.id

    # 2. Persist user query
    user_message = ChatMessage(
        session_id=session_id,
        role=ChatRoleEnum.USER,
        content=request.question,
    )
    db.add(user_message)
    await db.commit()

    # 3. Fetch chat history
    history_res = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.created_at)
    )
    history = history_res.scalars().all()
    history_context = "\n".join([f"{msg.role.value.capitalize()}: {msg.content}" for msg in history[:-1]])

    llm_router = LLMRouter()
    try:
        pinecone_store = PineconeStore()
        retriever = HybridRetriever(llm_router, pinecone_store)

        retrieval_result = await retriever.retrieve(
            query=request.question,
            tenant_id=current_user.tenant_id,
            document_id=retrieval_document_id,
            db=db,
            top_k=6,
        )

        # Privacy masking & egress validation on user question and prompt (API-03)
        masking_pipeline = MaskingPipeline()
        egress_validator = EgressValidator()

        registry = get_registry(session_id)
        masked_question, _ = await run_in_threadpool(
            masking_pipeline.mask_document, request.question, registry=registry
        )
        await run_in_threadpool(egress_validator.validate, masked_question, registry)

        # Multi-turn chat unmasked history context fix: mask prior conversation history using the session registry
        # to prevent unmasked entities from prior turns tripping egress validation on the final prompt.
        masked_history_context = ""
        if history_context:
            masked_history_context, _ = await run_in_threadpool(
                masking_pipeline.mask_document, history_context, registry=registry
            )

        context_text = "\n\n".join([
            f"Source: {c.source}\nSection: {c.section}\nContent: {c.text}"
            for c in retrieval_result.citations
        ])

        system_prompt = (
            "You are ModelAudit AI, a virtual analyst expert in credit risk model validation and CBUAE Model Management Guidelines (MMG). "
            "Answer the user's question based strictly on the provided context and the conversation history. "
            "When referencing information, you MUST cite the source using the format [Source: <source_name>, Section: <section_name>]."
        )

        prompt = ""
        if masked_history_context:
            prompt += f"Conversation History:\n{masked_history_context}\n\n"
        prompt += f"Context:\n{context_text}\n\nQuestion: {masked_question}"
        
        await run_in_threadpool(egress_validator.validate, prompt, registry)

        # Yield citations as a custom dict first, then yield the string tokens
        async def generator() -> AsyncIterator[Union[str, Dict[str, Any]]]:
            try:
                yield {
                    "type": "session_id",
                    "content": str(session_id),
                }
                
                yield {
                    "type": "citations",
                    "content": [c.model_dump() for c in retrieval_result.citations],
                }

                full_response = ""
                async for chunk in llm_router.generate_stream(prompt, system_prompt):
                    full_response += chunk
                    yield chunk

                # Output guardrails — log-only on this endpoint. The answer has
                # already been streamed to the client chunk by chunk and cannot
                # be retracted, so a violation is recorded but not enforced.
                try:
                    out_violation = await run_output_guardrails(
                        full_response,
                        context=context_text,
                        retrieved_contexts=[c.text for c in retrieval_result.citations],
                    )
                    if out_violation:
                        logger.warning(
                            f"Output guardrail '{out_violation.reason}' flagged a streamed "
                            f"/query response for session {session_id}: {out_violation.detail}"
                        )
                except Exception as e:
                    logger.error(f"Output guardrail check failed: {e}", exc_info=True)

                # Persist assistant response safely using fresh session
                try:
                    async with async_session_maker() as stream_db:
                        ai_message = ChatMessage(
                            session_id=session_id,
                            role=ChatRoleEnum.ASSISTANT,
                            content=full_response,
                            sources_json=[c.model_dump() for c in retrieval_result.citations],
                        )
                        stream_db.add(ai_message)
                        await stream_db.commit()
                except Exception as e:
                    logger.error(f"Failed to persist assistant chat message: {e}", exc_info=True)
            finally:
                await llm_router.aclose()

        return sse_stream(generator())
    except Exception:
        await llm_router.aclose()
        raise


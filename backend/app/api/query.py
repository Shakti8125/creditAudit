from __future__ import annotations

import logging
from typing import Any, AsyncIterator, Dict, Union

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.database import async_session_maker, get_db
from app.models.document import Document
from starlette.concurrency import run_in_threadpool
from app.schemas.auth import TokenPayload
from app.schemas.query import QueryRequest, QueryResponse
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


@router.post("")
async def conversational_query(
    request: QueryRequest,
    current_user: TokenPayload = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Conversational Q&A endpoint against document chunks and CBUAE regulatory corpus."""
    import uuid
    from app.models.chat import ChatSession, ChatMessage, ChatRoleEnum
    from app.services.privacy.registry_store import get_registry

    doc = None
    if request.document_id:
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
        session_res = await db.execute(
            select(ChatSession).where(
                ChatSession.id == session_id,
                ChatSession.tenant_id == current_user.tenant_id,
            )
        )
        chat_session = session_res.scalar_one_or_none()
        if not chat_session:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Chat session not found",
            )
    else:
        chat_session = ChatSession(
            id=uuid.uuid4(),
            tenant_id=current_user.tenant_id,
            user_id=current_user.sub,
            model_version_id=doc.model_version_id if doc else None,
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
            document_id=request.document_id,
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

                # Add suggested actions
                yield {
                    "type": "suggestedActions",
                    "content": ["Explore related models", "View data source details", "Analyze discrepancies"],
                }
            finally:
                await llm_router.aclose()

        return sse_stream(generator())
    except Exception:
        await llm_router.aclose()
        raise


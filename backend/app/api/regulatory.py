from __future__ import annotations

import logging
import uuid
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.database import get_db
from app.models.rag_eval import TraceEndpoint
from app.models.system import RegulatoryStandard
from app.schemas.auth import TokenPayload
from app.schemas.regulatory import (
    RegulatoryQuery, 
    RegulatoryResponse,
    RegulatoryStandardListResponse,
    RegulatoryStandardResponse,
)
from app.services.evaluation.prompts import REGULATORY_SYSTEM_PROMPT, format_context
from app.services.evaluation.telemetry import RagTraceRecorder
from app.services.guardrails.checks import run_input_guardrails
from app.services.llm.router import LLMRouter
from app.services.privacy.egress_validator import EgressValidator
from app.services.privacy.masking_pipeline import MaskingPipeline
from app.services.retrieval.hybrid_retriever import HybridRetriever
from app.services.retrieval.pinecone_store import PineconeStore
from starlette.concurrency import run_in_threadpool

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/regulatory", tags=["Regulatory"])


@router.post("/search", response_model=RegulatoryResponse)
async def regulatory_search(
    request: RegulatoryQuery,
    current_user: TokenPayload = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Regulatory lookup endpoint for querying CBUAE Model Management Guidelines (MMG)."""
    recorder = RagTraceRecorder(
        tenant_id=current_user.tenant_id,
        user_id=current_user.sub,
        endpoint=TraceEndpoint.REGULATORY_SEARCH,
        top_k=5,
    )

    # 0. Input guardrails (same rails as /query) before any provider call.
    violation = await run_input_guardrails(request.question)
    if violation:
        logger.warning(
            f"Input guardrail '{violation.reason}' blocked a /regulatory/search request "
            f"for tenant {current_user.tenant_id}"
        )
        await recorder.record_blocked(violation.reason, request.question)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=violation.detail,
        )

    llm_router = LLMRouter()
    try:
        # Privacy masking & egress validation on user question (API-03). Runs BEFORE
        # retrieval so only the masked question reaches the embedding/rerank providers.
        masking_pipeline = MaskingPipeline()
        egress_validator = EgressValidator()

        with recorder.stage("masking"):
            masked_question, registry = await run_in_threadpool(masking_pipeline.mask_document, request.question)
            await run_in_threadpool(egress_validator.validate, masked_question, registry)
        recorder.set_masked_query(masked_question, raw_length=len(request.question))

        pinecone_store = PineconeStore()
        retriever = HybridRetriever(llm_router, pinecone_store)

        # Pure RAG against CBUAE corpus (no document upload needed).
        with recorder.stage("retrieval"):
            retrieval_result = await retriever.retrieve(
                query=masked_question,
                tenant_id=current_user.tenant_id,
                document_id=None,
                db=db,
                top_k=5,
            )
        recorder.record_retrieval(retrieval_result)

        context_text = format_context(retrieval_result.citations)
        prompt = f"Context:\n{context_text}\n\nQuestion: {masked_question}"
        with recorder.stage("masking"):
            await run_in_threadpool(egress_validator.validate, prompt, registry)
        recorder.record_prompt(prompt, REGULATORY_SYSTEM_PROMPT)

        with recorder.stage("generation"):
            answer = await llm_router.generate(prompt, system_prompt=REGULATORY_SYSTEM_PROMPT)
        recorder.record_answer(answer, contexts=[context_text])

        return RegulatoryResponse(
            answer=answer,
            citations=retrieval_result.citations,
            trace_id=recorder.trace_id,
        )
    except Exception as exc:
        await recorder.record_failure(exc, request.question)
        raise
    finally:
        await recorder.finish(llm_router)


@router.get("/standards", response_model=RegulatoryStandardListResponse)
async def get_regulatory_standards(
    current_user: TokenPayload = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Fetch the catalog of regulatory standards."""
    query = select(RegulatoryStandard).order_by(RegulatoryStandard.created_at.desc())
    result = await db.execute(query)
    standards = result.scalars().all()
    
    return RegulatoryStandardListResponse(standards=standards)


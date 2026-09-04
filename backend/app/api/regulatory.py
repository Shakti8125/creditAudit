from __future__ import annotations

import logging
import uuid
from typing import List

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.database import get_db
from app.models.system import RegulatoryStandard
from app.schemas.auth import TokenPayload
from app.schemas.regulatory import (
    RegulatoryQuery, 
    RegulatoryResponse,
    RegulatoryStandardListResponse,
    RegulatoryStandardResponse,
)
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
    llm_router = LLMRouter()
    try:
        pinecone_store = PineconeStore()
        retriever = HybridRetriever(llm_router, pinecone_store)

        # Pure RAG against CBUAE corpus (no document upload needed).
        retrieval_result = await retriever.retrieve(
            query=request.question,
            tenant_id=current_user.tenant_id,
            document_id=None,
            db=db,
            top_k=5,
        )

        # Privacy masking & egress validation on user question (API-03)
        masking_pipeline = MaskingPipeline()
        egress_validator = EgressValidator()

        masked_question, registry = await run_in_threadpool(masking_pipeline.mask_document, request.question)
        await run_in_threadpool(egress_validator.validate, masked_question, registry)

        context_text = "\n\n".join([
            f"Source: {c.source}\nSection: {c.section}\nContent: {c.text}"
            for c in retrieval_result.citations
        ])

        system_prompt = (
            "You are ModelAudit AI, a regulatory expert in CBUAE Model Management Guidelines (MMG). "
            "Answer the user's question based strictly on the provided regulatory context. "
            "Cite the source using the format [Source: <source_name>, Section: <section_name>]."
        )

        prompt = f"Context:\n{context_text}\n\nQuestion: {masked_question}"
        await run_in_threadpool(egress_validator.validate, prompt, registry)

        answer = await llm_router.generate(prompt, system_prompt=system_prompt)

        return RegulatoryResponse(
            answer=answer,
            citations=retrieval_result.citations,
        )
    finally:
        await llm_router.aclose()


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


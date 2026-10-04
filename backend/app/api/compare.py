from __future__ import annotations

import logging
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.api.errors import (
    CODE_GENERATION_FAILED,
    CODE_INPUT_BLOCKED,
    CODE_OUTPUT_BLOCKED,
    client_http_error,
    typed_error,
)
from app.db.database import get_db
from app.models.document import Document, DocumentChunk
from app.schemas.auth import TokenPayload
from app.schemas.compare import CompareRequest, CompareResponse
from app.services.guardrails.checks import run_input_guardrails, run_output_guardrails
from app.services.llm.router import LLMRouter
from app.services.privacy.egress_validator import EgressValidator, EgressViolationError
from app.services.privacy.masking_pipeline import MaskingPipeline
from starlette.concurrency import run_in_threadpool

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/compare", tags=["Compare"])

# JSON schema sent to the provider. It lives next to CompareResponse, which validates the reply.
COMPARE_SCHEMA = {
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
        "Extract key differences in Methodology, Assumptions, Validation Results, and Metrics. "
        "Respond with one JSON object only: `differences` is a list of objects with the string fields "
        "`category`, `description`, `doc_a_value` and `doc_b_value`, and `summary` is a short string."
    )

    focus = ", ".join(request.focus_areas) if request.focus_areas else "all relevant credit risk areas"

    # Input guardrails on the caller-supplied focus areas — they are untrusted
    # free text that gets embedded verbatim into the prompt below.
    if request.focus_areas:
        violation = await run_input_guardrails(" ".join(request.focus_areas))
        if violation:
            logger.warning(
                f"Input guardrail '{violation.reason}' blocked a /compare request "
                f"for tenant {current_user.tenant_id}"
            )
            raise typed_error(
                status.HTTP_400_BAD_REQUEST, violation.detail, CODE_INPUT_BLOCKED, retryable=False
            )

    # Privacy masking & egress validation on user focus areas (API-03)
    masking_pipeline = MaskingPipeline()
    egress_validator = EgressValidator()

    masked_focus, registry = await run_in_threadpool(masking_pipeline.mask_document, focus)
    prompt = (
        f"Document A:\n{text_a}\n\n"
        f"Document B:\n{text_b}\n\n"
        f"Please compare Document A and Document B focusing on: {masked_focus}."
    )
    try:
        await run_in_threadpool(egress_validator.validate, masked_focus, registry)
        await run_in_threadpool(egress_validator.validate, prompt, registry)
    except EgressViolationError as exc:
        raise client_http_error(exc, "/compare", typed=True) from exc

    llm_router = LLMRouter()

    async def check_repair_egress(repair_prompt: str) -> None:
        """The repair prompt carries the model's own output: validate it like any other prompt."""
        await run_in_threadpool(egress_validator.validate, repair_prompt, registry)

    try:
        # Validated JSON or a typed error: schema-constrained call, thinking off, a structured
        # budget, one repair round, Gemini failover. Raw model text is never returned (QA-005).
        response = await llm_router.generate_structured(
            prompt,
            CompareResponse,
            COMPARE_SCHEMA,
            system_prompt=system_prompt,
            egress_check=check_repair_egress,
        )

        # Output guardrails — this endpoint is non-streaming, so a violation is
        # a hard block. The checks run over the generated prose fields rather
        # than the raw JSON envelope, whose structural brackets would otherwise
        # trip the placeholder-integrity check.
        out_violation = await run_output_guardrails(_guardrail_text(response))
        if out_violation:
            logger.warning(
                f"Output guardrail '{out_violation.reason}' blocked a /compare response: "
                f"{out_violation.detail}"
            )
            raise typed_error(
                status.HTTP_502_BAD_GATEWAY,
                "Generated comparison failed guardrail validation",
                CODE_OUTPUT_BLOCKED,
                retryable=True,
            )

        return response
    except HTTPException:
        raise
    except Exception as exc:
        mapped = client_http_error(exc, "/compare", typed=True)
        if mapped is not None:
            raise mapped from exc
        logger.error("Failed to generate a comparison: %s", type(exc).__name__, exc_info=True)
        raise typed_error(
            status.HTTP_502_BAD_GATEWAY,
            "Failed to generate the comparison. Please retry.",
            CODE_GENERATION_FAILED,
            retryable=True,
        ) from exc
    finally:
        await llm_router.aclose()


def _guardrail_text(response: CompareResponse) -> str:
    """Flatten a comparison response into the prose the output rails inspect."""
    parts: List[str] = [response.summary or ""]
    for diff in response.differences:
        parts.extend([diff.category, diff.description, diff.doc_a_value, diff.doc_b_value])
    return "\n".join(p for p in parts if p)


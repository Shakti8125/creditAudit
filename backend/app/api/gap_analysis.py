from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.api.errors import (
    CODE_EGRESS_BLOCKED,
    CODE_GENERATION_FAILED,
    CODE_INPUT_BLOCKED,
    CODE_OUTPUT_BLOCKED,
    client_http_error,
    typed_error,
)
from app.db.database import get_db
from app.models.document import Document, DocumentChunk
from app.schemas.auth import TokenPayload
from app.schemas.gap_analysis import GapAnalysisRequest, GapAnalysisResponse
from app.services.guardrails.checks import run_input_guardrails, run_output_guardrails
from app.services.llm.router import LLMRouter
from app.services.privacy.egress_validator import EgressValidator, EgressViolationError
from app.services.privacy.masking_pipeline import MaskingPipeline
from starlette.concurrency import run_in_threadpool

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/gap-analysis", tags=["Gap Analysis"])

# JSON schema sent to the provider. It lives next to GapAnalysisResponse, which validates the reply.
GAP_ANALYSIS_SCHEMA = {
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

    # Input guardrails on the document body itself. Gap analysis takes no free
    # text from the caller, but the uploaded document is untrusted content and
    # can carry an indirect prompt-injection payload (e.g. a PDF footnote that
    # reads "ignore previous instructions"). The off-topic rail is skipped here:
    # it keys off conversational phrases that legitimately occur in prose.
    violation = await run_input_guardrails(text, check_off_topic=False)
    if violation:
        logger.warning(
            f"Input guardrail '{violation.reason}' blocked gap analysis for "
            f"doc {request.document_id}"
        )
        raise typed_error(status.HTTP_400_BAD_REQUEST, violation.detail, CODE_INPUT_BLOCKED, retryable=False)

    system_prompt = (
        "You are ModelAudit AI, checking a model document for compliance against CBUAE Model Management Guidelines. "
        "Respond with one JSON object only: `gaps` is a list of objects with the string fields `requirement`, "
        "`status` (PASS, WARNING, BREACH or MISSING), `description` and `recommendation`, and `coverage_score` "
        "is a number from 0 to 1."
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
        raise typed_error(
            status.HTTP_400_BAD_REQUEST, f"Privacy validation failed: {str(e)}", CODE_EGRESS_BLOCKED, retryable=False
        ) from e

    llm_router = LLMRouter()

    async def check_repair_egress(repair_prompt: str) -> None:
        """The repair prompt carries the model's own output: validate it like any other prompt."""
        await run_in_threadpool(validator.validate, repair_prompt)

    try:
        # Validated JSON or a typed error: schema-constrained call, thinking off, a structured
        # budget, one repair round, Gemini failover (QA-005).
        response = await llm_router.generate_structured(
            prompt,
            GapAnalysisResponse,
            GAP_ANALYSIS_SCHEMA,
            system_prompt=system_prompt,
            egress_check=check_repair_egress,
        )

        # Output guardrails — non-streaming endpoint, so a violation hard-blocks.
        # Checked over the generated prose rather than the raw JSON envelope,
        # whose structural brackets would trip the placeholder-integrity rail.
        out_violation = await run_output_guardrails(_guardrail_text(response))
        if out_violation:
            logger.warning(
                f"Output guardrail '{out_violation.reason}' blocked a /gap-analysis "
                f"response for doc {request.document_id}: {out_violation.detail}"
            )
            raise typed_error(
                status.HTTP_502_BAD_GATEWAY,
                "Generated gap analysis failed guardrail validation",
                CODE_OUTPUT_BLOCKED,
                retryable=True,
            )

        await _persist_gap_analysis(db, doc, response)
        return response
    except HTTPException:
        raise
    except Exception as exc:
        mapped = client_http_error(exc, "/gap-analysis", typed=True)
        if mapped is not None:
            raise mapped from exc
        logger.error(f"Failed to generate gap analysis from LLM: {exc}", exc_info=True)
        raise typed_error(
            status.HTTP_502_BAD_GATEWAY,
            "Failed to generate gap analysis from LLM",
            CODE_GENERATION_FAILED,
            retryable=True,
        ) from exc
    finally:
        # Prevent connection pool leaks by closing LLMRouter client
        await llm_router.aclose()


def _guardrail_text(response: GapAnalysisResponse) -> str:
    """Flatten a gap analysis response into the prose the output rails inspect."""
    parts: list[str] = []
    for gap in response.gaps:
        parts.extend([gap.requirement, gap.description, gap.recommendation])
    return "\n".join(p for p in parts if p)


async def _persist_gap_analysis(
    db: AsyncSession,
    doc: Document,
    response: GapAnalysisResponse,
) -> None:
    """Store a validated gap analysis under ``metadata_json["llm_gap_analysis"]``.

    Exposed afterwards through ``GET /documents/{id}`` as
    ``metrics_summary.llm_gap_analysis``. Persistence is best effort: a database
    error is logged and the freshly generated analysis is still returned.

    Args:
        db: Session the document was loaded with.
        doc: Tenant-verified document the analysis was generated for.
        response: Gap analysis that passed the output guardrails.
    """
    document_id = doc.id
    try:
        # Reassign a new dict (not an in-place mutation) so the JSON column is flagged dirty.
        doc.metadata_json = {
            **(doc.metadata_json or {}),
            "llm_gap_analysis": response.model_dump(mode="json"),
        }
        await db.commit()
    except SQLAlchemyError as exc:
        logger.error(f"Failed to persist gap analysis for doc {document_id}: {exc}", exc_info=True)
        await db.rollback()

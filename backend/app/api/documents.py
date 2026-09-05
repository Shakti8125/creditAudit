from __future__ import annotations

import logging
import uuid
import tempfile
from pathlib import Path
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.api.deps import get_current_user
from app.db.database import get_db
from app.models.audit import Model, ModelStatusEnum, ModelVersion
from app.models.document import Document, DocumentChunk, DocumentStatus
from app.models.system import TenantSettings
from app.schemas.auth import TokenPayload
from app.schemas.document import DocumentListResponse, DocumentMetadata, UploadResponse
from app.schemas.retrieval import ChunkData
from app.services.analytics.ews_detector import EarlyWarningDetector
from app.services.analytics.model_metrics_extractor import ModelMetricsExtractor, parse_population_deciles
from app.services.analytics.policy_checker import PolicyChecker
from app.services.chunker import MarkdownChunker
from app.services.document_extractor import DocumentExtractor
from app.services.privacy.egress_validator import EgressValidator, EgressViolationError
from app.services.privacy.masking_pipeline import MaskingPipeline
from app.services.llm.router import LLMRouter
from app.services.retrieval.pinecone_store import PineconeStore

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/documents", tags=["documents"])

MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB
CHUNK_READ_SIZE = 1024 * 1024  # 1MB chunk size for streaming read

_document_extractor: DocumentExtractor | None = None


def get_document_extractor() -> DocumentExtractor:
    """Return shared DocumentExtractor instance to avoid reloading models on every upload."""
    global _document_extractor
    if _document_extractor is None:
        _document_extractor = DocumentExtractor()
    return _document_extractor


@router.post("/upload", response_model=UploadResponse)
async def upload_document(
    model_version_id: uuid.UUID = Form(...),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: TokenPayload = Depends(get_current_user),
):
    """Upload, extract, mask, chunk, embed, and analyze document."""
    if not file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Filename is required",
        )

    safe_filename = Path(file.filename).name.strip()
    if not safe_filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid filename",
        )

    ext = safe_filename.rsplit(".", 1)[-1].lower() if "." in safe_filename else ""
    if ext not in ("pdf", "docx"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only PDF and DOCX files are supported",
        )

    # Validate model_version_id
    mv_res = await db.execute(
        select(ModelVersion)
        .join(Model)
        .where(
            ModelVersion.id == model_version_id,
            Model.tenant_id == current_user.tenant_id,
        )
    )
    model_version = mv_res.scalars().first()
    if not model_version:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Model version not found",
        )

    # Chunked streaming read with SpooledTemporaryFile to prevent memory leaks
    spool = tempfile.SpooledTemporaryFile(max_size=1024 * 1024)
    try:
        total_bytes = 0
        while True:
            chunk = await file.read(CHUNK_READ_SIZE)
            if not chunk:
                break
            total_bytes += len(chunk)
            if total_bytes > MAX_FILE_SIZE:
                raise HTTPException(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    detail="File too large (max 50MB)",
                )
            await run_in_threadpool(spool.write, chunk)

        if total_bytes == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Uploaded file is empty",
            )

        spool.seek(0)

        # 1. Store initial Document in DB (PROCESSING state)
        doc_id = uuid.uuid4()
        db_doc = Document(
            id=doc_id,
            tenant_id=current_user.tenant_id,
            user_id=current_user.sub,
            model_version_id=model_version_id,
            filename=safe_filename,
            file_type=ext,
            raw_markdown="",
            status=DocumentStatus.PROCESSING,
        )
        db.add(db_doc)
        await db.commit()
        await db.refresh(db_doc)

        try:
            # 2. Extract markdown
            extractor = get_document_extractor()
            raw_markdown = await extractor.extract_to_markdown(spool, safe_filename)
            db_doc.raw_markdown = raw_markdown

            # 3. Analytics Extraction
            metrics_extractor = ModelMetricsExtractor()
            profile = await run_in_threadpool(metrics_extractor.extract, raw_markdown)

            # Query tenant-specific settings for dynamic thresholds during policy verification
            settings_res = await db.execute(
                select(TenantSettings).where(TenantSettings.tenant_id == current_user.tenant_id)
            )
            tenant_settings = settings_res.scalars().first()

            policy_checker = PolicyChecker()
            breach_report = await run_in_threadpool(policy_checker.check, profile, tenant_settings)

            ews_detector = EarlyWarningDetector()
            ews_report = await run_in_threadpool(ews_detector.scan, raw_markdown, profile)

            metrics_summary = {
                "profile": profile.model_dump(),
                "breach_report": breach_report.model_dump(),
                "ews_report": ews_report.model_dump(),
            }

            # Persist metrics and gap analysis results to the ModelVersion
            model_version.metrics = profile.model_dump()
            model_version.gap_analysis = breach_report.model_dump()
            model_version.population_deciles = parse_population_deciles(raw_markdown)
            db.add(model_version)

            # Model status update: Calculate overall compliance status & score for parent Model
            # This ensures GET /dashboard/metrics properly reflects model status and compliance issues
            num_breaches = sum(1 for r in breach_report.results if r.status == "BREACH")
            num_warnings = sum(1 for r in breach_report.results if r.status == "WARNING")
            num_passes = sum(1 for r in breach_report.results if r.status == "PASS")
            total_rules = len(breach_report.results)

            if num_breaches > 0:
                computed_status = ModelStatusEnum.BREACH
            elif num_warnings > 0:
                computed_status = ModelStatusEnum.WARNING
            else:
                computed_status = ModelStatusEnum.PASS

            # Update parent Model entity
            model_res = await db.execute(
                select(Model).where(
                    Model.id == model_version.model_id,
                    Model.tenant_id == current_user.tenant_id,
                )
            )
            parent_model = model_res.scalars().first()
            if parent_model:
                parent_model.status = computed_status
                db.add(parent_model)

            # 4. Privacy Masking
            masking_pipeline = MaskingPipeline()
            masked_markdown, registry = await run_in_threadpool(masking_pipeline.mask_document, raw_markdown)

            # Egress validation to ensure 0 leaks
            validator = EgressValidator()
            await run_in_threadpool(validator.validate, masked_markdown, registry)

            # 5. Chunking
            chunker = MarkdownChunker()
            chunks = await run_in_threadpool(chunker.chunk, masked_markdown)

            # 6. Embedding and storing chunks
            llm_router = LLMRouter()
            try:
                embeddings = await llm_router.embed(chunks, input_type="document")
            finally:
                await llm_router.aclose()

            pinecone_store = PineconeStore()
            # RET-06 / HybridRetriever: namespace must follow user-docs:{tenant_id}:{document_id} format
            namespace = f"user-docs:{current_user.tenant_id}:{doc_id}"

            chunk_data_list = []
            for c in chunks:
                section = ""
                # Header extraction: check for header context at the start of the chunk
                if ":\n" in c:
                    header_cand, _, _ = c.partition(":\n")
                    if "\n" not in header_cand and header_cand.strip():
                        section = header_cand.strip()
                chunk_data_list.append(ChunkData(source=safe_filename, section=section, text=c))
                
            vector_ids = [str(uuid.uuid4()) for _ in chunks]
            
            await pinecone_store.aupsert_chunks(
                chunks=chunk_data_list,
                namespace=namespace,
                vectors=embeddings,
                ids=vector_ids
            )

            for i, (chunk_text, vec_id) in enumerate(zip(chunks, vector_ids)):
                db_chunk = DocumentChunk(
                    document_id=doc_id,
                    chunk_index=i,
                    masked_text=chunk_text,
                    embedding_id=vec_id,
                )
                db.add(db_chunk)

            db_doc.status = DocumentStatus.READY
            db_doc.metadata_json = metrics_summary

            await db.commit()

            # Build category statistics summary without leaking raw unmasked entities
            entity_mapping = registry.get_mapping()
            category_counts: dict[str, int] = {}
            for token in entity_mapping.values():
                cat = token.strip("[]").split("_")[0] if "_" in token else "OTHER"
                category_counts[cat] = category_counts.get(cat, 0) + 1

            masking_report = {
                "total_entities_masked": len(entity_mapping),
                "category_counts": category_counts,
            }

            return UploadResponse(
                document_id=doc_id,
                filename=safe_filename,
                file_type=ext,
                page_count=0,
                chunk_count=len(chunks),
                masking_report=masking_report,
                metrics_summary=metrics_summary,
            )

        except EgressViolationError as e:
            logger.warning(f"Privacy egress violation on document upload {doc_id}: {e}")
            await db.rollback()
            res = await db.execute(select(Document).where(Document.id == doc_id))
            err_doc = res.scalars().first()
            if err_doc:
                err_doc.status = DocumentStatus.ERROR
                await db.commit()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Privacy validation failed: {str(e)}",
            )
        except Exception as e:
            logger.error(f"Error processing document {doc_id}: {e}", exc_info=True)
            await db.rollback()
            res = await db.execute(select(Document).where(Document.id == doc_id))
            err_doc = res.scalars().first()
            if err_doc:
                err_doc.status = DocumentStatus.ERROR
                await db.commit()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Error processing document: {str(e)}",
            )
    finally:
        spool.close()


@router.get("", response_model=DocumentListResponse)
async def list_documents(
    db: AsyncSession = Depends(get_db),
    current_user: TokenPayload = Depends(get_current_user),
):
    """List all documents for the current tenant with accurate chunk counts."""
    # Group by document and count associated chunks to avoid hardcoding chunk_count=0
    query = (
        select(Document, func.count(DocumentChunk.id).label("chunk_count"))
        .outerjoin(DocumentChunk, Document.id == DocumentChunk.document_id)
        .where(Document.tenant_id == current_user.tenant_id)
        .group_by(Document.id)
        .order_by(Document.upload_time.desc())
    )
    result = await db.execute(query)
    rows = result.all()

    metadata_list = [
        DocumentMetadata(
            id=d.id,
            filename=d.filename,
            file_type=d.file_type,
            upload_time=d.upload_time,
            status=d.status,
            chunk_count=cnt,
            model_version_id=d.model_version_id,
        )
        for d, cnt in rows
    ]
    return DocumentListResponse(documents=metadata_list)


@router.get("/{document_id}")
async def get_document(
    document_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: TokenPayload = Depends(get_current_user),
):
    """Get document metadata and chunks."""
    result = await db.execute(
        select(Document).where(
            Document.id == document_id,
            Document.tenant_id == current_user.tenant_id,
        )
    )
    doc = result.scalars().first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    chunks_result = await db.execute(
        select(DocumentChunk)
        .where(DocumentChunk.document_id == document_id)
        .order_by(DocumentChunk.chunk_index)
    )
    chunks = chunks_result.scalars().all()

    return {
        "id": doc.id,
        "filename": doc.filename,
        "status": doc.status,
        "model_version_id": doc.model_version_id,
        "metrics_summary": doc.metadata_json,
        "chunks": [{"index": c.chunk_index, "text": c.masked_text} for c in chunks],
    }


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    document_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: TokenPayload = Depends(get_current_user),
):
    """Delete document, chunks, and purge associated Pinecone vector data."""
    result = await db.execute(
        select(Document).where(
            Document.id == document_id,
            Document.tenant_id == current_user.tenant_id,
        )
    )
    doc = result.scalars().first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    # Purge vectors from Pinecone using the tenant-and-doc-isolated namespace
    pinecone_store = PineconeStore()
    try:
        await pinecone_store.adelete_namespace(f"user-docs:{current_user.tenant_id}:{document_id}")
    except Exception as exc:
        logger.warning(f"Failed to purge Pinecone namespace on document delete {document_id}: {exc}")

    await db.delete(doc)
    await db.commit()
    return None

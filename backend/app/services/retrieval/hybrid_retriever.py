from __future__ import annotations

import logging
import time
import uuid
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document, DocumentChunk
from app.schemas.retrieval import (
    CandidatePreview,
    Citation,
    RetrievalCandidate,
    RetrievalDiagnostics,
    RetrievalMode,
    RetrievalResult,
)
from app.services.llm.router import LLMRouter
from app.services.retrieval.bm25 import BM25Okapi
from app.services.retrieval.dense_retriever import DenseRetriever
from app.services.retrieval.pinecone_store import PineconeStore
from app.services.retrieval.reranker import Reranker
from app.services.retrieval.rrf_fusion import rrf_fuse

logger = logging.getLogger(__name__)

# Number of pre-rerank candidates kept (without text) in RetrievalDiagnostics.
FUSED_PREVIEW_SIZE = 10


def _elapsed_ms(t0: float) -> float:
    """Return milliseconds elapsed since a ``time.perf_counter()`` reading."""
    return (time.perf_counter() - t0) * 1000.0

# CBUAE Model Management Standards regulatory corpus for BM25 when document_id is None
CBUAE_REGULATORY_CORPUS: list[dict[str, str]] = [
    {
        "source": "CBUAE-MMG-2022",
        "section": "Section 1 - Governance & Model Risk Management Framework",
        "text": (
            "Banks in the UAE must establish a comprehensive Model Risk Management (MRM) "
            "framework approved by the Board of Directors. The MRM framework must define model "
            "risk appetite, three lines of defense, roles and responsibilities of model owners, "
            "developers, and independent model validation units."
        ),
    },
    {
        "source": "CBUAE-MMG-2022",
        "section": "Section 2 - Model Inventory, Classification & Tiering",
        "text": (
            "Institutions must maintain a centralized Model Inventory cataloging all models in use. "
            "Models must be tiered into Tier 1 (High Materiality), Tier 2 (Medium Materiality), and "
            "Tier 3 (Low Materiality) based on financial exposure, regulatory capital impact, "
            "algorithmic complexity, and decision autonomy. Tier 1 models require annual validation."
        ),
    },
    {
        "source": "CBUAE-MMG-2022",
        "section": "Section 3 - Model Development & Data Quality Standards",
        "text": (
            "Model development requires representative historical data covering at least one full "
            "economic cycle (minimum 5-7 years). Rigorous data governance, completeness checks, "
            "outlier treatment, missing value imputation, and sample selection rationale must be "
            "fully documented in the Model Development Document (MDD)."
        ),
    },
    {
        "source": "CBUAE-MMG-2022",
        "section": "Section 4 - Quantitative Validation & Discriminatory Power",
        "text": (
            "Credit scoring and rating models must be validated using statistical discriminatory power "
            "metrics. Minimum regulatory benchmarks include: Gini Coefficient >= 0.40 (40%), "
            "Area Under Receiver Operating Characteristic Curve (AUC-ROC) >= 0.70, and "
            "Kolmogorov-Smirnov (KS) statistic >= 30.0 (30%)."
        ),
    },
    {
        "source": "CBUAE-MMG-2022",
        "section": "Section 5 - Calibration & Goodness-of-Fit Standards",
        "text": (
            "Probability of Default (PD) calibration requires binomial tests, traffic light tests, "
            "Hosmer-Lemeshow goodness-of-fit tests, and Brier score evaluation (target <= 0.15). "
            "Models must not systematically underestimate default probabilities across rating grades "
            "or retail risk segments."
        ),
    },
    {
        "source": "CBUAE-MMG-2022",
        "section": "Section 6 - Population Stability & Characteristic Drift",
        "text": (
            "Ongoing model stability must be tracked using Population Stability Index (PSI) and "
            "Characteristic Stability Index (CSI). PSI < 0.10 indicates no significant change; "
            "0.10 <= PSI < 0.25 indicates moderate shift requiring investigation; and "
            "PSI >= 0.25 indicates significant shift triggering mandatory recalibration or rebuild."
        ),
    },
    {
        "source": "CBUAE-MMG-2022",
        "section": "Section 7 - IFRS 9 ECL Staging & SICR Criteria",
        "text": (
            "IFRS 9 Expected Credit Loss (ECL) models must incorporate forward-looking macroeconomic "
            "scenarios (baseline, upside, downside) with probability weightings. Significant Increase "
            "in Credit Risk (SICR) criteria must combine quantitative lifetime PD changes, qualitative "
            "watchlist flags, and the mandatory 30 days past due (DPD) backstop."
        ),
    },
    {
        "source": "CBUAE-MMG-2022",
        "section": "Section 8 - Stress Testing & Sensitivity Analysis",
        "text": (
            "Credit risk models must undergo stress testing and sensitivity analysis under severe but "
            "plausible macroeconomic shocks. Impact on risk-weighted assets (RWA), impairment provisions, "
            "and capital adequacy ratios must be evaluated across real estate shocks, oil price volatility, "
            "and interest rate fluctuations."
        ),
    },
    {
        "source": "CBUAE-MMG-2022",
        "section": "Section 9 - Independent Model Validation Standards",
        "text": (
            "Independent Model Validation (IMV) units must maintain strict organizational and reporting "
            "independence from model development. Validation encompasses conceptual soundness review, "
            "developmental evidence verification, replication, outcome analysis, benchmarking, and "
            "implementation verification."
        ),
    },
    {
        "source": "CBUAE-MMG-2022",
        "section": "Section 10 - Early Warning Systems & Ongoing Monitoring",
        "text": (
            "Banks must operate Early Warning Systems (EWS) to detect deteriorating borrower "
            "creditworthiness and emerging portfolio stress. Ongoing monitoring reports, override "
            "tracking, policy exception rates, and validation findings must be reported quarterly to "
            "the Board Risk Committee."
        ),
    },
]


class HybridRetriever:
    """Orchestrates hybrid retrieval combining Dense Pinecone embeddings, BM25, RRF, and neural reranking."""

    def __init__(self, llm_router: LLMRouter, pinecone_store: PineconeStore) -> None:
        """Initialize HybridRetriever.

        Args:
            llm_router: Multi-provider LLM router for embedding and reranking.
            pinecone_store: Pinecone vector store wrapper.
        """
        self.llm_router = llm_router
        self.pinecone_store = pinecone_store
        self.dense_retriever = DenseRetriever(llm_router, pinecone_store)
        self.reranker = Reranker(llm_router)

    async def _fetch_chunks_for_document(
        self,
        db: AsyncSession,
        tenant_id: uuid.UUID,
        document_id: uuid.UUID,
    ) -> List[DocumentChunk]:
        """Fetch document chunks with strict multi-tenant isolation.

        RET-06: Joins Document and filters by Document.tenant_id == tenant_id to
        prevent cross-tenant data access.

        Args:
            db: Database session.
            tenant_id: Tenant UUID from authenticated context.
            document_id: Target document UUID.

        Returns:
            List of DocumentChunk objects belonging to the tenant.
        """
        result = await db.execute(
            select(DocumentChunk)
            .join(Document, DocumentChunk.document_id == Document.id)
            .where(
                Document.id == document_id,
                Document.tenant_id == tenant_id,
            )
            .order_by(DocumentChunk.chunk_index)
        )
        return list(result.scalars().all())

    async def _bm25_candidates(
        self,
        query: str,
        tenant_id: uuid.UUID,
        document_id: Optional[uuid.UUID],
        db: AsyncSession,
        top_n: int,
    ) -> List[RetrievalCandidate]:
        """Lexical BM25 retrieval over the document's chunks or the CBUAE corpus.

        Args:
            query: Search query.
            tenant_id: Authenticated user's tenant UUID (RET-06 isolation).
            document_id: Optional document UUID; ``None`` searches the regulatory corpus.
            db: Async database session.
            top_n: Maximum number of candidates to return.

        Returns:
            BM25 candidates sorted by score descending.
        """
        bm25_candidates: List[RetrievalCandidate] = []
        if document_id:
            # Document-specific query: retrieve chunks belonging to this tenant and document
            db_chunks = await self._fetch_chunks_for_document(db, tenant_id, document_id)
            if db_chunks:
                bm25 = BM25Okapi()
                corpus = [chunk.masked_text for chunk in db_chunks]
                bm25.fit(corpus)

                bm25_scores = bm25.score(query, top_k=top_n)
                for idx, score in bm25_scores:
                    if 0 <= idx < len(db_chunks):
                        chunk = db_chunks[idx]
                        bm25_candidates.append(
                            RetrievalCandidate(
                                chunk_text=chunk.masked_text,
                                source=f"doc-{document_id}",
                                section=f"chunk-{chunk.chunk_index}",
                                score=score,
                                retrieval_method="bm25",
                            )
                        )
        else:
            # RET-07: Pure regulatory search (document_id is None): index CBUAE regulatory guidelines into BM25
            bm25 = BM25Okapi()
            corpus = [item["text"] for item in CBUAE_REGULATORY_CORPUS]
            bm25.fit(corpus)

            bm25_scores = bm25.score(query, top_k=top_n)
            for idx, score in bm25_scores:
                if 0 <= idx < len(CBUAE_REGULATORY_CORPUS):
                    item = CBUAE_REGULATORY_CORPUS[idx]
                    bm25_candidates.append(
                        RetrievalCandidate(
                            chunk_text=item["text"],
                            source=item["source"],
                            section=item["section"],
                            score=score,
                            retrieval_method="bm25",
                        )
                    )
        return bm25_candidates

    async def retrieve(
        self,
        query: str,
        tenant_id: uuid.UUID,
        document_id: Optional[uuid.UUID],
        db: AsyncSession,
        top_k: int = 6,
        mode: RetrievalMode = RetrievalMode.HYBRID_RERANK,
        candidate_pool: int = 20,
    ) -> RetrievalResult:
        """Execute the retrieval pipeline for the requested mode.

        1. Determine namespaces (cbuae-manuals + optional user doc namespace).
        2. Dense retrieval via Pinecone (dense / hybrid modes).
        3. Lexical BM25 retrieval (user doc chunks if document_id, CBUAE regulatory guidelines if None).
        4. Reciprocal Rank Fusion (RRF) with [0, 1] normalization (hybrid modes).
        5. Neural cross-encoder reranking (``hybrid_rerank`` only, the production default).

        Args:
            query: Search query. Callers must pass privacy-masked text: it is sent to
                the embedding and rerank providers.
            tenant_id: Authenticated user's tenant UUID.
            document_id: Optional document UUID to search within.
            db: Async database session.
            top_k: Number of final citations to return.
            mode: Retrieval pipeline configuration (ablation mode).
            candidate_pool: Candidates fetched per retriever before fusion.

        Returns:
            RetrievalResult containing citations, latency_ms, metadata and diagnostics.
        """
        start = time.perf_counter()
        use_dense = mode in (RetrievalMode.DENSE, RetrievalMode.HYBRID, RetrievalMode.HYBRID_RERANK)
        use_bm25 = mode in (RetrievalMode.BM25, RetrievalMode.HYBRID, RetrievalMode.HYBRID_RERANK)

        # 1. Determine namespaces
        namespaces = ["cbuae-manuals"]
        if document_id:
            namespaces.append(f"user-docs:{tenant_id}:{document_id}")

        # 2. Dense retrieval from Pinecone (top-20)
        dense_candidates: List[RetrievalCandidate] = []
        dense_ms: float | None = None
        if use_dense:
            t0 = time.perf_counter()
            try:
                dense_candidates = await self.dense_retriever.retrieve(
                    query=query,
                    namespaces=namespaces,
                    top_k=candidate_pool,
                )
            except Exception as exc:
                logger.error(f"Dense retrieval failed: {exc}", exc_info=True)
            dense_ms = _elapsed_ms(t0)

        # 3. BM25 retrieval from in-memory corpus (top-20)
        bm25_candidates: List[RetrievalCandidate] = []
        bm25_ms: float | None = None
        if use_bm25:
            t0 = time.perf_counter()
            bm25_candidates = await self._bm25_candidates(query, tenant_id, document_id, db, candidate_pool)
            bm25_ms = _elapsed_ms(t0)

        # 4. RRF fusion of dense + BM25
        fused_candidates: List[RetrievalCandidate]
        fusion_ms: float | None = None
        if mode in (RetrievalMode.HYBRID, RetrievalMode.HYBRID_RERANK):
            t0 = time.perf_counter()
            if dense_candidates and bm25_candidates:
                fused_candidates = rrf_fuse([dense_candidates, bm25_candidates])
            else:
                fused_candidates = dense_candidates or bm25_candidates
            fusion_ms = _elapsed_ms(t0)
        elif mode == RetrievalMode.DENSE:
            fused_candidates = dense_candidates
        else:
            fused_candidates = bm25_candidates

        # 5. Neural reranking -> top_k
        rerank_ms: float | None = None
        rerank_fallback = False
        final_candidates: List[RetrievalCandidate]
        if mode == RetrievalMode.HYBRID_RERANK and fused_candidates:
            t0 = time.perf_counter()
            final_candidates, rerank_fallback = await self.reranker.rerank_with_status(
                query=query,
                candidates=fused_candidates,
                top_n=top_k,
            )
            rerank_ms = _elapsed_ms(t0)
        else:
            final_candidates = [c.model_copy() for c in fused_candidates[:top_k]]

        # Map back to Citations
        citations = [
            Citation(
                source=cand.source,
                section=cand.section,
                text=cand.chunk_text,
                score=cand.score,
                retrieval_method=cand.retrieval_method,
            )
            for cand in final_candidates
        ]

        diagnostics = RetrievalDiagnostics(
            mode=mode,
            dense_ms=dense_ms,
            bm25_ms=bm25_ms,
            fusion_ms=fusion_ms,
            rerank_ms=rerank_ms,
            dense_count=len(dense_candidates),
            bm25_count=len(bm25_candidates),
            fused_count=len(fused_candidates),
            final_count=len(final_candidates),
            rerank_applied=(
                mode == RetrievalMode.HYBRID_RERANK and bool(fused_candidates) and not rerank_fallback
            ),
            rerank_fallback=rerank_fallback,
            dense_empty=(use_dense and not dense_candidates),
            fused_preview=[
                CandidatePreview(
                    source=c.source,
                    section=c.section,
                    score=c.score,
                    retrieval_method=c.retrieval_method,
                )
                for c in fused_candidates[:FUSED_PREVIEW_SIZE]
            ],
        )

        return RetrievalResult(
            citations=citations,
            latency_ms=_elapsed_ms(start),
            retrieval_metadata={
                "dense_count": len(dense_candidates),
                "bm25_count": len(bm25_candidates),
                "fused_count": len(fused_candidates),
                "reranked_count": len(final_candidates),
                "mode": mode.value,
                "rerank_fallback": rerank_fallback,
            },
            diagnostics=diagnostics,
        )


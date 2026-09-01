from __future__ import annotations

import logging
from typing import List

from app.schemas.retrieval import RetrievalCandidate
from app.services.llm.router import LLMRouter

logger = logging.getLogger(__name__)


class Reranker:
    """Neural cross-encoder reranker with fallback to input candidates on failure."""

    def __init__(self, llm_router: LLMRouter) -> None:
        """Initialize Reranker with LLMRouter.

        Args:
            llm_router: Multi-provider LLM router for cross-encoder reranking.
        """
        self.llm_router = llm_router

    async def rerank(
        self,
        query: str,
        candidates: List[RetrievalCandidate],
        top_n: int = 6,
    ) -> List[RetrievalCandidate]:
        """Rerank candidates using cross-encoder, falling back to top_n input candidates.

        Args:
            query: User query string.
            candidates: Candidate list from dense/BM25/RRF fusion.
            top_n: Max reranked candidates to return.

        Returns:
            List of cloned RetrievalCandidate objects with updated scores and methods.
        """
        if not candidates:
            return []

        passages = [c.chunk_text for c in candidates]

        # RET-13: Catch API failure and fallback to top-N input candidates
        try:
            rerank_results = await self.llm_router.rerank(query, passages, top_n=top_n)
        except Exception as exc:
            logger.warning(
                f"Reranking API call failed ({exc}); falling back to top-{top_n} input candidates.",
                exc_info=True,
            )
            return [c.model_copy() for c in candidates[:top_n]]

        if not rerank_results:
            logger.warning(
                f"Reranking API returned empty results; falling back to top-{top_n} input candidates."
            )
            return [c.model_copy() for c in candidates[:top_n]]

        # RET-12: Clone candidates with model_copy instead of in-place mutation
        reranked_candidates: List[RetrievalCandidate] = []
        for res in rerank_results:
            idx = getattr(res, "index", -1)
            if 0 <= idx < len(candidates):
                candidate = candidates[idx]
                reranked_candidates.append(
                    candidate.model_copy(
                        update={
                            "score": getattr(res, "score", candidate.score),
                            "retrieval_method": f"{candidate.retrieval_method}_reranked",
                        }
                    )
                )

        if not reranked_candidates:
            return [c.model_copy() for c in candidates[:top_n]]

        # Sort by reranker score descending
        reranked_candidates.sort(key=lambda x: x.score, reverse=True)
        return reranked_candidates[:top_n]


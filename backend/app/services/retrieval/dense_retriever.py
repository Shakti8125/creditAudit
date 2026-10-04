from __future__ import annotations

import asyncio
import logging
from typing import List

from app.schemas.retrieval import RetrievalCandidate, VectorResult
from app.services.llm.router import LLMRouter
from app.services.retrieval.pinecone_store import PineconeStore, parse_user_docs_namespace

logger = logging.getLogger(__name__)


class DenseRetriever:
    """Dense retriever that embeds queries and searches Pinecone namespaces in parallel."""

    def __init__(self, llm_router: LLMRouter, pinecone_store: PineconeStore) -> None:
        """Initialize DenseRetriever.

        Args:
            llm_router: Multi-provider LLM router for generating embeddings.
            pinecone_store: Pinecone vector store client.
        """
        self.llm_router = llm_router
        self.pinecone_store = pinecone_store

    async def retrieve(
        self,
        query: str,
        namespaces: List[str],
        top_k: int = 20,
    ) -> List[RetrievalCandidate]:
        """Retrieve dense candidates across namespaces in parallel.

        Args:
            query: User query string.
            namespaces: List of Pinecone namespaces to query.
            top_k: Max candidates to return across all namespaces.

        Returns:
            List of RetrievalCandidate objects sorted by score descending.
        """
        if not namespaces or not query:
            return []

        # Generate query embedding
        try:
            embeddings = await self.llm_router.embed([query], input_type="query")
        except Exception as exc:
            logger.error(f"Failed to generate query embedding in DenseRetriever: {exc}", exc_info=True)
            return []

        if not embeddings:
            return []

        query_embedding = embeddings[0]

        # RET-11: Parallelize multi-namespace querying using asyncio.gather
        tasks = [
            self.pinecone_store.query(
                embedding=query_embedding,
                namespace=namespace,
                top_k=top_k,
            )
            for namespace in namespaces
        ]

        results_per_namespace = await asyncio.gather(*tasks, return_exceptions=True)

        candidates: List[RetrievalCandidate] = []
        for namespace, results in zip(namespaces, results_per_namespace):
            if isinstance(results, Exception):
                logger.error(
                    f"Query failed for namespace '{namespace}': {results}",
                    exc_info=True,
                )
                continue

            # A tenant document namespace names its document: the citation identity
            # comes from there, never from vector metadata, which older uploads
            # filled with the raw filename (QA-004 / NEW-03).
            owner = parse_user_docs_namespace(namespace)
            for res in results:
                metadata = res.metadata or {}
                chunk_text = metadata.get("text", "")
                section = metadata.get("section", "")
                if owner is not None:
                    source = f"doc-{owner[1]}"
                    document_id: str | None = owner[1]
                else:
                    source = metadata.get("source", "")
                    document_id = None

                candidates.append(
                    RetrievalCandidate(
                        chunk_text=chunk_text,
                        source=source,
                        section=section,
                        score=res.score,
                        retrieval_method="dense",
                        document_id=document_id,
                    )
                )

        # Sort combined results from multiple namespaces descending by score
        candidates.sort(key=lambda x: x.score, reverse=True)
        return candidates[:top_k]


from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any, List, Optional

try:
    from pinecone import Pinecone
except Exception as e:  # noqa: BLE001
    _logger = logging.getLogger(__name__)
    _logger.error(
        "Failed to import Pinecone. Install `pinecone>=5.0.0` (not `pinecone-client`). "
        "Vector upsert/query will be disabled. Error: %s", e
    )
    Pinecone = None  # type: ignore[assignment, misc]

from app.config import settings
from app.schemas.retrieval import ChunkData, VectorResult

logger = logging.getLogger(__name__)


class PineconeStore:
    """Wrapper around Pinecone vector store with async support and multi-tenancy."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        index_name: Optional[str] = None,
    ) -> None:
        """Initialize PineconeStore with configuration.

        Args:
            api_key: Pinecone API key. Defaults to settings.pinecone.api_key.
            index_name: Pinecone Index name. Defaults to settings.pinecone.index_name.
        """
        self.api_key = api_key or settings.pinecone.api_key
        self.index_name = index_name or settings.pinecone.index_name
        self.pc: Optional[Pinecone] = None
        self.index = None

        if Pinecone is not None and self.api_key:
            try:
                self.pc = Pinecone(api_key=self.api_key)
                if self.index_name:
                    self.index = self.pc.Index(self.index_name)
            except Exception as exc:
                logger.error(f"Failed to initialize Pinecone client: {exc}", exc_info=True)

    def upsert_vectors(
        self,
        ids: List[str],
        vectors: List[List[float]],
        chunks: List[ChunkData],
        namespace: str,
    ) -> None:
        """Upsert vectors with metadata into Pinecone index synchronously.

        Args:
            ids: Unique IDs for vectors.
            vectors: Embedding vector list.
            chunks: ChunkData objects providing metadata.
            namespace: Target namespace.
        """
        if not self.index:
            logger.error("Cannot upsert vectors: Pinecone index is not initialized.")
            return

        records = []
        for vid, vec, chunk in zip(ids, vectors, chunks):
            meta: dict[str, Any] = {
                "source": chunk.source,
                "section": chunk.section,
                "text": chunk.text,
            }
            if chunk.page is not None:
                meta["page"] = chunk.page
            records.append((vid, vec, meta))

        batch_size = 100
        for i in range(0, len(records), batch_size):
            try:
                self.index.upsert(vectors=records[i : i + batch_size], namespace=namespace)
            except Exception as exc:
                logger.error(
                    f"Failed to upsert vector batch into namespace '{namespace}': {exc}",
                    exc_info=True,
                )
                raise

    def upsert_chunks(
        self,
        chunks: List[ChunkData],
        namespace: str,
        vectors: Optional[List[List[float]]] = None,
        ids: Optional[List[str]] = None,
    ) -> None:
        """Convert chunks to vectors and delegate to upsert_vectors.

        Args:
            chunks: List of ChunkData objects.
            namespace: Target Pinecone namespace.
            vectors: Pre-computed embeddings matching chunks.
            ids: Optional vector IDs matching chunks (UUIDs generated if omitted).
        """
        if not chunks:
            return

        if ids is None:
            ids = [str(uuid.uuid4()) for _ in chunks]

        if vectors is None:
            logger.error("Cannot upsert chunks without embedding vectors.")
            raise ValueError("vectors must be provided to upsert_chunks.")

        self.upsert_vectors(ids=ids, vectors=vectors, chunks=chunks, namespace=namespace)

    async def aupsert_chunks(
        self,
        chunks: List[ChunkData],
        namespace: str,
        vectors: Optional[List[List[float]]] = None,
        ids: Optional[List[str]] = None,
    ) -> None:
        """Async wrapper for upsert_chunks."""
        await asyncio.to_thread(self.upsert_chunks, chunks, namespace, vectors, ids)

    async def aupsert_vectors(
        self,
        ids: List[str],
        vectors: List[List[float]],
        chunks: List[ChunkData],
        namespace: str,
    ) -> None:
        """Async wrapper for upsert_vectors."""
        await asyncio.to_thread(self.upsert_vectors, ids, vectors, chunks, namespace)

    def _query_sync(
        self,
        embedding: List[float],
        namespace: str,
        top_k: int = 20,
    ) -> List[VectorResult]:
        """Synchronous query implementation against Pinecone index."""
        if not self.index:
            logger.error("Cannot query: Pinecone index is not initialized.")
            return []

        try:
            response = self.index.query(
                namespace=namespace,
                vector=embedding,
                top_k=top_k,
                include_metadata=True,
            )

            results: List[VectorResult] = []
            matches = getattr(response, "matches", []) or []
            for match in matches:
                results.append(
                    VectorResult(
                        id=match.id,
                        score=match.score,
                        metadata=match.metadata or {},
                    )
                )
            return results
        except Exception as exc:
            logger.error(
                f"Error querying Pinecone namespace '{namespace}': {exc}",
                exc_info=True,
            )
            return []

    async def query(
        self,
        embedding: List[float],
        namespace: str,
        top_k: int = 20,
    ) -> List[VectorResult]:
        """Query Pinecone asynchronously offloaded to thread pool.

        Args:
            embedding: Dense query vector.
            namespace: Target namespace.
            top_k: Number of nearest neighbors to retrieve.

        Returns:
            List of VectorResult objects.
        """
        return await asyncio.to_thread(self._query_sync, embedding, namespace, top_k)

    def delete_namespace(self, namespace: str) -> None:
        """Delete all vectors in the specified namespace synchronously.
        
        Gracefully handles uninitialized client, non-existent namespaces, or empty namespaces.
        """
        # Ensure Pinecone index client is active before attempting deletion
        if not self.index:
            logger.warning(f"Cannot delete namespace '{namespace}': Pinecone index is not initialized.")
            return

        try:
            # Issue delete_all on the specified namespace
            self.index.delete(delete_all=True, namespace=namespace)
            logger.info(f"Successfully purged Pinecone vector namespace '{namespace}'.")
        except Exception as exc:
            err_msg = str(exc).lower()
            # Handle non-existent namespace or 404 gracefully without crashing or noisy error logs
            if "not found" in err_msg or "404" in err_msg or "does not exist" in err_msg:
                logger.info(f"Pinecone namespace '{namespace}' not found or already purged: {exc}")
            else:
                logger.error(
                    f"Error deleting Pinecone namespace '{namespace}': {exc}",
                    exc_info=True,
                )

    async def adelete_namespace(self, namespace: str) -> None:
        """Async wrapper for delete_namespace offloaded to threadpool."""
        await asyncio.to_thread(self.delete_namespace, namespace)

    def list_namespaces(self, prefix: Optional[str] = None) -> List[str]:
        """List active namespaces in index synchronously.

        Safely handles empty index where stats.namespaces is None.
        """
        if not self.index:
            return []

        try:
            stats = self.index.describe_index_stats()
            namespaces_dict = getattr(stats, "namespaces", None) or {}
            namespaces = list(namespaces_dict.keys())
            if prefix:
                return [ns for ns in namespaces if ns.startswith(prefix)]
            return namespaces
        except Exception as exc:
            logger.error(f"Error listing Pinecone namespaces: {exc}", exc_info=True)
            return []

    async def alist_namespaces(self, prefix: Optional[str] = None) -> List[str]:
        """Async wrapper for list_namespaces."""
        return await asyncio.to_thread(self.list_namespaces, prefix)


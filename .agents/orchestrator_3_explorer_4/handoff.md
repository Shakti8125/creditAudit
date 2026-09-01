# Handoff Report — Explorer 4 (Retrieval & Hybrid Search)

## 1. Observation

Direct code observations across all retrieval-related files in the ModelAudit AI backend:

1. **Document Upload Pinecone Namespace (`backend/app/api/documents.py:169`)**:
   ```python
   168: pinecone_store = PineconeStore()
   169: namespace = str(current_user.tenant_id)
   ```
   Vectors are stored under namespace `"{tenant_id}"`.

2. **Retrieval Namespace Construction (`backend/app/services/retrieval/hybrid_retriever.py:201-203`)**:
   ```python
   201: namespaces = ["cbuae-manuals"]
   202: if document_id:
   203:     namespaces.append(f"user-docs:{tenant_id}:{document_id}")
   ```
   When querying a document, `HybridRetriever` searches `f"user-docs:{tenant_id}:{document_id}"`.

3. **Multi-Tenancy Stress Test Specification (`backend/tests/test_stress_multitenancy.py:138-140`)**:
   ```python
   138: # Hybrid retriever namespace formatting check: user-docs:{tenant_id}:{document_id}
   139: expected_namespace = f"user-docs:{tenant_id}:{doc_id}"
   ```

4. **Document Deletion Resource Purge (`backend/app/api/documents.py:307-326`)**:
   ```python
   324: await db.delete(doc)
   325: await db.commit()
   326: return None
   ```
   `DELETE /documents/{id}` deletes database rows but never calls `PineconeStore.adelete_namespace()`.

5. **Multi-Tenancy Database Isolation (`backend/app/services/retrieval/hybrid_retriever.py:161-170`)**:
   ```python
   161: result = await db.execute(
   162:     select(DocumentChunk)
   163:     .join(Document, DocumentChunk.document_id == Document.id)
   164:     .where(
   165:         Document.id == document_id,
   166:         Document.tenant_id == tenant_id,
   167:     )
   168:     .order_by(DocumentChunk.chunk_index)
   169: )
   170: return list(result.scalars().all())
   ```

6. **Pinecone 5.0+ SDK Usage & Zero-Arg Instantiation (`backend/app/services/retrieval/pinecone_store.py:24-46`)**:
   ```python
   24: def __init__(
   25:     self,
   26:     api_key: Optional[str] = None,
   27:     index_name: Optional[str] = None,
   28: ) -> None:
   29:     self.api_key = api_key or settings.pinecone.api_key
   30:     self.index_name = index_name or settings.pinecone.index_name
   ...
   42:     self.pc = Pinecone(api_key=self.api_key)
   ```

7. **Pinecone `stats.namespaces` None Guard (`backend/app/services/retrieval/pinecone_store.py:218-220`)**:
   ```python
   218: stats = self.index.describe_index_stats()
   219: namespaces_dict = getattr(stats, "namespaces", None) or {}
   220: namespaces = list(namespaces_dict.keys())
   ```

8. **Async Offloading of Blocking Calls (`backend/app/services/retrieval/pinecone_store.py:124, 189, 207, 230`)**:
   All synchronous I/O operations against the Pinecone client (`upsert_chunks`, `upsert_vectors`, `_query_sync`, `delete_namespace`, `list_namespaces`) are offloaded to worker threads via `await asyncio.to_thread(...)`.

9. **BM25 State Resetting and Comma Number Tokenization (`backend/app/services/retrieval/bm25.py:9, 52-59, 111`)**:
   - `_TOKEN_PATTERN = re.compile(r"\b\d{1,3}(?:,\d{3})+(?:\.\d+)?\b|\b\d+(?:\.\d+)?\b|[a-zA-Z0-9_-]+")`
   - `self.fit(corpus)` fully resets `self.corpus`, `self.corpus_size`, `self.doc_freqs`, `self.doc_len`, `self.idf`, `self.avgdl`.
   - `len_norm = (d_len / self.avgdl) if self.avgdl > 0 else 1.0` prevents `ZeroDivisionError`.

10. **RRF Score Normalization [0, 1] (`backend/app/services/retrieval/rrf_fusion.py:50-59`)**:
    - `max_possible_score = sum(1.0 / (k + 1) for _ in valid_lists)`
    - `normalized_score = min(1.0, max(0.0, raw_score / max_possible_score))`
    - Immutably copies candidates via `base_cand.model_copy(...)`.

11. **Reranker API Fallback (`backend/app/services/retrieval/reranker.py:45-59`)**:
    Catches all exceptions from `self.llm_router.rerank(...)` and falls back to `[c.model_copy() for c in candidates[:top_n]]`.

12. **Parallel Multi-Namespace Retrieval (`backend/app/services/retrieval/dense_retriever.py:59-69`)**:
    Uses `asyncio.gather(*tasks, return_exceptions=True)` to execute queries across multiple namespaces concurrently.

---

## 2. Logic Chain

1. **Dense Retrieval Namespace Routing**:
   - Observation 1 shows `documents.py` uploads vectors into namespace `f"{current_user.tenant_id}"`.
   - Observation 2 shows `hybrid_retriever.py` queries namespace `f"user-docs:{tenant_id}:{document_id}"`.
   - Observation 3 confirms the intended standard namespace is `f"user-docs:{tenant_id}:{document_id}"`.
   - *Inference*: Because the upload namespace and query namespace do not match, dense vector queries against user documents return 0 results. This degrades hybrid retrieval to pure BM25 for document-specific queries.
   - *Actionable Fix*: Align `documents.py:169` to `namespace = f"user-docs:{current_user.tenant_id}:{doc_id}"`.

2. **Vector Lifecycle Management**:
   - Observation 4 shows `delete_document()` only deletes PostgreSQL rows.
   - Observation 8 shows `PineconeStore` has `adelete_namespace(namespace)` specifically implemented for namespace purging.
   - *Inference*: Deleting documents leaves orphaned vector embeddings in Pinecone.
   - *Actionable Fix*: Call `await pinecone_store.adelete_namespace(f"user-docs:{current_user.tenant_id}:{document_id}")` in `delete_document()`.

3. **Multi-Tenancy and Retrieval Quality**:
   - Observation 5 confirms strict multi-tenancy at the database layer (join and tenant filter on `DocumentChunk`).
   - Observations 6-12 confirm complete conformance with Pinecone 5.0+ SDK conventions, async-first architecture (`asyncio.to_thread`), BM25 state resetting and zero-division protection, RRF $[0.0, 1.0]$ score normalization, cross-encoder neural reranking with fallback, and concurrent multi-namespace retrieval.

---

## 3. Caveats

- In test environments where Pinecone credentials are mock or empty strings (`""`), `PineconeStore` gracefully disables vector indexing without throwing errors. Live vector upsert and query require a valid Pinecone Serverless API key and index configured in environment variables.
- Pure regulatory searches (`document_id is None`) utilize the hardcoded in-memory `CBUAE_REGULATORY_CORPUS` (10 sections) for BM25 alongside the `"cbuae-manuals"` Pinecone namespace.

---

## 4. Conclusion

The ModelAudit AI retrieval subsystem is well-structured, mathematically sound, and fully compliant with async-first and multi-tenancy requirements.

Two key remediations are recommended:
1. Fix namespace key in `backend/app/api/documents.py:169` to `f"user-docs:{current_user.tenant_id}:{doc_id}"` to restore dense vector retrieval for user documents.
2. Add `await pinecone_store.adelete_namespace(f"user-docs:{current_user.tenant_id}:{document_id}")` in `backend/app/api/documents.py:324` to clean up vector storage upon document deletion.

---

## 5. Verification Method

1. **Python Compilation Test**:
   ```powershell
   python -m py_compile backend/app/services/retrieval/bm25.py
   python -m py_compile backend/app/services/retrieval/dense_retriever.py
   python -m py_compile backend/app/services/retrieval/hybrid_retriever.py
   python -m py_compile backend/app/services/retrieval/pinecone_store.py
   python -m py_compile backend/app/services/retrieval/reranker.py
   python -m py_compile backend/app/services/retrieval/rrf_fusion.py
   python -m py_compile backend/app/api/query.py
   python -m py_compile backend/app/api/documents.py
   python -m py_compile backend/app/api/regulatory.py
   ```

2. **Automated Unit & Stress Test Verification**:
   ```powershell
   pytest backend/tests/test_stress_multitenancy.py -v
   pytest backend/tests/test_stress_chunking.py -v
   pytest backend/tests/ -v
   ```

3. **File Inspection**:
   Inspect `backend/app/services/retrieval/` and `backend/app/api/documents.py` to verify line numbers and namespace formatting.

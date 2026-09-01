# Retrieval & Hybrid Search Subsystem Deep Technical Analysis

**Target Subsystem**: Retrieval & Hybrid Search (BM25 + Pinecone Vector)  
**Investigator**: `explorer_4` (ModelAudit AI Backend Deep Review & Remediation Team)  
**Date**: 2026-08-29  
**Status**: Investigation Complete

---

## 1. Executive Summary

A comprehensive, line-by-line audit of the ModelAudit AI retrieval subsystem was conducted across all retrieval services (`bm25.py`, `dense_retriever.py`, `hybrid_retriever.py`, `pinecone_store.py`, `reranker.py`, `rrf_fusion.py`), schemas (`schemas/retrieval.py`), and consuming API endpoints (`api/query.py`, `api/regulatory.py`, `api/documents.py`).

The retrieval subsystem implements an enterprise-grade, privacy-preserving hybrid search architecture combining:
1. **Dense Vector Retrieval**: Pinecone Serverless vector database queried in parallel across namespaces using `asyncio.gather`.
2. **Lexical BM25 Search**: Zero-dependency `BM25Okapi` with financial comma-number preservation and non-negative Robertson-Spärck Jones IDF.
3. **Reciprocal Rank Fusion (RRF)**: Mathematical rank fusion with theoretical maximum normalization to $[0.0, 1.0]$ and immutable candidate cloning.
4. **Neural Cross-Encoder Reranking**: Multi-provider reranker with automatic fallback to top-N candidates on API failure or rate limit.
5. **Multi-Tenancy Enforcement**: SQL joins on `Document.tenant_id == tenant_id` and tenant-isolated vector namespaces.

### Key Finding Highlights:
- **Major Finding (Namespace Naming Inconsistency)**: In `backend/app/api/documents.py:169`, document vectors are uploaded to namespace `str(tenant_id)`, whereas `HybridRetriever.retrieve()` queries `f"user-docs:{tenant_id}:{document_id}"`. This discrepancy causes dense search against specific user documents to miss uploaded chunks.
- **Resource Lifecycle Finding**: `DELETE /documents/{id}` removes PostgreSQL records but does not invoke Pinecone namespace deletion (`pinecone_store.adelete_namespace()`).
- **Robustness Observation**: `pinecone_store.py`'s `list_namespaces()` handles `IndexStats` objects but should also handle dictionary returns if mocked or returned as raw dicts.

---

## 2. Component-by-Component Deep Review

### 2.1. Pinecone Vector Store (`backend/app/services/retrieval/pinecone_store.py`)

#### Code Conformance & Architecture
- **Pinecone 5.0+ SDK Usage**: Imports `from pinecone import Pinecone` with graceful fallback if the package is missing.
- **Zero-Arg Instantiation**: `PineconeStore()` defaults `api_key` and `index_name` to `settings.pinecone.api_key` and `settings.pinecone.index_name`. If unconfigured, `self.index` remains `None` and all methods return safe defaults (`[]` or `None`) without throwing uncaught exceptions.
- **Async Wrapping of Blocking I/O**:
  - `aupsert_chunks` $\rightarrow$ `await asyncio.to_thread(self.upsert_chunks, ...)`
  - `aupsert_vectors` $\rightarrow$ `await asyncio.to_thread(self.upsert_vectors, ...)`
  - `query` $\rightarrow$ `await asyncio.to_thread(self._query_sync, ...)`
  - `adelete_namespace` $\rightarrow$ `await asyncio.to_thread(self.delete_namespace, ...)`
  - `alist_namespaces` $\rightarrow$ `await asyncio.to_thread(self.list_namespaces, ...)`
- **`stats.namespaces` None Guard**:
  ```python
  stats = self.index.describe_index_stats()
  namespaces_dict = getattr(stats, "namespaces", None) or {}
  ```
  Safely prevents `AttributeError` or `TypeError` when an index is empty or fresh.

#### Batching & Metadata Handling
- Upserts are chunked into batches of 100 vectors (`batch_size = 100`).
- Metadata payload maps `source`, `section`, `text`, and optional `page`.

---

### 2.2. BM25 Lexical Retriever (`backend/app/services/retrieval/bm25.py`)

#### Code Conformance & Formula Verification
- **Regex & Financial Number Preservation**:
  ```python
  _TOKEN_PATTERN = re.compile(
      r"\b\d{1,3}(?:,\d{3})+(?:\.\d+)?\b|\b\d+(?:\.\d+)?\b|[a-zA-Z0-9_-]+"
  )
  ```
  - Branch 1 captures formatted numbers with commas (e.g., `1,250,000`, `25,000.50`), preventing splitting across commas.
  - Branch 2 captures unformatted numbers/percentages (e.g., `98.5`, `40`).
  - Branch 3 captures alphanumeric words, privacy tokens (`[BANK_1]`, `[ORG_2]`), and hyphenated terms (`AUC-ROC`, `IFRS-9`).
- **State Resetting on `fit()` (RET-08)**:
  `self.fit(corpus)` fully resets all instance attributes (`self.corpus`, `self.corpus_size`, `self.doc_freqs`, `self.doc_len`, `self.idf`, `self.avgdl`), ensuring no state contamination across repeated calls.
- **Zero-Division & Edge Case Protection (RET-10)**:
  ```python
  self.avgdl = total_len / num_doc if num_doc > 0 else 0.0
  ...
  len_norm = (d_len / self.avgdl) if self.avgdl > 0 else 1.0
  ```
  Guards against `ZeroDivisionError` when the corpus contains only empty strings or 0 documents.
- **Non-Negative IDF Formulation**:
  Uses `math.log((self.corpus_size - freq + 0.5) / (freq + 0.5) + 1.0)`. The `+ 1.0` inside the logarithm guarantees the operand is $\ge 1.0$, preventing negative IDF scores for frequent terms in small document corpora.

---

### 2.3. Dense Retriever (`backend/app/services/retrieval/dense_retriever.py`)

#### Code Conformance & Concurrency
- **Multi-Namespace Concurrency (RET-11)**:
  ```python
  tasks = [
      self.pinecone_store.query(
          embedding=query_embedding,
          namespace=namespace,
          top_k=top_k,
      )
      for namespace in namespaces
  ]
  results_per_namespace = await asyncio.gather(*tasks, return_exceptions=True)
  ```
  Executes queries across all target namespaces concurrently. Uses `return_exceptions=True` so a failure or network timeout on one namespace does not crash or abort remaining namespace searches.
- **Input Embedding Routing**:
  Delegates embedding generation to `llm_router.embed([query], input_type="query")`, utilizing NVIDIA NIM `nvidia/nv-embedqa-e5-v5` with automatic fallback to Gemini `models/text-embedding-004`.
- **Result Aggregation**:
  Gathers all namespace matches into `RetrievalCandidate(chunk_text=..., source=..., section=..., score=..., retrieval_method="dense")`, sorts globally by score descending, and returns `top_k`.

---

### 2.4. Reciprocal Rank Fusion (`backend/app/services/retrieval/rrf_fusion.py`)

#### Mathematical Correctness & Score Normalization
- **RRF Formula**:
  $$RRF(d) = \sum_{m \in M} \frac{1}{k + \text{rank}_m(d)}$$
  Default smoothing constant $k = 60$.
- **Score Normalization (RET-14)**:
  Theoretical maximum score achievable occurs when document $d$ is ranked position 1 ($\text{rank}=1$) across all $M$ non-empty input lists:
  $$\text{MaxScore} = \sum_{m=1}^{M} \frac{1}{k + 1} = \frac{M}{k + 1}$$
  The normalized score is calculated as:
  $$\text{NormalizedScore}(d) = \min\left(1.0, \max\left(0.0, \frac{RRF(d)}{\text{MaxScore}}\right)\right)$$
- **Immutable Cloning**:
  Candidate objects are cloned via `base_cand.model_copy(update={"score": normalized_score, "retrieval_method": "hybrid_rrf"})`, preventing unexpected side-effects on original candidate instances.
- **Deduplication**:
  Uses SHA-256 hash of `chunk_text` for deterministic deduplication across dense and lexical result sets.

---

### 2.5. Neural Cross-Encoder Reranker (`backend/app/services/retrieval/reranker.py`)

#### Code Conformance & Fallback Mechanics
- **Fallback Mechanism (RET-13)**:
  Calls `await self.llm_router.rerank(query, passages, top_n=top_n)` inside a protected `try...except Exception:` block:
  - If the reranking API fails (e.g. rate limit, circuit breaker open, HTTP error), logs a warning and gracefully falls back to `[c.model_copy() for c in candidates[:top_n]]`.
  - If the API returns an empty list or invalid indices, falls back to top-N input candidates.
- **Candidate Immutability (RET-12)**:
  Clones candidates using `model_copy(update={"score": ..., "retrieval_method": f"{candidate.retrieval_method}_reranked"})`.
- **Index Bounds Protection**:
  Explicitly checks `0 <= idx < len(candidates)` before dereferencing candidate indices returned by the cross-encoder.

---

### 2.6. Hybrid Retriever Orchestrator (`backend/app/services/retrieval/hybrid_retriever.py`)

#### Multi-Tenancy & Search Workflow
- **Multi-Tenant SQL Isolation (RET-06)**:
  `_fetch_chunks_for_document()` joins `DocumentChunk` with `Document` and enforces `Document.tenant_id == tenant_id`:
  ```python
  result = await db.execute(
      select(DocumentChunk)
      .join(Document, DocumentChunk.document_id == Document.id)
      .where(
          Document.id == document_id,
          Document.tenant_id == tenant_id,
      )
      .order_by(DocumentChunk.chunk_index)
  )
  ```
  Verified by test `test_fetch_chunks_cross_tenant_isolation` in `backend/tests/test_stress_multitenancy.py`.
- **Dual-Mode Retrieval Pipeline**:
  - **Mode A (Document-Specific Q&A)**: When `document_id` is supplied, sets `namespaces = ["cbuae-manuals", f"user-docs:{tenant_id}:{document_id}"]`, fetches masked document chunks from DB for in-memory BM25, fuses candidates via RRF, and neural reranks.
  - **Mode B (Pure Regulatory Lookup - RET-07)**: When `document_id is None`, sets `namespaces = ["cbuae-manuals"]`, indexes `CBUAE_REGULATORY_CORPUS` (10 sections of CBUAE MMG standards) into BM25, fuses candidates via RRF, and neural reranks.
- **Latency & Metadata Tracking**:
  Measures total retrieval pipeline wall-clock time and returns comprehensive telemetry (`dense_count`, `bm25_count`, `fused_count`, `reranked_count`, `latency_ms`).

---

## 3. Findings, Bugs, and Remediation Matrix

| ID | Component / File | Severity | Issue Description | Proposed Remediation |
|---|---|---|---|---|
| **BUG-01** | `api/documents.py:169` | **High** | **Namespace Mismatch on Document Upload**: `documents.py` uploads vectors to namespace `str(tenant_id)`, but `hybrid_retriever.py:203` queries `f"user-docs:{tenant_id}:{document_id}"`. Dense queries for uploaded documents find 0 vector matches. | Update `documents.py` line 169 to: `namespace = f"user-docs:{current_user.tenant_id}:{doc_id}"`. |
| **BUG-02** | `api/documents.py:307-326` | **Medium** | **Orphaned Vectors on Document Delete**: `DELETE /documents/{id}` deletes SQL records but never calls `PineconeStore.adelete_namespace()`, leaving vectors in Pinecone indefinitely. | In `delete_document()`, instantiate `PineconeStore()` and call `await pinecone_store.adelete_namespace(f"user-docs:{current_user.tenant_id}:{document_id}")`. |
| **BUG-03** | `retrieval/pinecone_store.py:218-223` | **Low** | **`list_namespaces` Dictionary Compatibility**: `describe_index_stats()` may return a dict in mock/test or certain SDK configurations. `getattr(stats, "namespaces", None)` returns `None` for dicts. | Check `isinstance(stats, dict)`: `namespaces_dict = (stats.get("namespaces") if isinstance(stats, dict) else getattr(stats, "namespaces", None)) or {}`. |
| **IMPR-01** | `retrieval/rrf_fusion.py:42-48` | **Low** | **Metadata Preservation on Fusion**: When duplicate chunk texts appear across dense and BM25, first-seen candidate metadata is kept. If BM25 has richer section titles, they may be overwritten if dense candidate was processed first. | Merge metadata by keeping the candidate with non-empty `section` or richer metadata. |
| **IMPR-02** | `api/query.py:99`, `api/regulatory.py:38` | **Low** | **LLMRouter Client Lifecycle**: `LLMRouter()` is instantiated per request without explicit `await llm_router.aclose()`. | Use FastAPI dependency injection or ensure client cleanup upon stream completion. |

---

## 4. Detailed Code Diffs for Proposed Remediations

### Fix 1: Align Document Upload Namespace with Hybrid Retriever (`backend/app/api/documents.py`)
```python
<<<<
            pinecone_store = PineconeStore()
            namespace = str(current_user.tenant_id)
====
            pinecone_store = PineconeStore()
            # Multi-tenancy: align namespace format with HybridRetriever (user-docs:{tenant_id}:{doc_id})
            namespace = f"user-docs:{current_user.tenant_id}:{doc_id}"
>>>>
```

### Fix 2: Clean up Pinecone Namespace on Document Deletion (`backend/app/api/documents.py`)
```python
<<<<
    await db.delete(doc)
    await db.commit()
    return None
====
    # Purge vector namespace from Pinecone
    pinecone_store = PineconeStore()
    namespace = f"user-docs:{current_user.tenant_id}:{document_id}"
    try:
        await pinecone_store.adelete_namespace(namespace)
    except Exception as exc:
        logger.warning(f"Failed to delete Pinecone namespace '{namespace}': {exc}")

    await db.delete(doc)
    await db.commit()
    return None
>>>>
```

### Fix 3: Robust `list_namespaces` Dict/Object Handling (`backend/app/services/retrieval/pinecone_store.py`)
```python
<<<<
        try:
            stats = self.index.describe_index_stats()
            namespaces_dict = getattr(stats, "namespaces", None) or {}
            namespaces = list(namespaces_dict.keys())
====
        try:
            stats = self.index.describe_index_stats()
            if isinstance(stats, dict):
                namespaces_dict = stats.get("namespaces") or {}
            else:
                namespaces_dict = getattr(stats, "namespaces", None) or {}
            namespaces = list(namespaces_dict.keys())
>>>>
```

---

## 5. Verification Commands & Test Matrix

To independently verify all retrieval components and multi-tenancy rules:

1. **Syntax and Parsing Verification**:
   ```bash
   python -m py_compile backend/app/services/retrieval/*.py
   python -m py_compile backend/app/api/query.py
   python -m py_compile backend/app/api/documents.py
   python -m py_compile backend/app/api/regulatory.py
   ```

2. **Multi-Tenancy Stress & Isolation Test**:
   ```bash
   pytest backend/tests/test_stress_multitenancy.py -v
   ```

3. **Full Backend Integration & Stress Test Suite**:
   ```bash
   pytest backend/tests/ -v
   ```

---

## 6. Conclusion

The ModelAudit AI Retrieval & Hybrid Search subsystem exhibits clean algorithmic designs, proper async offloading for all blocking network calls, robust zero-division guards in BM25, and mathematical precision in RRF score normalization and reranker fallback handling.

Applying the single namespace alignment fix in `documents.py` (BUG-01) and the delete cleanup (BUG-02) completes full multi-tenant end-to-end integration between document ingestion, Pinecone vector storage, and hybrid retrieval.

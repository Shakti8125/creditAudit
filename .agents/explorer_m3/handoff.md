# Handoff Report — Explorer M3 (Retrieval Pipeline & Analytics Engine)

## 1. Observation
- Target files audited across scope:
  - `backend/app/services/retrieval/__init__.py`
  - `backend/app/services/retrieval/bm25.py`
  - `backend/app/services/retrieval/dense_retriever.py`
  - `backend/app/services/retrieval/hybrid_retriever.py`
  - `backend/app/services/retrieval/pinecone_store.py`
  - `backend/app/services/retrieval/reranker.py`
  - `backend/app/services/retrieval/rrf_fusion.py`
  - `backend/app/services/analytics/__init__.py`
  - `backend/app/services/analytics/ews_detector.py`
  - `backend/app/services/analytics/model_metrics_extractor.py`
  - `backend/app/services/analytics/policy_checker.py`
  - `backend/app/services/__init__.py`
- Concrete code observations:
  1. `backend/app/services/retrieval/pinecone_store.py:7-9`: `PineconeStore.__init__(self, api_key: str, index_name: str)` requires 2 positional parameters with no default values, but `app/api/query.py:23` and `app/api/regulatory.py:21` call `PineconeStore()` with 0 arguments.
  2. `backend/app/services/retrieval/pinecone_store.py:11-21`: `upsert_chunks()` body consists of scratchpad notes and `pass`.
  3. `backend/app/services/retrieval/hybrid_retriever.py:26-30`: `select(DocumentChunk).where(DocumentChunk.document_id == document_id)` has no `tenant_id` filter.
  4. `backend/app/services/analytics/model_metrics_extractor.py:12`: `self.val_pattern = r"(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>%|percent|%?)?"` fails to parse comma-separated numbers like `1,250,000`.
  5. `backend/app/services/retrieval/bm25.py:21-52`: `fit()` appends to `self.doc_freqs` and `self.doc_len` without resetting them.
  6. `backend/app/services/retrieval/reranker.py:24-27`: Mutates `candidate.retrieval_method += "_reranked"` in place and drops all candidates if `llm_router.rerank` returns `[]`.
  7. `backend/requirements.txt:16`: Uses `pinecone-client` instead of modern `pinecone>=3.0.0`.

## 2. Logic Chain
- Observation 1 → In Python, invoking a constructor without required positional arguments raises `TypeError`. Callers in API endpoints will fail immediately at runtime upon receiving requests at `/query` and `/regulatory/search`.
- Observation 2 → Calling an empty method (`pass`) when indexing chunks into vector storage leaves vector search unpopulated.
- Observation 3 → Omitting `tenant_id` from database queries allows cross-tenant data leakage if an attacker or user supplies another tenant's `document_id`, directly violating multi-tenancy isolation requirements.
- Observation 4 → Standard credit risk models report metrics (e.g. EAD, Provisions, Portfolio balances) with comma thousand-separators. Matching only `\d+` truncates `1,500,000` to `1`, producing invalid regulatory metrics.
- Observation 5 → Reusing or re-fitting a BM25 instance causes cumulative array growth, leading to index out-of-bounds or scoring against mismatched documents.
- Observation 6 → Lack of fallback logic on neural reranker failure results in total citation loss, rendering RAG responses ungrounded.

## 3. Caveats
- Strictly read-only audit: No code was executed, modified, or tested via `pytest`.
- Live Pinecone Serverless connection, NVIDIA NIM endpoints, and Gemini API calls require environment credentials and were verified through static API signature analysis.

## 4. Conclusion
A total of **29 findings** were documented (4 Critical, 8 High, 10 Medium, 7 Low). The most urgent issues require fixing constructor defaults in `PineconeStore`, adding `tenant_id` filtering in `HybridRetriever`, completing `upsert_chunks()`, and updating regexes in `ModelMetricsExtractor` to preserve comma-formatted numbers.

## 5. Verification Method
- Independent static code inspection of the line references cited in `report.md`.
- Unit tests to be added during remediation:
  - Verify `PineconeStore()` instantiation with default configuration settings.
  - Verify `_fetch_chunks_for_document` generates SQL containing `tenant_id = :tenant_id`.
  - Test `ModelMetricsExtractor.extract()` with input strings containing `1,250,000 AED`, `| Gini | 65.4% |`, and `45 bps`.
  - Test `BM25Okapi.fit()` called twice sequentially to ensure internal frequency lists reset cleanly.

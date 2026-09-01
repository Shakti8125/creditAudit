# DISPATCH — 2026-08-28T13:51:04Z

## Task Assignment
You are a specialist Worker for ModelAudit AI Milestone 6: Retrieval Pipeline & Hybrid Search.

### Assigned Files (Exclusive Ownership)
- `backend/app/services/retrieval/pinecone_store.py`
- `backend/app/services/retrieval/hybrid_retriever.py`
- `backend/app/services/retrieval/bm25.py`
- `backend/app/services/retrieval/dense_retriever.py`
- `backend/app/services/retrieval/reranker.py`
- `backend/app/services/retrieval/rrf_fusion.py`
- `backend/app/services/retrieval/__init__.py`

### Assigned Issues
1. RET-01 (Critical): In `pinecone_store.py`, provide default settings in `__init__` pulling from `app.config.settings.pinecone` so callers can instantiate `PineconeStore()` without arguments.
2. RET-02 (Critical): In `pinecone_store.py`, implement `upsert_chunks()` by converting chunks to vectors and delegating to `upsert_vectors()`.
3. RET-03 (High): In `pinecone_store.py`, safely check `stats.namespaces` for None before `.keys()`: `namespaces_dict = getattr(stats, "namespaces", None) or {}`.
4. RET-04 (Medium): In `pinecone_store.py`, log exceptions with `logger.error` instead of silently returning `[]` on query failure.
5. RET-05 (Medium): In `pinecone_store.py`, use `asyncio.to_thread` for blocking Pinecone client SDK calls.
6. RET-06 (Critical): In `hybrid_retriever.py`, enforce multi-tenant isolation in `_fetch_chunks_for_document` by joining `Document` and filtering `Document.tenant_id == tenant_id`.
7. RET-07 (Medium): In `hybrid_retriever.py`, ensure BM25 corpus supports regulatory guideline searches when `document_id=None`.
8. RET-08 (High): In `bm25.py`, reset `self.doc_freqs = []`, `self.doc_len = []`, `self.idf = {}` at the start of `fit()` to prevent stateful contamination across multiple calls.
9. RET-09 (Medium): In `bm25.py`, use regex tokenization that preserves words and comma-formatted financial numbers.
10. RET-10 (Medium): In `bm25.py`, guard against `ZeroDivisionError` when `self.avgdl == 0`.
11. RET-11 (High): In `dense_retriever.py`, parallelize multi-namespace querying using `asyncio.gather` instead of sequential blocking loops.
12. RET-12 (High): In `reranker.py`, clone candidate objects (e.g. `candidate.model_copy(update=...)`) instead of mutating input objects in-place.
13. RET-13 (High): In `reranker.py`, fall back to top-N RRF candidates if the reranking API fails or returns empty.
14. RET-14 (Medium): In `rrf_fusion.py`, normalize raw RRF scores to standard [0, 1] confidence range.
15. Re-export public retrieval classes in `services/retrieval/__init__.py`.

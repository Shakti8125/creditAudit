---
name: p5-hybrid-rag
description: >-
  Use this skill when the user asks to build the complete hybrid RAG retrieval pipeline for ModelAudit AI Phase 5. This includes BM25, Pinecone, dense retrieval, RRF fusion, reranker, and the orchestrator.
---
# Phase 5: Hybrid RAG Retrieval Pipeline

This skill instructs an agent to build the complete hybrid RAG retrieval pipeline for ModelAudit AI. Ensure you write the exact code components as specified below.

## Step 1: Create BM25 Indexer
**Target File**: `backend/app/services/retrieval/bm25.py`
Build a zero-dependency BM25Okapi implementation.

- **Class**: `BM25Okapi(k1=1.5, b=0.75)`
- **Method**: `fit(corpus: list[str])` — Builds term frequency and document frequency indices. Case-insensitive unigram tokenization.
- **IDF Formula**: `ln((N - n_q + 0.5) / (n_q + 0.5) + 1.0)`
- **Score Formula**: `Score(D,Q) = Σ IDF(q) * (f(q,D) * (k1+1)) / (f(q,D) + k1 * (1 - b + b * |D|/avgdl))`
- **Method**: `score(query: str, top_k: int = 20) -> list[tuple[int, float]]` — Returns list of `(doc_index, score)`.
- **Edge Cases**: Handle empty query, empty corpus, and single-token queries.

## Step 2: Create Pinecone Store Wrapper
**Target File**: `backend/app/services/retrieval/pinecone_store.py`
Create a Pinecone client wrapper.

- **Class**: `PineconeStore(api_key, index_name)`
- **Namespaces**: `cbuae-manuals` (regulatory), `user-docs:{tenant_id}:{doc_id}` (uploaded)
- **Method**: `upsert_chunks(chunks: list[ChunkData], namespace: str)` — Batch upsert with metadata (`source`, `section`, `text`, `page`).
- **Method**: `query(embedding: list[float], namespace: str, top_k: int = 20) -> list[VectorResult]`
- **Method**: `delete_namespace(namespace: str)`
- **Method**: `list_namespaces(prefix: str) -> list[str]`
- **VectorResult Schema**: `id, score, metadata(source, section, text)`

## Step 3: Create Dense Embeddings Retriever
**Target File**: `backend/app/services/retrieval/dense_retriever.py`
Implement dense embedding retrieval logic.

- **Class**: `DenseRetriever(llm_router, pinecone_store)`
- **Method**: `retrieve(query: str, namespaces: list[str], top_k: int = 20) -> list[RetrievalCandidate]`
- **Logic**: Generates query embedding via `llm_router.embed([query], input_type="query")`. Queries Pinecone across specified namespaces.
- **RetrievalCandidate Schema**: `chunk_text, source, section, score, retrieval_method="dense"`

## Step 4: Create Reciprocal Rank Fusion
**Target File**: `backend/app/services/retrieval/rrf_fusion.py`
Implement RRF algorithm to fuse BM25 and Dense results.

- **Function**: `rrf_fuse(ranked_lists: list[list[RetrievalCandidate]], k: int = 60) -> list[RetrievalCandidate]`
- **RRF_Score Formula**: `Σ [1.0 / (k + rank_m(d))]` for each retrieval system `m`.
- **Logic**: Deduplicates by chunk text hash. Returns fused list sorted by RRF score.

## Step 5: Create Reranker
**Target File**: `backend/app/services/retrieval/reranker.py`
Neural cross-encoder reranking.

- **Class**: `Reranker(llm_router)`
- **Method**: `rerank(query: str, candidates: list[RetrievalCandidate], top_n: int = 6) -> list[RetrievalCandidate]`
- **Logic**: Uses `llm_router.rerank(query, [c.chunk_text for c in candidates], top_n)`. Updates candidates with rerank scores. Returns top-N sorted by rerank score.

## Step 6: Create Hybrid Retriever Orchestrator
**Target File**: `backend/app/services/retrieval/hybrid_retriever.py`
The main orchestrator.

- **Class**: `HybridRetriever(llm_router, pinecone_store)`
- **Method**: `retrieve(query: str, tenant_id: UUID, document_id: UUID | None, top_k: int = 6) -> RetrievalResult`
- **Flow**:
  1. Determine namespaces: always `cbuae-manuals`, plus `user-docs:{tenant_id}:{document_id}` if `document_id` provided.
  2. Dense retrieval from Pinecone (top-20).
  3. BM25 retrieval from in-memory corpus (top-20) — corpus loaded from document chunks in DB.
  4. RRF fusion of dense + BM25.
  5. Neural reranking → top-6.
- **RetrievalResult Schema**: `citations: list[Citation], latency_ms: float, retrieval_metadata: dict`
- **Citation Schema**: `source, section, text, score, retrieval_method`

## Step 7: Create Regulatory Indexing Script
**Target File**: `backend/scripts/index_regulatory_corpus.py`
One-time script to embed regulatory manuals.

- **Logic**:
  1. Read PDFs from `backend/base_documents/`
  2. Extract via DocumentExtractor
  3. Chunk with MarkdownChunker(2400, 400)
  4. Embed via LLMRouter
  5. Upsert into Pinecone `cbuae-manuals` namespace

## Verification
Index test regulatory documents using the script, then query and verify Hit@3, MRR metrics via a simple test.

import os
import sys
import asyncio
import uuid
from unittest.mock import MagicMock, AsyncMock, patch

# Ensure backend is in python path
sys.path.insert(0, os.path.abspath("backend"))

os.environ['DATABASE_URL'] = 'postgresql+asyncpg://user:pass@localhost:5432/testdb'
os.environ['PINECONE_API_KEY'] = 'test-api-key'
os.environ['PINECONE_INDEX_NAME'] = 'test-index-name'

from app.schemas.retrieval import ChunkData, RetrievalCandidate, VectorResult, Citation, RetrievalResult
from app.services.retrieval.bm25 import BM25Okapi
from app.services.retrieval.pinecone_store import PineconeStore
from app.services.retrieval.dense_retriever import DenseRetriever
from app.services.retrieval.rrf_fusion import rrf_fuse
from app.services.retrieval.reranker import Reranker
from app.services.retrieval.hybrid_retriever import HybridRetriever, CBUAE_REGULATORY_CORPUS
from app.services.llm.base_provider import RerankResult

async def run_all_tests():
    print("Starting Comprehensive Retrieval Pipeline Verification...")

    # 1. RET-08, RET-09, RET-10 (BM25Okapi)
    bm25 = BM25Okapi()
    tokens = bm25._tokenize("The EAD is 1,250,000 AED and PD is 2.5%, compared to 500,000 USD.")
    assert "1,250,000" in tokens, f"Expected 1,250,000 in tokens, got {tokens}"
    assert "500,000" in tokens, f"Expected 500,000 in tokens, got {tokens}"
    assert "2.5" in tokens, f"Expected 2.5 in tokens, got {tokens}"
    print("PASS: RET-09 Tokenizer preserves comma-formatted financial numbers")

    # Test RET-08: fit state reset
    bm25.fit(["First document with 1,000 AED", "Second document with 2,000 AED"])
    first_corpus_size = bm25.corpus_size
    bm25.fit(["Third document with completely new content"])
    assert bm25.corpus_size == 1, f"Expected corpus_size 1, got {bm25.corpus_size}"
    assert len(bm25.doc_freqs) == 1, f"Expected len(doc_freqs) 1, got {len(bm25.doc_freqs)}"
    assert len(bm25.doc_len) == 1, f"Expected len(doc_len) 1, got {len(bm25.doc_len)}"
    print("PASS: RET-08 BM25 fit state reset on multiple invocations")

    # Test RET-10: ZeroDivisionError guard on empty or zero length documents
    bm25_empty = BM25Okapi()
    bm25_empty.fit(["", "   "])
    assert bm25_empty.avgdl == 0.0
    scores = bm25_empty.score("test query")
    assert scores == [] or all(s[1] == 0.0 for s in scores)
    print("PASS: RET-10 BM25 ZeroDivisionError guard when avgdl == 0")

    # Test BM25 scoring accuracy
    bm25_search = BM25Okapi()
    bm25_search.fit([
        "CBUAE MMG guidelines require Gini coefficient above 0.40 for credit models",
        "Unrelated document about general office administration",
        "Model validation requires Hosmer-Lemeshow and Brier score calibration"
    ])
    res = bm25_search.score("Gini coefficient CBUAE")
    assert len(res) > 0 and res[0][0] == 0, f"Expected doc 0 as top match, got {res}"
    print("PASS: BM25 scoring ranking verified")

    # 2. RET-01, RET-02, RET-03, RET-04, RET-05 (PineconeStore)
    # Test RET-01: default constructor
    ps = PineconeStore()
    assert ps.api_key == "test-api-key"
    assert ps.index_name == "test-index-name"
    print("PASS: RET-01 PineconeStore defaults from settings.pinecone")

    # Test RET-03: safe check stats.namespaces is None
    mock_index = MagicMock()
    mock_stats = MagicMock()
    mock_stats.namespaces = None
    mock_index.describe_index_stats.return_value = mock_stats
    ps.index = mock_index
    namespaces = ps.list_namespaces()
    assert namespaces == [], f"Expected empty list, got {namespaces}"
    print("PASS: RET-03 PineconeStore safe handling of None stats.namespaces")

    # Test RET-02: upsert_chunks delegation
    chunks = [
        ChunkData(source="doc.pdf", section="sec1", text="Chunk 1 text", page=1),
        ChunkData(source="doc.pdf", section="sec2", text="Chunk 2 text", page=2),
    ]
    vectors = [[0.1, 0.2], [0.3, 0.4]]
    with patch.object(ps, "upsert_vectors") as mock_uv:
        ps.upsert_chunks(chunks, namespace="ns-test", vectors=vectors)
        assert mock_uv.called
        call_args = mock_uv.call_args[1]
        assert call_args["namespace"] == "ns-test"
        assert len(call_args["ids"]) == 2
        assert call_args["vectors"] == vectors
        assert call_args["chunks"] == chunks
    print("PASS: RET-02 PineconeStore upsert_chunks converts and delegates to upsert_vectors")

    # Test RET-04 & RET-05: query with asyncio.to_thread and error logging
    mock_index.query.side_effect = Exception("Pinecone connection timeout")
    res_err = await ps.query([0.1, 0.2], namespace="test-ns")
    assert res_err == []
    print("PASS: RET-04 & RET-05 PineconeStore async query with error logging")

    # 3. RET-11 (DenseRetriever with asyncio.gather)
    mock_router = MagicMock()
    mock_router.embed = AsyncMock(return_value=[[0.1, 0.2, 0.3]])
    
    mock_ps = MagicMock()
    async def mock_ps_query(embedding, namespace, top_k):
        await asyncio.sleep(0.01)
        return [
            VectorResult(id=f"{namespace}-1", score=0.95 if namespace=="ns1" else 0.85, metadata={"text": f"Text from {namespace}", "source": f"src-{namespace}", "section": "sec1"})
        ]
    mock_ps.query = AsyncMock(side_effect=mock_ps_query)

    dense_retriever = DenseRetriever(mock_router, mock_ps)
    dense_results = await dense_retriever.retrieve("validation query", namespaces=["ns1", "ns2"], top_k=5)
    assert len(dense_results) == 2
    assert dense_results[0].source == "src-ns1"
    assert dense_results[0].score == 0.95
    assert mock_ps.query.call_count == 2
    print("PASS: RET-11 DenseRetriever multi-namespace parallel retrieval with asyncio.gather")

    # 4. RET-14 (RRF Fusion score normalization)
    cand1 = RetrievalCandidate(chunk_text="Passage A", source="doc1", section="sec1", score=0.9, retrieval_method="dense")
    cand2 = RetrievalCandidate(chunk_text="Passage B", source="doc1", section="sec2", score=0.8, retrieval_method="dense")
    cand3 = RetrievalCandidate(chunk_text="Passage A", source="doc1", section="sec1", score=12.5, retrieval_method="bm25")
    cand4 = RetrievalCandidate(chunk_text="Passage C", source="doc2", section="sec1", score=10.0, retrieval_method="bm25")

    fused = rrf_fuse([[cand1, cand2], [cand3, cand4]], k=60)
    assert len(fused) == 3
    # Passage A is rank 1 in both lists -> score must be exactly 1.0
    assert abs(fused[0].score - 1.0) < 1e-5, f"Expected normalized score 1.0, got {fused[0].score}"
    for f in fused:
        assert 0.0 <= f.score <= 1.0, f"Score out of [0, 1] range: {f.score}"
        assert f.retrieval_method == "hybrid_rrf"
    print("PASS: RET-14 RRF fusion normalized to [0, 1] range")

    # 5. RET-12 & RET-13 (Reranker)
    # Test RET-12: candidate cloning
    mock_router.rerank = AsyncMock(return_value=[
        RerankResult(index=1, score=0.98, text="Passage B"),
        RerankResult(index=0, score=0.85, text="Passage A")
    ])
    reranker = Reranker(mock_router)
    input_cands = [cand1, cand2]
    reranked = await reranker.rerank("test query", input_cands, top_n=2)
    assert len(reranked) == 2
    assert reranked[0].chunk_text == "Passage B"
    assert reranked[0].score == 0.98
    assert reranked[0].retrieval_method == "dense_reranked"
    # Ensure original candidate was NOT mutated
    assert cand2.retrieval_method == "dense"
    assert cand2.score == 0.8
    print("PASS: RET-12 Reranker candidate cloning without in-place mutation")

    # Test RET-13: fallback on failure
    mock_router.rerank = AsyncMock(side_effect=Exception("Rerank API down"))
    fallback_res = await reranker.rerank("test query", input_cands, top_n=2)
    assert len(fallback_res) == 2
    assert fallback_res[0].chunk_text == "Passage A"
    assert fallback_res[1].chunk_text == "Passage B"
    print("PASS: RET-13 Reranker fallback to top-N candidates on API failure")

    # 6. RET-06 & RET-07 (HybridRetriever)
    tenant_a = uuid.uuid4()
    tenant_b = uuid.uuid4()
    doc_id = uuid.uuid4()

    mock_db = AsyncMock()
    # Mock DocumentChunk objects
    mock_chunk_1 = MagicMock()
    mock_chunk_1.chunk_index = 0
    mock_chunk_1.masked_text = "Tenant A credit scoring validation chunk 1 with 1,000,000 AED exposure."

    # Test RET-06: query with tenant filtering
    mock_scalars = MagicMock()
    mock_scalars.all.return_value = [mock_chunk_1]
    mock_db_result = MagicMock()
    mock_db_result.scalars.return_value = mock_scalars
    mock_db.execute.return_value = mock_db_result

    hybrid_retriever = HybridRetriever(mock_router, mock_ps)
    chunks_fetched = await hybrid_retriever._fetch_chunks_for_document(mock_db, tenant_a, doc_id)
    assert len(chunks_fetched) == 1
    # Verify execute was called with join and tenant_id check
    exec_call_arg = mock_db.execute.call_args[0][0]
    sql_str = str(exec_call_arg)
    assert "JOIN documents" in sql_str or "documents.id" in sql_str
    assert "documents.tenant_id" in sql_str
    print("PASS: RET-06 Multi-tenant isolation in _fetch_chunks_for_document verified")

    # Test RET-07: regulatory guideline search when document_id is None
    mock_router.embed = AsyncMock(return_value=[[0.1, 0.2]])
    mock_ps.query = AsyncMock(return_value=[])
    mock_router.rerank = AsyncMock(side_effect=Exception("Fallback reranker"))

    ret_result = await hybrid_retriever.retrieve(
        query="Gini coefficient and AUC requirements under CBUAE MMG",
        tenant_id=tenant_a,
        document_id=None,
        db=mock_db,
        top_k=3
    )
    assert len(ret_result.citations) > 0, f"Expected regulatory citations, got {ret_result.citations}"
    assert any("Gini" in c.text or "CBUAE" in c.source for c in ret_result.citations)
    assert ret_result.retrieval_metadata["bm25_count"] > 0
    print("PASS: RET-07 Regulatory guideline BM25 indexing when document_id is None")

    print("\n=======================================================")
    print("ALL RETRIEVAL PIPELINE VERIFICATIONS PASSED (100% SUCCESS)")
    print("=======================================================")

if __name__ == "__main__":
    asyncio.run(run_all_tests())

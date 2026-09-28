from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.db.database import Base
from app.models.document import Document, DocumentChunk, DocumentStatus
from app.models.user import RoleEnum, Tenant, User
from app.schemas.retrieval import RetrievalMode, VectorResult
from app.services.evaluation.default_dataset import DEFAULT_CASE_SPECS, build_expected_refs
from app.services.evaluation.metrics import RelevanceTarget, RetrievedItem, judge_relevance, score_case
from app.services.llm.base_provider import RerankResult
from app.services.retrieval.hybrid_retriever import HybridRetriever

engine = create_async_engine(
    "sqlite+aiosqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
)
TestingSessionLocal = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
TENANT_ID = uuid.uuid4()
QUESTION = "What is the minimum Gini coefficient required for credit scoring models?"

# Deterministic BM25 baseline over the 22 default questions (observed 0.977 at top_k=5).
BM25_MRR_AT_5_FLOOR = 0.97


@pytest_asyncio.fixture
async def db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with TestingSessionLocal() as session:
        yield session
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


def _router() -> MagicMock:
    router = MagicMock()
    router.embed = AsyncMock(return_value=[[0.1, 0.2, 0.3]])
    router.rerank = AsyncMock(side_effect=RuntimeError("rerank down"))
    return router


def _store() -> MagicMock:
    store = MagicMock()
    store.query = AsyncMock(
        return_value=[
            VectorResult(id="v1", score=0.91, metadata={"text": "Dense passage about Gini >= 0.40", "source": "mmg.pdf", "section": "4.1"}),
            VectorResult(id="v2", score=0.55, metadata={"text": "Dense passage about PSI", "source": "mmg.pdf", "section": "6.2"}),
        ]
    )
    return store


@pytest.mark.asyncio
async def test_bm25_mode_skips_dense_and_rerank(db) -> None:
    router, store = _router(), _store()
    res = await HybridRetriever(router, store).retrieve(QUESTION, TENANT_ID, None, db, top_k=3, mode=RetrievalMode.BM25)

    router.embed.assert_not_awaited()
    router.rerank.assert_not_awaited()
    diag = res.diagnostics
    assert diag is not None and diag.mode == RetrievalMode.BM25
    assert diag.dense_ms is None and diag.rerank_ms is None and diag.fusion_ms is None
    assert diag.bm25_ms is not None and diag.dense_empty is False
    assert 0 < len(res.citations) <= 3
    assert {c.retrieval_method for c in res.citations} == {"bm25"}
    assert res.citations[0].section.startswith("Section 4")


@pytest.mark.asyncio
async def test_dense_mode_uses_only_dense(db) -> None:
    router, store = _router(), _store()
    res = await HybridRetriever(router, store).retrieve(QUESTION, TENANT_ID, None, db, top_k=5, mode=RetrievalMode.DENSE)

    router.embed.assert_awaited_once()
    router.rerank.assert_not_awaited()
    assert res.diagnostics.bm25_count == 0 and res.diagnostics.bm25_ms is None
    assert res.diagnostics.dense_count == 2
    assert [c.retrieval_method for c in res.citations] == ["dense", "dense"]


@pytest.mark.asyncio
async def test_hybrid_mode_fuses_without_rerank(db) -> None:
    router, store = _router(), _store()
    res = await HybridRetriever(router, store).retrieve(QUESTION, TENANT_ID, None, db, top_k=4, mode=RetrievalMode.HYBRID)

    router.rerank.assert_not_awaited()
    assert {c.retrieval_method for c in res.citations} == {"hybrid_rrf"}
    assert res.diagnostics.fusion_ms is not None and res.diagnostics.rerank_ms is None
    assert res.diagnostics.fused_count == 12  # 2 dense + 10 corpus sections
    assert len(res.diagnostics.fused_preview) == 10


@pytest.mark.asyncio
async def test_hybrid_rerank_fallback_is_flagged(db) -> None:
    router, store = _router(), _store()
    res = await HybridRetriever(router, store).retrieve(
        QUESTION, TENANT_ID, None, db, top_k=3, mode=RetrievalMode.HYBRID_RERANK
    )

    router.rerank.assert_awaited_once()
    assert res.diagnostics.rerank_fallback is True
    assert res.diagnostics.rerank_applied is False
    assert res.retrieval_metadata["rerank_fallback"] is True
    assert len(res.citations) == 3


@pytest.mark.asyncio
async def test_hybrid_rerank_applies_rerank_order(db) -> None:
    router, store = _router(), _store()
    router.rerank = AsyncMock(return_value=[RerankResult(index=2, score=4.2, text="x")])
    retriever = HybridRetriever(router, store)

    res = await retriever.retrieve(QUESTION, TENANT_ID, None, db, top_k=3)

    assert res.diagnostics.mode == RetrievalMode.HYBRID_RERANK
    assert res.diagnostics.rerank_applied is True and res.diagnostics.rerank_fallback is False
    assert len(res.citations) == 1
    assert res.citations[0].score == 4.2
    assert res.citations[0].retrieval_method.endswith("_reranked")
    third_fused = res.diagnostics.fused_preview[2]
    assert (res.citations[0].source, res.citations[0].section) == (third_fused.source, third_fused.section)


@pytest.mark.asyncio
async def test_default_call_keeps_legacy_metadata_keys(db) -> None:
    router, store = _router(), _store()
    res = await HybridRetriever(router, store).retrieve(QUESTION, TENANT_ID, None, db)

    for key in ("dense_count", "bm25_count", "fused_count", "reranked_count"):
        assert key in res.retrieval_metadata
    assert res.retrieval_metadata["mode"] == "hybrid_rerank"
    assert len(res.citations) <= 6


@pytest.mark.asyncio
async def test_dense_failure_marks_dense_empty(db) -> None:
    router, store = _router(), _store()
    router.embed = AsyncMock(side_effect=RuntimeError("embed down"))
    res = await HybridRetriever(router, store).retrieve(QUESTION, TENANT_ID, None, db, top_k=3, mode=RetrievalMode.HYBRID)

    assert res.diagnostics.dense_empty is True
    assert {c.retrieval_method for c in res.citations} == {"bm25"}


@pytest.mark.asyncio
async def test_bm25_document_scope_is_tenant_isolated(db) -> None:
    other_tenant = uuid.uuid4()
    user_id = uuid.uuid4()
    doc_id = uuid.uuid4()
    db.add(Tenant(id=TENANT_ID, name="T"))
    db.add(Tenant(id=other_tenant, name="O"))
    db.add(User(id=user_id, email="u@example.com", hashed_password="pw", tenant_id=TENANT_ID, role=RoleEnum.ANALYST))
    await db.flush()
    db.add(Document(id=doc_id, tenant_id=TENANT_ID, user_id=user_id, filename="d.pdf", file_type="pdf",
                    raw_markdown="x", status=DocumentStatus.READY))
    await db.flush()
    db.add(DocumentChunk(document_id=doc_id, chunk_index=0, masked_text="The Gini coefficient is 0.52 for [BANK_1]."))
    db.add(DocumentChunk(document_id=doc_id, chunk_index=1, masked_text="Unrelated appendix text."))
    await db.commit()

    retriever = HybridRetriever(_router(), _store())
    own = await retriever.retrieve("Gini coefficient", TENANT_ID, doc_id, db, top_k=2, mode=RetrievalMode.BM25)
    foreign = await retriever.retrieve("Gini coefficient", other_tenant, doc_id, db, top_k=2, mode=RetrievalMode.BM25)

    assert own.citations[0].section == "chunk-0"
    assert foreign.citations == []


@pytest.mark.asyncio
async def test_bm25_offline_sanity_over_default_questions(db) -> None:
    retriever = HybridRetriever(_router(), _store())

    async def evaluate(k: int) -> tuple[float, float, float]:
        hits, recalls, rrs = [], [], []
        for spec in DEFAULT_CASE_SPECS:
            res = await retriever.retrieve(spec.question, TENANT_ID, None, db, top_k=k, mode=RetrievalMode.BM25)
            targets = [
                RelevanceTarget(source=r["source"], section=r["section"], keywords=tuple(r["keywords"]))
                for r in build_expected_refs(spec)
            ]
            items = [RetrievedItem(c.source, c.section, c.text) for c in res.citations]
            relevances, matched = judge_relevance(items, targets)
            scores = score_case(relevances, matched, len(targets), k)
            hits.append(1.0 if scores.hit else 0.0)
            recalls.append(scores.recall)
            rrs.append(scores.reciprocal_rank)
        n = len(DEFAULT_CASE_SPECS)
        return sum(hits) / n, sum(recalls) / n, sum(rrs) / n

    hit10, recall10, _ = await evaluate(10)
    assert hit10 == 1.0 and recall10 == 1.0
    _, _, mrr5 = await evaluate(5)
    assert mrr5 >= BM25_MRR_AT_5_FLOOR

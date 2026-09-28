from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.db.database import Base
from app.models.document import Document, DocumentChunk, DocumentStatus
from app.models.rag_eval import RagEvalCase, RagEvalResult, RagEvalRun
from app.models.user import RoleEnum, Tenant, User
from app.services.evaluation.default_dataset import DEFAULT_CASE_SPECS, build_expected_refs
from app.services.evaluation.runner import aggregate_run_results, estimate_llm_calls, evaluate_case
from app.schemas.retrieval import RetrievalMode
from app.services.privacy.egress_validator import EgressReport, EgressViolationError
from app.services.privacy.entity_registry import EntityRegistry
from app.services.retrieval.hybrid_retriever import HybridRetriever

engine = create_async_engine(
    "sqlite+aiosqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
)
TestingSessionLocal = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
TENANT_ID = uuid.uuid4()
USER_ID = uuid.uuid4()
JUDGE_JSON = '{"faithfulness":0.9,"answer_relevance":0.8,"correctness":0.7,"rationale":"ok"}'
ANSWER = "Gini must be at least 0.40 [Source: CBUAE-MMG-2022, Section: Section 4 - Quantitative Validation & Discriminatory Power]"


class IdentityMasking:
    def mask_document(self, text: str, registry: EntityRegistry | None = None) -> tuple[str, EntityRegistry]:
        return text, registry or EntityRegistry()


class NoopEgress:
    def validate(self, text: str, registry: EntityRegistry | None = None) -> None:
        return None


class ViolatingEgress:
    def validate(self, text: str, registry: EntityRegistry | None = None) -> None:
        raise EgressViolationError("leak", EgressReport(is_clean=False, violations=["x"], warnings=[]))


class FakeRouter:
    def __init__(self, generation_fails: bool = False, judge_fails: bool = False) -> None:
        self.call_log: list[Any] = []
        self.generation_fails = generation_fails
        self.judge_fails = judge_fails
        self.aclose = AsyncMock()

    async def embed(self, texts: list[str], input_type: str = "query") -> list[list[float]]:
        raise RuntimeError("no embeddings offline")

    async def rerank(self, query: str, passages: list[str], top_n: int = 5) -> list[Any]:
        raise RuntimeError("no rerank offline")

    async def generate(self, prompt: str, system_prompt: str | None = None, **kwargs: Any) -> str:
        if kwargs.get("json_schema"):
            if self.judge_fails:
                raise RuntimeError("judge down")
            return JUDGE_JSON
        if self.generation_fails:
            raise RuntimeError("generation down")
        return ANSWER


@pytest_asyncio.fixture
async def db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with TestingSessionLocal() as session:
        session.add(Tenant(id=TENANT_ID, name="T"))
        await session.flush()
        session.add(User(id=USER_ID, email="r@example.com", hashed_password="pw", tenant_id=TENANT_ID, role=RoleEnum.ANALYST))
        await session.commit()
        yield session
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


def _run(mode: str = "bm25", include_generation: bool = False, judge: str = "auto", top_k: int = 5) -> RagEvalRun:
    return RagEvalRun(
        id=uuid.uuid4(), tenant_id=TENANT_ID, user_id=USER_ID, group_id=uuid.uuid4(), status="running",
        mode=mode, top_k=top_k, include_generation=include_generation, judge=judge, case_ids_json=[],
        total_cases=1, completed_cases=0, failed_cases=0,
    )


def _default_case(index: int = 6) -> RagEvalCase:
    spec = DEFAULT_CASE_SPECS[index]
    return RagEvalCase(
        id=uuid.uuid4(), tenant_id=TENANT_ID, question=spec.question, reference_answer=spec.reference_answer,
        expected_refs_json=build_expected_refs(spec), document_id=None, origin="default", default_key=spec.key,
        is_active=True,
    )


async def _evaluate(db, run, case, router=None, egress=None) -> RagEvalResult:
    router = router or FakeRouter()
    return await evaluate_case(
        db=db, run=run, case=case, position=0, retriever=HybridRetriever(router, MagicMock()),
        llm_router=router, masking=IdentityMasking(), egress=egress or NoopEgress(),
    )


@pytest.mark.asyncio
async def test_retrieval_only_case_scores(db) -> None:
    row = await _evaluate(db, _run(), _default_case(6))  # Gini case -> Section 4
    assert row.status == "ok"
    assert row.hit is True and row.first_relevant_rank == 1
    assert row.recall == 1.0 and row.reciprocal_rank == 1.0
    assert row.retrieved_json[0]["relevant"] is True and row.retrieved_json[0]["matched_targets"] == [0]
    assert len(row.retrieved_json[0]["snippet"]) <= 280
    assert row.diagnostics_json["mode"] == "bm25" and row.diagnostics_json["unresolved_chunk_targets"] == 0
    assert "fused_preview" not in row.diagnostics_json
    assert row.judge_method == "none" and row.answer_masked is None


@pytest.mark.asyncio
async def test_egress_violation_gives_error_row_without_question(db) -> None:
    row = await _evaluate(db, _run(), _default_case(), egress=ViolatingEgress())
    assert row.status == "error"
    assert row.error_stage == "egress" and row.error_type == "EgressViolationError"
    assert row.question_masked is None


@pytest.mark.asyncio
async def test_missing_document_gives_document_error(db) -> None:
    case = _default_case()
    case.document_id = uuid.uuid4()
    row = await _evaluate(db, _run(), case)
    assert row.status == "error"
    assert row.error_stage == "document" and row.error_type == "DocumentNotFound"


@pytest.mark.asyncio
async def test_chunk_index_target_matches_by_fingerprint(db) -> None:
    doc_id = uuid.uuid4()
    db.add(Document(id=doc_id, tenant_id=TENANT_ID, user_id=USER_ID, filename="pd.pdf", file_type="pdf",
                    raw_markdown="x", status=DocumentStatus.READY))
    await db.flush()
    db.add_all(
        [
            DocumentChunk(document_id=doc_id, chunk_index=0, masked_text="Appendix with unrelated tables."),
            DocumentChunk(document_id=doc_id, chunk_index=1, masked_text="The PD model Gini coefficient is 0.52 on the holdout sample."),
            DocumentChunk(document_id=doc_id, chunk_index=2, masked_text="Population stability index stays below 0.10."),
        ]
    )
    await db.commit()
    case = RagEvalCase(
        id=uuid.uuid4(), tenant_id=TENANT_ID, question="What Gini does the PD model achieve on the holdout?",
        reference_answer=None, expected_refs_json=[{"chunk_index": 1}, {"chunk_index": 9}], document_id=doc_id,
        origin="custom", is_active=True,
    )

    row = await _evaluate(db, _run(top_k=3), case)

    assert row.status == "ok"
    assert row.n_targets == 2 and row.targets_matched == 1
    assert row.first_relevant_rank == 1 and row.recall == 0.5
    assert row.retrieved_json[0]["section"] == "chunk-1"
    assert row.diagnostics_json["unresolved_chunk_targets"] == 1


@pytest.mark.asyncio
async def test_generation_failure_keeps_retrieval_metrics(db) -> None:
    row = await _evaluate(db, _run(include_generation=True), _default_case(), router=FakeRouter(generation_fails=True))
    assert row.status == "ok"
    assert row.hit is True and row.recall == 1.0
    assert row.error_stage == "generation" and row.error_type == "RuntimeError"
    assert row.judge_method == "none" and row.answer_masked is None


@pytest.mark.asyncio
async def test_generation_and_llm_judge(db) -> None:
    row = await _evaluate(db, _run(mode="hybrid_rerank", include_generation=True), _default_case())
    assert row.answer_masked == ANSWER
    assert row.judge_method == "llm"
    assert (row.faithfulness, row.answer_relevance, row.answer_correctness) == (0.9, 0.8, 0.7)
    assert row.diagnostics_json["dense_empty"] is True and row.diagnostics_json["rerank_fallback"] is True


@pytest.mark.asyncio
async def test_judge_failure_falls_back_to_deterministic(db) -> None:
    row = await _evaluate(db, _run(include_generation=True), _default_case(), router=FakeRouter(judge_fails=True))
    assert row.judge_method == "deterministic"
    assert row.faithfulness is not None and row.answer_correctness is not None
    assert "RuntimeError" in row.judge_rationale


@pytest.mark.asyncio
async def test_deterministic_judge_mode_skips_llm(db) -> None:
    row = await _evaluate(db, _run(include_generation=True, judge="deterministic"), _default_case())
    assert row.judge_method == "deterministic"
    assert row.judge_rationale == "Deterministic token-overlap proxy."


def test_aggregate_run_results_means_and_curves() -> None:
    def result(**kw: Any) -> RagEvalResult:
        base = dict(status="ok", n_targets=1, judge_method="none", diagnostics_json={})
        base.update(kw)
        return RagEvalResult(**base)

    rows = [
        result(hit=True, recall=1.0, precision=0.5, reciprocal_rank=1.0, ndcg=1.0, retrieval_ms=10.0,
               generation_ms=90.0, faithfulness=0.9, judge_method="llm", relevances_json=[1, 0],
               retrieved_json=[{"matched_targets": [0]}, {"matched_targets": []}],
               diagnostics_json={"dense_empty": True, "rerank_fallback": True, "unresolved_chunk_targets": 1}),
        result(hit=False, recall=0.0, precision=0.0, reciprocal_rank=0.0, ndcg=0.0, retrieval_ms=20.0,
               relevances_json=[0, 0], retrieved_json=[{"matched_targets": []}, {"matched_targets": []}]),
        result(status="error", hit=None, error_stage="egress"),
    ]
    agg = aggregate_run_results(rows, top_k=2, include_generation=True)
    assert agg["hit_rate"] == 0.5 and agg["mean_recall"] == 0.5 and agg["mrr"] == 0.5
    assert agg["mean_faithfulness"] == 0.9 and agg["mean_answer_correctness"] is None
    assert agg["p50_latency_ms"] == 60.0
    metrics = agg["metrics_json"]
    assert metrics["curves"]["k"] == [1, 2] and metrics["curves"]["hit"] == [0.5, 0.5]
    assert metrics["judge_breakdown"] == {"llm": 1, "deterministic": 0, "none": 1}
    assert metrics["degraded"] == {"dense_empty": 1, "rerank_fallback": 1, "unresolved_chunk_targets": 1}
    assert metrics["generation_temperature"] == 0.0
    empty = aggregate_run_results([], top_k=5, include_generation=False)
    assert empty["hit_rate"] is None and empty["metrics_json"]["curves"] is None


def test_estimate_llm_calls_formula() -> None:
    modes = [RetrievalMode.BM25, RetrievalMode.HYBRID, RetrievalMode.HYBRID_RERANK]
    assert estimate_llm_calls(modes, 22, True, "auto") == 22 * (2 + 3 + 4)
    assert estimate_llm_calls([RetrievalMode.BM25], 10, False, "auto") == 0
    assert estimate_llm_calls([RetrievalMode.DENSE], 10, True, "deterministic") == 20

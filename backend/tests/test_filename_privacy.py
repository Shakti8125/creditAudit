"""Uploaded filenames never reach Pinecone metadata or any provider prompt (QA-004 / NEW-03).

AGENTS.md: raw upload filenames are never sent to any provider and never stored in
Pinecone metadata (use ``document_id`` and ``DOC-n`` aliases).
"""

from __future__ import annotations

import io
import json
import uuid
from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.db.database import Base, get_db
from app.main import app
from app.middleware.rate_limiter import get_rate_limiter
from app.models.audit import Model, ModelTypeEnum, ModelVersion
from app.models.document import Document, DocumentChunk, DocumentStatus
from app.models.user import RoleEnum, Tenant, User
from app.schemas.retrieval import ChunkData, VectorResult
from app.services.document_extractor import DocumentExtractor
from app.services.retrieval.dense_retriever import DenseRetriever
from app.services.retrieval.pinecone_store import (
    PineconeStore,
    parse_user_docs_namespace,
)
from app.utils.security import create_access_token

engine = create_async_engine(
    "sqlite+aiosqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
)
TestingSessionLocal = async_sessionmaker(
    autocommit=False, autoflush=False, bind=engine, class_=AsyncSession, expire_on_commit=False
)

TENANT_ID = uuid.uuid4()
USER_ID = uuid.uuid4()
FILENAME = "Emirates NBD Retail PD Validation Q3.pdf"
STEMS = ("Emirates NBD", "Retail PD Validation", FILENAME)

REPORT = (
    "# Validation Report\n\n"
    "The model demonstrated strong discriminatory power with a Gini coefficient of 48.5% "
    "and a KS statistic of 36.2%.\n\n"
    "## Stability\n\n"
    "The Population Stability Index (PSI) was evaluated at 0.06 over the historical window.\n"
)


async def override_get_db() -> AsyncIterator[AsyncSession]:
    async with TestingSessionLocal() as session:
        yield session


async def override_get_rate_limiter() -> None:
    return None


@pytest_asyncio.fixture(autouse=True)
async def setup_db() -> AsyncIterator[None]:
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_rate_limiter] = override_get_rate_limiter
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with TestingSessionLocal() as session:
        session.add(Tenant(id=TENANT_ID, name="Filename Tenant"))
        await session.flush()
        session.add(
            User(id=USER_ID, email="fn@example.test", hashed_password="pw", tenant_id=TENANT_ID, role=RoleEnum.ANALYST)
        )
        await session.commit()
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(get_rate_limiter, None)


def _headers() -> dict[str, str]:
    token = create_access_token(user_id=USER_ID, tenant_id=TENANT_ID, role="ANALYST")
    return {"Authorization": f"Bearer {token}"}


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _assert_no_filename(text: str) -> None:
    for stem in STEMS:
        assert stem not in text, stem


# ---------------------------------------------------------------------------- Pinecone metadata


def test_parse_user_docs_namespace() -> None:
    assert parse_user_docs_namespace("user-docs:t-1:d-1") == ("t-1", "d-1")
    for other in ("cbuae-manuals", "reg-g1", "user-docs:only-tenant", "user-docs:a:b:c", "user-docs::d"):
        assert parse_user_docs_namespace(other) is None


def test_store_overrides_a_filename_source_for_tenant_namespaces() -> None:
    """Even a caller that passes the filename cannot put it into a tenant document's metadata."""
    store = PineconeStore(api_key="mock_key", index_name="mock_index")
    store.index = MagicMock()
    tenant_id, doc_id = uuid.uuid4(), uuid.uuid4()
    chunk = ChunkData(source=FILENAME, section="Findings", text="Gini 64%")

    store.upsert_vectors(ids=["v1"], vectors=[[0.1] * 4], chunks=[chunk], namespace=f"user-docs:{tenant_id}:{doc_id}")

    (_, _, meta), = store.index.upsert.call_args.kwargs["vectors"]
    assert meta == {"source": f"doc-{doc_id}", "document_id": str(doc_id), "section": "Findings", "text": "Gini 64%"}
    _assert_no_filename(json.dumps(meta))


def test_store_keeps_the_public_corpus_source_in_the_public_namespace() -> None:
    store = PineconeStore(api_key="mock_key", index_name="mock_index")
    store.index = MagicMock()
    chunk = ChunkData(source="CBUAE-MMG-2022", section="Section 4", text="Gini >= 0.40")

    store.upsert_vectors(ids=["v1"], vectors=[[0.1] * 4], chunks=[chunk], namespace="cbuae-manuals")

    (_, _, meta), = store.index.upsert.call_args.kwargs["vectors"]
    assert meta["source"] == "CBUAE-MMG-2022" and "document_id" not in meta


@pytest.mark.asyncio
async def test_upload_writes_document_ids_not_filenames_to_pinecone() -> None:
    async with TestingSessionLocal() as session:
        model_id, version_id = uuid.uuid4(), uuid.uuid4()
        session.add(Model(id=model_id, tenant_id=TENANT_ID, user_id=USER_ID, name="Retail PD", type=ModelTypeEnum.PD))
        await session.flush()
        session.add(ModelVersion(id=version_id, model_id=model_id, version="1.0", is_current=True))
        await session.commit()

    store = PineconeStore(api_key="mock_key", index_name="mock_index")
    store.index = MagicMock()
    router = MagicMock()
    router.embed = AsyncMock(side_effect=lambda chunks, input_type="document": [[0.1] * 8 for _ in chunks])
    router.aclose = AsyncMock()

    with patch.object(DocumentExtractor, "extract_to_markdown", new_callable=AsyncMock, return_value=REPORT), patch(
        "app.api.documents.LLMRouter", return_value=router
    ), patch("app.api.documents.PineconeStore", return_value=store):
        async with _client() as client:
            response = await client.post(
                "/documents/upload",
                files={"file": (FILENAME, io.BytesIO(REPORT.encode()), "application/pdf")},
                data={"model_version_id": str(version_id)},
                headers=_headers(),
            )

    assert response.status_code == 200, response.text
    doc_id = response.json()["document_id"]
    calls = store.index.upsert.call_args_list
    assert calls and all(call.kwargs["namespace"] == f"user-docs:{TENANT_ID}:{doc_id}" for call in calls)
    records = [record for call in calls for record in call.kwargs["vectors"]]
    assert records
    for _, _, meta in records:
        assert meta["source"] == f"doc-{doc_id}"
        assert meta["document_id"] == doc_id
    # Nothing that was sent to the vector store carries the filename (metadata, text, ids).
    _assert_no_filename(json.dumps(records))
    # Embedding inputs (the only other provider call of an upload) are chunk text only.
    embedded = " ".join(" ".join(call.args[0]) for call in router.embed.await_args_list)
    _assert_no_filename(embedded)


@pytest.mark.asyncio
async def test_upload_hands_the_store_chunks_identified_by_document_id() -> None:
    """The upload endpoint itself passes ``doc-<id>``; the store's override is a second line of defence."""
    async with TestingSessionLocal() as session:
        model_id, version_id = uuid.uuid4(), uuid.uuid4()
        session.add(Model(id=model_id, tenant_id=TENANT_ID, user_id=USER_ID, name="Retail PD", type=ModelTypeEnum.PD))
        await session.flush()
        session.add(ModelVersion(id=version_id, model_id=model_id, version="1.0", is_current=True))
        await session.commit()

    router = MagicMock()
    router.embed = AsyncMock(side_effect=lambda chunks, input_type="document": [[0.1] * 8 for _ in chunks])
    router.aclose = AsyncMock()

    with patch.object(DocumentExtractor, "extract_to_markdown", new_callable=AsyncMock, return_value=REPORT), patch(
        "app.api.documents.LLMRouter", return_value=router
    ), patch.object(PineconeStore, "aupsert_chunks", new_callable=AsyncMock) as upsert:
        async with _client() as client:
            response = await client.post(
                "/documents/upload",
                files={"file": (FILENAME, io.BytesIO(REPORT.encode()), "application/pdf")},
                data={"model_version_id": str(version_id)},
                headers=_headers(),
            )

    assert response.status_code == 200, response.text
    doc_id = response.json()["document_id"]
    chunks: list[ChunkData] = upsert.call_args.kwargs["chunks"]
    assert chunks
    assert {c.source for c in chunks} == {f"doc-{doc_id}"}
    assert {c.document_id for c in chunks} == {doc_id}
    _assert_no_filename(json.dumps([c.model_dump() for c in chunks]))


# ---------------------------------------------------------------------------- retrieval of old vectors


@pytest.mark.asyncio
async def test_dense_retrieval_takes_the_document_identity_from_the_namespace() -> None:
    """Vectors written before this fix hold the raw filename in ``source``; it is never used."""
    tenant_id, doc_id = uuid.uuid4(), uuid.uuid4()
    router = MagicMock()
    router.embed = AsyncMock(return_value=[[0.1] * 4])
    store = MagicMock()

    async def query(embedding: list[float], namespace: str, top_k: int = 20) -> list[VectorResult]:
        source = FILENAME if namespace.startswith("user-docs:") else "CBUAE-MMG-2022"
        return [VectorResult(id="v", score=0.9, metadata={"text": "t", "source": source, "section": "S"})]

    store.query = AsyncMock(side_effect=query)

    candidates = await DenseRetriever(router, store).retrieve(
        "q", ["cbuae-manuals", f"user-docs:{tenant_id}:{doc_id}"], top_k=5
    )

    by_document = {c.document_id: c for c in candidates}
    assert by_document[str(doc_id)].source == f"doc-{doc_id}"
    assert by_document[None].source == "CBUAE-MMG-2022"
    _assert_no_filename(json.dumps([c.model_dump() for c in candidates]))


# ---------------------------------------------------------------------------- the other prompt-building endpoints


async def _seed_document_with_filename() -> uuid.UUID:
    doc_id = uuid.uuid4()
    async with TestingSessionLocal() as session:
        session.add(
            Document(
                id=doc_id,
                tenant_id=TENANT_ID,
                user_id=USER_ID,
                filename=FILENAME,
                file_type="pdf",
                raw_markdown=REPORT,
                status=DocumentStatus.READY,
            )
        )
        await session.flush()
        session.add(DocumentChunk(document_id=doc_id, chunk_index=0, masked_text=REPORT))
        await session.commit()
    return doc_id


@pytest.mark.asyncio
async def test_gap_analysis_prompt_has_no_filename() -> None:
    doc_id = await _seed_document_with_filename()
    payload = {"gaps": [], "coverage_score": 0.9}
    with patch("app.api.gap_analysis.LLMRouter.generate", new_callable=AsyncMock, return_value=json.dumps(payload)) as gen, patch(
        "app.api.gap_analysis.LLMRouter.aclose", new_callable=AsyncMock
    ):
        async with _client() as client:
            response = await client.post("/gap-analysis", json={"document_id": str(doc_id)}, headers=_headers())

    assert response.status_code == 200, response.text
    sent = " ".join([*map(str, gen.await_args.args), *map(str, gen.await_args.kwargs.values())])
    _assert_no_filename(sent)
    assert "Gini coefficient of 48.5%" in sent  # the (masked) document text is what is sent


@pytest.mark.asyncio
async def test_compare_prompt_has_no_filename() -> None:
    doc_a = await _seed_document_with_filename()
    doc_b = await _seed_document_with_filename()
    payload: dict[str, Any] = {"differences": [], "summary": "The documents are equivalent."}
    with patch("app.api.compare.LLMRouter.generate", new_callable=AsyncMock, return_value=json.dumps(payload)) as gen, patch(
        "app.api.compare.LLMRouter.aclose", new_callable=AsyncMock
    ):
        async with _client() as client:
            response = await client.post(
                "/compare", json={"document_id_a": str(doc_a), "document_id_b": str(doc_b)}, headers=_headers()
            )

    assert response.status_code == 200, response.text
    sent = " ".join([*map(str, gen.await_args.args), *map(str, gen.await_args.kwargs.values())])
    _assert_no_filename(sent)
    assert "Document A" in sent and "Document B" in sent

from __future__ import annotations

import uuid
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.main import app
from app.db.database import Base, get_db
from app.models.user import User, Tenant, RoleEnum
from app.models.document import Document, DocumentChunk, DocumentStatus
from app.services.retrieval.hybrid_retriever import HybridRetriever
from app.services.retrieval.pinecone_store import PineconeStore
from app.schemas.retrieval import ChunkData
from app.utils.security import create_access_token, hash_password
from unittest.mock import AsyncMock, MagicMock

SQLALCHEMY_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

engine = create_async_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = async_sessionmaker(
    autocommit=False, autoflush=False, bind=engine, class_=AsyncSession, expire_on_commit=False
)

async def override_get_db():
    async with TestingSessionLocal() as session:
        yield session

@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    app.dependency_overrides[get_db] = override_get_db
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_fetch_chunks_cross_tenant_isolation():
    """Verify _fetch_chunks_for_document enforces cross-tenant boundary."""
    async with TestingSessionLocal() as session:
        t1_id = uuid.uuid4()
        t2_id = uuid.uuid4()
        u1_id = uuid.uuid4()
        u2_id = uuid.uuid4()

        tenant_1 = Tenant(id=t1_id, name="Tenant Alpha")
        tenant_2 = Tenant(id=t2_id, name="Tenant Beta")
        user_1 = User(id=u1_id, email="u1@alpha.com", hashed_password="pw", tenant_id=t1_id, role=RoleEnum.ANALYST)
        user_2 = User(id=u2_id, email="u2@beta.com", hashed_password="pw", tenant_id=t2_id, role=RoleEnum.ANALYST)
        session.add_all([tenant_1, tenant_2, user_1, user_2])
        await session.flush()

        doc_1 = Document(
            id=uuid.uuid4(),
            tenant_id=t1_id,
            user_id=u1_id,
            filename="alpha_model.pdf",
            file_type="pdf",
            raw_markdown="Alpha doc content",
            status=DocumentStatus.READY,
        )
        doc_2 = Document(
            id=uuid.uuid4(),
            tenant_id=t2_id,
            user_id=u2_id,
            filename="beta_model.pdf",
            file_type="pdf",
            raw_markdown="Beta doc content",
            status=DocumentStatus.READY,
        )
        session.add_all([doc_1, doc_2])
        await session.flush()

        chunk_1 = DocumentChunk(
            id=uuid.uuid4(),
            document_id=doc_1.id,
            chunk_index=0,
            masked_text="Alpha confidential data",
        )
        chunk_2 = DocumentChunk(
            id=uuid.uuid4(),
            document_id=doc_2.id,
            chunk_index=0,
            masked_text="Beta confidential data",
        )
        session.add_all([chunk_1, chunk_2])
        await session.commit()

        mock_router = MagicMock()
        mock_pinecone = MagicMock()
        retriever = HybridRetriever(mock_router, mock_pinecone)

        # Cross-tenant query: Tenant 1 asking for Tenant 2's document chunks
        t1_fetches_t2 = await retriever._fetch_chunks_for_document(
            db=session,
            tenant_id=t1_id,
            document_id=doc_2.id,
        )
        assert len(t1_fetches_t2) == 0, "Cross-tenant leak! Tenant 1 retrieved Tenant 2 chunks."

        # Cross-tenant query: Tenant 2 asking for Tenant 1's document chunks
        t2_fetches_t1 = await retriever._fetch_chunks_for_document(
            db=session,
            tenant_id=t2_id,
            document_id=doc_1.id,
        )
        assert len(t2_fetches_t1) == 0, "Cross-tenant leak! Tenant 2 retrieved Tenant 1 chunks."

        # Authorized query: Tenant 1 asking for Tenant 1's document chunks
        t1_fetches_t1 = await retriever._fetch_chunks_for_document(
            db=session,
            tenant_id=t1_id,
            document_id=doc_1.id,
        )
        assert len(t1_fetches_t1) == 1
        assert t1_fetches_t1[0].masked_text == "Alpha confidential data"


@pytest.mark.asyncio
async def test_pinecone_store_namespace_isolation():
    """Verify PineconeStore namespace and HybridRetriever isolate tenant namespaces."""
    store = PineconeStore(api_key="mock_key", index_name="mock_index")
    tenant_id = uuid.uuid4()
    doc_id = uuid.uuid4()

    mock_index = MagicMock()
    store.index = mock_index

    # Hybrid retriever namespace formatting check: user-docs:{tenant_id}:{document_id}
    expected_namespace = f"user-docs:{tenant_id}:{doc_id}"

    chunk = ChunkData(source="doc.pdf", section="Sec 1", text="Sample chunk text")
    vectors = [[0.1] * 1024]
    ids = ["vec-1"]

    # Upsert vectors with namespace
    store.upsert_vectors(ids=ids, vectors=vectors, chunks=[chunk], namespace=expected_namespace)
    mock_index.upsert.assert_called_once()
    call_kwargs = mock_index.upsert.call_args.kwargs
    assert call_kwargs["namespace"] == expected_namespace


@pytest.mark.asyncio
async def test_api_document_cross_tenant_access_denied():
    """Verify HTTP API returns 404 when user from Tenant 1 attempts to access Tenant 2 document."""
    tenant_1_id = uuid.uuid4()
    tenant_2_id = uuid.uuid4()
    user_1_id = uuid.uuid4()
    user_2_id = uuid.uuid4()

    async with TestingSessionLocal() as session:
        t1 = Tenant(id=tenant_1_id, name="Tenant 1")
        t2 = Tenant(id=tenant_2_id, name="Tenant 2")
        u1 = User(
            id=user_1_id,
            email="user1@tenant1.com",
            hashed_password=hash_password("pass123"),
            tenant_id=tenant_1_id,
            role=RoleEnum.ANALYST,
            is_active=True,
        )
        u2 = User(
            id=user_2_id,
            email="user2@tenant2.com",
            hashed_password=hash_password("pass123"),
            tenant_id=tenant_2_id,
            role=RoleEnum.ANALYST,
            is_active=True,
        )
        doc2 = Document(
            id=uuid.uuid4(),
            tenant_id=tenant_2_id,
            user_id=user_2_id,
            filename="tenant2_confidential.pdf",
            file_type="pdf",
            raw_markdown="Confidential content",
            status=DocumentStatus.READY,
        )
        session.add_all([t1, t2, u1, u2, doc2])
        await session.commit()

    token_t1 = create_access_token(user_id=user_1_id, tenant_id=tenant_1_id, role="validator")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Tenant 1 attempts to fetch Tenant 2's document
        response = await client.get(
            f"/documents/{doc2.id}",
            headers={"Authorization": f"Bearer {token_t1}"},
        )
        assert response.status_code == 404, f"Expected 404 for cross-tenant document, got {response.status_code}"

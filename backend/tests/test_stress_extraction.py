from __future__ import annotations

import io
import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.db.database import Base, get_db
from app.main import app
from app.middleware.rate_limiter import get_rate_limiter
from app.models.audit import Model, ModelStatusEnum, ModelTypeEnum, ModelVersion
from app.models.document import Document, DocumentChunk, DocumentStatus
from app.models.system import TenantSettings
from app.models.user import RoleEnum, Tenant, User
from app.schemas.auth import TokenPayload
from app.schemas.metrics import BreachReport, MetricValue, ModelValidationProfile, PolicyResult
from app.services.chunker import MarkdownChunker
from app.services.document_extractor import DocumentExtractionError, DocumentExtractor
from app.services.privacy.egress_validator import EgressViolationError
from app.services.retrieval.pinecone_store import PineconeStore
from app.utils.security import create_access_token

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


async def override_get_rate_limiter():
    pass


@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_rate_limiter] = override_get_rate_limiter
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(get_rate_limiter, None)


@pytest.mark.asyncio
async def test_document_extractor_unsupported_format():
    """Verify DocumentExtractor rejects unsupported file formats."""
    extractor = DocumentExtractor()
    with pytest.raises(ValueError, match="Unsupported file type"):
        await extractor.extract_to_markdown(b"sample content", "report.txt")

    with pytest.raises(ValueError, match="Unsupported file type"):
        await extractor.extract_to_markdown(b"sample content", "data.csv")


@pytest.mark.asyncio
async def test_pinecone_store_adelete_namespace():
    """Verify PineconeStore.delete_namespace and adelete_namespace handle cases robustly."""
    store = PineconeStore(api_key="mock_key", index_name="mock_index")

    # Case 1: Uninitialized index handles deletion gracefully without raising
    store.index = None
    await store.adelete_namespace("user-docs:tenant1:doc1")

    # Case 2: Initialized index calls index.delete
    mock_index = MagicMock()
    store.index = mock_index
    await store.adelete_namespace("user-docs:tenant1:doc1")
    mock_index.delete.assert_called_once_with(delete_all=True, namespace="user-docs:tenant1:doc1")

    # Case 3: 404 / NotFound does not raise an exception
    mock_index.reset_mock()
    mock_index.delete.side_effect = Exception("404: Namespace user-docs:tenant1:doc1 not found")
    # Should not raise exception
    await store.adelete_namespace("user-docs:tenant1:doc1")
    mock_index.delete.assert_called_once_with(delete_all=True, namespace="user-docs:tenant1:doc1")


def test_section_header_extraction_logic():
    """Verify section header extraction accurately captures single and multi-level headings."""
    sample_chunks = [
        "Model Overview > Credit Scoring Methodology:\nThis section describes the scorecard.",
        "Executive Summary:\nOverall validation passed with minor caveats.",
        "General text line 1.\nGeneral text line 2:\nThis colon is mid-text.",
        "Plain body paragraph without header context.",
    ]

    extracted_sections = []
    for c in sample_chunks:
        section = ""
        if ":\n" in c:
            header_cand, _, _ = c.partition(":\n")
            if "\n" not in header_cand and header_cand.strip():
                section = header_cand.strip()
        extracted_sections.append(section)

    assert extracted_sections[0] == "Model Overview > Credit Scoring Methodology"
    assert extracted_sections[1] == "Executive Summary"
    assert extracted_sections[2] == ""  # Colon was on line 2, not a header prefix
    assert extracted_sections[3] == ""


@pytest.mark.asyncio
async def test_gap_analysis_egress_validator_privacy_enforcement():
    """Verify EgressValidator blocks unmasked entity leakage in gap analysis endpoint."""
    t_id = uuid.uuid4()
    u_id = uuid.uuid4()
    doc_id = uuid.uuid4()

    token = create_access_token(user_id=u_id, tenant_id=t_id, role="ANALYST")
    headers = {"Authorization": f"Bearer {token}"}

    async with TestingSessionLocal() as session:
        tenant = Tenant(id=t_id, name="Test Tenant")
        user = User(id=u_id, email="auditor@test.com", hashed_password="pw", tenant_id=t_id, role=RoleEnum.ANALYST)
        doc = Document(
            id=doc_id,
            tenant_id=t_id,
            user_id=u_id,
            filename="leak_test.pdf",
            file_type="pdf",
            raw_markdown="Unmasked text with First Abu Dhabi Bank",
            status=DocumentStatus.READY,
        )
        chunk = DocumentChunk(
            id=uuid.uuid4(),
            document_id=doc_id,
            chunk_index=0,
            # Leaking raw bank name
            masked_text="First Abu Dhabi Bank credit portfolio validation summary.",
        )
        session.add_all([tenant, user, doc, chunk])
        await session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/gap-analysis",
            json={"document_id": str(doc_id)},
            headers=headers,
        )
        # Should be blocked with 400 Bad Request by EgressValidator
        assert response.status_code == 400
        assert "Privacy validation failed" in response.json()["detail"]


@pytest.mark.asyncio
async def test_list_documents_chunk_count_and_delete_document():
    """Verify list_documents returns accurate chunk_count and delete_document purges Pinecone namespace."""
    t_id = uuid.uuid4()
    u_id = uuid.uuid4()
    doc_id = uuid.uuid4()

    token = create_access_token(user_id=u_id, tenant_id=t_id, role="ANALYST")
    headers = {"Authorization": f"Bearer {token}"}

    async with TestingSessionLocal() as session:
        tenant = Tenant(id=t_id, name="Test Tenant")
        user = User(id=u_id, email="analyst@test.com", hashed_password="pw", tenant_id=t_id, role=RoleEnum.ANALYST)
        doc = Document(
            id=doc_id,
            tenant_id=t_id,
            user_id=u_id,
            filename="scored_model.pdf",
            file_type="pdf",
            raw_markdown="Scored model markdown",
            status=DocumentStatus.READY,
        )
        chunk1 = DocumentChunk(id=uuid.uuid4(), document_id=doc_id, chunk_index=0, masked_text="Chunk 1")
        chunk2 = DocumentChunk(id=uuid.uuid4(), document_id=doc_id, chunk_index=1, masked_text="Chunk 2")
        chunk3 = DocumentChunk(id=uuid.uuid4(), document_id=doc_id, chunk_index=2, masked_text="Chunk 3")
        session.add_all([tenant, user, doc, chunk1, chunk2, chunk3])
        await session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Test list_documents chunk count
        list_resp = await client.get("/documents", headers=headers)
        assert list_resp.status_code == 200
        docs_data = list_resp.json()["documents"]
        assert len(docs_data) == 1
        assert docs_data[0]["id"] == str(doc_id)
        assert docs_data[0]["chunk_count"] == 3, f"Expected chunk_count 3, got {docs_data[0]['chunk_count']}"

        # 2. Test delete_document purges vector namespace
        with patch.object(PineconeStore, "adelete_namespace", new_callable=AsyncMock) as mock_adelete:
            del_resp = await client.delete(f"/documents/{doc_id}", headers=headers)
            assert del_resp.status_code == 204
            mock_adelete.assert_called_once_with(f"user-docs:{t_id}:{doc_id}")

        # 3. Confirm document deleted from DB
        get_resp = await client.get(f"/documents/{doc_id}", headers=headers)
        assert get_resp.status_code == 404


@pytest.mark.asyncio
async def test_upload_document_pipeline_and_model_status_update():
    """Verify document upload updates parent Model status, compliance score, and upserts to user-docs namespace."""
    t_id = uuid.uuid4()
    u_id = uuid.uuid4()
    model_id = uuid.uuid4()
    version_id = uuid.uuid4()

    token = create_access_token(user_id=u_id, tenant_id=t_id, role="ANALYST")
    headers = {"Authorization": f"Bearer {token}"}

    async with TestingSessionLocal() as session:
        tenant = Tenant(id=t_id, name="Corporate Bank")
        user = User(id=u_id, email="auditor@corp.com", hashed_password="pw", tenant_id=t_id, role=RoleEnum.ANALYST)
        model = Model(
            id=model_id,
            tenant_id=t_id,
            user_id=u_id,
            name="Retail Scorecard",
            type=ModelTypeEnum.CREDIT_SCORING,
            description="Credit scorecard model",
            status=None,
        )
        model_version = ModelVersion(
            id=version_id,
            model_id=model_id,
            version="1.0.0",
            is_current=True,
        )
        settings = TenantSettings(
            tenant_id=t_id,
            gini_tolerance=0.05,
            psi_warning_threshold=0.10,
            psi_breach_threshold=0.25,
        )
        session.add_all([tenant, user, model, model_version, settings])
        await session.commit()

    sample_doc_content = (
        b"# Retail Credit Scorecard Report\n\n"
        b"## Quantitative Validation Results\n\n"
        b"The model demonstrated strong discriminatory power with Gini coefficient of 48.5% and KS statistic of 36.2%.\n"
        b"The Population Stability Index (PSI) was evaluated at 0.06 over the historical window.\n"
        b"Backtesting accuracy ratio was 58.0%."
    )

    transport = ASGITransport(app=app)
    with patch.object(DocumentExtractor, "extract_to_markdown", new_callable=AsyncMock) as mock_extract, \
         patch.object(PineconeStore, "aupsert_chunks", new_callable=AsyncMock) as mock_upsert, \
         patch("app.api.documents.LLMRouter") as mock_router_cls:

        mock_extract.return_value = sample_doc_content.decode("utf-8")
        mock_router_instance = MagicMock()
        mock_router_instance.embed = AsyncMock(return_value=[[0.1] * 1024])
        mock_router_instance.aclose = AsyncMock()
        mock_router_cls.return_value = mock_router_instance

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            files = {"file": ("scorecard.pdf", io.BytesIO(sample_doc_content), "application/pdf")}
            data = {"model_version_id": str(version_id)}

            response = await client.post(
                "/documents/upload",
                files=files,
                data=data,
                headers=headers,
            )

            assert response.status_code == 200, f"Upload failed: {response.text}"
            res_json = response.json()
            doc_id = res_json["document_id"]
            assert res_json["chunk_count"] > 0
            assert "metrics_summary" in res_json

            # Verify Pinecone namespace was isolated with user-docs:{tenant_id}:{document_id}
            expected_namespace = f"user-docs:{t_id}:{doc_id}"
            mock_upsert.assert_called_once()
            called_namespace = mock_upsert.call_args.kwargs.get("namespace")
            assert called_namespace == expected_namespace, f"Expected namespace '{expected_namespace}', got '{called_namespace}'"

    # Verify parent Model was updated with status and compliance metrics
    async with TestingSessionLocal() as session:
        from sqlalchemy import select
        res = await session.execute(select(Model).where(Model.id == model_id))
        updated_model = res.scalars().first()
        assert updated_model is not None
        assert updated_model.status in (ModelStatusEnum.PASS, ModelStatusEnum.WARNING, ModelStatusEnum.BREACH)
        assert updated_model.status == ModelStatusEnum.PASS


"""Tests for the backend wiring behind the UI gap items.

Covers upload notifications (W1), the AI-reviews KPI (W2), model-scoped chat
and chat history (W3/W4), redaction-log ownership (W5), threshold
re-evaluation (W6), model compare fixes (W8/R7), gap-analysis persistence (W9),
global search (W12), profile edits (W13), export options (W14), model
versions (W15), ``last_analyzed_at`` (W18) and the removed suggested-actions
SSE event (R4). Everything runs offline: LLM, Pinecone and extraction are mocked.
"""

from __future__ import annotations

import io
import json
import uuid
from datetime import datetime, timedelta
from typing import Any, AsyncIterator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.api.documents import build_upload_notification
from app.db.database import Base, get_db
from app.main import app
from app.middleware.rate_limiter import get_rate_limiter
from app.models.audit import Model, ModelStatusEnum, ModelTypeEnum, ModelVersion
from app.models.chat import ChatMessage, ChatRoleEnum, ChatSession
from app.models.document import Document, DocumentStatus
from app.models.system import Notification, NotificationTypeEnum, RegulatoryStandard
from app.models.user import RoleEnum, Tenant, User
from app.schemas.retrieval import Citation, RetrievalResult
from app.services.document_extractor import DocumentExtractor
from app.services.privacy.registry_store import clear_registry, get_registry
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

TENANT_ID = uuid.uuid4()
OTHER_TENANT_ID = uuid.uuid4()
USER_ID = uuid.uuid4()
PEER_USER_ID = uuid.uuid4()  # same tenant, different user
OUTSIDER_ID = uuid.uuid4()  # different tenant

BASE_TIME = datetime(2026, 1, 1, 12, 0, 0)


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
        session.add_all(
            [
                Tenant(id=TENANT_ID, name="Wiring Bank"),
                Tenant(id=OTHER_TENANT_ID, name="Other Bank"),
            ]
        )
        await session.flush()
        session.add_all(
            [
                User(
                    id=USER_ID,
                    email="owner@wiring.test",
                    hashed_password="pw",
                    tenant_id=TENANT_ID,
                    role=RoleEnum.ANALYST,
                    security_clearance="Level 2",
                ),
                User(
                    id=PEER_USER_ID,
                    email="peer@wiring.test",
                    hashed_password="pw",
                    tenant_id=TENANT_ID,
                    role=RoleEnum.ANALYST,
                ),
                User(
                    id=OUTSIDER_ID,
                    email="outsider@other.test",
                    hashed_password="pw",
                    tenant_id=OTHER_TENANT_ID,
                    role=RoleEnum.ANALYST,
                ),
            ]
        )
        await session.commit()
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(get_rate_limiter, None)


def _headers(user_id: uuid.UUID, tenant_id: uuid.UUID = TENANT_ID) -> dict[str, str]:
    token = create_access_token(user_id=user_id, tenant_id=tenant_id, role="ANALYST")
    return {"Authorization": f"Bearer {token}"}


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _metric(value: float, unit: str) -> dict[str, Any]:
    return {"value": value, "unit": unit, "raw_text": f"{value}{unit}", "context": "table"}


async def _seed_model(
    *,
    tenant_id: uuid.UUID = TENANT_ID,
    user_id: uuid.UUID = USER_ID,
    name: str = "Retail PD",
    metrics: dict[str, Any] | None = None,
    status: ModelStatusEnum | None = None,
    description: str | None = None,
) -> tuple[uuid.UUID, uuid.UUID]:
    """Create a model with a single current version; returns (model_id, version_id)."""
    model_id = uuid.uuid4()
    version_id = uuid.uuid4()
    async with TestingSessionLocal() as session:
        session.add(
            Model(
                id=model_id,
                tenant_id=tenant_id,
                user_id=user_id,
                name=name,
                type=ModelTypeEnum.PD,
                description=description,
                status=status,
            )
        )
        await session.flush()
        session.add(
            ModelVersion(
                id=version_id,
                model_id=model_id,
                version="1.0",
                is_current=True,
                metrics=metrics,
                created_at=BASE_TIME,
            )
        )
        await session.commit()
    return model_id, version_id


async def _seed_document(
    *,
    version_id: uuid.UUID | None,
    tenant_id: uuid.UUID = TENANT_ID,
    user_id: uuid.UUID = USER_ID,
    filename: str = "validation_report.pdf",
    status: DocumentStatus = DocumentStatus.READY,
    upload_time: datetime = BASE_TIME,
    raw_markdown: str = "content",
) -> uuid.UUID:
    doc_id = uuid.uuid4()
    async with TestingSessionLocal() as session:
        session.add(
            Document(
                id=doc_id,
                tenant_id=tenant_id,
                user_id=user_id,
                model_version_id=version_id,
                filename=filename,
                file_type="pdf",
                raw_markdown=raw_markdown,
                status=status,
                upload_time=upload_time,
            )
        )
        await session.commit()
    return doc_id


async def _seed_chat(
    *,
    user_id: uuid.UUID = USER_ID,
    tenant_id: uuid.UUID = TENANT_ID,
    version_id: uuid.UUID | None = None,
    created_at: datetime = BASE_TIME,
    messages: list[tuple[ChatRoleEnum, str, list[dict[str, Any]] | None]] | None = None,
) -> uuid.UUID:
    session_id = uuid.uuid4()
    async with TestingSessionLocal() as session:
        session.add(
            ChatSession(
                id=session_id,
                tenant_id=tenant_id,
                user_id=user_id,
                model_version_id=version_id,
                created_at=created_at,
            )
        )
        await session.flush()
        for offset, (role, content, sources) in enumerate(messages or []):
            session.add(
                ChatMessage(
                    session_id=session_id,
                    role=role,
                    content=content,
                    sources_json=sources,
                    created_at=created_at + timedelta(seconds=offset + 1),
                )
            )
        await session.commit()
    return session_id


SAMPLE_SOURCES = [
    {
        "source": "CBUAE MMS",
        "section": "4.2",
        "text": "Discriminatory power shall be monitored.",
        "score": 0.91,
        "retrieval_method": "hybrid",
    }
]


# --------------------------------------------------------------------------
# W1 — notifications
# --------------------------------------------------------------------------


def test_build_upload_notification_mirrors_policy_outcome() -> None:
    model_id = uuid.uuid4()
    notification = build_upload_notification(
        tenant_id=TENANT_ID,
        user_id=USER_ID,
        model_id=model_id,
        model_name="Retail PD",
        filename="report.pdf",
        status_counts={"BREACH": 1, "WARNING": 0, "PASS": 2},
        computed_status=ModelStatusEnum.BREACH,
    )
    assert notification.type == NotificationTypeEnum.BREACH
    assert notification.title == "Retail PD: BREACH"
    assert notification.description == "report.pdf: 1 breach / 0 warning / 2 pass"
    assert notification.model_id == model_id
    assert notification.user_id == USER_ID
    assert notification.tenant_id == TENANT_ID


@pytest.mark.asyncio
async def test_upload_creates_status_notification() -> None:
    model_id, version_id = await _seed_model(name="Retail Scorecard")
    content = (
        "# Retail Credit Scorecard Report\n\n"
        "The model demonstrated strong discriminatory power with Gini coefficient of 48.5% "
        "and KS statistic of 36.2%.\n"
        "The Population Stability Index (PSI) was evaluated at 0.06 over the historical window.\n"
    )

    with patch.object(DocumentExtractor, "extract_to_markdown", new_callable=AsyncMock) as extract, \
         patch.object(PineconeStore, "aupsert_chunks", new_callable=AsyncMock), \
         patch("app.api.documents.LLMRouter") as router_cls:
        extract.return_value = content
        router = MagicMock()
        router.embed = AsyncMock(return_value=[[0.1] * 1024])
        router.aclose = AsyncMock()
        router_cls.return_value = router

        async with _client() as client:
            response = await client.post(
                "/documents/upload",
                files={"file": ("scorecard.pdf", io.BytesIO(content.encode()), "application/pdf")},
                data={"model_version_id": str(version_id)},
                headers=_headers(USER_ID),
            )
            assert response.status_code == 200, response.text

            notes = await client.get("/notifications", headers=_headers(USER_ID))
            peer_notes = await client.get("/notifications", headers=_headers(PEER_USER_ID))

    assert notes.status_code == 200
    body = notes.json()
    assert len(body) == 1
    assert body[0]["type"] == "PASS"
    assert body[0]["title"] == "Retail Scorecard: PASS"
    assert body[0]["description"].startswith("scorecard.pdf: 0 breach / 0 warning / ")
    assert body[0]["model_id"] == str(model_id)
    assert body[0]["is_read"] is False
    # Notifications are addressed to the uploader only.
    assert peer_notes.json() == []


@pytest.mark.asyncio
async def test_upload_failure_creates_info_notification() -> None:
    model_id, version_id = await _seed_model(name="Broken Model")

    with patch.object(DocumentExtractor, "extract_to_markdown", new_callable=AsyncMock) as extract:
        extract.side_effect = RuntimeError("docling exploded")
        async with _client() as client:
            response = await client.post(
                "/documents/upload",
                files={"file": ("broken.pdf", io.BytesIO(b"%PDF-1.4 junk"), "application/pdf")},
                data={"model_version_id": str(version_id)},
                headers=_headers(USER_ID),
            )
            assert response.status_code == 500

            notes = (await client.get("/notifications", headers=_headers(USER_ID))).json()

    assert len(notes) == 1
    assert notes[0]["type"] == "INFO"
    assert notes[0]["title"] == "Broken Model: processing failed"
    assert notes[0]["description"] == "broken.pdf: document processing failed"
    assert notes[0]["model_id"] == str(model_id)

    async with TestingSessionLocal() as session:
        docs = (await session.execute(select(Document))).scalars().all()
    assert [d.status for d in docs] == [DocumentStatus.ERROR]


# --------------------------------------------------------------------------
# W2 — dashboard ai_reviews
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dashboard_counts_assistant_messages_in_tenant() -> None:
    await _seed_chat(
        messages=[
            (ChatRoleEnum.USER, "q1", None),
            (ChatRoleEnum.ASSISTANT, "a1", SAMPLE_SOURCES),
            (ChatRoleEnum.USER, "q2", None),
            (ChatRoleEnum.ASSISTANT, "a2", []),
        ]
    )
    await _seed_chat(user_id=PEER_USER_ID, messages=[(ChatRoleEnum.ASSISTANT, "peer answer", None)])
    await _seed_chat(
        user_id=OUTSIDER_ID,
        tenant_id=OTHER_TENANT_ID,
        messages=[(ChatRoleEnum.ASSISTANT, "other tenant", None)],
    )

    async with _client() as client:
        response = await client.get("/dashboard/metrics", headers=_headers(USER_ID))
        empty = await client.get("/dashboard/metrics", headers=_headers(OUTSIDER_ID, OTHER_TENANT_ID))

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"active_models", "documents_analyzed", "compliance_issues", "ai_reviews"}
    assert body["ai_reviews"] == 3  # tenant-wide: 2 (owner) + 1 (peer); user turns excluded
    assert empty.json()["ai_reviews"] == 1


# --------------------------------------------------------------------------
# W3 / R4 — model-scoped /query
# --------------------------------------------------------------------------


def _mock_llm_router() -> MagicMock:
    async def _stream(prompt: str, system_prompt: str) -> AsyncIterator[str]:
        for token in ("The Gini ", "is monitored."):
            yield token

    router = MagicMock()
    router.generate_stream = _stream
    router.aclose = AsyncMock()
    return router


def _parse_sse(text: str) -> list[dict[str, Any]]:
    return [
        json.loads(line[len("data: "):])
        for line in text.splitlines()
        if line.startswith("data: ")
    ]


def _query_patches(retrieve: AsyncMock):
    """Patch the heavy /query collaborators; returns a context manager stack."""
    masking = MagicMock()
    masking.mask_document.side_effect = lambda text, registry=None: (text, registry)
    retriever = MagicMock()
    retriever.retrieve = retrieve
    return (
        patch("app.api.query.HybridRetriever", return_value=retriever),
        patch("app.api.query.PineconeStore"),
        patch("app.api.query.LLMRouter", return_value=_mock_llm_router()),
        patch("app.api.query.MaskingPipeline", return_value=masking),
        patch("app.api.query.EgressValidator"),
        patch("app.api.query.async_session_maker", TestingSessionLocal),
    )


@pytest.mark.asyncio
async def test_query_scoped_to_model_version_uses_latest_ready_document() -> None:
    _, version_id = await _seed_model()
    await _seed_document(version_id=version_id, upload_time=BASE_TIME)
    latest_ready = await _seed_document(version_id=version_id, upload_time=BASE_TIME + timedelta(hours=1))
    await _seed_document(
        version_id=version_id,
        status=DocumentStatus.ERROR,
        upload_time=BASE_TIME + timedelta(hours=2),
    )

    retrieve = AsyncMock(
        return_value=RetrievalResult(
            citations=[Citation(**SAMPLE_SOURCES[0])],
            latency_ms=1.0,
            retrieval_metadata={},
        )
    )
    p1, p2, p3, p4, p5, p6 = _query_patches(retrieve)
    with p1, p2, p3, p4, p5, p6:
        async with _client() as client:
            response = await client.post(
                "/query",
                json={
                    "question": "What is the Gini coefficient of the PD model?",
                    "model_version_id": str(version_id),
                },
                headers=_headers(USER_ID),
            )

    assert response.status_code == 200
    events = _parse_sse(response.text)
    types = [e["type"] for e in events]
    assert "suggestedActions" not in types
    assert types[0] == "session_id"
    assert "citations" in types and types[-1] == "done"

    assert retrieve.await_args.kwargs["document_id"] == latest_ready

    session_id = uuid.UUID(events[0]["content"])
    async with TestingSessionLocal() as session:
        chat_session = (
            await session.execute(select(ChatSession).where(ChatSession.id == session_id))
        ).scalar_one()
        messages = (
            await session.execute(
                select(ChatMessage)
                .where(ChatMessage.session_id == session_id)
                .order_by(ChatMessage.created_at)
            )
        ).scalars().all()
    assert chat_session.model_version_id == version_id
    assert chat_session.user_id == USER_ID
    assert [m.role for m in messages] == [ChatRoleEnum.USER, ChatRoleEnum.ASSISTANT]
    assert messages[1].content == "The Gini is monitored."
    assert messages[1].sources_json == SAMPLE_SOURCES


@pytest.mark.asyncio
async def test_query_model_version_without_documents_falls_back_to_regulatory_corpus() -> None:
    _, version_id = await _seed_model()
    retrieve = AsyncMock(return_value=RetrievalResult(citations=[], latency_ms=1.0, retrieval_metadata={}))
    p1, p2, p3, p4, p5, p6 = _query_patches(retrieve)
    with p1, p2, p3, p4, p5, p6:
        async with _client() as client:
            response = await client.post(
                "/query",
                json={"question": "What does the MMS require for PSI?", "model_version_id": str(version_id)},
                headers=_headers(USER_ID),
            )

    assert response.status_code == 200
    assert retrieve.await_args.kwargs["document_id"] is None


@pytest.mark.asyncio
async def test_query_rejects_foreign_model_version_and_foreign_session() -> None:
    _, foreign_version = await _seed_model(tenant_id=OTHER_TENANT_ID, user_id=OUTSIDER_ID)
    peer_session = await _seed_chat(user_id=PEER_USER_ID)

    async with _client() as client:
        foreign = await client.post(
            "/query",
            json={"question": "What is the Gini?", "model_version_id": str(foreign_version)},
            headers=_headers(USER_ID),
        )
        hijack = await client.post(
            "/query",
            json={"question": "What is the Gini?", "session_id": str(peer_session)},
            headers=_headers(USER_ID),
        )

    assert foreign.status_code == 404
    assert hijack.status_code == 404
    async with TestingSessionLocal() as session:
        peer_messages = (
            await session.execute(select(ChatMessage).where(ChatMessage.session_id == peer_session))
        ).scalars().all()
    assert peer_messages == []


# --------------------------------------------------------------------------
# W4 — chat history
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_sessions_returns_only_callers_sessions_newest_first() -> None:
    _, version_id = await _seed_model()
    long_answer = "A" * 400
    older = await _seed_chat(
        version_id=version_id,
        created_at=BASE_TIME,
        messages=[(ChatRoleEnum.USER, "q", None), (ChatRoleEnum.ASSISTANT, long_answer, SAMPLE_SOURCES)],
    )
    newer = await _seed_chat(version_id=None, created_at=BASE_TIME + timedelta(days=1))
    await _seed_chat(user_id=PEER_USER_ID, version_id=version_id)

    async with _client() as client:
        all_sessions = await client.get("/query/sessions", headers=_headers(USER_ID))
        scoped = await client.get(
            "/query/sessions",
            params={"model_version_id": str(version_id)},
            headers=_headers(USER_ID),
        )

    assert all_sessions.status_code == 200
    body = all_sessions.json()
    assert [s["id"] for s in body] == [str(newer), str(older)]
    assert set(body[0]) == {"id", "model_version_id", "created_at", "message_count", "last_message_preview"}
    assert body[0]["message_count"] == 0
    assert body[0]["last_message_preview"] is None
    assert body[0]["model_version_id"] is None
    assert body[1]["message_count"] == 2
    assert body[1]["last_message_preview"] == long_answer[:160]

    assert [s["id"] for s in scoped.json()] == [str(older)]


@pytest.mark.asyncio
async def test_session_messages_ownership_and_order() -> None:
    session_id = await _seed_chat(
        messages=[
            (ChatRoleEnum.USER, "What is the PSI?", None),
            (ChatRoleEnum.ASSISTANT, "PSI is 0.06.", SAMPLE_SOURCES),
        ]
    )

    async with _client() as client:
        own = await client.get(f"/query/sessions/{session_id}/messages", headers=_headers(USER_ID))
        peer = await client.get(f"/query/sessions/{session_id}/messages", headers=_headers(PEER_USER_ID))
        outsider = await client.get(
            f"/query/sessions/{session_id}/messages",
            headers=_headers(OUTSIDER_ID, OTHER_TENANT_ID),
        )
        missing = await client.get(f"/query/sessions/{uuid.uuid4()}/messages", headers=_headers(USER_ID))

    assert own.status_code == 200
    messages = own.json()
    assert [m["role"] for m in messages] == ["user", "assistant"]
    assert messages[0]["content"] == "What is the PSI?"
    assert messages[0]["sources_json"] is None
    assert messages[1]["sources_json"] == SAMPLE_SOURCES
    assert set(messages[1]) == {"id", "role", "content", "sources_json", "created_at"}

    assert peer.status_code == 404
    assert outsider.status_code == 404
    assert missing.status_code == 404


# --------------------------------------------------------------------------
# W5 — redaction log ownership
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_redactions_only_served_to_session_owner() -> None:
    session_id = await _seed_chat()
    get_registry(session_id).mask("Emirates NBD", "BANK")
    try:
        async with _client() as client:
            own = await client.get(
                "/privacy/redactions", params={"session_id": str(session_id)}, headers=_headers(USER_ID)
            )
            peer = await client.get(
                "/privacy/redactions", params={"session_id": str(session_id)}, headers=_headers(PEER_USER_ID)
            )
            unknown = await client.get(
                "/privacy/redactions", params={"session_id": str(uuid.uuid4())}, headers=_headers(USER_ID)
            )
            peer_mask = await client.post(
                "/privacy/mask",
                json={"text": "anything", "session_id": str(session_id)},
                headers=_headers(PEER_USER_ID),
            )
    finally:
        clear_registry(session_id)

    assert own.status_code == 200
    assert own.json()["session_id"] == str(session_id)
    assert "Emirates NBD" in own.json()["redactions"]
    assert peer.status_code == 404
    assert unknown.status_code == 404
    assert peer_mask.status_code == 404


# --------------------------------------------------------------------------
# W6 — settings re-evaluate model status
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_settings_update_reevaluates_current_versions() -> None:
    gini_model, gini_version = await _seed_model(name="Gini 44", metrics={"gini": _metric(44.0, "%")})
    psi_model, _ = await _seed_model(name="PSI 0.15", metrics={"psi": _metric(0.15, "absolute")})
    pending_model, _ = await _seed_model(name="No metrics", status=ModelStatusEnum.BREACH)
    foreign_model, _ = await _seed_model(
        tenant_id=OTHER_TENANT_ID,
        user_id=OUTSIDER_ID,
        name="Foreign",
        metrics={"gini": _metric(44.0, "%")},
    )

    async def statuses() -> dict[uuid.UUID, ModelStatusEnum | None]:
        async with TestingSessionLocal() as session:
            rows = (await session.execute(select(Model.id, Model.status))).all()
        return {model_id: status for model_id, status in rows}

    async with _client() as client:
        # Default tolerance 0.05 -> warning band 40%..45% -> Gini 44% is WARNING.
        first = await client.put("/settings", json={"gini_tolerance": 0.05}, headers=_headers(USER_ID))
        assert first.status_code == 200
        assert first.json()["psi_breach_threshold"] == 0.25
        after_first = await statuses()
        assert after_first[gini_model] == ModelStatusEnum.WARNING
        assert after_first[psi_model] == ModelStatusEnum.WARNING  # 0.10 <= 0.15 <= 0.25
        assert after_first[pending_model] == ModelStatusEnum.BREACH  # untouched
        assert after_first[foreign_model] is None  # other tenant untouched

        # Narrow the Gini band and tighten PSI.
        second = await client.put(
            "/settings",
            json={"gini_tolerance": 0.02, "psi_breach_threshold": 0.12},
            headers=_headers(USER_ID),
        )
        assert second.status_code == 200
        assert second.json()["gini_tolerance"] == 0.02

    after_second = await statuses()
    assert after_second[gini_model] == ModelStatusEnum.PASS
    assert after_second[psi_model] == ModelStatusEnum.BREACH
    assert after_second[foreign_model] is None

    async with TestingSessionLocal() as session:
        version = (
            await session.execute(select(ModelVersion).where(ModelVersion.id == gini_version))
        ).scalar_one()
    results = version.gap_analysis["results"]
    assert [(r["metric_name"], r["status"]) for r in results] == [("Gini Coefficient", "PASS")]


# --------------------------------------------------------------------------
# W8 / R7 — model compare
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_compare_shows_baseline_values_and_normalised_percentages() -> None:
    baseline_id, _ = await _seed_model(
        name="Baseline",
        metrics={
            "gini": _metric(0.42, "absolute"),
            "ks": _metric(0.35, "absolute"),
            "auc": _metric(0.78, "absolute"),
        },
    )
    challenger_id, _ = await _seed_model(
        name="Challenger",
        metrics={
            "gini": _metric(48.5, "%"),
            "ks": _metric(35.0, "%"),
            "auc": _metric(81.0, "%"),
        },
    )

    async with _client() as client:
        response = await client.post(
            "/models/compare",
            json={"model_id_a": str(baseline_id), "model_id_b": str(challenger_id)},
            headers=_headers(USER_ID),
        )

    assert response.status_code == 200
    body = response.json()
    baseline = {m["name"]: m for m in body["baseline"]["metrics"]}
    challenger = {m["name"]: m for m in body["challenger"]["metrics"]}

    assert baseline["Gini Coefficient"]["value"] == "42%"
    assert baseline["KS Statistic"]["value"] == "35%"
    assert baseline["AUC"]["value"] == "0.78"
    assert baseline["PSI"]["value"] == ""
    assert all(m["is_diff"] is False and m["old_value"] is None for m in baseline.values())

    assert challenger["Gini Coefficient"] == {
        "name": "Gini Coefficient",
        "value": "48.5%",
        "old_value": "42%",
        "new_value": "48.5%",
        "is_diff": True,
    }
    assert challenger["KS Statistic"]["is_diff"] is False  # 0.35 absolute == 35%
    assert challenger["AUC"]["value"] == "0.81"
    assert challenger["AUC"]["is_diff"] is True
    assert challenger["PSI"] == {
        "name": "PSI",
        "value": "",
        "old_value": None,
        "new_value": None,
        "is_diff": False,
    }

    assert body["baseline"]["data_config"] == ""
    assert body["challenger"]["data_config"] == ""


# --------------------------------------------------------------------------
# W9 — gap analysis persisted on the document
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_gap_analysis_persisted_into_document_metadata() -> None:
    _, version_id = await _seed_model()
    doc_id = await _seed_document(version_id=version_id)
    async with TestingSessionLocal() as session:
        doc = (await session.execute(select(Document).where(Document.id == doc_id))).scalar_one()
        doc.metadata_json = {"profile": {"gini": None}}
        await session.commit()

    payload = {
        "gaps": [
            {
                "requirement": "Population Stability Index (PSI)",
                "status": "PASS",
                "description": "The document reports PSI: 0.05, within the 0.25 threshold.",
                "recommendation": "No action required.",
            }
        ],
        "coverage_score": 0.9,
    }
    with patch("app.api.gap_analysis.LLMRouter.generate", new_callable=AsyncMock) as generate, patch(
        "app.api.gap_analysis.LLMRouter.aclose", new_callable=AsyncMock
    ):
        generate.return_value = json.dumps(payload)
        async with _client() as client:
            response = await client.post(
                "/gap-analysis", json={"document_id": str(doc_id)}, headers=_headers(USER_ID)
            )
            detail = await client.get(f"/documents/{doc_id}", headers=_headers(USER_ID))

    assert response.status_code == 200
    summary = detail.json()["metrics_summary"]
    assert summary["llm_gap_analysis"] == payload
    assert summary["profile"] == {"gini": None}  # existing metadata preserved


# --------------------------------------------------------------------------
# W12 — global search
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_returns_models_standards_and_documents() -> None:
    model_id, version_id = await _seed_model(name="Retail Scorecard", description="Behavioural PD")
    doc_id = await _seed_document(version_id=version_id, filename="retail_scorecard_v2.pdf")
    await _seed_document(
        version_id=None,
        tenant_id=OTHER_TENANT_ID,
        user_id=OUTSIDER_ID,
        filename="retail_scorecard_foreign.pdf",
    )
    async with TestingSessionLocal() as session:
        session.add(
            RegulatoryStandard(
                code="MMS-2022",
                title="Model Management Standards",
                authority="CBUAE",
                jurisdiction="UAE",
                clauses_json=[],
                description="Supervisory expectations for model risk.",
            )
        )
        await session.commit()

    async with _client() as client:
        by_code = await client.get("/search", params={"q": "mms-2022"}, headers=_headers(USER_ID))
        by_description = await client.get("/search", params={"q": "model risk"}, headers=_headers(USER_ID))
        by_filename = await client.get("/search", params={"q": "scorecard_v2"}, headers=_headers(USER_ID))
        wildcard = await client.get("/search", params={"q": "retail%foreign"}, headers=_headers(USER_ID))

    standards = by_code.json()["results"]
    assert [(r["type"], r["title"], r["description"], r["model_id"]) for r in standards] == [
        ("regulatory_standard", "Model Management Standards", "MMS-2022", None)
    ]
    assert [r["type"] for r in by_description.json()["results"]] == ["regulatory_standard"]

    hits = by_filename.json()["results"]
    assert hits == [
        {
            "id": str(doc_id),
            "type": "document",
            "title": "retail_scorecard_v2.pdf",
            "description": "Document",
            "model_id": str(model_id),
        }
    ]
    # LIKE wildcards in the query are matched literally and never cross tenants.
    assert wildcard.json()["results"] == []

    async with _client() as client:
        models = await client.get("/search", params={"q": "retail"}, headers=_headers(USER_ID))
    model_hits = [r for r in models.json()["results"] if r["type"] == "model"]
    assert model_hits == [
        {
            "id": str(model_id),
            "type": "model",
            "title": "Retail Scorecard",
            "description": "Behavioural PD",
            "model_id": str(model_id),
        }
    ]
    assert all("foreign" not in r["title"] for r in models.json()["results"])


# --------------------------------------------------------------------------
# W13 — PATCH /users/me
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_patch_profile_updates_only_editable_fields() -> None:
    async with _client() as client:
        first = await client.patch(
            "/users/me",
            json={
                "full_name": "  Jane Doe  ",
                "title": "Model Validator",
                "role": "ADMIN",
                "security_clearance": "TOP SECRET",
            },
            headers=_headers(USER_ID),
        )
        second = await client.patch("/users/me", json={"division": "Model Risk"}, headers=_headers(USER_ID))
        cleared = await client.patch("/users/me", json={"title": None}, headers=_headers(USER_ID))
        too_long = await client.patch("/users/me", json={"full_name": "x" * 121}, headers=_headers(USER_ID))
        profile = await client.get("/users/me", headers=_headers(USER_ID))

    assert first.status_code == 200
    assert first.json()["full_name"] == "Jane Doe"
    assert first.json()["title"] == "Model Validator"
    assert first.json()["role"] == "ANALYST"
    assert first.json()["security_clearance"] == "Level 2"

    assert second.status_code == 200
    assert second.json()["full_name"] == "Jane Doe"
    assert second.json()["division"] == "Model Risk"

    assert cleared.json()["title"] is None
    assert too_long.status_code == 422

    body = profile.json()
    assert (body["full_name"], body["title"], body["division"]) == ("Jane Doe", None, "Model Risk")
    assert set(body) == set(first.json())


# --------------------------------------------------------------------------
# W14 — export options
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_export_data_optional_sections() -> None:
    model_id, version_id = await _seed_model()
    doc_id = await _seed_document(version_id=version_id, filename="annual_validation.pdf")
    await _seed_document(version_id=None, filename="unrelated.pdf")
    own_session = await _seed_chat(
        version_id=version_id,
        messages=[
            (ChatRoleEnum.USER, "question", None),
            (ChatRoleEnum.ASSISTANT, "answer", SAMPLE_SOURCES),
        ],
    )
    await _seed_chat(
        user_id=PEER_USER_ID,
        version_id=version_id,
        messages=[(ChatRoleEnum.ASSISTANT, "peer answer", SAMPLE_SOURCES)],
    )

    async with _client() as client:
        plain = await client.get(f"/models/{model_id}/export-data", headers=_headers(USER_ID))
        full = await client.get(
            f"/models/{model_id}/export-data",
            params={"include_citations": "true", "include_audit_trail": "true"},
            headers=_headers(USER_ID),
        )

    assert plain.status_code == 200
    assert plain.json()["documents"] is None
    assert plain.json()["chat_citations"] is None
    assert plain.json()["model_info"]["id"] == str(model_id)
    assert len(plain.json()["history"]) == 1

    body = full.json()
    assert [d["id"] for d in body["documents"]] == [str(doc_id)]
    assert set(body["documents"][0]) == {"id", "filename", "file_type", "upload_time", "status", "model_version_id"}
    assert body["documents"][0]["status"] == "READY"
    assert body["documents"][0]["model_version_id"] == str(version_id)

    citations = body["chat_citations"]
    assert len(citations) == 1  # only the caller's own assistant answer
    assert citations[0]["session_id"] == str(own_session)
    assert set(citations[0]) == {"session_id", "message_id", "created_at", "sources"}
    assert citations[0]["sources"] == SAMPLE_SOURCES


# --------------------------------------------------------------------------
# W15 — model versions
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_model_version_lifecycle() -> None:
    model_id, first_version = await _seed_model(
        metrics={"gini": _metric(44.0, "%")}, status=ModelStatusEnum.WARNING
    )
    foreign_model, _ = await _seed_model(tenant_id=OTHER_TENANT_ID, user_id=OUTSIDER_ID)

    async with _client() as client:
        created = await client.post(
            f"/models/{model_id}/versions", json={"version": "2.0"}, headers=_headers(USER_ID)
        )
        duplicate = await client.post(
            f"/models/{model_id}/versions", json={"version": " 2.0 "}, headers=_headers(USER_ID)
        )
        blank = await client.post(f"/models/{model_id}/versions", json={"version": "  "}, headers=_headers(USER_ID))
        too_long = await client.post(
            f"/models/{model_id}/versions", json={"version": "v" * 33}, headers=_headers(USER_ID)
        )
        foreign = await client.post(
            f"/models/{foreign_model}/versions", json={"version": "9.9"}, headers=_headers(USER_ID)
        )
        lineage = await client.get(f"/models/{model_id}/versions", headers=_headers(USER_ID))
        summary = await client.get(f"/models/{model_id}", headers=_headers(USER_ID))

    assert created.status_code == 201
    body = created.json()
    assert set(body) == {
        "id",
        "model_id",
        "version",
        "is_current",
        "parent_version_id",
        "metrics",
        "gap_analysis",
        "population_deciles",
        "created_at",
    }
    assert body["model_id"] == str(model_id)
    assert body["version"] == "2.0"
    assert body["is_current"] is True
    assert body["parent_version_id"] == str(first_version)
    assert body["metrics"] is None and body["gap_analysis"] is None and body["population_deciles"] is None

    assert duplicate.status_code == 409
    assert blank.status_code == 422
    assert too_long.status_code == 422
    assert foreign.status_code == 404

    flags = {v["id"]: v["is_current"] for v in lineage.json()}
    assert flags == {body["id"]: True, str(first_version): False}

    assert summary.json()["current_version"]["id"] == body["id"]
    assert summary.json()["status"] is None  # new version awaits analysis


# --------------------------------------------------------------------------
# W18 — last_analyzed_at
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_last_analyzed_at_uses_ready_documents_of_current_version() -> None:
    model_id, current_version = await _seed_model()
    old_version = uuid.uuid4()
    async with TestingSessionLocal() as session:
        session.add(
            ModelVersion(id=old_version, model_id=model_id, version="0.9", is_current=False)
        )
        await session.commit()
    idle_model, _ = await _seed_model(name="Never analysed")

    expected = BASE_TIME + timedelta(days=2)
    await _seed_document(version_id=current_version, upload_time=BASE_TIME + timedelta(days=1))
    await _seed_document(version_id=current_version, upload_time=expected)
    await _seed_document(
        version_id=current_version,
        status=DocumentStatus.ERROR,
        upload_time=BASE_TIME + timedelta(days=3),
    )
    await _seed_document(version_id=old_version, upload_time=BASE_TIME + timedelta(days=4))

    async with _client() as client:
        listing = await client.get("/models", headers=_headers(USER_ID))
        detail = await client.get(f"/models/{model_id}", headers=_headers(USER_ID))

    by_id = {m["id"]: m for m in listing.json()}
    assert datetime.fromisoformat(by_id[str(model_id)]["last_analyzed_at"]) == expected
    assert by_id[str(idle_model)]["last_analyzed_at"] is None
    assert datetime.fromisoformat(detail.json()["last_analyzed_at"]) == expected


# --------------------------------------------------------------------------
# Notification ORM sanity (type attribute maps to notification_type column)
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_notifications_are_persisted_with_type_column() -> None:
    model_id, _ = await _seed_model()
    async with TestingSessionLocal() as session:
        session.add(
            build_upload_notification(
                tenant_id=TENANT_ID,
                user_id=USER_ID,
                model_id=model_id,
                model_name="Retail PD",
                filename="r.pdf",
                status_counts={"WARNING": 1},
                computed_status=ModelStatusEnum.WARNING,
            )
        )
        await session.commit()
        stored = (await session.execute(select(Notification))).scalar_one()
    assert stored.type == NotificationTypeEnum.WARNING
    assert stored.description == "r.pdf: 0 breach / 1 warning / 0 pass"

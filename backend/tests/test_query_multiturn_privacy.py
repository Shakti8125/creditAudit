"""Multi-turn AI Analyst privacy (QA-004, QA-011, NEW-03): API level, LLM and Pinecone faked.

The audit's failure: the first question about an uploaded document works, the
second one is blocked with 422 because the assistant's first answer cited the
uploaded filename, the masker registered the filename as an entity, and the
filename was still raw in the next prompt. These tests run the real masking
pipeline, egress validator, retriever and chat endpoint; only the providers
(embedding, rerank, generation) and Pinecone are replaced by fakes.
"""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import AsyncIterator
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.api.errors import EGRESS_BLOCKED_DETAIL
from app.db.database import Base, get_db
from app.main import app
from app.middleware.rate_limiter import get_rate_limiter
from app.models.chat import ChatMessage, ChatRoleEnum, ChatSession
from app.models.document import Document, DocumentChunk, DocumentStatus
from app.models.user import RoleEnum, Tenant, User
from app.schemas.retrieval import Citation, RetrievalResult, VectorResult
from app.services.evaluation.prompts import QUERY_SYSTEM_PROMPT
from app.services.privacy import registry_store
from app.services.privacy.session_registry import MAX_SESSION_MESSAGES
from app.utils.security import create_access_token

engine = create_async_engine(
    "sqlite+aiosqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
)
TestingSessionLocal = async_sessionmaker(
    autocommit=False, autoflush=False, bind=engine, class_=AsyncSession, expire_on_commit=False
)

TENANT_ID = uuid.uuid4()
USER_ID = uuid.uuid4()
BASE_TIME = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

# The file name of the audit repro. The masker registers it as an ORG (QA-004).
AUDIT_FILENAME = "qa_synthetic_pd_validation_v1.pdf"
# A file name that contains a bank name from gcc_bank_names.json.
BANK_FILENAME = "Emirates NBD PD Validation v1.pdf"

CHUNKS = [
    ("Discriminatory Power", "The PD model reports a Gini of 64% and an AUC of 0.82 on the out-of-time sample."),
    ("Calibration Results", "The Hosmer-Lemeshow test returned a p-value of 0.31 and the Brier score was 0.04."),
    ("Stability", "The Population Stability Index (PSI) was 0.06 over the monitoring window."),
]


async def override_get_db() -> AsyncIterator[AsyncSession]:
    async with TestingSessionLocal() as session:
        yield session


async def override_get_rate_limiter() -> None:
    return None


@pytest_asyncio.fixture(autouse=True)
async def setup_db(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[None]:
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_rate_limiter] = override_get_rate_limiter
    monkeypatch.setattr("app.services.evaluation.telemetry.async_session_maker", TestingSessionLocal)
    monkeypatch.setattr("app.api.query.async_session_maker", TestingSessionLocal)
    registry_store.clear_all()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with TestingSessionLocal() as session:
        session.add(Tenant(id=TENANT_ID, name="Multiturn Tenant"))
        await session.flush()
        session.add(
            User(
                id=USER_ID,
                email="multiturn@example.test",
                hashed_password="pw",
                tenant_id=TENANT_ID,
                role=RoleEnum.ANALYST,
            )
        )
        await session.commit()
    yield
    registry_store.clear_all()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(get_rate_limiter, None)


def _headers() -> dict[str, str]:
    token = create_access_token(user_id=USER_ID, tenant_id=TENANT_ID, role="ANALYST")
    return {"Authorization": f"Bearer {token}"}


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _seed_document(filename: str = AUDIT_FILENAME) -> uuid.UUID:
    """A READY document whose (already masked) chunks are in the database."""
    doc_id = uuid.uuid4()
    async with TestingSessionLocal() as session:
        session.add(
            Document(
                id=doc_id,
                tenant_id=TENANT_ID,
                user_id=USER_ID,
                filename=filename,
                file_type="pdf",
                raw_markdown="",
                status=DocumentStatus.READY,
                upload_time=BASE_TIME,
            )
        )
        await session.flush()
        for index, (section, text) in enumerate(CHUNKS):
            session.add(DocumentChunk(document_id=doc_id, chunk_index=index, masked_text=f"{section}:\n{text}"))
        await session.commit()
    return doc_id


class ProviderSpy:
    """Fake embedding, rerank and generation providers that record every text sent to them."""

    def __init__(self, answers: list[str], legacy_filename: str | None = None) -> None:
        self.answers = list(answers)
        self.legacy_filename = legacy_filename
        self.sent: list[str] = []  # every text handed to any provider
        self.prompts: list[str] = []  # the generation prompts
        self.system_prompts: list[str] = []

    async def embed(self, texts: list[str], input_type: str = "document") -> list[list[float]]:
        self.sent.extend(texts)
        return [[0.1] * 8 for _ in texts]

    async def rerank(self, query: str, passages: list[str], top_n: int = 5) -> list[Any]:
        self.sent.extend([query, *passages])
        raise RuntimeError("rerank is down: the retriever falls back to the fused order")

    async def stream(self, prompt: str, system_prompt: str | None = None, **kwargs: Any) -> AsyncIterator[str]:
        self.sent.extend([prompt, system_prompt or ""])
        self.prompts.append(prompt)
        self.system_prompts.append(system_prompt or "")
        for part in re.findall(r"\S+\s*", self.answers.pop(0)):
            yield part

    def pinecone_store(self) -> MagicMock:
        """A store whose tenant namespace holds vectors with the OLD metadata (raw filename)."""

        async def query(embedding: list[float], namespace: str, top_k: int = 20) -> list[VectorResult]:
            if not namespace.startswith("user-docs:") or self.legacy_filename is None:
                return []
            return [
                VectorResult(
                    id=f"v{i}",
                    score=0.9 - i / 10,
                    metadata={"text": f"{section}:\n{text}", "source": self.legacy_filename, "section": section},
                )
                for i, (section, text) in enumerate(CHUNKS)
            ]

        store = MagicMock()
        store.query = AsyncMock(side_effect=query)
        return store

    def patches(self) -> list[Any]:
        return [
            patch("app.api.query.LLMRouter.embed", new=self.embed),
            patch("app.api.query.LLMRouter.rerank", new=self.rerank),
            patch("app.api.query.LLMRouter.generate_stream", new=self.stream),
            patch("app.api.query.LLMRouter.aclose", new_callable=AsyncMock),
            patch("app.api.query.PineconeStore", return_value=self.pinecone_store()),
        ]


def _events(text: str) -> list[dict[str, Any]]:
    return [json.loads(line[len("data: "):]) for line in text.splitlines() if line.startswith("data: ")]


async def _ask(
    question: str,
    spy: ProviderSpy,
    document_id: uuid.UUID,
    session_id: str | None = None,
) -> tuple[int, list[dict[str, Any]], str]:
    with ExitStack() as stack:
        for p in spy.patches():
            stack.enter_context(p)
        async with _client() as client:
            body: dict[str, Any] = {"question": question, "document_id": str(document_id)}
            if session_id:
                body["session_id"] = session_id
            response = await client.post("/query", json=body, headers=_headers())
    return response.status_code, (_events(response.text) if response.status_code == 200 else []), response.text


def _session_id(events: list[dict[str, Any]]) -> str:
    return next(e["content"] for e in events if e["type"] == "session_id")


async def _redactions(session_id: str) -> dict[str, str]:
    async with _client() as client:
        response = await client.get("/privacy/redactions", params={"session_id": session_id}, headers=_headers())
    assert response.status_code == 200, response.text
    return response.json()["redactions"]


def _raw_occurrence(entity: str, text: str) -> bool:
    return re.search(rf"(?<!\w){re.escape(entity)}(?!\w)", text) is not None


async def _message_count() -> int:
    async with TestingSessionLocal() as session:
        return (await session.execute(select(func.count(ChatMessage.id)))).scalar_one()


# ---------------------------------------------------------------------------- the audit repro


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("filename", "registered"),
    [(AUDIT_FILENAME, AUDIT_FILENAME), (BANK_FILENAME, "Emirates NBD")],
)
async def test_second_turn_succeeds_when_the_answer_repeats_the_filename(filename: str, registered: str) -> None:
    """Worst case: the model ignores the DOC-1 instruction and cites the uploaded filename.

    Before the fix the second question was blocked with 422. Now the filename is never
    in a prompt, whatever the model writes, and the second turn is answered.
    """
    doc_id = await _seed_document(filename)
    spy = ProviderSpy(
        answers=[
            f"The PD model reports a Gini of 64% [Source: {filename}, Section: Discriminatory Power].",
            "The Hosmer-Lemeshow p-value is 0.31 [Source: DOC-1, Section: Calibration Results].",
        ],
        legacy_filename=filename,  # old vectors still carry the raw filename in Pinecone metadata
    )

    status_1, events_1, _ = await _ask("Extract Metrics", spy, doc_id)
    assert status_1 == 200
    session_id = _session_id(events_1)
    status_2, events_2, body_2 = await _ask("Summarise the calibration results.", spy, doc_id, session_id)

    assert status_2 == 200, body_2
    assert events_2[-1]["type"] == "done"
    assert _session_id(events_2) == session_id

    # The mechanism of QA-004 really happened: the repeated filename (or the bank name in
    # it) was registered as an entity by the masker...
    redactions = await _redactions(session_id)
    assert registered in redactions
    # ...and still no text that went to a provider contains the filename, the document
    # id, or any registered entity.
    everything = "\n".join(spy.sent)
    assert filename not in everything and filename.rsplit(".", 1)[0] not in everything
    assert str(doc_id) not in everything
    for entity in redactions:
        assert not _raw_occurrence(entity, everything), entity

    # Documents are DOC-1 in the prompt, with the instruction to cite it.
    assert len(spy.prompts) == 2
    assert all("Source: DOC-1\n" in prompt for prompt in spy.prompts)
    assert spy.system_prompts == [QUERY_SYSTEM_PROMPT, QUERY_SYSTEM_PROMPT]
    assert "DOC-1" in QUERY_SYSTEM_PROMPT
    # Turn 2 carries the (masked) first exchange.
    assert "Conversation History:" in spy.prompts[1] and "Extract Metrics" in spy.prompts[1]
    assert "Conversation History:" not in spy.prompts[0]

    # The UI gets the alias and the document id (it maps them to the filename itself);
    # the citations never carry the filename.
    citations = next(e["content"] for e in events_2 if e["type"] == "citations")
    assert citations and {c["alias"] for c in citations} == {"DOC-1"}
    assert {c["document_id"] for c in citations} == {str(doc_id)}
    assert {c["source"] for c in citations} == {f"doc-{doc_id}"}
    assert filename not in json.dumps(citations)

    assert await _message_count() == 4


@pytest.mark.asyncio
async def test_compliant_answers_cite_the_alias_over_many_turns() -> None:
    doc_id = await _seed_document()
    spy = ProviderSpy(
        answers=[f"Answer {n} [Source: DOC-1, Section: Discriminatory Power]." for n in range(4)],
        legacy_filename=AUDIT_FILENAME,
    )
    session_id: str | None = None
    for question in ("Extract Metrics", "What is the AUC?", "And the PSI?", "Summarise the calibration results."):
        status, events, body = await _ask(question, spy, doc_id, session_id)
        assert status == 200, body
        session_id = _session_id(events)
    assert AUDIT_FILENAME not in "\n".join(spy.sent)
    assert await _message_count() == 8


# ---------------------------------------------------------------------------- determinism


@pytest.mark.asyncio
async def test_same_input_masks_the_same_way_on_every_turn_and_worker() -> None:
    doc_id = await _seed_document()
    q1 = "Does Emirates NBD meet the minimum Gini for the PD model?"
    q2 = "Does Northwind Credit Bank meet the PSI requirement for the Jane Testperson portfolio?"
    q3 = "And does Emirates NBD meet the PSI limit?"
    spy = ProviderSpy(answers=["Yes [Source: DOC-1, Section: Stability]."] * 3)

    _, events_1, _ = await _ask(q1, spy, doc_id)
    session_id = _session_id(events_1)
    for question in (q2, q3):
        status, _, body = await _ask(question, spy, doc_id, session_id)
        assert status == 200, body

    # The bank keeps its token in every prompt (the registry carries across turns), and
    # no raw entity ever reaches a provider.
    assert all("[BANK_1]" in prompt for prompt in spy.prompts)
    assert spy.prompts[2].endswith("Question: And does [BANK_1] meet the PSI limit?")
    everything = "\n".join(spy.sent)
    for raw in ("Emirates NBD", "Northwind Credit Bank", "Jane Testperson"):
        assert raw not in everything

    # A different worker (empty cache) derives the same map from the persisted messages,
    # and the log is the same on every call (QA-011: 7 of 12 calls were empty).
    first = await _redactions(session_id)
    assert first["Emirates NBD"] == "[BANK_1]"
    assert {"Northwind Credit Bank", "Jane Testperson"} <= set(first)
    for index in range(12):
        if index % 3 == 0:
            registry_store.clear_all()
        assert await _redactions(session_id) == first


# ---------------------------------------------------------------------------- nothing is persisted before the checks pass


def _leaky_result(entity: str, document_id: uuid.UUID) -> RetrievalResult:
    """Retrieval whose tenant-document chunk repeats an entity the question registered."""
    return RetrievalResult(
        citations=[
            Citation(
                source=f"doc-{document_id}",
                document_id=str(document_id),
                section="Findings",
                text=f"{entity} reported a Gini coefficient of 0.45 for the retail PD model.",
                score=2.0,
                retrieval_method="hybrid_rrf_reranked",
            )
        ],
        latency_ms=1.0,
        retrieval_metadata={},
    )


@pytest.mark.asyncio
async def test_blocked_first_turn_leaves_no_session_and_no_message() -> None:
    doc_id = await _seed_document()
    entity = "Emirates NBD"
    with patch(
        "app.api.query.HybridRetriever.retrieve", new_callable=AsyncMock, return_value=_leaky_result(entity, doc_id)
    ), patch("app.api.query.LLMRouter.aclose", new_callable=AsyncMock):
        async with _client() as client:
            response = await client.post(
                "/query",
                json={"question": f"Does {entity} meet the minimum Gini?", "document_id": str(doc_id)},
                headers=_headers(),
            )

    assert response.status_code == 422
    assert response.json() == {"detail": EGRESS_BLOCKED_DETAIL}
    assert entity not in response.text
    async with TestingSessionLocal() as session:
        assert (await session.execute(select(func.count(ChatSession.id)))).scalar_one() == 0
    assert await _message_count() == 0


@pytest.mark.asyncio
async def test_blocked_follow_up_turn_leaves_no_orphan_user_message() -> None:
    doc_id = await _seed_document()
    spy = ProviderSpy(answers=["Fine [Source: DOC-1, Section: Stability]."], legacy_filename=AUDIT_FILENAME)
    status, events, _ = await _ask("Extract Metrics", spy, doc_id)
    assert status == 200
    session_id = _session_id(events)
    assert await _message_count() == 2

    entity = "Emirates NBD"
    with patch(
        "app.api.query.HybridRetriever.retrieve", new_callable=AsyncMock, return_value=_leaky_result(entity, doc_id)
    ), patch("app.api.query.LLMRouter.aclose", new_callable=AsyncMock):
        async with _client() as client:
            response = await client.post(
                "/query",
                json={
                    "question": f"Does {entity} meet the minimum Gini?",
                    "document_id": str(doc_id),
                    "session_id": session_id,
                },
                headers=_headers(),
            )

    assert response.status_code == 422
    assert await _message_count() == 2  # no orphan user message


# ---------------------------------------------------------------------------- public context substitution (defence in depth)


@pytest.mark.asyncio
async def test_registered_entity_in_public_regulatory_text_is_replaced_not_blocked() -> None:
    """A raw registered string inside PUBLIC regulatory text is tokenised; the prompt stays clean."""
    entity = "Emirates NBD"
    captured: list[str] = []

    async def stream(self: Any, prompt: str, system_prompt: str | None = None, **kwargs: Any) -> AsyncIterator[str]:
        captured.append(prompt)
        yield "ok"

    public = RetrievalResult(
        citations=[
            Citation(
                source="CBUAE-MMG-2022",
                section="Section 4",
                text=f"Credit scoring models at {entity} and peers must reach a Gini of at least 0.40.",
                score=1.0,
                retrieval_method="bm25",
            )
        ],
        latency_ms=1.0,
        retrieval_metadata={},
    )
    with patch("app.api.query.HybridRetriever.retrieve", new_callable=AsyncMock, return_value=public), patch(
        "app.api.query.LLMRouter.generate_stream", new=stream
    ), patch("app.api.query.LLMRouter.aclose", new_callable=AsyncMock):
        async with _client() as client:
            response = await client.post(
                "/query", json={"question": f"What Gini must {entity} meet?"}, headers=_headers()
            )

    assert response.status_code == 200, response.text
    assert entity not in captured[0]
    assert "at [BANK_1] and peers" in captured[0]


# ---------------------------------------------------------------------------- conversation length cap


@pytest.mark.asyncio
async def test_a_conversation_at_the_cap_is_refused_and_nothing_is_persisted() -> None:
    doc_id = await _seed_document()
    session_id = uuid.uuid4()
    async with TestingSessionLocal() as session:
        session.add(ChatSession(id=session_id, tenant_id=TENANT_ID, user_id=USER_ID, created_at=BASE_TIME))
        await session.flush()
        for index in range(MAX_SESSION_MESSAGES):
            session.add(
                ChatMessage(
                    session_id=session_id,
                    role=ChatRoleEnum.USER if index % 2 == 0 else ChatRoleEnum.ASSISTANT,
                    content=f"message {index}",
                    created_at=BASE_TIME + timedelta(seconds=index),
                )
            )
        await session.commit()

    spy = ProviderSpy(answers=["never used"])
    status, _, body = await _ask("One more question?", spy, doc_id, str(session_id))

    assert status == 409
    assert "Start a new conversation" in body
    assert spy.sent == []
    assert await _message_count() == MAX_SESSION_MESSAGES

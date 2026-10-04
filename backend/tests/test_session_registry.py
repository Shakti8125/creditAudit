"""Deterministic, derived session registry (QA-011, QA-004 item 3).

The registry of a chat session is never stored: it is rebuilt by masking the
session's persisted messages in chronological order. Different workers (empty
caches) must therefore derive exactly the same tokens.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.db.database import Base, get_db
from app.main import app
from app.middleware.rate_limiter import get_rate_limiter
from app.models.chat import ChatMessage, ChatRoleEnum, ChatSession
from app.models.user import RoleEnum, Tenant, User
from app.services.privacy import registry_store
from app.services.privacy.masking_pipeline import MaskingPipeline
from app.services.privacy.ner_masker import EntitySpan
from app.services.privacy.session_registry import (
    MAX_SESSION_MESSAGES,
    SessionMessage,
    build_session_state,
    load_session_messages,
)
from app.utils.security import create_access_token

engine = create_async_engine(
    "sqlite+aiosqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
)
TestingSessionLocal = async_sessionmaker(
    autocommit=False, autoflush=False, bind=engine, class_=AsyncSession, expire_on_commit=False
)

TENANT_ID = uuid.uuid4()
OTHER_TENANT_ID = uuid.uuid4()
USER_ID = uuid.uuid4()
OTHER_USER_ID = uuid.uuid4()
BASE_TIME = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

CONVERSATION = [
    (ChatRoleEnum.USER, "Does Emirates NBD meet the minimum Gini for the PD model?"),
    (ChatRoleEnum.ASSISTANT, "Yes, the Gini is 64% [Source: DOC-1, Section: Discriminatory Power]."),
    (ChatRoleEnum.USER, "Does Northwind Credit Bank meet the PSI requirement for the Jane Testperson portfolio?"),
    (ChatRoleEnum.ASSISTANT, "The PSI is 0.06 for [BANK_1] [Source: DOC-1, Section: Stability]."),
    (ChatRoleEnum.USER, "And does Mashreq Bank meet the same requirement?"),
]


async def override_get_db() -> AsyncIterator[AsyncSession]:
    async with TestingSessionLocal() as session:
        yield session


async def override_get_rate_limiter() -> None:
    return None


@pytest_asyncio.fixture(autouse=True)
async def setup_db() -> AsyncIterator[None]:
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_rate_limiter] = override_get_rate_limiter
    registry_store.clear_all()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with TestingSessionLocal() as session:
        session.add_all([Tenant(id=TENANT_ID, name="Registry Tenant"), Tenant(id=OTHER_TENANT_ID, name="Other")])
        await session.flush()
        session.add_all(
            [
                User(id=USER_ID, email="reg@example.test", hashed_password="pw", tenant_id=TENANT_ID, role=RoleEnum.ANALYST),
                User(id=OTHER_USER_ID, email="other@example.test", hashed_password="pw", tenant_id=OTHER_TENANT_ID, role=RoleEnum.ANALYST),
            ]
        )
        await session.commit()
    yield
    registry_store.clear_all()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(get_rate_limiter, None)


def _headers(user_id: uuid.UUID = USER_ID, tenant_id: uuid.UUID = TENANT_ID) -> dict[str, str]:
    token = create_access_token(user_id=user_id, tenant_id=tenant_id, role="ANALYST")
    return {"Authorization": f"Bearer {token}"}


async def _seed_session(
    conversation: list[tuple[ChatRoleEnum, str]] = CONVERSATION,
    *,
    same_timestamp: bool = False,
) -> uuid.UUID:
    session_id = uuid.uuid4()
    async with TestingSessionLocal() as session:
        session.add(ChatSession(id=session_id, tenant_id=TENANT_ID, user_id=USER_ID, created_at=BASE_TIME))
        await session.flush()
        for index, (role, content) in enumerate(conversation):
            session.add(
                ChatMessage(
                    session_id=session_id,
                    role=role,
                    content=content,
                    created_at=BASE_TIME if same_timestamp else BASE_TIME + timedelta(seconds=index + 1),
                )
            )
        await session.commit()
    return session_id


def _messages(conversation: list[tuple[ChatRoleEnum, str]] = CONVERSATION) -> list[SessionMessage]:
    return [SessionMessage(uuid.uuid4(), role.value, content) for role, content in conversation]


# ---------------------------------------------------------------------------- derivation


def test_fresh_workers_derive_identical_state() -> None:
    session_id = uuid.uuid4()
    messages = _messages()

    registry_store.clear_all()
    worker_a = build_session_state(session_id, messages, MaskingPipeline())
    registry_store.clear_all()
    worker_b = build_session_state(session_id, messages, MaskingPipeline())

    assert worker_a.registry.get_mapping() == worker_b.registry.get_mapping()
    assert worker_a.history == worker_b.history
    mapping = worker_a.registry.get_mapping()
    assert mapping["Emirates NBD"] == "[BANK_1]"
    assert {"Northwind Credit Bank", "Jane Testperson", "Mashreq Bank"} <= set(mapping)
    # Tokens are numbered in order of the conversation, never reused.
    assert len(set(mapping.values())) == len(mapping)


def test_masked_history_never_contains_a_registered_entity() -> None:
    state = build_session_state(uuid.uuid4(), _messages(), MaskingPipeline())
    joined = "\n".join(turn.masked_text for turn in state.history)
    for entity in state.registry.get_mapping():
        assert entity not in joined
    assert "[BANK_1]" in joined


def test_cached_prefix_gives_the_same_result_as_a_rebuild_from_scratch() -> None:
    session_id = uuid.uuid4()
    messages = _messages()

    registry_store.clear_all()
    build_session_state(session_id, messages[:2], MaskingPipeline())  # a turn ago: cached
    assert registry_store.get_cached_state(session_id) is not None
    incremental = build_session_state(session_id, messages, MaskingPipeline())

    registry_store.clear_all()
    scratch = build_session_state(session_id, messages, MaskingPipeline())

    assert incremental.registry.get_mapping() == scratch.registry.get_mapping()
    assert incremental.history == scratch.history


def test_a_cache_entry_that_is_not_a_prefix_is_ignored() -> None:
    session_id = uuid.uuid4()
    messages = _messages()
    build_session_state(session_id, _messages()[:3], MaskingPipeline())  # other message ids
    state = build_session_state(session_id, messages, MaskingPipeline())

    registry_store.clear_all()
    scratch = build_session_state(session_id, messages, MaskingPipeline())
    assert state.registry.get_mapping() == scratch.registry.get_mapping()


class _NoBanks:
    def find_matches(self, text: str) -> list[tuple[int, int, str]]:
        return []


class _ContextSensitiveNer:
    """A tagger that finds "Acme Holdings" in a question but not in an assistant sentence."""

    def find_entities(self, text: str) -> list[EntitySpan]:
        start = text.find("Acme Holdings")
        if start < 0 or not text.startswith("Does"):
            return []
        return [EntitySpan(start, start + len("Acme Holdings"), "Acme Holdings", "ORG")]


def test_history_is_cleaned_with_the_final_registry() -> None:
    """An entity found late is also replaced in the earlier messages that still hold it raw."""
    pipeline = MaskingPipeline(bank_matcher=_NoBanks(), ner_masker=_ContextSensitiveNer())  # type: ignore[arg-type]
    messages = [
        SessionMessage(uuid.uuid4(), "assistant", "Last year's report came from Acme Holdings."),
        SessionMessage(uuid.uuid4(), "user", "Does Acme Holdings comply?"),
    ]

    state = build_session_state(uuid.uuid4(), messages, pipeline)

    assert "Acme Holdings" in state.history[0].masked_text  # masked before the tagger found it
    context = state.history_context()
    assert "Acme Holdings" not in context
    assert context == "Assistant: Last year's report came from [ORG_1].\nUser: Does [ORG_1] comply?"


def test_returned_registry_is_a_private_copy() -> None:
    session_id = uuid.uuid4()
    messages = _messages()
    state = build_session_state(session_id, messages, MaskingPipeline())
    expected = state.registry.get_mapping()

    state.registry.mask("Some Mutating Entity", "ORG")  # what masking the new question does
    again = build_session_state(session_id, messages, MaskingPipeline())

    assert again.registry.get_mapping() == expected


def test_empty_history_gives_an_empty_state() -> None:
    state = build_session_state(uuid.uuid4(), [], MaskingPipeline())
    assert state.history == [] and state.registry.get_mapping() == {}


def test_cache_is_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(registry_store, "MAX_REGISTRIES", 3)
    ids = [uuid.uuid4() for _ in range(5)]
    for session_id in ids:
        build_session_state(session_id, _messages()[:1], MaskingPipeline())
    cached = [registry_store.get_cached_state(i) is not None for i in ids]
    assert cached == [False, False, True, True, True]


# ---------------------------------------------------------------------------- loading


@pytest.mark.asyncio
async def test_messages_are_loaded_in_a_canonical_order() -> None:
    session_id = await _seed_session(same_timestamp=True)  # identical created_at: the id breaks the tie

    async with TestingSessionLocal() as session:
        first = await load_session_messages(session, session_id, TENANT_ID)
    async with TestingSessionLocal() as session:
        second = await load_session_messages(session, session_id, TENANT_ID)

    assert [m.id for m in first] == [m.id for m in second] == sorted(m.id for m in first)
    assert len(first) == len(CONVERSATION)


@pytest.mark.asyncio
async def test_messages_follow_created_at_before_id() -> None:
    session_id = await _seed_session()
    async with TestingSessionLocal() as session:
        loaded = await load_session_messages(session, session_id, TENANT_ID)
    assert [m.content for m in loaded] == [content for _, content in CONVERSATION]
    assert [m.role for m in loaded] == [role.value for role, _ in CONVERSATION]


@pytest.mark.asyncio
async def test_messages_of_another_tenant_are_never_loaded() -> None:
    session_id = await _seed_session()
    async with TestingSessionLocal() as session:
        assert await load_session_messages(session, session_id, OTHER_TENANT_ID) == []


# ---------------------------------------------------------------------------- /privacy endpoints


@pytest.mark.asyncio
async def test_redaction_log_is_the_same_on_every_call_and_every_worker() -> None:
    session_id = await _seed_session()
    expected = build_session_state(session_id, _messages(), MaskingPipeline()).registry.get_mapping()
    registry_store.clear_all()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        logs = []
        for index in range(12):
            if index % 4 == 0:
                registry_store.clear_all()  # another worker answers
            response = await client.get(
                "/privacy/redactions", params={"session_id": str(session_id)}, headers=_headers()
            )
            assert response.status_code == 200
            logs.append(response.json()["redactions"])

    assert all(log == logs[0] for log in logs)
    assert logs[0] == expected and logs[0]["Emirates NBD"] == "[BANK_1]"


@pytest.mark.asyncio
async def test_a_session_without_messages_has_an_empty_log() -> None:
    session_id = await _seed_session([])
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/privacy/redactions", params={"session_id": str(session_id)}, headers=_headers())
    assert response.status_code == 200 and response.json()["redactions"] == {}


@pytest.mark.asyncio
async def test_mask_simulator_does_not_change_what_the_chat_masks() -> None:
    session_id = await _seed_session()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        before = (
            await client.get("/privacy/redactions", params={"session_id": str(session_id)}, headers=_headers())
        ).json()["redactions"]
        simulated = await client.post(
            "/privacy/mask",
            json={"text": "Dubai Islamic Bank approved it, reviewed by Mark Simulated.", "session_id": str(session_id)},
            headers=_headers(),
        )
        after = (
            await client.get("/privacy/redactions", params={"session_id": str(session_id)}, headers=_headers())
        ).json()["redactions"]

    assert simulated.status_code == 200
    masked = simulated.json()
    assert "Dubai Islamic Bank" not in masked["masked_text"]
    assert "Dubai Islamic Bank" in masked["redactions"]  # the simulator shows its own entities
    assert before == after  # but the session's registry is untouched
    assert "Dubai Islamic Bank" not in after


@pytest.mark.asyncio
async def test_rebuild_for_reading_is_capped() -> None:
    conversation = [
        (ChatRoleEnum.USER if i % 2 == 0 else ChatRoleEnum.ASSISTANT, f"message {i}")
        for i in range(MAX_SESSION_MESSAGES + 10)
    ]
    # Entities only in the messages beyond the cap are not part of the (bounded) rebuild.
    conversation[MAX_SESSION_MESSAGES + 2] = (ChatRoleEnum.USER, "Does Emirates NBD meet it?")
    conversation[3] = (ChatRoleEnum.ASSISTANT, "Mashreq Bank is fine.")
    session_id = await _seed_session(conversation)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/privacy/redactions", params={"session_id": str(session_id)}, headers=_headers())

    redactions = response.json()["redactions"]
    assert "Mashreq Bank" in redactions and "Emirates NBD" not in redactions

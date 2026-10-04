"""PR-03: a chat or Q&A answer cut off at the token budget is reported, never shown as complete.

The provider records the stop reason of a plain or streamed call, the router exposes it as
``last_answer_truncated``, ``/query`` puts ``truncated`` in the SSE ``done`` event and stores it
with the message, and ``/regulatory/search`` returns it in the JSON body.
"""

from __future__ import annotations

import json
import logging
import uuid
from types import SimpleNamespace
from typing import Any, AsyncIterator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.db.database import Base, get_db
from app.main import app
from app.models.chat import ChatMessage, ChatRoleEnum
from app.models.user import RoleEnum, Tenant, User
from app.schemas.retrieval import Citation, RetrievalResult
from app.services.llm.gemini_provider import GeminiProvider
from app.services.llm.nvidia_provider import NvidiaProvider
from app.services.llm.router import LLMRouter
from app.utils.security import create_access_token
from app.utils.streaming import sse_stream

# ------------------------------------------------------------------------------ providers


def _nvidia_completion(text: str, finish_reason: str | None) -> MagicMock:
    choice = MagicMock()
    choice.message = MagicMock(content=text)
    choice.finish_reason = finish_reason
    completion = MagicMock()
    completion.choices = [choice]
    return completion


class _NvidiaStream:
    """An OpenAI-style stream: content deltas, then a last chunk with the stop reason and no content."""

    def __init__(self, tokens: list[str], finish_reason: str | None) -> None:
        chunks = []
        for token in tokens:
            chunks.append(SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=token), finish_reason=None)]))
        chunks.append(SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=None), finish_reason=finish_reason)]))
        # Some servers also send a trailing usage chunk with no choices.
        chunks.append(SimpleNamespace(choices=[]))
        self._chunks = iter(chunks)

    def __aiter__(self) -> "_NvidiaStream":
        return self

    async def __anext__(self) -> Any:
        try:
            return next(self._chunks)
        except StopIteration:
            raise StopAsyncIteration


def _nvidia() -> NvidiaProvider:
    return NvidiaProvider(api_key="nvapi-test", base_url="https://integrate.api.nvidia.com/v1")


@pytest.mark.asyncio
@pytest.mark.parametrize(("raw", "expected"), [("length", "length"), ("stop", "stop")])
async def test_nvidia_generate_records_the_stop_reason(raw: str, expected: str) -> None:
    provider = _nvidia()
    provider.client.chat.completions.create = AsyncMock(return_value=_nvidia_completion("answer", raw))

    assert await provider.generate("question") == "answer"

    assert provider.last_finish_reason == expected
    await provider.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize(("raw", "expected"), [("length", "length"), ("stop", "stop")])
async def test_nvidia_stream_records_the_stop_reason_of_the_last_chunk(raw: str, expected: str) -> None:
    provider = _nvidia()
    provider.client.chat.completions.create = AsyncMock(return_value=_NvidiaStream(["Basel ", "III"], raw))

    tokens = [t async for t in provider.generate_stream("Explain Basel III")]

    assert tokens == ["Basel ", "III"]
    assert provider.last_finish_reason == expected
    await provider.aclose()


@pytest.mark.asyncio
async def test_nvidia_stream_resets_the_stop_reason_for_each_call() -> None:
    provider = _nvidia()
    provider.last_finish_reason = "length"  # left over from an earlier, truncated call
    provider.client.chat.completions.create = AsyncMock(return_value=_NvidiaStream(["ok"], None))

    _ = [t async for t in provider.generate_stream("q")]

    assert provider.last_finish_reason is None
    await provider.aclose()


def _gemini_chunk(text: str, finish_reason: str | None) -> SimpleNamespace:
    candidate = SimpleNamespace(finish_reason=SimpleNamespace(name=finish_reason) if finish_reason else None)
    return SimpleNamespace(text=text, candidates=[candidate])


@pytest.mark.asyncio
async def test_gemini_stream_maps_max_tokens_to_length() -> None:
    provider = GeminiProvider(api_key="gemini-test")

    async def stream() -> AsyncIterator[SimpleNamespace]:
        yield _gemini_chunk("Capital ", None)
        yield _gemini_chunk("adequacy", "MAX_TOKENS")

    provider.client = MagicMock()
    provider.client.aio.models.generate_content_stream = AsyncMock(return_value=stream())

    tokens = [t async for t in provider.generate_stream("q")]

    assert tokens == ["Capital ", "adequacy"]
    assert provider.last_finish_reason == "length"


@pytest.mark.asyncio
async def test_gemini_generate_records_a_normal_stop() -> None:
    provider = GeminiProvider(api_key="gemini-test")
    provider.client = MagicMock()
    provider.client.aio.models.generate_content = AsyncMock(return_value=_gemini_chunk("done", "STOP"))

    assert await provider.generate("q") == "done"
    assert provider.last_finish_reason == "stop"


# --------------------------------------------------------------------------------- router


@pytest.mark.asyncio
async def test_router_reports_a_truncated_generate() -> None:
    nvidia, gemini = MagicMock(), MagicMock()
    nvidia.generate = AsyncMock(return_value="cut off mid-sen")
    nvidia.last_finish_reason = "length"
    router = LLMRouter(nvidia=nvidia, gemini=gemini)

    await router.generate("p")

    assert router.last_finish_reason == "length"
    assert router.last_answer_truncated is True


@pytest.mark.asyncio
async def test_router_reports_a_truncated_stream() -> None:
    nvidia, gemini = MagicMock(), MagicMock()

    async def stream(*args: Any, **kwargs: Any) -> AsyncIterator[str]:
        nvidia.last_finish_reason = "length"  # the provider sets it as the stream ends
        yield "partial"

    nvidia.generate_stream = stream
    router = LLMRouter(nvidia=nvidia, gemini=gemini)

    assert [c async for c in router.generate_stream("p")] == ["partial"]

    assert router.last_answer_truncated is True


@pytest.mark.asyncio
async def test_router_does_not_flag_a_finished_answer_or_a_provider_with_no_report() -> None:
    nvidia, gemini = MagicMock(), MagicMock()
    nvidia.generate = AsyncMock(return_value="complete.")
    nvidia.last_finish_reason = "stop"
    router = LLMRouter(nvidia=nvidia, gemini=gemini)
    assert router.last_answer_truncated is False  # nothing generated yet

    await router.generate("p")
    assert router.last_answer_truncated is False

    # A test double that never sets the attribute reports a MagicMock, which is not a stop reason.
    silent = MagicMock()
    silent.generate = AsyncMock(return_value="x")
    quiet_router = LLMRouter(nvidia=silent, gemini=MagicMock())
    await quiet_router.generate("p")
    assert quiet_router.last_finish_reason is None
    assert quiet_router.last_answer_truncated is False


@pytest.mark.asyncio
async def test_router_reads_the_stop_reason_of_the_provider_that_served_the_call() -> None:
    nvidia, gemini = MagicMock(), MagicMock()
    nvidia.generate = AsyncMock(side_effect=RuntimeError("503"))
    nvidia.last_finish_reason = "length"  # stale: NVIDIA did not serve this call
    gemini.generate = AsyncMock(return_value="complete.")
    gemini.last_finish_reason = "stop"
    router = LLMRouter(nvidia=nvidia, gemini=gemini)

    assert await router.generate("p") == "complete."

    assert router.last_answer_truncated is False


# --------------------------------------------------------------------------- sse done event


async def _events(response: Any) -> list[dict[str, Any]]:
    chunks = [chunk async for chunk in response.body_iterator]
    text = "".join(c if isinstance(c, str) else c.decode() for c in chunks)
    return [json.loads(block[len("data: "):]) for block in text.split("\n\n") if block.startswith("data: ")]


@pytest.mark.asyncio
async def test_done_event_carries_the_extra_fields() -> None:
    async def tokens() -> AsyncIterator[str]:
        yield "answer"

    events = await _events(sse_stream(tokens(), done_extra=lambda: {"truncated": True}))

    assert events == [{"type": "token", "content": "answer"}, {"type": "done", "truncated": True}]


@pytest.mark.asyncio
async def test_failing_done_extra_does_not_turn_a_finished_answer_into_an_error(caplog: pytest.LogCaptureFixture) -> None:
    async def tokens() -> AsyncIterator[str]:
        yield "answer"

    def boom() -> dict[str, Any]:
        raise RuntimeError("extra failed")

    with caplog.at_level(logging.ERROR, logger="app.utils.streaming"):
        events = await _events(sse_stream(tokens(), done_extra=boom))

    assert events == [{"type": "token", "content": "answer"}, {"type": "done"}]
    assert "SSE done_extra failed" in caplog.text


# ------------------------------------------------------------------------------ endpoints

engine = create_async_engine(
    "sqlite+aiosqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
)
TestingSessionLocal = async_sessionmaker(
    autocommit=False, autoflush=False, bind=engine, class_=AsyncSession, expire_on_commit=False
)
TENANT = uuid.uuid4()
USER = uuid.uuid4()


async def _override_get_db() -> AsyncIterator[AsyncSession]:
    async with TestingSessionLocal() as session:
        yield session


@pytest_asyncio.fixture
async def db(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[None]:
    app.dependency_overrides[get_db] = _override_get_db
    monkeypatch.setattr("app.services.evaluation.telemetry.async_session_maker", TestingSessionLocal)
    monkeypatch.setattr("app.api.query.async_session_maker", TestingSessionLocal)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with TestingSessionLocal() as session:
        session.add(Tenant(id=TENANT, name="Alpha"))
        await session.flush()
        session.add(User(id=USER, email="a@alpha.test", hashed_password="pw", tenant_id=TENANT, role=RoleEnum.ANALYST))
        await session.commit()
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    app.dependency_overrides.pop(get_db, None)


def _headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user_id=USER, tenant_id=TENANT, role='analyst')}"}


def _retrieval() -> RetrievalResult:
    citation = Citation(
        source="CBUAE-MMG-2022",
        section="Section 4",
        text="Credit scoring models should reach a Gini coefficient of at least 0.40.",
        score=1.0,
        retrieval_method="hybrid_rrf_reranked",
    )
    return RetrievalResult(citations=[citation], latency_ms=1.0, retrieval_metadata={})


def _sse(text: str) -> list[dict[str, Any]]:
    return [json.loads(b[len("data: "):]) for b in text.split("\n\n") if b.startswith("data: ")]


async def _ask_query(stream: Any) -> list[dict[str, Any]]:
    with patch("app.api.query.HybridRetriever.retrieve", new_callable=AsyncMock, return_value=_retrieval()), patch(
        "app.api.query.LLMRouter.generate_stream", new=stream
    ), patch("app.api.query.LLMRouter.aclose", new_callable=AsyncMock):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/query", json={"question": "What Gini threshold applies?"}, headers=_headers()
            )
    assert response.status_code == 200
    return _sse(response.text)


async def _assistant_message(session_id: uuid.UUID) -> ChatMessage:
    async with TestingSessionLocal() as session:
        return (
            await session.execute(
                select(ChatMessage).where(
                    ChatMessage.session_id == session_id, ChatMessage.role == ChatRoleEnum.ASSISTANT
                )
            )
        ).scalar_one()


@pytest.mark.asyncio
async def test_query_flags_a_cut_off_answer_in_done_and_in_the_stored_message(db: None) -> None:
    async def cut_off(self: LLMRouter, prompt: str, system_prompt: str | None = None, **kwargs: Any) -> AsyncIterator[str]:
        yield "Gini must be at least 0.40 and the validation must consider the foundational"
        self.last_finish_reason = "length"

    events = await _ask_query(cut_off)

    assert events[-1] == {"type": "done", "truncated": True}
    session_id = uuid.UUID(next(e["content"] for e in events if e["type"] == "session_id"))
    assert (await _assistant_message(session_id)).truncated is True

    # The flag survives a reload of the conversation.
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        history = await client.get(f"/query/sessions/{session_id}/messages", headers=_headers())
    assert history.status_code == 200
    by_role = {m["role"]: m for m in history.json()}
    assert by_role["assistant"]["truncated"] is True
    assert by_role["user"]["truncated"] is False


@pytest.mark.asyncio
async def test_query_does_not_flag_a_finished_answer(db: None) -> None:
    async def finished(self: LLMRouter, prompt: str, system_prompt: str | None = None, **kwargs: Any) -> AsyncIterator[str]:
        yield "Gini must be at least 0.40."
        self.last_finish_reason = "stop"

    events = await _ask_query(finished)

    assert events[-1] == {"type": "done"}
    session_id = uuid.UUID(next(e["content"] for e in events if e["type"] == "session_id"))
    assert (await _assistant_message(session_id)).truncated is False


async def _ask_regulatory(finish_reason: str | None) -> dict[str, Any]:
    async def generate(self: LLMRouter, prompt: str, **kwargs: Any) -> str:
        self.last_finish_reason = finish_reason
        return "Gini must be at least 0.40."

    with patch("app.api.regulatory.HybridRetriever.retrieve", new_callable=AsyncMock, return_value=_retrieval()), patch(
        "app.api.regulatory.LLMRouter.generate", new=generate
    ), patch("app.api.regulatory.LLMRouter.aclose", new_callable=AsyncMock):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/regulatory/search", json={"question": "What Gini threshold applies?"}, headers=_headers()
            )
    assert response.status_code == 200
    return response.json()


@pytest.mark.asyncio
async def test_regulatory_search_reports_truncation(db: None) -> None:
    assert (await _ask_regulatory("length"))["truncated"] is True


@pytest.mark.asyncio
async def test_regulatory_search_reports_a_finished_answer_as_not_truncated(db: None) -> None:
    assert (await _ask_regulatory("stop"))["truncated"] is False
    assert (await _ask_regulatory(None))["truncated"] is False

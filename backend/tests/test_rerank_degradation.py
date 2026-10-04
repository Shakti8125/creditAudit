"""M1 exit criterion (PR-01): the reranker works or degrades cleanly.

These tests drive the real NvidiaProvider, LLMRouter, Reranker and HybridRetriever. Only the
network is faked (an httpx mock transport answers the rerank endpoint), so they exercise the
actual retry, breaker, logging and fallback code.
"""

from __future__ import annotations

import logging
import uuid
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from app.config import settings
from app.schemas.retrieval import RetrievalMode, VectorResult
from app.services.llm.circuit_breaker import CircuitState
from app.services.llm.gemini_provider import GeminiProvider
from app.services.llm.model_catalog import rerank_url
from app.services.llm.nvidia_provider import NvidiaProvider
from app.services.llm.router import LLMRouter
from app.services.retrieval.hybrid_retriever import HybridRetriever

TENANT_ID = uuid.uuid4()
QUESTION = "What is the minimum Gini coefficient required for credit scoring models?"


class FakeRerankEndpoint:
    """An httpx mock transport for the NVIDIA rerank endpoint that records every request."""

    def __init__(self, *replies: httpx.Response | Exception) -> None:
        self.replies = list(replies)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        reply = self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
        if isinstance(reply, Exception):
            raise reply
        return reply


def _json(status: int, body: dict | None = None) -> httpx.Response:
    return httpx.Response(status, json=body if body is not None else {"status": status, "title": "x"})


def _provider(endpoint: FakeRerankEndpoint) -> NvidiaProvider:
    provider = NvidiaProvider(api_key="nvapi-test", base_url="https://integrate.api.nvidia.com/v1")
    provider.httpx_client = httpx.AsyncClient(transport=httpx.MockTransport(endpoint))
    provider.embed = AsyncMock(return_value=[[0.1, 0.2, 0.3]])  # dense retrieval: embeddings are not under test
    return provider


def _retriever(endpoint: FakeRerankEndpoint) -> tuple[HybridRetriever, LLMRouter, GeminiProvider]:
    gemini = GeminiProvider(api_key="gemini-test")
    gemini.generate = AsyncMock(return_value='{"score": 9}')
    router = LLMRouter(nvidia=_provider(endpoint), gemini=gemini)
    store = MagicMock()
    store.query = AsyncMock(
        return_value=[VectorResult(id="v1", score=0.9, metadata={"text": "Dense passage about Gini", "source": "mmg", "section": "4.1"})]
    )
    return HybridRetriever(router, store), router, gemini


async def _retrieve(retriever: HybridRetriever):
    return await retriever.retrieve(QUESTION, TENANT_ID, None, db=MagicMock(), top_k=3, mode=RetrievalMode.HYBRID_RERANK)


def _warnings(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.levelno >= logging.WARNING]


@pytest.fixture(autouse=True)
def no_backoff(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    sleep = AsyncMock()
    monkeypatch.setattr("app.services.llm.nvidia_provider.asyncio.sleep", sleep)
    return sleep


async def test_a_working_reranker_orders_the_results() -> None:
    ranking = {"rankings": [{"index": 2, "logit": 5.5}, {"index": 0, "logit": 1.0}]}
    endpoint = FakeRerankEndpoint(_json(200, ranking))
    retriever, router, _ = _retriever(endpoint)

    result = await _retrieve(retriever)

    assert result.diagnostics.rerank_applied is True and result.diagnostics.rerank_fallback is False
    assert result.citations[0].score == 5.5
    assert str(endpoint.requests[0].url) == rerank_url()
    assert router.breakers.get("nvidia", "rerank").get_state() == CircuitState.CLOSED


@pytest.mark.parametrize("status", [404, 410])
async def test_a_removed_reranker_degrades_to_the_fused_order(
    status: int, caplog: pytest.LogCaptureFixture
) -> None:
    endpoint = FakeRerankEndpoint(_json(status))
    retriever, router, gemini = _retriever(endpoint)

    with caplog.at_level(logging.INFO):
        result = await _retrieve(retriever)  # must not raise

    assert len(result.citations) == 3  # retrieval still returns
    assert result.diagnostics.rerank_fallback is True and result.diagnostics.rerank_applied is False
    assert result.retrieval_metadata["rerank_fallback"] is True
    assert router.breakers.get("nvidia", "rerank").get_state() == CircuitState.OPEN
    assert len(endpoint.requests) == 1  # a 404 is not retried
    gemini.generate.assert_not_awaited()  # no LLM-as-reranker by default
    lines = [r.getMessage() for r in _warnings(caplog)]
    assert len(lines) == 1 and "circuit_open breaker=nvidia/rerank" in lines[0] and f"status={status}" in lines[0]


async def test_later_requests_skip_a_removed_reranker_silently(caplog: pytest.LogCaptureFixture) -> None:
    endpoint = FakeRerankEndpoint(_json(404))
    retriever, _, _ = _retriever(endpoint)
    await _retrieve(retriever)

    caplog.clear()  # the first request logs the one line; what follows must log nothing
    with caplog.at_level(logging.INFO):
        for _ in range(3):
            # each request builds its own router, as the API does; the breaker outlives them
            later, _, _ = _retriever(endpoint)
            result = await _retrieve(later)
            assert result.diagnostics.rerank_fallback is True and len(result.citations) == 3

    assert len(endpoint.requests) == 1  # only the first request ever called the dead endpoint
    assert _warnings(caplog) == []


async def test_a_transient_outage_degrades_each_request_and_trips_after_repeated_failures(
    caplog: pytest.LogCaptureFixture,
) -> None:
    endpoint = FakeRerankEndpoint(_json(503))
    retriever, router, _ = _retriever(endpoint)

    with caplog.at_level(logging.INFO):
        results = [await _retrieve(retriever) for _ in range(settings.rerank_breaker_failures + 2)]

    assert all(r.diagnostics.rerank_fallback and len(r.citations) == 3 for r in results)
    assert router.breakers.get("nvidia", "rerank").get_state() == CircuitState.OPEN
    # two attempts per failing request (503 is retried once), then the open breaker stops all calls
    assert len(endpoint.requests) == settings.rerank_breaker_failures * 2
    lines = [r.getMessage() for r in _warnings(caplog)]
    assert sum("circuit_open" in line for line in lines) == 1


async def test_transport_errors_are_retried_then_degrade(no_backoff: AsyncMock) -> None:
    endpoint = FakeRerankEndpoint(httpx.ConnectError("connection refused"))
    retriever, _, _ = _retriever(endpoint)

    result = await _retrieve(retriever)  # must not raise

    assert result.diagnostics.rerank_fallback is True and len(result.citations) == 3
    assert len(endpoint.requests) == 2  # one retry
    no_backoff.assert_awaited_once()


async def test_a_transport_error_that_clears_on_retry_still_reranks() -> None:
    ranking = {"rankings": [{"index": 0, "logit": 3.0}]}
    endpoint = FakeRerankEndpoint(httpx.ReadTimeout("slow"), _json(200, ranking))
    retriever, router, _ = _retriever(endpoint)

    result = await _retrieve(retriever)

    assert result.diagnostics.rerank_applied is True
    assert len(endpoint.requests) == 2
    assert router.breakers.get("nvidia", "rerank").get_state() == CircuitState.CLOSED


async def test_a_garbage_reply_degrades_without_raising() -> None:
    endpoint = FakeRerankEndpoint(httpx.Response(200, content=b"<html>not json</html>"))
    retriever, _, _ = _retriever(endpoint)

    result = await _retrieve(retriever)

    assert result.diagnostics.rerank_fallback is True and len(result.citations) == 3


async def test_an_empty_ranking_degrades() -> None:
    endpoint = FakeRerankEndpoint(_json(200, {"rankings": []}))
    retriever, _, _ = _retriever(endpoint)

    result = await _retrieve(retriever)

    assert result.diagnostics.rerank_fallback is True and len(result.citations) == 3


async def test_a_broken_reranker_never_blocks_chat_generation_or_embedding() -> None:
    endpoint = FakeRerankEndpoint(_json(404))
    retriever, router, gemini = _retriever(endpoint)
    router.nvidia.generate = AsyncMock(return_value="grounded answer")
    await _retrieve(retriever)
    assert router.breakers.get("nvidia", "rerank").get_state() == CircuitState.OPEN

    assert await router.generate("question") == "grounded answer"
    assert await router.embed(["question"]) == [[0.1, 0.2, 0.3]]
    gemini.generate.assert_not_awaited()


async def test_a_reranker_without_a_key_degrades_without_a_request() -> None:
    endpoint = FakeRerankEndpoint(_json(200))
    retriever, router, _ = _retriever(endpoint)
    router.nvidia.is_configured = False

    result = await _retrieve(retriever)

    assert result.diagnostics.rerank_fallback is True and len(result.citations) == 3
    assert endpoint.requests == []

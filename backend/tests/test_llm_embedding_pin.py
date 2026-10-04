"""Embeddings are pinned to one model and size and never fail over (PR-01, CorpusPlan section 8)."""

from __future__ import annotations

import math
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.config import settings
from app.services.llm.circuit_breaker import CircuitState
from app.services.llm.embeddings import (
    EmbeddingDimensionError,
    EmbeddingNotSupportedError,
    pin_dimensions,
)
from app.services.llm.gemini_provider import GeminiProvider
from app.services.llm.nvidia_provider import NvidiaProvider
from app.services.llm.router import AllProvidersUnavailableError, LLMRouter


def _gemini() -> MagicMock:
    gemini = MagicMock()
    gemini.embed = AsyncMock(return_value=[[9.0, 9.0]])
    gemini.generate = AsyncMock(return_value="gemini answer")
    return gemini


def _embedding_response(*vectors: list[float]) -> SimpleNamespace:
    return SimpleNamespace(data=[SimpleNamespace(embedding=v) for v in vectors])


# --- no failover ----------------------------------------------------------------------------


async def test_a_failing_nvidia_embedding_never_falls_over_to_gemini() -> None:
    nvidia, gemini = MagicMock(), _gemini()
    nvidia.embed = AsyncMock(side_effect=RuntimeError("nvidia embed 503"))
    router = LLMRouter(nvidia=nvidia, gemini=gemini)

    with pytest.raises(AllProvidersUnavailableError) as raised:
        await router.embed(["capital adequacy"], input_type="document")

    assert isinstance(raised.value.__cause__, RuntimeError)
    gemini.embed.assert_not_awaited()
    assert [(r.provider, r.method, r.success) for r in router.call_log] == [("nvidia", "embed", False)]


async def test_an_open_nvidia_embed_breaker_does_not_route_to_gemini() -> None:
    nvidia, gemini = MagicMock(), _gemini()
    nvidia.embed = AsyncMock(return_value=[[0.1]])
    router = LLMRouter(nvidia=nvidia, gemini=gemini)
    router.breakers.get("nvidia", "embed").trip()

    with pytest.raises(AllProvidersUnavailableError, match="OPEN"):
        await router.embed(["text"])

    nvidia.embed.assert_not_awaited()
    gemini.embed.assert_not_awaited()


async def test_a_missing_nvidia_key_does_not_route_embeddings_to_gemini() -> None:
    nvidia, gemini = MagicMock(), _gemini()
    nvidia.is_configured = False
    router = LLMRouter(nvidia=nvidia, gemini=gemini)

    with pytest.raises(AllProvidersUnavailableError, match="never fail over"):
        await router.embed(["text"])
    # generation, by contrast, may use the backup
    assert await router.generate("prompt") == "gemini answer"

    gemini.embed.assert_not_awaited()


async def test_the_llm_rerank_fallback_flag_does_not_open_a_path_for_embeddings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "rerank_llm_fallback", True)
    nvidia, gemini = MagicMock(), _gemini()
    nvidia.embed = AsyncMock(side_effect=RuntimeError("down"))
    router = LLMRouter(nvidia=nvidia, gemini=gemini)

    assert router._get_candidate_providers("embed") == ["nvidia"]
    with pytest.raises(AllProvidersUnavailableError):
        await router.embed(["text"])
    gemini.embed.assert_not_awaited()


async def test_the_gemini_provider_refuses_to_embed() -> None:
    gemini = GeminiProvider(api_key="gemini-test")
    gemini.client.aio.models.embed_content = AsyncMock()

    with pytest.raises(EmbeddingNotSupportedError):
        await gemini.embed(["text"])

    gemini.client.aio.models.embed_content.assert_not_awaited()
    await gemini.aclose()


async def test_a_failed_embedding_is_reported_by_the_dense_retriever_as_no_dense_results() -> None:
    """Dense retrieval degrades to BM25 instead of mixing vector spaces (CorpusPlan section 8)."""
    from app.services.retrieval.dense_retriever import DenseRetriever

    nvidia, gemini = MagicMock(), _gemini()
    nvidia.embed = AsyncMock(side_effect=RuntimeError("down"))
    store = MagicMock()
    store.query = AsyncMock()

    found = await DenseRetriever(LLMRouter(nvidia=nvidia, gemini=gemini), store).retrieve("q", ["ns"])

    assert found == []
    store.query.assert_not_awaited()
    gemini.embed.assert_not_awaited()


# --- pinned model and size ------------------------------------------------------------------


async def test_the_nvidia_provider_embeds_with_the_configured_model_and_pinned_size(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "nvidia_embedding_model", "nvidia/some-embed-model")
    monkeypatch.setattr(settings, "embedding_dimensions", 4)
    provider = NvidiaProvider(api_key="nvapi-test")
    provider.client.embeddings.create = AsyncMock(return_value=_embedding_response([3.0, 4.0, 0.0, 0.0, 9.0, 9.0]))

    vectors = await provider.embed(["text"], input_type="document")

    call = provider.client.embeddings.create.await_args.kwargs
    assert call["model"] == "nvidia/some-embed-model"
    assert call["extra_body"] == {"input_type": "passage"}  # no `dimensions` unless asked for
    assert len(vectors) == 1 and len(vectors[0]) == 4
    assert math.isclose(math.sqrt(sum(x * x for x in vectors[0])), 1.0)  # renormalised after slicing
    assert vectors[0][:2] == pytest.approx([0.6, 0.8])
    await provider.aclose()


async def test_the_dimensions_parameter_is_sent_only_when_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "embedding_dimensions", 3)
    monkeypatch.setattr(settings, "embedding_send_dimensions", True)
    provider = NvidiaProvider(api_key="nvapi-test")
    provider.client.embeddings.create = AsyncMock(return_value=_embedding_response([0.1, 0.2, 0.3]))

    await provider.embed(["text"])

    assert provider.client.embeddings.create.await_args.kwargs["extra_body"] == {
        "input_type": "query",
        "dimensions": 3,
    }
    await provider.aclose()


async def test_vectors_of_the_right_size_pass_through_untouched(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "embedding_dimensions", 3)
    provider = NvidiaProvider(api_key="nvapi-test")
    original = [0.5, 0.25, 0.125]
    provider.client.embeddings.create = AsyncMock(return_value=_embedding_response(list(original)))

    assert await provider.embed(["text"]) == [original]
    await provider.aclose()


async def test_vectors_shorter_than_the_pinned_size_are_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "embedding_dimensions", 8)
    provider = NvidiaProvider(api_key="nvapi-test")
    provider.client.embeddings.create = AsyncMock(return_value=_embedding_response([0.1, 0.2]))

    with pytest.raises(EmbeddingDimensionError, match="EMBEDDING_DIMENSIONS=8"):
        await provider.embed(["text"])
    await provider.aclose()


def test_pin_dimensions_edge_cases() -> None:
    assert pin_dimensions([[1.0, 2.0, 3.0]], 0) == [[1.0, 2.0, 3.0]]  # 0 turns the pin off
    assert pin_dimensions([], 4) == []
    assert pin_dimensions([[0.0, 0.0, 5.0]], 2) == [[0.0, 0.0]]  # an all-zero head cannot be normalised
    with pytest.raises(EmbeddingDimensionError):
        pin_dimensions([[1.0, 2.0], [1.0]], 2)


async def test_an_embedding_size_error_counts_as_an_embed_failure_and_never_fails_over(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "embedding_dimensions", 8)
    nvidia = NvidiaProvider(api_key="nvapi-test")
    nvidia.client.embeddings.create = AsyncMock(return_value=_embedding_response([0.1, 0.2]))
    gemini = _gemini()
    router = LLMRouter(nvidia=nvidia, gemini=gemini)

    with pytest.raises(AllProvidersUnavailableError) as raised:
        await router.embed(["text"])

    assert isinstance(raised.value.__cause__, EmbeddingDimensionError)
    assert router.breakers.get("nvidia", "embed").failures == 1
    assert router.breakers.get("nvidia", "embed").get_state() == CircuitState.CLOSED
    gemini.embed.assert_not_awaited()
    await nvidia.aclose()

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.llm.nvidia_provider import NVIDIA_EMBEDDING_MODEL, NVIDIA_GENERATION_MODEL
from app.services.llm.gemini_provider import GEMINI_GENERATION_MODEL
from app.services.llm.router import MAX_CALL_LOG, LLMRouter, ProviderCallRecord


@pytest.mark.asyncio
async def test_failover_is_recorded_with_attempts() -> None:
    nvidia, gemini = MagicMock(), MagicMock()
    nvidia.generate = AsyncMock(side_effect=RuntimeError("503"))
    gemini.generate = AsyncMock(return_value="ok")
    router = LLMRouter(nvidia=nvidia, gemini=gemini)

    assert await router.generate("prompt") == "ok"

    assert len(router.call_log) == 2
    first, second = router.call_log
    assert (first.provider, first.attempt, first.success, first.error_type) == ("nvidia", 0, False, "RuntimeError")
    assert (second.provider, second.attempt, second.success, second.error_type) == ("gemini", 1, True, None)
    assert second.model == GEMINI_GENERATION_MODEL
    assert first.to_dict()["method"] == "generate"


@pytest.mark.asyncio
async def test_mock_providers_yield_string_models() -> None:
    nvidia, gemini = MagicMock(), MagicMock()
    nvidia.generate = AsyncMock(return_value="x")
    nvidia.embed = AsyncMock(return_value=[[0.1]])
    router = LLMRouter(nvidia=nvidia, gemini=gemini)

    await router.generate("p")
    await router.embed(["q"])

    assert all(isinstance(r.model, str) for r in router.call_log)
    assert router.call_log[0].model == NVIDIA_GENERATION_MODEL
    # NVIDIA stays primary: Gemini has no latency samples, so it cannot win on latency.
    embed_ok = [r for r in router.call_log if r.method == "embed" and r.success]
    assert len(embed_ok) == 1
    assert embed_ok[0].model == NVIDIA_EMBEDDING_MODEL


@pytest.mark.asyncio
async def test_provider_reported_generation_model_is_used() -> None:
    nvidia, gemini = MagicMock(), MagicMock()
    nvidia.generate = AsyncMock(return_value="x")
    nvidia.last_generation_model = "nvidia/fallback-model"
    router = LLMRouter(nvidia=nvidia, gemini=gemini)

    await router.generate("p")

    assert router.call_log[0].model == "nvidia/fallback-model"


@pytest.mark.asyncio
async def test_stream_success_recorded_as_generate_stream() -> None:
    nvidia, gemini = MagicMock(), MagicMock()

    async def stream(*args, **kwargs):
        for token in ["a", "b"]:
            yield token

    nvidia.generate_stream = stream
    router = LLMRouter(nvidia=nvidia, gemini=gemini)

    assert [c async for c in router.generate_stream("p")] == ["a", "b"]
    assert len(router.call_log) == 1
    record = router.call_log[0]
    assert (record.method, record.provider, record.success, record.attempt) == ("generate_stream", "nvidia", True, 0)


@pytest.mark.asyncio
async def test_call_log_is_bounded() -> None:
    nvidia, gemini = MagicMock(), MagicMock()
    nvidia.embed = AsyncMock(return_value=[[0.0]])
    router = LLMRouter(nvidia=nvidia, gemini=gemini)

    for _ in range(MAX_CALL_LOG + 25):
        await router.embed(["q"])

    assert len(router.call_log) == MAX_CALL_LOG
    assert isinstance(router.call_log[0], ProviderCallRecord)

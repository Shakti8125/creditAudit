from __future__ import annotations

import asyncio
import time
import pytest
from unittest.mock import AsyncMock, MagicMock

from app.config import settings
from app.services.llm.router import LLMRouter, AllProvidersUnavailableError
from app.services.llm.circuit_breaker import CircuitBreaker, CircuitState
from app.services.llm.gemini_provider import GeminiProvider
from app.services.llm.nvidia_provider import NvidiaProvider


@pytest.mark.asyncio
async def test_router_generate_stream_async_iteration():
    """Verify router.generate_stream yields chunks as an async generator."""
    mock_nvidia = MagicMock()
    mock_gemini = MagicMock()

    async def mock_stream(*args, **kwargs):
        for token in ["Credit ", "Risk ", "Validation ", "Complete."]:
            yield token

    mock_nvidia.generate_stream = mock_stream
    router = LLMRouter(nvidia=mock_nvidia, gemini=mock_gemini)

    chunks = []
    async for chunk in router.generate_stream("Validate credit model"):
        chunks.append(chunk)

    assert chunks == ["Credit ", "Risk ", "Validation ", "Complete."]


@pytest.mark.asyncio
async def test_router_automatic_fallback_to_gemini():
    """Verify automatic fallback to Gemini when Nvidia provider fails."""
    mock_nvidia = MagicMock()
    mock_gemini = MagicMock()

    mock_nvidia.generate = AsyncMock(side_effect=RuntimeError("Nvidia NIM 503 Service Unavailable"))
    mock_gemini.generate = AsyncMock(return_value="Response from Gemini fallback")

    router = LLMRouter(nvidia=mock_nvidia, gemini=mock_gemini)

    result = await router.generate("Evaluate PD model calibration")
    assert result == "Response from Gemini fallback"
    mock_nvidia.generate.assert_called_once()
    mock_gemini.generate.assert_called_once()


@pytest.mark.asyncio
async def test_router_all_providers_unavailable():
    """Verify AllProvidersUnavailableError is raised when both providers fail."""
    mock_nvidia = MagicMock()
    mock_gemini = MagicMock()

    mock_nvidia.generate = AsyncMock(side_effect=RuntimeError("Nvidia 500"))
    mock_gemini.generate = AsyncMock(side_effect=RuntimeError("Gemini 500"))

    router = LLMRouter(nvidia=mock_nvidia, gemini=mock_gemini)

    # The router used to re-raise the last provider's raw error, so callers could
    # not tell "every provider failed" apart from any other exception.
    with pytest.raises(AllProvidersUnavailableError) as exc_info:
        await router.generate("Test prompt")
    assert isinstance(exc_info.value.__cause__, RuntimeError)
    assert str(exc_info.value.__cause__) == "Gemini 500"


@pytest.mark.asyncio
async def test_circuit_breaker_transitions_and_concurrency():
    """Verify CircuitBreaker state transitions: CLOSED -> OPEN -> HALF_OPEN -> CLOSED under concurrent calls."""
    cb = CircuitBreaker("test_provider", max_failures=3, reset_timeout=1)

    assert cb.get_state() == CircuitState.CLOSED

    async def failing_func():
        raise ValueError("Downstream API timeout")

    # Trigger 3 failures to open circuit
    for _ in range(3):
        with pytest.raises(ValueError):
            await cb.call(failing_func)

    assert cb.get_state() == CircuitState.OPEN

    # While OPEN, call fails fast without invoking func
    mock_func = AsyncMock()
    with pytest.raises(RuntimeError) as exc_info:
        await cb.call(mock_func)
    assert "OPEN" in str(exc_info.value)
    mock_func.assert_not_called()

    # Wait for reset timeout
    await asyncio.sleep(1.1)
    assert cb.get_state() == CircuitState.HALF_OPEN

    # Concurrent probes during HALF_OPEN
    async def success_func():
        await asyncio.sleep(0.01)
        return "success"

    results = await asyncio.gather(
        cb.call(success_func),
        cb.call(success_func),
        cb.call(success_func),
    )
    assert results == ["success", "success", "success"]
    assert cb.get_state() == CircuitState.CLOSED


@pytest.mark.asyncio
async def test_router_stream_all_providers_fail_before_yield_raises_all_unavailable():
    """A stream that fails on every provider before any chunk raises the typed router error."""
    mock_nvidia = MagicMock()
    mock_gemini = MagicMock()

    async def failing_stream(*args, **kwargs):
        raise RuntimeError("API_KEY_INVALID")
        yield  # pragma: no cover - makes this an async generator

    mock_nvidia.generate_stream = failing_stream
    mock_gemini.generate_stream = failing_stream
    router = LLMRouter(nvidia=mock_nvidia, gemini=mock_gemini)

    with pytest.raises(AllProvidersUnavailableError) as exc_info:
        async for _ in router.generate_stream("Test prompt"):
            pass
    assert isinstance(exc_info.value.__cause__, RuntimeError)
    assert [r.provider for r in router.call_log] == ["nvidia", "gemini"]


# --------------------------------------------------------------------------
# Providers without a usable API key are skipped
# --------------------------------------------------------------------------


@pytest.mark.parametrize("provider_cls, placeholder", [(NvidiaProvider, "nvapi-placeholder"), (GeminiProvider, "gemini-placeholder")])
@pytest.mark.asyncio
async def test_provider_reports_missing_or_placeholder_key(monkeypatch, provider_cls, placeholder):
    monkeypatch.setattr(settings, "nvidia_api_key", "")
    monkeypatch.setattr(settings, "gemini_api_key", "")

    missing = provider_cls()
    placeholder_key = provider_cls(api_key=placeholder)
    real = provider_cls(api_key="real-looking-key")

    assert missing.is_configured is False
    assert placeholder_key.is_configured is False
    assert real.is_configured is True
    for provider in (missing, placeholder_key, real):
        await provider.aclose()


@pytest.mark.asyncio
async def test_router_skips_provider_without_usable_key():
    """An unconfigured NVIDIA is never called; Gemini serves as the only candidate."""
    mock_nvidia = MagicMock()
    mock_nvidia.is_configured = False
    mock_nvidia.generate = AsyncMock(return_value="should not be used")
    mock_gemini = MagicMock()
    mock_gemini.generate = AsyncMock(return_value="gemini answer")
    router = LLMRouter(nvidia=mock_nvidia, gemini=mock_gemini)

    assert router.get_routing_decision().provider == "gemini"
    assert await router.generate("prompt") == "gemini answer"
    mock_nvidia.generate.assert_not_called()
    assert [(r.provider, r.attempt, r.success) for r in router.call_log] == [("gemini", 0, True)]


@pytest.mark.asyncio
async def test_router_skips_unconfigured_secondary_on_failover():
    """When the primary fails, an unconfigured secondary is not tried either."""
    mock_nvidia = MagicMock()
    mock_nvidia.generate = AsyncMock(side_effect=RuntimeError("Nvidia 500"))
    mock_gemini = MagicMock()
    mock_gemini.is_configured = False
    mock_gemini.generate = AsyncMock(return_value="should not be used")
    router = LLMRouter(nvidia=mock_nvidia, gemini=mock_gemini)

    with pytest.raises(AllProvidersUnavailableError):
        await router.generate("prompt")
    mock_gemini.generate.assert_not_called()
    assert [r.provider for r in router.call_log] == ["nvidia"]


@pytest.mark.asyncio
async def test_router_with_no_configured_provider_fails_fast_without_requests():
    """Real providers with placeholder keys: no request leaves, the router raises its normal error."""
    nvidia = NvidiaProvider(api_key="nvapi-placeholder")
    gemini = GeminiProvider(api_key="gemini-placeholder")
    nvidia.client.chat.completions.create = AsyncMock()
    nvidia.client.embeddings.create = AsyncMock()
    gemini.generate = AsyncMock()
    gemini.embed = AsyncMock()
    router = LLMRouter(nvidia=nvidia, gemini=gemini)

    with pytest.raises(AllProvidersUnavailableError, match="usable API key"):
        await router.generate("prompt")
    with pytest.raises(AllProvidersUnavailableError):
        await router.embed(["query"])
    with pytest.raises(AllProvidersUnavailableError):
        async for _ in router.generate_stream("prompt"):
            pass

    nvidia.client.chat.completions.create.assert_not_called()
    nvidia.client.embeddings.create.assert_not_called()
    gemini.generate.assert_not_called()
    gemini.embed.assert_not_called()
    assert router.call_log == []
    await router.aclose()


# --------------------------------------------------------------------------
# Latency-based routing: an empty history is not "0 ms"
# --------------------------------------------------------------------------


def _router_with_history(nvidia_ms: list[float], gemini_ms: list[float]) -> LLMRouter:
    router = LLMRouter(nvidia=MagicMock(), gemini=MagicMock())
    router.latency_history["nvidia"] = list(nvidia_ms)
    router.latency_history["gemini"] = list(gemini_ms)
    return router


@pytest.mark.parametrize(
    "nvidia_ms, gemini_ms, expected",
    [
        ([], [], "nvidia"),  # no history -> default primary
        ([900.0], [], "nvidia"),  # regression: Gemini's empty history used to win as 0 ms
        ([], [50.0], "nvidia"),  # NVIDIA has no samples -> stays the default primary
        ([900.0, 800.0], [100.0], "gemini"),  # both sampled, Gemini faster
        ([100.0], [900.0], "nvidia"),  # both sampled, NVIDIA faster
        ([200.0], [200.0], "nvidia"),  # tie prefers NVIDIA
    ],
)
def test_routing_decision_requires_latency_samples_on_both_sides(nvidia_ms, gemini_ms, expected):
    assert _router_with_history(nvidia_ms, gemini_ms).get_routing_decision().provider == expected


@pytest.mark.asyncio
async def test_nvidia_stays_primary_after_its_first_success():
    """After one NVIDIA call, the next call must not jump to the never-sampled Gemini."""
    mock_nvidia = MagicMock()
    mock_nvidia.generate = AsyncMock(return_value="nvidia answer")
    mock_gemini = MagicMock()
    mock_gemini.generate = AsyncMock(return_value="gemini answer")
    router = LLMRouter(nvidia=mock_nvidia, gemini=mock_gemini)

    assert await router.generate("first") == "nvidia answer"
    assert await router.generate("second") == "nvidia answer"
    mock_gemini.generate.assert_not_called()
    assert mock_nvidia.generate.await_count == 2

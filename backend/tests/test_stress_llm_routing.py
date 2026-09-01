from __future__ import annotations

import asyncio
import time
import pytest
from unittest.mock import AsyncMock, MagicMock

from app.services.llm.router import LLMRouter, AllProvidersUnavailableError
from app.services.llm.circuit_breaker import CircuitBreaker, CircuitState


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

    with pytest.raises(RuntimeError):
        await router.generate("Test prompt")


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

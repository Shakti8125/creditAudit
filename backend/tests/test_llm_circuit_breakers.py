"""Per-method circuit breakers (PR-01, QA-006): a broken method must not stop the others."""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from openai import NotFoundError

from app.config import settings
from app.services.llm.circuit_breaker import (
    BreakerRegistry,
    CircuitBreaker,
    CircuitState,
    get_shared_breakers,
    is_permanent_failure,
    status_code_of,
)
from app.services.llm.router import AllProvidersUnavailableError, LLMRouter


def _status_error(status: int) -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "https://ai.api.nvidia.com/v1/retrieval/x/reranking")
    return httpx.HTTPStatusError("boom", request=request, response=httpx.Response(status, request=request))


def _providers() -> tuple[MagicMock, MagicMock]:
    nvidia, gemini = MagicMock(), MagicMock()
    nvidia.generate = AsyncMock(return_value="generated")
    nvidia.embed = AsyncMock(return_value=[[0.1, 0.2]])
    nvidia.rerank = AsyncMock(return_value=[])
    gemini.generate = AsyncMock(return_value="from gemini")
    return nvidia, gemini


def _warnings(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.levelno >= logging.WARNING]


async def test_a_failing_rerank_does_not_stop_generation_or_embedding() -> None:
    nvidia, gemini = _providers()
    nvidia.rerank = AsyncMock(side_effect=_status_error(404))
    router = LLMRouter(nvidia=nvidia, gemini=gemini)

    with pytest.raises(AllProvidersUnavailableError):
        await router.rerank("query", ["a", "b"])

    assert router.breakers.get("nvidia", "rerank").get_state() == CircuitState.OPEN
    # the same provider still serves every other method, on NVIDIA and without failover
    assert await router.generate("prompt") == "generated"
    assert await router.embed(["text"]) == [[0.1, 0.2]]
    assert router.breakers.get("nvidia", "generate").get_state() == CircuitState.CLOSED
    assert router.breakers.get("nvidia", "embed").get_state() == CircuitState.CLOSED
    gemini.generate.assert_not_awaited()


async def test_a_failing_generate_does_not_stop_rerank_or_embedding() -> None:
    nvidia, gemini = _providers()
    nvidia.generate = AsyncMock(side_effect=RuntimeError("503"))
    nvidia.rerank = AsyncMock(return_value=["ranked"])
    router = LLMRouter(nvidia=nvidia, gemini=gemini)

    for _ in range(settings.llm_breaker_failures):
        assert await router.generate("prompt") == "from gemini"  # failover each time

    assert router.breakers.get("nvidia", "generate").get_state() == CircuitState.OPEN
    assert await router.rerank("query", ["a"]) == ["ranked"]
    assert await router.embed(["text"]) == [[0.1, 0.2]]


async def test_with_the_generate_breaker_open_gemini_serves_without_calling_nvidia() -> None:
    nvidia, gemini = _providers()
    router = LLMRouter(nvidia=nvidia, gemini=gemini)
    router.breakers.get("nvidia", "generate").trip()

    assert await router.generate("prompt") == "from gemini"

    nvidia.generate.assert_not_awaited()
    assert router.get_routing_decision("generate").provider == "gemini"
    # embed and rerank are different breakers: NVIDIA is still their primary
    assert router.get_routing_decision("embed").provider == "nvidia"
    assert router.get_routing_decision("rerank").provider == "nvidia"


async def test_breaker_state_is_shared_by_every_router_in_the_process() -> None:
    first_nvidia, first_gemini = _providers()
    first_nvidia.rerank = AsyncMock(side_effect=_status_error(404))
    await_first = LLMRouter(nvidia=first_nvidia, gemini=first_gemini)
    with pytest.raises(AllProvidersUnavailableError):
        await await_first.rerank("query", ["a"])

    second_nvidia, second_gemini = _providers()
    second = LLMRouter(nvidia=second_nvidia, gemini=second_gemini)  # a later request builds a new router
    with pytest.raises(AllProvidersUnavailableError, match="OPEN"):
        await second.rerank("query", ["a"])

    second_nvidia.rerank.assert_not_awaited()
    assert second.breakers is get_shared_breakers()


async def test_a_router_can_be_given_its_own_registry() -> None:
    nvidia, gemini = _providers()
    nvidia.rerank = AsyncMock(side_effect=_status_error(404))
    private = BreakerRegistry()
    router = LLMRouter(nvidia=nvidia, gemini=gemini, breakers=private)

    with pytest.raises(AllProvidersUnavailableError):
        await router.rerank("query", ["a"])

    assert private.get("nvidia", "rerank").get_state() == CircuitState.OPEN
    assert get_shared_breakers().snapshot() == {}


@pytest.mark.parametrize("status", [401, 403, 404, 410])
async def test_a_permanent_rerank_error_opens_the_breaker_at_once(status: int) -> None:
    nvidia, gemini = _providers()
    nvidia.rerank = AsyncMock(side_effect=_status_error(status))
    router = LLMRouter(nvidia=nvidia, gemini=gemini)

    with pytest.raises(AllProvidersUnavailableError):
        await router.rerank("query", ["a"])

    assert router.breakers.get("nvidia", "rerank").get_state() == CircuitState.OPEN


@pytest.mark.parametrize("status", [400, 422, 429, 500, 503])
async def test_other_rerank_errors_open_it_only_after_repeated_failures(status: int) -> None:
    nvidia, gemini = _providers()
    nvidia.rerank = AsyncMock(side_effect=_status_error(status))
    router = LLMRouter(nvidia=nvidia, gemini=gemini)
    breaker = router.breakers.get("nvidia", "rerank")

    for attempt in range(1, settings.rerank_breaker_failures):
        with pytest.raises(AllProvidersUnavailableError):
            await router.rerank("query", ["a"])
        assert breaker.get_state() == CircuitState.CLOSED, f"opened after only {attempt} failure(s)"

    with pytest.raises(AllProvidersUnavailableError):
        await router.rerank("query", ["a"])
    assert breaker.get_state() == CircuitState.OPEN


async def test_a_permanent_error_does_not_open_the_generate_breaker_at_once() -> None:
    """A 404 on generate is handled by the NVIDIA model fallback and Gemini failover, not a fast trip."""
    nvidia, gemini = _providers()
    nvidia.generate = AsyncMock(side_effect=_status_error(404))
    router = LLMRouter(nvidia=nvidia, gemini=gemini)

    assert await router.generate("prompt") == "from gemini"

    assert router.breakers.get("nvidia", "generate").get_state() == CircuitState.CLOSED


async def test_the_breaker_half_opens_after_its_reset_time_and_closes_on_success() -> None:
    nvidia, gemini = _providers()
    nvidia.rerank = AsyncMock(side_effect=[_status_error(404), ["ranked"]])
    router = LLMRouter(nvidia=nvidia, gemini=gemini)
    breaker = router.breakers.get("nvidia", "rerank")

    with pytest.raises(AllProvidersUnavailableError):
        await router.rerank("query", ["a"])
    assert breaker.get_state() == CircuitState.OPEN
    assert breaker.reset_timeout == settings.rerank_breaker_reset_seconds

    breaker.last_failure_time -= breaker.reset_timeout + 1  # the cool-down has passed
    assert breaker.get_state() == CircuitState.HALF_OPEN
    assert await router.rerank("query", ["a"]) == ["ranked"]
    assert breaker.get_state() == CircuitState.CLOSED


async def test_a_failed_half_open_probe_reopens_the_breaker() -> None:
    nvidia, gemini = _providers()
    nvidia.rerank = AsyncMock(side_effect=_status_error(404))
    router = LLMRouter(nvidia=nvidia, gemini=gemini)
    breaker = router.breakers.get("nvidia", "rerank")
    with pytest.raises(AllProvidersUnavailableError):
        await router.rerank("query", ["a"])
    breaker.last_failure_time -= breaker.reset_timeout + 1

    with pytest.raises(AllProvidersUnavailableError):
        await router.rerank("query", ["a"])  # the one probe call

    assert breaker.get_state() == CircuitState.OPEN
    assert nvidia.rerank.await_count == 2


async def test_a_dead_reranker_logs_one_warning_then_nothing(caplog: pytest.LogCaptureFixture) -> None:
    nvidia, gemini = _providers()
    nvidia.rerank = AsyncMock(side_effect=_status_error(404))
    router = LLMRouter(nvidia=nvidia, gemini=gemini)

    with caplog.at_level(logging.INFO):
        with pytest.raises(AllProvidersUnavailableError):
            await router.rerank("query", ["a"])
        first = _warnings(caplog)
        caplog.clear()
        for _ in range(5):
            with pytest.raises(AllProvidersUnavailableError):
                await router.rerank("query", ["a"])

    assert len(first) == 1
    assert "circuit_open" in first[0].getMessage() and "nvidia/rerank" in first[0].getMessage()
    assert "status=404" in first[0].getMessage()
    assert _warnings(caplog) == []
    assert nvidia.rerank.await_count == 1


async def test_a_failover_logs_one_line_naming_both_providers(caplog: pytest.LogCaptureFixture) -> None:
    nvidia, gemini = _providers()
    nvidia.generate = AsyncMock(side_effect=RuntimeError("503 Service Unavailable"))
    router = LLMRouter(nvidia=nvidia, gemini=gemini)

    with caplog.at_level(logging.INFO):
        assert await router.generate("prompt") == "from gemini"

    lines = [r.getMessage() for r in _warnings(caplog)]
    assert len(lines) == 1
    assert lines[0].startswith("llm_failover from=nvidia to=gemini method=generate reason=RuntimeError")


def test_status_code_of_reads_httpx_openai_and_genai_style_errors() -> None:
    assert status_code_of(_status_error(410)) == 410

    request = httpx.Request("POST", "https://integrate.api.nvidia.com/v1/chat/completions")
    openai_error = NotFoundError("nf", response=httpx.Response(404, request=request), body=None)
    assert status_code_of(openai_error) == 404

    class GenaiStyle(Exception):
        code = 403

    assert status_code_of(GenaiStyle()) == 403
    assert status_code_of(RuntimeError("plain")) is None
    assert is_permanent_failure(GenaiStyle()) and not is_permanent_failure(_status_error(500))


async def test_the_circuit_breaker_keeps_its_original_behaviour_without_a_method() -> None:
    breaker = CircuitBreaker("standalone", max_failures=2, reset_timeout=60)

    async def boom() -> None:
        raise ValueError("x")

    for _ in range(2):
        with pytest.raises(ValueError):
            await breaker.call(boom)

    assert breaker.get_state() == CircuitState.OPEN
    assert breaker.name == "standalone"


def test_the_registry_applies_the_policy_per_method(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "llm_breaker_failures", 7)
    monkeypatch.setattr(settings, "llm_breaker_reset_seconds", 11)
    monkeypatch.setattr(settings, "rerank_breaker_failures", 2)
    monkeypatch.setattr(settings, "rerank_breaker_reset_seconds", 99)
    registry = BreakerRegistry()

    generate, rerank = registry.get("nvidia", "generate"), registry.get("nvidia", "rerank")

    assert (generate.max_failures, generate.reset_timeout, generate.fatal) == (7, 11, None)
    assert (rerank.max_failures, rerank.reset_timeout) == (2, 99)
    assert rerank.fatal is is_permanent_failure
    assert registry.get("nvidia", "rerank") is rerank
    assert registry.get("gemini", "rerank") is not rerank
    assert registry.snapshot()["nvidia/rerank"] == {"state": "CLOSED", "failures": 0}

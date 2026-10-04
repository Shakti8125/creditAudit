"""The optional start-up model probe (PR-01): cheap, off by default, never blocks or crashes start-up."""

from __future__ import annotations

import asyncio
import logging
import time
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from app.config import Settings, settings
from app.main import app, lifespan
from app.services.llm import startup_probe
from app.services.llm.circuit_breaker import CircuitState
from app.services.llm.router import LLMRouter

NVIDIA_KEY = "nvapi-SECRETKEY0123456789"
GEMINI_KEY = "AIzaSECRETGEMINIKEY0123456789"


def _status_error(status: int) -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "https://ai.api.nvidia.com/v1/retrieval/x/reranking")
    return httpx.HTTPStatusError("boom", request=request, response=httpx.Response(status, request=request))


def _router(*, nvidia_key: bool = True, gemini_key: bool = True) -> LLMRouter:
    nvidia, gemini = MagicMock(), MagicMock()
    nvidia.is_configured, gemini.is_configured = nvidia_key, gemini_key
    nvidia.client.chat.completions.create = AsyncMock(return_value=MagicMock())
    nvidia.embed = AsyncMock(return_value=[[0.1, 0.2]])
    nvidia.rerank = AsyncMock(return_value=[MagicMock()])
    nvidia.aclose = AsyncMock()
    gemini.client.aio.models.get_model = AsyncMock(return_value=MagicMock())
    gemini.aclose = AsyncMock()
    return LLMRouter(nvidia=nvidia, gemini=gemini)


def _messages(caplog: pytest.LogCaptureFixture, level: int = logging.INFO) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.levelno >= level and r.name == startup_probe.logger.name]


# --- off by default, optional ----------------------------------------------------------------


def test_the_probe_is_off_by_default() -> None:
    assert Settings.model_construct().llm_startup_probe is False
    assert settings.llm_startup_probe is False


async def test_starting_the_probe_does_nothing_when_it_is_off() -> None:
    assert startup_probe.start_startup_probe() is None


async def test_lifespan_does_not_touch_the_probe_when_it_is_off(monkeypatch: pytest.MonkeyPatch) -> None:
    started = MagicMock()
    monkeypatch.setattr(startup_probe, "start_startup_probe", started)
    monkeypatch.setattr(settings, "llm_startup_probe", False)

    async with lifespan(app):
        pass

    started.assert_not_called()


# --- never blocks or crashes start-up --------------------------------------------------------


async def test_a_probe_that_never_finishes_does_not_delay_start_up_and_is_cancelled_at_shutdown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release = asyncio.Event()
    entered: list[bool] = []

    async def hangs(*args, **kwargs):
        entered.append(True)
        await release.wait()  # never set: a provider that never answers

    monkeypatch.setattr(startup_probe, "run_startup_probe", hangs)
    monkeypatch.setattr(settings, "llm_startup_probe", True)

    started = time.perf_counter()
    async with lifespan(app):
        entered_after = time.perf_counter() - started
        await asyncio.sleep(0)  # let the detached task begin
        assert entered == [True]
    exited_after = time.perf_counter() - started

    assert entered_after < 1.0  # the app was serving while the probe was still hanging
    assert exited_after < 2.0  # and shutdown did not wait for it


async def test_a_probe_that_crashes_does_not_crash_start_up(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(startup_probe, "run_startup_probe", AsyncMock(side_effect=RuntimeError("provider exploded")))
    monkeypatch.setattr(settings, "llm_startup_probe", True)

    with caplog.at_level(logging.INFO):
        async with lifespan(app):
            await asyncio.sleep(0.05)

    assert any("llm_startup_probe aborted: RuntimeError" in m for m in _messages(caplog, logging.WARNING))


async def test_starting_the_probe_outside_a_running_loop_does_not_raise(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "llm_startup_probe", True)
    monkeypatch.setattr(asyncio, "get_running_loop", MagicMock(side_effect=RuntimeError("no loop")))

    assert startup_probe.start_startup_probe() is None


async def test_stopping_a_finished_or_missing_probe_is_a_no_op() -> None:
    await startup_probe.stop_startup_probe(None)
    done = asyncio.get_running_loop().create_task(asyncio.sleep(0))
    await done
    await startup_probe.stop_startup_probe(done)


# --- what the probe checks and logs ----------------------------------------------------------


async def test_a_healthy_set_of_models_is_logged_ok(caplog: pytest.LogCaptureFixture) -> None:
    router = _router()

    with caplog.at_level(logging.INFO):
        checks = await startup_probe.run_startup_probe(router=router, timeout=2)

    assert [(c.provider, c.method, c.ok) for c in checks] == [
        ("nvidia", "generate", True),
        ("nvidia", "generate", True),
        ("nvidia", "embed", True),
        ("nvidia", "rerank", True),
        ("gemini", "lookup", True),
    ]
    assert [c.model for c in checks] == [
        settings.nvidia_generation_model,
        settings.nvidia_fallback_generation_model,
        settings.nvidia_embedding_model,
        settings.nvidia_rerank_model,
        settings.gemini_generation_model,
    ]
    messages = _messages(caplog)
    assert sum(m.startswith("model_ok ") for m in messages) == 5
    assert "llm_startup_probe checked=5 unavailable=0" in messages
    assert _messages(caplog, logging.WARNING) == []


async def test_the_probe_uses_cheap_synthetic_calls_only() -> None:
    router = _router()

    await startup_probe.run_startup_probe(router=router, timeout=2)

    chat = router.nvidia.client.chat.completions.create.await_args.kwargs
    assert chat["max_tokens"] <= 16 and chat["messages"] == [{"role": "user", "content": startup_probe.PROBE_PROMPT}]
    assert router.nvidia.embed.await_args.args == (["test"],)
    rerank_args = router.nvidia.rerank.await_args.args
    assert rerank_args[1] == startup_probe.PROBE_PASSAGES and len(rerank_args[1]) == 2
    router.gemini.client.aio.models.get_model.assert_awaited_once_with(model=settings.gemini_generation_model)
    assert not router.gemini.generate.called  # the Gemini check uses no generation quota


async def test_a_gone_reranker_is_logged_with_its_status_and_trips_the_shared_breaker(
    caplog: pytest.LogCaptureFixture,
) -> None:
    router = _router()
    router.nvidia.rerank = AsyncMock(side_effect=_status_error(404))

    with caplog.at_level(logging.INFO):
        checks = await startup_probe.run_startup_probe(router=router, timeout=2)

    rerank = next(c for c in checks if c.method == "rerank")
    assert (rerank.ok, rerank.status) == (False, "404")
    warnings = _messages(caplog, logging.WARNING)
    assert any(
        m.startswith("model_unavailable provider=nvidia method=rerank")
        and f"model={settings.nvidia_rerank_model}" in m
        and "status=404" in m
        for m in warnings
    )
    # the first user request already skips the dead reranker
    assert router.breakers.get("nvidia", "rerank").get_state() == CircuitState.OPEN
    assert router.breakers.get("nvidia", "embed").get_state() == CircuitState.CLOSED
    assert "llm_startup_probe checked=5 unavailable=1" in _messages(caplog)


async def test_a_slow_model_times_out_instead_of_hanging(caplog: pytest.LogCaptureFixture) -> None:
    router = _router()

    async def never_answers(*args, **kwargs):
        await asyncio.sleep(30)

    router.nvidia.embed = AsyncMock(side_effect=never_answers)

    started = time.perf_counter()
    with caplog.at_level(logging.INFO):
        checks = await startup_probe.run_startup_probe(router=router, timeout=0.05)

    assert time.perf_counter() - started < 2.0
    embed = next(c for c in checks if c.method == "embed")
    assert (embed.ok, embed.status) == (False, "timeout")
    assert any("method=embed" in m and "status=timeout" in m for m in _messages(caplog, logging.WARNING))


async def test_an_unexpected_exception_from_a_provider_is_a_result_not_a_crash() -> None:
    router = _router()
    router.nvidia.client.chat.completions.create = AsyncMock(side_effect=ValueError("surprise"))
    router.gemini.client.aio.models.get_model = AsyncMock(side_effect=ConnectionError("offline"))

    checks = await startup_probe.run_startup_probe(router=router, timeout=2)

    assert [c.status for c in checks if not c.ok] == ["ValueError", "ValueError", "ConnectionError"]


async def test_providers_without_a_key_are_skipped_without_any_call(caplog: pytest.LogCaptureFixture) -> None:
    router = _router(nvidia_key=False, gemini_key=False)

    with caplog.at_level(logging.INFO):
        checks = await startup_probe.run_startup_probe(router=router, timeout=2)

    assert checks == []
    router.nvidia.client.chat.completions.create.assert_not_called()
    router.nvidia.embed.assert_not_called()
    router.nvidia.rerank.assert_not_called()
    router.gemini.client.aio.models.get_model.assert_not_called()
    messages = _messages(caplog)
    assert "model_check_skipped provider=nvidia reason=no_key" in messages
    assert "model_check_skipped provider=gemini reason=no_key" in messages


async def test_the_probe_closes_the_router_it_creates_but_not_one_it_was_given(monkeypatch: pytest.MonkeyPatch) -> None:
    owned = _router(nvidia_key=False, gemini_key=False)
    owned.aclose = AsyncMock()
    monkeypatch.setattr(startup_probe, "LLMRouter", lambda: owned)
    await startup_probe.run_startup_probe(timeout=1)
    owned.aclose.assert_awaited_once()

    given = _router(nvidia_key=False, gemini_key=False)
    given.aclose = AsyncMock()
    await startup_probe.run_startup_probe(router=given, timeout=1)
    given.aclose.assert_not_awaited()


async def test_the_probe_output_carries_no_secrets(caplog: pytest.LogCaptureFixture) -> None:
    router = _router()
    router.nvidia.rerank = AsyncMock(side_effect=RuntimeError(f"Bearer {NVIDIA_KEY} rejected"))
    router.gemini.client.aio.models.get_model = AsyncMock(side_effect=RuntimeError(f"bad key {GEMINI_KEY}"))

    with caplog.at_level(logging.DEBUG):
        await startup_probe.run_startup_probe(router=router, timeout=2)

    output = "\n".join(r.getMessage() for r in caplog.records)
    assert NVIDIA_KEY not in output and GEMINI_KEY not in output  # only class names and statuses are logged

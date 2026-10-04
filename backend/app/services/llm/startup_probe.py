"""Optional start-up check of the configured provider models (PR-01, QA-006).

Off by default (``LLM_STARTUP_PROBE=false``). When on, a background task makes a few tiny
synthetic calls once the app is already serving: one generation call per configured NVIDIA
chat model, an embedding of the word "test", a rerank of two toy passages, and a model lookup
for the Gemini backup (which uses no generation quota). Each result is one log line:

    model_ok          provider=nvidia method=rerank model=... ms=212
    model_unavailable provider=nvidia method=rerank model=... status=404 ms=18

The probe can never hold up or crash start-up: it runs as a detached task, every call has its
own timeout (``LLM_STARTUP_PROBE_TIMEOUT_SECONDS``), and every exception is caught. A rerank
or embedding failure is also recorded on the shared circuit breaker, so the first user
request already skips a reranker that is gone.

Prompts are synthetic. The authoritative check is still the keyed probe
(``python -m scripts.diag.pr00_probe`` or ``scripts/demo.sh preflight``).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from app.config import settings
from app.services.llm.circuit_breaker import status_code_of
from app.services.llm.model_catalog import nvidia_generation_models
from app.services.llm.router import LLMRouter

logger = logging.getLogger(__name__)

PROBE_PROMPT = "Reply with the single word OK."
PROBE_PASSAGES = [
    "The binomial test compares observed default rates with predicted probabilities of default.",
    "The office is open from nine to five on weekdays.",
]


@dataclass(frozen=True)
class ModelCheck:
    """Outcome of one start-up model check.

    Attributes:
        provider: ``nvidia`` or ``gemini``.
        method: What was checked (``generate``, ``embed``, ``rerank`` or ``lookup``).
        model: The configured model ID that was checked.
        ok: Whether the call succeeded.
        status: ``ok``, an HTTP status, ``timeout`` or an exception class name.
        ms: Duration of the call.
    """

    provider: str
    method: str
    model: str
    ok: bool
    status: str
    ms: int


async def _check(
    router: LLMRouter,
    provider: str,
    method: str,
    model: str,
    call: Callable[[], Awaitable[object]],
    timeout: float,
) -> ModelCheck:
    """Run one call with a timeout, log its outcome and return it; never raises."""
    started = time.perf_counter()
    status, ok, error = "ok", True, None
    try:
        await asyncio.wait_for(call(), timeout=timeout)
    except asyncio.TimeoutError:
        status, ok = "timeout", False
    except Exception as exc:  # noqa: BLE001 - a failing model is a result here, not an error
        code = status_code_of(exc)
        status, ok, error = (str(code) if code is not None else type(exc).__name__), False, exc
    result = ModelCheck(provider, method, model, ok, status, int((time.perf_counter() - started) * 1000))
    if ok:
        logger.info("model_ok provider=%s method=%s model=%s ms=%d", provider, method, model, result.ms)
    else:
        logger.warning(
            "model_unavailable provider=%s method=%s model=%s status=%s ms=%d",
            provider, method, model, status, result.ms,
        )
    _feed_breaker(router, provider, method, ok, error)
    return result


def _feed_breaker(router: LLMRouter, provider: str, method: str, ok: bool, error: BaseException | None) -> None:
    """Record rerank and embed outcomes on the shared breaker so request one is already informed."""
    if method not in ("rerank", "embed"):
        return
    breaker = router.breakers.get(provider, method)
    if ok:
        breaker.record_success()
    else:
        breaker.record_failure(error)


def _usable(provider: object) -> bool:
    """Whether a provider has a usable API key (an explicit ``is_configured = False`` disables it)."""
    return getattr(provider, "is_configured", True) is not False


async def run_startup_probe(router: LLMRouter | None = None, timeout: float | None = None) -> list[ModelCheck]:
    """Check each configured model once and log the outcomes.

    Args:
        router: Router whose providers and breakers are used; defaults to a new one that is
            closed afterwards.
        timeout: Seconds per call; defaults to ``LLM_STARTUP_PROBE_TIMEOUT_SECONDS``.

    Returns:
        One ``ModelCheck`` per call made. Providers without a usable key are skipped.
    """
    seconds = timeout if timeout is not None else settings.llm_startup_probe_timeout_seconds
    owned = router is None
    router = router or LLMRouter()
    results: list[ModelCheck] = []
    try:
        nvidia, gemini = router.nvidia, router.gemini
        if _usable(nvidia):
            for model in nvidia_generation_models():
                results.append(
                    await _check(
                        router,
                        "nvidia",
                        "generate",
                        model,
                        lambda model=model: nvidia.client.chat.completions.create(
                            model=model,
                            messages=[{"role": "user", "content": PROBE_PROMPT}],
                            max_tokens=16,
                        ),
                        seconds,
                    )
                )
            results.append(
                await _check(
                    router, "nvidia", "embed", settings.nvidia_embedding_model,
                    lambda: nvidia.embed(["test"], input_type="query"), seconds,
                )
            )
            results.append(
                await _check(
                    router, "nvidia", "rerank", settings.nvidia_rerank_model,
                    lambda: nvidia.rerank("probability of default calibration", PROBE_PASSAGES, top_n=2), seconds,
                )
            )
        else:
            logger.info("model_check_skipped provider=nvidia reason=no_key")

        if _usable(gemini):
            results.append(
                await _check(
                    router, "gemini", "lookup", settings.gemini_generation_model,
                    lambda: gemini.client.aio.models.get_model(model=settings.gemini_generation_model), seconds,
                )
            )
        else:
            logger.info("model_check_skipped provider=gemini reason=no_key")
    finally:
        if owned:
            with contextlib.suppress(Exception):
                await router.aclose()
    failed = [r for r in results if not r.ok]
    logger.info("llm_startup_probe checked=%d unavailable=%d", len(results), len(failed))
    return results


async def _run_logged() -> None:
    """Task body: run the probe and swallow every error except cancellation."""
    try:
        await run_startup_probe()
    except Exception as exc:  # noqa: BLE001 - the probe must never take the app down
        logger.warning("llm_startup_probe aborted: %s", type(exc).__name__)


def start_startup_probe() -> asyncio.Task[None] | None:
    """Start the probe as a detached background task when ``LLM_STARTUP_PROBE`` is on.

    Returns:
        The task (to cancel on shutdown), or None when the probe is off or could not start.
        Never raises and never waits for the probe.
    """
    if not settings.llm_startup_probe:
        return None
    try:
        return asyncio.get_running_loop().create_task(_run_logged(), name="llm-startup-probe")
    except Exception as exc:  # noqa: BLE001
        logger.warning("llm_startup_probe not started: %s", type(exc).__name__)
        return None


async def stop_startup_probe(task: asyncio.Task[None] | None) -> None:
    """Cancel a still-running probe at shutdown."""
    if task is None or task.done():
        return
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError, Exception):
        await task

from __future__ import annotations
import time
import logging
import asyncio
from enum import Enum
from typing import Any, Callable, TypeVar, Coroutine, AsyncIterator

from app.config import settings

logger = logging.getLogger(__name__)

class CircuitState(str, Enum):
    """Circuit breaker states."""
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"

T = TypeVar('T')

# Statuses that will not heal by retrying and do not depend on the input: bad credentials
# and a missing or retired model. A call that returns one trips a breaker that opted in at once.
PERMANENT_STATUSES = frozenset({401, 403, 404, 410})


def status_code_of(error: BaseException) -> int | None:
    """Best-effort HTTP status of a provider error (httpx, openai or google-genai), else None."""
    response = getattr(error, "response", None)
    for candidate in (getattr(response, "status_code", None), getattr(error, "status_code", None), getattr(error, "code", None)):
        if isinstance(candidate, int) and not isinstance(candidate, bool):
            return candidate
    return None


def is_permanent_failure(error: BaseException) -> bool:
    """Whether ``error`` is a status in ``PERMANENT_STATUSES`` (a gone model or a bad key)."""
    return status_code_of(error) in PERMANENT_STATUSES


class CircuitBreaker:
    """Circuit breaker for one provider method, with concurrency locks and streaming support.

    Args:
        provider_name: Provider key (``nvidia`` or ``gemini``).
        max_failures: Consecutive failures that open the breaker.
        reset_timeout: Seconds the breaker stays open before one half-open probe is allowed.
        method: Router method this breaker guards (``generate``, ``embed``, ``rerank``...).
            Breakers are per (provider, method), so a failing reranker cannot stop generation.
        fatal: Optional predicate; a failure it accepts opens the breaker immediately.
    """
    def __init__(
        self,
        provider_name: str,
        max_failures: int = 5,
        reset_timeout: int = 30,
        method: str | None = None,
        fatal: Callable[[BaseException], bool] | None = None,
    ):
        self.provider_name = provider_name
        self.method = method
        self.max_failures = max_failures
        self.reset_timeout = reset_timeout
        self.fatal = fatal
        self.state = CircuitState.CLOSED
        self.failures = 0
        self.last_failure_time = 0.0
        self._lock: asyncio.Lock | None = None

    @property
    def name(self) -> str:
        """Label used in logs: ``provider`` or ``provider/method``."""
        return f"{self.provider_name}/{self.method}" if self.method else self.provider_name

    @property
    def lock(self) -> asyncio.Lock:
        """Lazily initialize asyncio.Lock bound to current event loop."""
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    def get_state(self) -> CircuitState:
        """Get current circuit breaker state, evaluating timeout transitions."""
        if self.state == CircuitState.OPEN:
            if time.time() - self.last_failure_time >= self.reset_timeout:
                self.state = CircuitState.HALF_OPEN
                logger.info(f"CircuitBreaker({self.name}) transitioned OPEN -> HALF_OPEN")
        return self.state

    def record_success(self) -> None:
        """Record a successful request."""
        if self.state != CircuitState.CLOSED:
            logger.info(f"CircuitBreaker({self.name}) transitioned {self.state.value} -> CLOSED")
            self.state = CircuitState.CLOSED
        self.failures = 0

    def _open(self, error: BaseException | None) -> None:
        """Move to OPEN and log the one WARNING line for it (class name and status only)."""
        if self.state == CircuitState.OPEN:
            return
        self.state = CircuitState.OPEN
        status = status_code_of(error) if error is not None else None
        logger.warning(
            "circuit_open breaker=%s failures=%d skip_for=%ds reason=%s%s",
            self.name,
            self.failures,
            self.reset_timeout,
            type(error).__name__ if error is not None else "unknown",
            f" status={status}" if status is not None else "",
        )

    def record_failure(self, error: BaseException | None = None) -> None:
        """Record a failed request and open the breaker when the policy says so.

        Opening logs exactly one WARNING line (the "log once" of PR-01); later calls are
        skipped without logging until the half-open probe.

        Args:
            error: The failure, used for the ``fatal`` check and the log line.
        """
        self.failures += 1
        self.last_failure_time = time.time()
        is_fatal = error is not None and self.fatal is not None and self.fatal(error)
        if is_fatal or self.state == CircuitState.HALF_OPEN or self.failures >= self.max_failures:
            self._open(error)

    def trip(self, error: BaseException | None = None) -> None:
        """Open the breaker now, for a caller that already knows the method is unusable."""
        self.failures = max(self.failures + 1, self.max_failures)
        self.last_failure_time = time.time()
        self._open(error)

    async def call(self, func: Callable[..., Coroutine[Any, Any, T]], *args: Any, **kwargs: Any) -> T:
        """Wrap an async function call with circuit breaker logic and lock protection."""
        async with self.lock:
            current_state = self.get_state()
            if current_state == CircuitState.OPEN:
                raise RuntimeError(f"Circuit breaker for {self.name} is OPEN")

        try:
            result = await func(*args, **kwargs)
            async with self.lock:
                self.record_success()
            return result
        except Exception as e:
            async with self.lock:
                self.record_failure(e)
            raise e

    async def call_stream(
        self,
        func: Callable[..., AsyncIterator[T] | Coroutine[Any, Any, AsyncIterator[T]]],
        *args: Any,
        **kwargs: Any
    ) -> AsyncIterator[T]:
        """Wrap an async generator call with circuit breaker logic and lock protection."""
        async with self.lock:
            current_state = self.get_state()
            if current_state == CircuitState.OPEN:
                raise RuntimeError(f"Circuit breaker for {self.name} is OPEN")

        try:
            gen_or_coro = func(*args, **kwargs)
            if asyncio.iscoroutine(gen_or_coro):
                gen = await gen_or_coro
            else:
                gen = gen_or_coro

            async for item in gen:
                yield item

            async with self.lock:
                self.record_success()
        except Exception as e:
            async with self.lock:
                self.record_failure(e)
            raise e


class BreakerRegistry:
    """Circuit breakers keyed by (provider, method), created on first use.

    The policy per method comes from settings: ``rerank`` opens after
    ``RERANK_BREAKER_FAILURES`` failures, immediately on a permanent 401/403/404/410, and
    stays open ``RERANK_BREAKER_RESET_SECONDS``; every other method uses ``LLM_BREAKER_*``.
    """

    def __init__(self) -> None:
        self._breakers: dict[tuple[str, str], CircuitBreaker] = {}

    def get(self, provider: str, method: str) -> CircuitBreaker:
        """Return the breaker for ``(provider, method)``, creating it from settings if needed."""
        key = (provider, method)
        breaker = self._breakers.get(key)
        if breaker is None:
            if method == "rerank":
                breaker = CircuitBreaker(
                    provider,
                    max_failures=settings.rerank_breaker_failures,
                    reset_timeout=settings.rerank_breaker_reset_seconds,
                    method=method,
                    fatal=is_permanent_failure,
                )
            else:
                breaker = CircuitBreaker(
                    provider,
                    max_failures=settings.llm_breaker_failures,
                    reset_timeout=settings.llm_breaker_reset_seconds,
                    method=method,
                )
            self._breakers[key] = breaker
        return breaker

    def snapshot(self) -> dict[str, dict[str, Any]]:
        """Return ``{"provider/method": {"state": ..., "failures": n}}`` for diagnostics."""
        return {
            f"{provider}/{method}": {"state": breaker.get_state().value, "failures": breaker.failures}
            for (provider, method), breaker in sorted(self._breakers.items())
        }

    def reset(self) -> None:
        """Forget every breaker (tests, and a manual recovery after fixing a key)."""
        self._breakers.clear()


# Routers are built per request, so breaker state lives here to outlive them: a reranker that
# is gone is skipped by every later request until its reset timeout, not rediscovered each time.
_shared_breakers = BreakerRegistry()


def get_shared_breakers() -> BreakerRegistry:
    """Return the process-wide registry that routers use unless given their own."""
    return _shared_breakers


def reset_shared_breakers() -> None:
    """Clear the process-wide registry."""
    _shared_breakers.reset()

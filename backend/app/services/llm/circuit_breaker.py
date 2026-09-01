from __future__ import annotations
import time
import logging
import asyncio
from enum import Enum
from typing import Any, Callable, TypeVar, Coroutine, AsyncIterator

logger = logging.getLogger(__name__)

class CircuitState(str, Enum):
    """Circuit breaker states."""
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"

T = TypeVar('T')

class CircuitBreaker:
    """Circuit breaker for LLM providers with concurrency locks and streaming support."""
    def __init__(self, provider_name: str, max_failures: int = 5, reset_timeout: int = 30):
        self.provider_name = provider_name
        self.max_failures = max_failures
        self.reset_timeout = reset_timeout
        self.state = CircuitState.CLOSED
        self.failures = 0
        self.last_failure_time = 0.0
        self._lock: asyncio.Lock | None = None

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
                logger.info(f"CircuitBreaker({self.provider_name}) transitioned OPEN -> HALF_OPEN")
        return self.state

    def record_success(self) -> None:
        """Record a successful request."""
        if self.state != CircuitState.CLOSED:
            logger.info(f"CircuitBreaker({self.provider_name}) transitioned {self.state.value} -> CLOSED")
            self.state = CircuitState.CLOSED
        self.failures = 0

    def record_failure(self) -> None:
        """Record a failed request."""
        self.failures += 1
        self.last_failure_time = time.time()
        
        if self.state == CircuitState.HALF_OPEN or self.failures >= self.max_failures:
            if self.state != CircuitState.OPEN:
                logger.warning(f"CircuitBreaker({self.provider_name}) tripped. Transitioned to OPEN")
                self.state = CircuitState.OPEN

    async def call(self, func: Callable[..., Coroutine[Any, Any, T]], *args: Any, **kwargs: Any) -> T:
        """Wrap an async function call with circuit breaker logic and lock protection."""
        async with self.lock:
            current_state = self.get_state()
            if current_state == CircuitState.OPEN:
                raise RuntimeError(f"Circuit breaker for {self.provider_name} is OPEN")
            
        try:
            result = await func(*args, **kwargs)
            async with self.lock:
                self.record_success()
            return result
        except Exception as e:
            async with self.lock:
                self.record_failure()
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
                raise RuntimeError(f"Circuit breaker for {self.provider_name} is OPEN")
            
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
                self.record_failure()
            raise e


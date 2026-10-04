from __future__ import annotations
import time
import statistics
import logging
from dataclasses import asdict, dataclass
from typing import AsyncIterator, Any
from pydantic import BaseModel, ConfigDict

from app.config import settings
from app.services.llm.base_provider import RerankResult
from app.services.llm.circuit_breaker import (
    BreakerRegistry,
    CircuitBreaker,
    CircuitState,
    get_shared_breakers,
    status_code_of,
)
from app.services.llm.gemini_provider import GeminiProvider
from app.services.llm.nvidia_provider import NvidiaProvider

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProviderCallRecord:
    """One provider attempt made by the router (success or failure).

    Attributes:
        method: Router method (``generate``, ``generate_stream``, ``embed`` or ``rerank``).
        provider: Provider key (``nvidia`` or ``gemini``).
        model: Model identifier that served (or was expected to serve) the call.
        latency_ms: Wall-clock duration of the attempt.
        success: Whether the attempt succeeded.
        attempt: 0 for the primary provider, 1+ for failover attempts.
        error_type: Exception class name on failure (never the message).
    """

    method: str
    provider: str
    model: str
    latency_ms: float
    success: bool
    attempt: int
    error_type: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return the record as a JSON-serialisable dict."""
        return asdict(self)


GENERATION_METHODS = ("generate", "generate_stream")
# Embeddings are pinned to one provider, model and size: vectors from two models are not
# comparable, so an embedding call never fails over (AGENTS.md, CorpusPlan section 8).
EMBEDDING_PROVIDER = "nvidia"


def configured_model(provider_name: str, method: str) -> str:
    """The model ID the app is configured to use for ``(provider, method)``, read from settings."""
    if provider_name == "nvidia":
        if method in GENERATION_METHODS:
            return settings.nvidia_generation_model
        if method == "embed":
            return settings.nvidia_embedding_model
        if method == "rerank":
            return settings.nvidia_rerank_model
    elif provider_name == "gemini" and method in (*GENERATION_METHODS, "rerank"):
        return settings.gemini_generation_model
    return "unknown"


# Upper bound on per-router call records (a router lives for one request or eval run).
MAX_CALL_LOG = 200

class RoutingDecision(BaseModel):
    """Routing decision details."""
    model_config = ConfigDict(from_attributes=True)

    provider: str
    model: str
    rationale: str

class AllProvidersUnavailableError(Exception):
    """Raised when no LLM provider can serve a call.

    Covers three cases: no provider has a usable API key, every configured
    provider's circuit breaker is OPEN, or every candidate provider failed the
    call (the last provider error is chained as ``__cause__``).
    """
    pass

class LLMRouter:
    """Multi-provider LLM router: NVIDIA first, Gemini only on failure, embeddings pinned.

    Circuit breakers are per (provider, method) and shared by every router in the process
    (``circuit_breaker.get_shared_breakers``), so a broken reranker neither stops generation
    nor embedding, and the next request skips it without calling it again.

    Args:
        nvidia: NVIDIA provider (defaults to one built from settings).
        gemini: Gemini provider (defaults to one built from settings).
        breakers: Breaker registry; defaults to the process-wide one.
    """
    def __init__(
        self,
        nvidia: NvidiaProvider | None = None,
        gemini: GeminiProvider | None = None,
        breakers: BreakerRegistry | None = None,
    ):
        self.nvidia = nvidia or NvidiaProvider()
        self.gemini = gemini or GeminiProvider()
        self.breakers = breakers if breakers is not None else get_shared_breakers()

        self.providers = {
            "nvidia": self.nvidia,
            "gemini": self.gemini
        }

        # Rolling window of latency measurements (last 50 requests per provider)
        self.latency_history: dict[str, list[float]] = {
            "nvidia": [],
            "gemini": []
        }

        self.costs: list[dict] = []
        # Per-instance log of provider attempts, read by RAG telemetry. Safe because
        # every request (and every eval run) builds its own router.
        self.call_log: list[ProviderCallRecord] = []

    def _breaker(self, provider_name: str, method: str) -> CircuitBreaker:
        """Breaker guarding ``method`` on ``provider_name``."""
        return self.breakers.get(provider_name, method)

    def _resolve_model(self, provider_name: str, method: str) -> str:
        """Best-effort model identifier for a provider call.

        Uses the provider's ``last_generation_model`` for generation (NVIDIA may fall
        back to a secondary model on 404) only when it is a non-empty string, so
        mocked providers never leak MagicMock objects into the log.
        """
        if method in GENERATION_METHODS:
            value = getattr(self.providers.get(provider_name), "last_generation_model", None)
            if isinstance(value, str) and value:
                return value
        return configured_model(provider_name, method)

    def _record_call(
        self,
        method: str,
        provider_name: str,
        latency_ms: float,
        success: bool,
        attempt: int,
        error: BaseException | None = None,
    ) -> None:
        """Append a ProviderCallRecord to ``call_log``; never raises."""
        try:
            if len(self.call_log) >= MAX_CALL_LOG:
                return
            self.call_log.append(
                ProviderCallRecord(
                    method=method,
                    provider=provider_name,
                    model=self._resolve_model(provider_name, method),
                    latency_ms=float(latency_ms),
                    success=success,
                    attempt=attempt,
                    error_type=type(error).__name__ if error is not None else None,
                )
            )
        except Exception as exc:  # noqa: BLE001 - call logging must never affect routing
            logger.debug("Failed to record provider call (%s)", type(exc).__name__)

    async def aclose(self) -> None:
        """Close underlying provider clients."""
        for provider in self.providers.values():
            if hasattr(provider, "aclose"):
                await provider.aclose()

    def _record_latency(self, provider_name: str, latency_ms: float) -> None:
        """Record request latency in rolling window."""
        history = self.latency_history[provider_name]
        history.append(latency_ms)
        if len(history) > 50:
            history.pop(0)

    def _has_usable_key(self, provider_name: str) -> bool:
        """Whether a provider has a usable API key.

        Providers expose ``is_configured`` (False for a missing/placeholder key).
        Only an explicit ``False`` disables a provider, so injected test doubles
        without the attribute stay routable.
        """
        return getattr(self.providers[provider_name], "is_configured", True) is not False

    def _get_p50_latency(self, provider_name: str) -> float:
        """Calculate p50 (median) latency for a provider."""
        history = self.latency_history[provider_name]
        if not history:
            return 0.0
        return statistics.median(history)

    @staticmethod
    def _allowed_providers(method: str) -> list[str]:
        """Providers that may serve ``method``, primary first.

        ``embed`` is pinned to NVIDIA and never fails over. ``rerank`` is NVIDIA only unless
        ``RERANK_LLM_FALLBACK`` allows the (slow, 20 calls per query) Gemini scorer.
        Generation and streaming may use both.
        """
        if method == "embed":
            return [EMBEDDING_PROVIDER]
        if method == "rerank":
            return ["nvidia", "gemini"] if settings.rerank_llm_fallback else ["nvidia"]
        return ["nvidia", "gemini"]

    def get_routing_decision(self, method: str = "generate") -> RoutingDecision:
        """Determine the provider that serves ``method`` first.

        Providers that may not serve the method, have no usable API key, or have an OPEN
        breaker for it are never chosen. NVIDIA is the primary. Gemini is promoted only
        when ``LLM_LATENCY_ROUTING`` is on, both providers have latency samples and
        Gemini's p50 is lower (an empty history is not "0 ms").

        Args:
            method: Router method (``generate``, ``generate_stream``, ``embed``, ``rerank``).

        Raises:
            AllProvidersUnavailableError: No allowed provider is configured, or every
                allowed provider has an OPEN breaker for ``method``.
        """
        allowed = self._allowed_providers(method)
        configured = [name for name in allowed if self._has_usable_key(name)]
        if not configured:
            if method == "embed":
                raise AllProvidersUnavailableError(
                    f"No usable API key for the pinned embedding provider ({EMBEDDING_PROVIDER}); "
                    "embeddings never fail over."
                )
            raise AllProvidersUnavailableError("No LLM provider is configured with a usable API key.")

        available_providers = [
            name for name in configured if self._breaker(name, method).get_state() != CircuitState.OPEN
        ]
        if not available_providers:
            raise AllProvidersUnavailableError(
                f"All LLM providers are currently OPEN (unavailable) for {method}."
            )

        def decision(provider: str, rationale: str) -> RoutingDecision:
            return RoutingDecision(provider=provider, model=configured_model(provider, method), rationale=rationale)

        if len(available_providers) == 1:
            provider = available_providers[0]
            return decision(provider, f"Only {provider} is available.")

        if not settings.llm_latency_routing:
            return decision(
                available_providers[0],
                f"Latency routing is off. {available_providers[0]} is the primary; "
                f"{available_providers[1]} is the failover backup.",
            )

        # A provider with no samples has no p50: compare only when both have history,
        # otherwise keep the default primary (an empty history must not read as 0 ms).
        if not self.latency_history["nvidia"] or not self.latency_history["gemini"]:
            return decision(
                "nvidia",
                "Insufficient latency history to compare providers. Defaulting to primary provider (nvidia).",
            )

        # Compare p50 latencies; a tie prefers nvidia
        nvidia_p50 = self._get_p50_latency("nvidia")
        gemini_p50 = self._get_p50_latency("gemini")

        if nvidia_p50 <= gemini_p50:
            return decision(
                "nvidia", f"Nvidia p50 ({nvidia_p50:.1f}ms) <= Gemini p50 ({gemini_p50:.1f}ms). Preferred primary."
            )
        return decision("gemini", f"Gemini p50 ({gemini_p50:.1f}ms) < Nvidia p50 ({nvidia_p50:.1f}ms).")

    def _get_candidate_providers(self, method: str = "generate") -> list[str]:
        """Providers to try for ``method`` in priority order (primary first, then failover)."""
        primary = self.get_routing_decision(method).provider
        candidates = [primary]
        for name in self._allowed_providers(method):
            if (
                name != primary
                and self._has_usable_key(name)
                and self._breaker(name, method).get_state() != CircuitState.OPEN
            ):
                candidates.append(name)
        return candidates

    def _log_failed_attempt(
        self,
        method: str,
        provider_name: str,
        error: BaseException,
        next_provider: str | None,
        tripped: bool,
    ) -> None:
        """Log one WARNING line for a failed provider attempt.

        A failover logs ``llm_failover``. Without a failover the line is ``llm_call_failed``,
        unless this failure just opened the breaker: the breaker's own ``circuit_open`` line
        already says it, so a dead method logs once, not twice.
        """
        status = status_code_of(error)
        reason = f"{type(error).__name__}{f' status={status}' if status is not None else ''}"
        detail = " ".join(str(error).split())[:200]
        if next_provider is not None:
            logger.warning(
                "llm_failover from=%s to=%s method=%s reason=%s detail=%s",
                provider_name, next_provider, method, reason, detail,
            )
        elif not tripped:
            logger.warning(
                "llm_call_failed provider=%s method=%s reason=%s detail=%s", provider_name, method, reason, detail
            )

    async def _execute_routed(self, method_name: str, *args: Any, **kwargs: Any) -> Any:
        """Execute a method on the routed provider, failing over where the method allows it.

        Raises:
            AllProvidersUnavailableError: No provider could be tried, or every candidate
                failed (the last provider error is chained as ``__cause__``).
        """
        candidates = self._get_candidate_providers(method_name)
        last_error: Exception | None = None

        for attempt, provider_name in enumerate(candidates):
            provider_inst = self.providers[provider_name]
            cb = self._breaker(provider_name, method_name)
            func = getattr(provider_inst, method_name)
            was_open = cb.state == CircuitState.OPEN

            start_time = time.time()
            try:
                result = await cb.call(func, *args, **kwargs)
                latency_ms = (time.time() - start_time) * 1000
                self._record_latency(provider_name, latency_ms)
                self._record_call(method_name, provider_name, latency_ms, True, attempt)
                return result
            except Exception as e:
                last_error = e
                self._record_call(
                    method_name, provider_name, (time.time() - start_time) * 1000, False, attempt, e
                )
                next_provider = candidates[attempt + 1] if attempt + 1 < len(candidates) else None
                tripped = not was_open and cb.state == CircuitState.OPEN
                self._log_failed_attempt(method_name, provider_name, e, next_provider, tripped)

        raise AllProvidersUnavailableError(
            f"All available LLM providers failed for {method_name}."
        ) from last_error

    async def generate(
        self,
        prompt: str,
        system_prompt: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 1024,
        json_schema: dict | None = None
    ) -> str:
        """Generate text using optimal provider with automatic failover."""
        return await self._execute_routed(
            "generate",
            prompt=prompt,
            system_prompt=system_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
            json_schema=json_schema
        )

    async def generate_stream(
        self,
        prompt: str,
        system_prompt: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 1024
    ) -> AsyncIterator[str]:
        """Stream generated text directly with automatic failover on initialization failure.

        Raises:
            AllProvidersUnavailableError: Every candidate failed before yielding a chunk.
                A failure after chunks were yielded re-raises the provider error as is.
        """
        candidates = self._get_candidate_providers("generate_stream")
        last_error: Exception | None = None
        success = False

        for attempt, provider_name in enumerate(candidates):
            provider_inst = self.providers[provider_name]
            cb = self._breaker(provider_name, "generate_stream")
            was_open = cb.state == CircuitState.OPEN
            start_time = time.time()
            yielded_any = False

            try:
                stream_func = provider_inst.generate_stream
                async for chunk in cb.call_stream(
                    stream_func,
                    prompt=prompt,
                    system_prompt=system_prompt,
                    temperature=temperature,
                    max_tokens=max_tokens
                ):
                    yielded_any = True
                    yield chunk

                latency_ms = (time.time() - start_time) * 1000
                self._record_latency(provider_name, latency_ms)
                self._record_call("generate_stream", provider_name, latency_ms, True, attempt)
                success = True
                break
            except Exception as e:
                last_error = e
                self._record_call(
                    "generate_stream", provider_name, (time.time() - start_time) * 1000, False, attempt, e
                )
                has_next = attempt + 1 < len(candidates) and not yielded_any
                tripped = not was_open and cb.state == CircuitState.OPEN
                self._log_failed_attempt(
                    "generate_stream", provider_name, e, candidates[attempt + 1] if has_next else None, tripped
                )
                if yielded_any:
                    # Chunks were already yielded to consumer; cannot re-stream from beginning
                    raise e
                # Otherwise, attempt next provider in candidates

        if not success:
            # Nothing was yielded by any candidate (a mid-stream failure re-raises above).
            raise AllProvidersUnavailableError(
                "All available LLM providers failed for generate_stream."
            ) from last_error

    async def embed(
        self,
        texts: list[str],
        input_type: str = "query"
    ) -> list[list[float]]:
        """Embed texts with the pinned NVIDIA model. Never fails over to another provider.

        Raises:
            AllProvidersUnavailableError: NVIDIA has no usable key, its embed breaker is
                open, or the call failed. Callers degrade (dense retrieval returns nothing
                and BM25 still serves); they never get vectors from a different model.
        """
        return await self._execute_routed("embed", texts=texts, input_type=input_type)

    async def rerank(
        self,
        query: str,
        passages: list[str],
        top_n: int = 5
    ) -> list[RerankResult]:
        """Rerank passages with NVIDIA; the retriever keeps its fused order when this raises.

        Gemini scores passages only when ``RERANK_LLM_FALLBACK`` is on.

        Raises:
            AllProvidersUnavailableError: The reranker is unusable (no key, breaker open, or
                the call failed). The failure is logged once, here or by the breaker; the
                caller is expected to degrade rather than surface an error.
        """
        return await self._execute_routed("rerank", query=query, passages=passages, top_n=top_n)

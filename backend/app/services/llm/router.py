from __future__ import annotations
import time
import statistics
import logging
from dataclasses import asdict, dataclass
from typing import AsyncIterator, Any
from pydantic import BaseModel, ConfigDict

from app.config import settings
from app.services.llm.base_provider import RerankResult, StructuredCompletion
from app.services.llm.circuit_breaker import (
    BreakerRegistry,
    CircuitBreaker,
    CircuitState,
    get_shared_breakers,
    status_code_of,
)
from app.services.llm.gemini_provider import GeminiProvider
from app.services.llm.nvidia_provider import NvidiaProvider
from app.services.llm.structured import (
    DEFAULT_STRUCTURED_TEMPERATURE,
    EgressCheck,
    ModelT,
    StructuredCall,
    StructuredOutputError,
    run_structured,
)

logger = logging.getLogger(__name__)


class _ProviderFailure(Exception):
    """A provider call failed (already recorded and logged); lets the structured loop tell a
    provider error, which fails over, from an error raised by the caller's own hook, which must not.

    Attributes:
        error: The provider's exception.
    """

    def __init__(self, error: Exception) -> None:
        super().__init__(type(error).__name__)
        self.error = error


@dataclass(frozen=True)
class ProviderCallRecord:
    """One provider attempt made by the router (success or failure).

    Attributes:
        method: Router method (``generate``, ``generate_stream``, ``generate_structured``, ``embed`` or ``rerank``).
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


GENERATION_METHODS = ("generate", "generate_stream", "generate_structured")
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
        # Stop reason of the last successful ``generate`` / ``generate_stream`` call (PR-03):
        # ``length`` means the answer was cut off at the token budget. None until a call
        # succeeds, and when the serving provider did not report one.
        self.last_finish_reason: str | None = None

    @property
    def last_answer_truncated(self) -> bool:
        """Whether the last ``generate`` / ``generate_stream`` answer was cut off at its token budget."""
        return self.last_finish_reason == "length"

    def _note_finish_reason(self, provider_name: str) -> None:
        """Remember the serving provider's stop reason (only a real string: test doubles report none)."""
        value = getattr(self.providers.get(provider_name), "last_finish_reason", None)
        self.last_finish_reason = value if isinstance(value, str) and value else None

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

    async def _attempt(
        self,
        method_name: str,
        provider_name: str,
        attempt: int,
        next_provider: str | None,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        """Call ``method_name`` on one provider through its breaker, recording and logging the outcome.

        Args:
            method_name: Provider method to call.
            provider_name: Provider to call.
            attempt: 0 for the primary, 1+ for failover attempts (call log).
            next_provider: Provider a failure would fail over to, for the log line.

        Raises:
            Exception: The provider's own error, after it was recorded and logged.
        """
        cb = self._breaker(provider_name, method_name)
        func = getattr(self.providers[provider_name], method_name)
        was_open = cb.state == CircuitState.OPEN

        start_time = time.time()
        try:
            result = await cb.call(func, *args, **kwargs)
        except Exception as e:
            self._record_call(method_name, provider_name, (time.time() - start_time) * 1000, False, attempt, e)
            tripped = not was_open and cb.state == CircuitState.OPEN
            self._log_failed_attempt(method_name, provider_name, e, next_provider, tripped)
            raise
        latency_ms = (time.time() - start_time) * 1000
        self._record_latency(provider_name, latency_ms)
        self._record_call(method_name, provider_name, latency_ms, True, attempt)
        if method_name == "generate":
            self._note_finish_reason(provider_name)
        return result

    async def _execute_routed(self, method_name: str, *args: Any, **kwargs: Any) -> Any:
        """Execute a method on the routed provider, failing over where the method allows it.

        Raises:
            AllProvidersUnavailableError: No provider could be tried, or every candidate
                failed (the last provider error is chained as ``__cause__``).
        """
        candidates = self._get_candidate_providers(method_name)
        last_error: Exception | None = None

        for attempt, provider_name in enumerate(candidates):
            next_provider = candidates[attempt + 1] if attempt + 1 < len(candidates) else None
            try:
                return await self._attempt(method_name, provider_name, attempt, next_provider, *args, **kwargs)
            except Exception as e:
                last_error = e

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

    def _structured_call(
        self,
        provider_name: str,
        attempt: int,
        next_provider: str | None,
        system_prompt: str | None,
        temperature: float,
        json_schema: dict[str, Any],
    ) -> StructuredCall:
        """The ``(prompt, max_tokens) -> StructuredCompletion`` call ``run_structured`` makes on one provider.

        It goes through the provider's own ``generate_structured`` breaker and call log. A provider
        error is re-raised as ``_ProviderFailure``, so the caller can tell it from an error raised
        by its own egress hook, which must not trigger a failover.
        """
        async def call(task_prompt: str, tokens: int) -> StructuredCompletion:
            try:
                return await self._attempt(
                    "generate_structured", provider_name, attempt, next_provider,
                    prompt=task_prompt, system_prompt=system_prompt, temperature=temperature,
                    max_tokens=tokens, json_schema=json_schema,
                )
            except Exception as exc:  # noqa: BLE001 - any provider error means failover
                raise _ProviderFailure(exc) from exc

        return call

    async def generate_structured(
        self,
        prompt: str,
        schema_model: type[ModelT],
        json_schema: dict[str, Any],
        *,
        system_prompt: str | None = None,
        temperature: float = DEFAULT_STRUCTURED_TEMPERATURE,
        max_tokens: int | None = None,
        egress_check: EgressCheck | None = None,
    ) -> ModelT:
        """Generate JSON that validates against ``schema_model``, or raise a typed error.

        Per provider (NVIDIA first, Gemini only when NVIDIA cannot serve it): a schema-
        constrained call with thinking off and the structured token budget, then validation.
        A reply cut off at the budget is retried once with double the budget; an invalid reply
        gets exactly one repair call (``structured.run_structured``). When a provider errors, or
        its output is still invalid after the repair, the next provider is tried with the same
        prompt, so the structured path survives the NVIDIA to Gemini failover.

        Args:
            prompt: Task prompt. The caller has already run it through the egress validator.
            schema_model: Pydantic model the reply must validate against.
            json_schema: JSON schema sent to the provider (kept next to the model by the caller).
            system_prompt: Optional system prompt.
            temperature: Sampling temperature (low: the reply must validate).
            max_tokens: Output budget of the first call; default ``STRUCTURED_MAX_TOKENS``.
            egress_check: Awaited with the repair prompt, which carries the model's own previous
                output, before it is sent. Raise (the egress validator does) to block it; the
                exception propagates unchanged.

        Returns:
            The validated ``schema_model`` instance.

        Raises:
            StructuredOutputError: Every provider that answered produced invalid output.
            AllProvidersUnavailableError: No provider could serve the call (no key, breaker
                open, or every call failed).
        """
        budget = max_tokens or settings.structured_max_tokens
        cap = max(settings.structured_max_tokens_cap, budget)
        candidates = self._get_candidate_providers("generate_structured")
        last_provider_error: Exception | None = None
        rejected: list[tuple[str, StructuredOutputError]] = []

        for attempt, provider_name in enumerate(candidates):
            next_provider = candidates[attempt + 1] if attempt + 1 < len(candidates) else None

            call = self._structured_call(
                provider_name, attempt, next_provider, system_prompt, temperature, json_schema
            )
            try:
                return await run_structured(
                    call, prompt, schema_model, json_schema,
                    max_tokens=budget, max_tokens_cap=cap, egress_check=egress_check, provider=provider_name,
                )
            except _ProviderFailure as failure:
                last_provider_error = failure.error
            except StructuredOutputError as error:
                rejected.append((provider_name, error))
                if next_provider is not None:
                    logger.warning(
                        "llm_failover from=%s to=%s method=generate_structured reason=StructuredOutputError "
                        "detail=%s", provider_name, next_provider, error.reason,
                    )

        if rejected:
            last = rejected[-1][1]
            raise StructuredOutputError(last.reason, last.attempts, tuple(name for name, _ in rejected))
        raise AllProvidersUnavailableError(
            "All available LLM providers failed for generate_structured."
        ) from last_provider_error

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
                self._note_finish_reason(provider_name)
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

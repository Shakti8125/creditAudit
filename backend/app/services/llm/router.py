from __future__ import annotations
import time
import statistics
import logging
from typing import AsyncIterator, Any
from pydantic import BaseModel, ConfigDict

from app.services.llm.base_provider import RerankResult
from app.services.llm.nvidia_provider import NvidiaProvider, NVIDIA_GENERATION_MODEL
from app.services.llm.gemini_provider import GeminiProvider, GEMINI_GENERATION_MODEL
from app.services.llm.circuit_breaker import CircuitBreaker, CircuitState

logger = logging.getLogger(__name__)

class RoutingDecision(BaseModel):
    """Routing decision details."""
    model_config = ConfigDict(from_attributes=True)

    provider: str
    model: str
    rationale: str

class AllProvidersUnavailableError(Exception):
    """Raised when all configured LLM providers are unavailable or circuit breakers are open."""
    pass

class LLMRouter:
    """Intelligent multi-provider LLM router with automatic failover and latency tracking."""
    def __init__(self, nvidia: NvidiaProvider | None = None, gemini: GeminiProvider | None = None):
        self.nvidia = nvidia or NvidiaProvider()
        self.gemini = gemini or GeminiProvider()
        
        self.circuit_breakers = {
            "nvidia": CircuitBreaker("nvidia"),
            "gemini": CircuitBreaker("gemini")
        }
        
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

    def _get_p50_latency(self, provider_name: str) -> float:
        """Calculate p50 (median) latency for a provider."""
        history = self.latency_history[provider_name]
        if not history:
            return 0.0
        return statistics.median(history)

    def get_routing_decision(self) -> RoutingDecision:
        """Determine the optimal LLM provider based on circuit breaker states and p50 latency."""
        available_providers = []
        for name in ["nvidia", "gemini"]:
            if self.circuit_breakers[name].get_state() != CircuitState.OPEN:
                available_providers.append(name)
                
        if not available_providers:
            raise AllProvidersUnavailableError("All LLM providers are currently OPEN (unavailable).")
            
        if len(available_providers) == 1:
            provider = available_providers[0]
            model = NVIDIA_GENERATION_MODEL if provider == "nvidia" else GEMINI_GENERATION_MODEL
            return RoutingDecision(
                provider=provider,
                model=model,
                rationale=f"Only {provider} is available."
            )
            
        # Compare p50 latencies
        nvidia_p50 = self._get_p50_latency("nvidia")
        gemini_p50 = self._get_p50_latency("gemini")
        
        # Tie, prefer nvidia
        if nvidia_p50 == 0.0 and gemini_p50 == 0.0:
            return RoutingDecision(
                provider="nvidia",
                model=NVIDIA_GENERATION_MODEL,
                rationale="No latency history. Defaulting to primary provider (nvidia)."
            )
            
        if nvidia_p50 <= gemini_p50:
            return RoutingDecision(
                provider="nvidia",
                model=NVIDIA_GENERATION_MODEL,
                rationale=f"Nvidia p50 ({nvidia_p50:.1f}ms) <= Gemini p50 ({gemini_p50:.1f}ms). Preferred primary."
            )
        else:
            return RoutingDecision(
                provider="gemini",
                model=GEMINI_GENERATION_MODEL,
                rationale=f"Gemini p50 ({gemini_p50:.1f}ms) < Nvidia p50 ({nvidia_p50:.1f}ms)."
            )

    def _get_candidate_providers(self) -> list[str]:
        """Get candidate providers in priority order for failover."""
        decision = self.get_routing_decision()
        primary = decision.provider
        secondary = "gemini" if primary == "nvidia" else "nvidia"
        
        candidates = [primary]
        if self.circuit_breakers[secondary].get_state() != CircuitState.OPEN:
            candidates.append(secondary)
        return candidates
            
    async def _execute_routed(self, method_name: str, *args: Any, **kwargs: Any) -> Any:
        """Execute a method on routed provider with automatic failover to secondary provider."""
        candidates = self._get_candidate_providers()
        last_error: Exception | None = None
        
        for provider_name in candidates:
            provider_inst = self.providers[provider_name]
            cb = self.circuit_breakers[provider_name]
            func = getattr(provider_inst, method_name)
            
            start_time = time.time()
            try:
                result = await cb.call(func, *args, **kwargs)
                latency_ms = (time.time() - start_time) * 1000
                self._record_latency(provider_name, latency_ms)
                return result
            except Exception as e:
                last_error = e
                logger.warning(
                    f"Provider '{provider_name}' failed on '{method_name}': {e}. "
                    f"Attempting failover if another provider is available."
                )
                
        if last_error:
            raise last_error
        raise AllProvidersUnavailableError(f"All available LLM providers failed for {method_name}.")

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
        """Stream generated text directly with automatic failover on initialization failure."""
        candidates = self._get_candidate_providers()
        last_error: Exception | None = None
        success = False

        for provider_name in candidates:
            provider_inst = self.providers[provider_name]
            cb = self.circuit_breakers[provider_name]
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
                success = True
                break
            except Exception as e:
                last_error = e
                logger.warning(f"Provider '{provider_name}' failed during stream: {e}.")
                if yielded_any:
                    # Chunks were already yielded to consumer; cannot re-stream from beginning
                    raise e
                # Otherwise, attempt next provider in candidates

        if not success:
            if last_error:
                raise last_error
            raise AllProvidersUnavailableError("No LLM provider available for streaming.")

    async def embed(
        self,
        texts: list[str],
        input_type: str = "query"
    ) -> list[list[float]]:
        """Embed texts using optimal provider with automatic failover."""
        return await self._execute_routed("embed", texts=texts, input_type=input_type)

    async def rerank(
        self,
        query: str,
        passages: list[str],
        top_n: int = 5
    ) -> list[RerankResult]:
        """Rerank passages using optimal provider with automatic failover."""
        return await self._execute_routed("rerank", query=query, passages=passages, top_n=top_n)


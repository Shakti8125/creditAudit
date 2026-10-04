from __future__ import annotations

from .base_provider import BaseLLMProvider, RerankResult, ProviderHealth
from .nvidia_provider import NvidiaProvider
from .gemini_provider import GeminiProvider
from .circuit_breaker import (
    BreakerRegistry,
    CircuitBreaker,
    CircuitState,
    get_shared_breakers,
    reset_shared_breakers,
)
from .embeddings import EmbeddingDimensionError, EmbeddingNotSupportedError
from .router import LLMRouter, RoutingDecision, AllProvidersUnavailableError
from .structured import StructuredOutputError

# Model IDs are settings (app/config.py), read through app/services/llm/model_catalog.py.

__all__ = [
    "BaseLLMProvider",
    "RerankResult",
    "ProviderHealth",
    "NvidiaProvider",
    "GeminiProvider",
    "BreakerRegistry",
    "CircuitBreaker",
    "CircuitState",
    "get_shared_breakers",
    "reset_shared_breakers",
    "EmbeddingDimensionError",
    "EmbeddingNotSupportedError",
    "LLMRouter",
    "RoutingDecision",
    "AllProvidersUnavailableError",
    "StructuredOutputError",
]

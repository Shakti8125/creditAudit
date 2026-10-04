from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import AsyncIterator
from pydantic import BaseModel, ConfigDict

class RerankResult(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    index: int
    score: float
    text: str

class ProviderHealth(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    provider: str
    status: str
    latency_ms: float
    error: str | None = None


@dataclass(frozen=True)
class StructuredCompletion:
    """Raw result of one structured-output call, before any validation.

    Attributes:
        text: The model's reply (empty when it produced no content).
        finish_reason: Provider-neutral stop reason: ``stop``, ``length`` (cut off at the
            token budget), ``content_filter``, or None when the provider did not say.
        model: Model ID that served the call, when known.
    """

    text: str
    finish_reason: str | None = None
    model: str | None = None

class BaseLLMProvider(ABC):
    """Abstract base class for LLM providers.

    Attributes:
        provider_name: Router key of the provider.
        is_configured: False when the provider has no usable API key (missing or
            placeholder); ``LLMRouter`` never routes calls to such a provider.
    """
    provider_name: str
    is_configured: bool = True
    
    @abstractmethod
    async def generate(
        self,
        prompt: str,
        system_prompt: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 1024,
        json_schema: dict | None = None
    ) -> str:
        """Generate text from the LLM."""
        ...

    async def generate_structured(
        self,
        prompt: str,
        system_prompt: str | None = None,
        temperature: float = 0.2,
        max_tokens: int = 4096,
        json_schema: dict | None = None,
    ) -> StructuredCompletion:
        """Ask for schema-constrained JSON and return the raw reply with its stop reason.

        The default delegates to ``generate`` and reports no stop reason. Providers override it
        to use their native structured-output form, thinking off, and to report ``finish_reason``.
        The reply is NOT validated here: ``LLMRouter.generate_structured`` validates and repairs.
        """
        text = await self.generate(
            prompt,
            system_prompt=system_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
            json_schema=json_schema,
        )
        return StructuredCompletion(text=text)

    @abstractmethod
    async def generate_stream(
        self,
        prompt: str,
        system_prompt: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 1024
    ) -> AsyncIterator[str]:
        """Generate text from the LLM in a streaming fashion."""
        ...
    
    @abstractmethod
    async def embed(
        self,
        texts: list[str],
        input_type: str = "query"
    ) -> list[list[float]]:
        """Embed a list of texts."""
        ...
    
    @abstractmethod
    async def rerank(
        self,
        query: str,
        passages: list[str],
        top_n: int = 5
    ) -> list[RerankResult]:
        """Rerank a list of passages for a given query."""
        ...
    
    @abstractmethod
    async def health_check(self) -> ProviderHealth:
        """Perform a health check on the provider."""
        ...

    async def aclose(self) -> None:
        """Close underlying provider resources if any."""
        pass


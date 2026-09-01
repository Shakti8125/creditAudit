from __future__ import annotations
from abc import ABC, abstractmethod
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

class BaseLLMProvider(ABC):
    """Abstract base class for LLM providers."""
    provider_name: str
    
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


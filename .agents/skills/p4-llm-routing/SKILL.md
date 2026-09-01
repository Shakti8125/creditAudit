---
name: p4-llm-routing
description: >-
  Use this skill when the user asks to build the Phase 4 multi-provider LLM routing layer for ModelAudit AI, including the NVIDIA and Gemini providers, circuit breaker, and intelligent router.
---

# Phase 4: Multi-Provider LLM Routing

This skill provides step-by-step instructions for building the LLM routing layer.

## Step 1: BaseLLMProvider
Create `backend/app/services/llm/base_provider.py`

Define the abstract base class for all LLM providers:
```python
from abc import ABC, abstractmethod
from typing import AsyncIterator

class BaseLLMProvider(ABC):
    provider_name: str  # "nvidia" or "gemini"
    
    @abstractmethod
    async def generate(self, prompt: str, system_prompt: str | None, temperature: float, max_tokens: int, json_schema: dict | None) -> str: ...
    
    @abstractmethod
    async def generate_stream(self, prompt: str, system_prompt: str | None, temperature: float, max_tokens: int) -> AsyncIterator[str]: ...
    
    @abstractmethod
    async def embed(self, texts: list[str], input_type: str) -> list[list[float]]: ...
    
    @abstractmethod
    async def rerank(self, query: str, passages: list[str], top_n: int) -> list['RerankResult']: ...
    
    @abstractmethod
    async def health_check(self) -> 'ProviderHealth': ...
```
Include models `RerankResult(index: int, score: float, text: str)` and `ProviderHealth(provider: str, status: str, latency_ms: float, error: str | None)`. Status should be `HEALTHY`, `DEGRADED`, or `DOWN`.

## Step 2: NvidiaProvider
Create `backend/app/services/llm/nvidia_provider.py`

Implement `NvidiaProvider(BaseLLMProvider)` with `provider_name = "nvidia"`.
- Use `openai.AsyncOpenAI(base_url="https://integrate.api.nvidia.com/v1", api_key=...)`.
- Use specific models (refer to `references/api_specs.md` for exact IDs).
- **generate()**: Use `chat.completions.create()` with optional `extra_body={"guided_json": schema}` for JSON schema enforcement.
- **generate_stream()**: Use `stream=True` and yield content deltas.
- Include exponential backoff with full jitter, extraction of Retry-After header, and a max of 5 retries.
- **embed()**: Use `client.embeddings.create()` with `extra_body={"input_type": input_type}`.
- **rerank()**: Use `httpx` POST to `/v1/ranking` endpoint with model, query, and passages.

## Step 3: GeminiProvider
Create `backend/app/services/llm/gemini_provider.py`

Implement `GeminiProvider(BaseLLMProvider)` with `provider_name = "gemini"`.
- Use `google.genai.Client(api_key=...)`.
- Use pinned models (refer to `references/api_specs.md` for exact IDs). All model IDs must be module-level constants.
- **generate()**: Use `client.models.generate_content()`.
- **generate_stream()**: Use streaming variant, yielding text chunks.
- **embed()**: Use `client.models.embed_content()`.
- **rerank()**: Since there is no native reranker, implement via LLM scoring (prompt the generation model to return a relevance score for each query-passage pair).

## Step 4: CircuitBreaker
Create `backend/app/services/llm/circuit_breaker.py`

Implement a `CircuitBreaker` class.
- Maintain a 3-state per-provider machine: `CLOSED` (normal), `OPEN` (tripped, reject all for 30s), `HALF_OPEN` (test 1 request).
- Trip after 5 consecutive failures.
- Implement `async def call(self, func, *args)` to wrap provider calls.
- Implement `get_state() -> CircuitState`.
- Log all state transitions.

## Step 5: LLMRouter
Create `backend/app/services/llm/router.py`

Implement an `LLMRouter` class for auto cost/latency-optimized routing.
- Initialize with instances of `NvidiaProvider` and `GeminiProvider`, each wrapped in a `CircuitBreaker`.
- Maintain a rolling window of latency measurements (last 50 requests per provider).
- **Routing algorithm**:
  1. Filter out providers whose circuit breaker is `OPEN`.
  2. Among available, pick the provider with the lowest p50 latency.
  3. If tied, prefer NVIDIA (primary).
  4. If all are `OPEN`, raise `AllProvidersUnavailableError`.
- Implement `generate()`, `generate_stream()`, `embed()`, and `rerank()`, all delegating to the selected provider.
- Implement `get_routing_decision() -> RoutingDecision(provider, model, rationale)`.
- Track per-request cost estimates.

## Verification
- Test with the NVIDIA key valid to verify primary routing.
- Simulate an NVIDIA failure and verify fallback to Gemini.
- Test circuit breaker state transitions (force failures and observe OPEN/HALF_OPEN states).

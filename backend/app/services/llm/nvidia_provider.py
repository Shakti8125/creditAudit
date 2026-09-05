from __future__ import annotations
import json
import logging
import time
import random
import asyncio
from typing import AsyncIterator, Any

from openai import AsyncOpenAI, RateLimitError, APIError, NotFoundError
import httpx

from app.config import settings
from app.services.llm.base_provider import BaseLLMProvider, RerankResult, ProviderHealth

logger = logging.getLogger(__name__)

NVIDIA_GENERATION_MODEL = "nvidia/nemotron-3-super-120b-a12b"
# Tried only if the primary returns 404. NVIDIA retires the NIM function behind a
# model ID while leaving the ID listed in GET /v1/models, so a stale primary looks
# valid in the catalog but 404s on inference -- which is exactly how
# nvidia/llama-3.1-nemotron-70b-instruct took the whole router down.
NVIDIA_FALLBACK_GENERATION_MODEL = "nvidia/nemotron-3.5-lightning-30b-a3b"
NVIDIA_EMBEDDING_MODEL = "nvidia/nemotron-3-embed-1b"
NVIDIA_RERANKING_MODEL = "nvidia/llama-3.2-nv-rerankqa-1b-v2"
NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1"
# Reranking is not served from the OpenAI-compatible integrate.api.nvidia.com
# surface. It lives on a separate host, carries the model in the URL path rather
# than the body, and takes a {query, passages} payload instead of chat messages.
NVIDIA_RERANKING_URL = (
    f"https://ai.api.nvidia.com/v1/retrieval/{NVIDIA_RERANKING_MODEL}/reranking"
)

# Attempted in order; a 404 on one falls through to the next before the router
# gives up on NVIDIA entirely and fails over to Gemini.
GENERATION_MODELS = (NVIDIA_GENERATION_MODEL, NVIDIA_FALLBACK_GENERATION_MODEL)

async def _execute_with_retry(func, *args, max_retries: int = 5, **kwargs):
    for attempt in range(max_retries):
        try:
            return await func(*args, **kwargs)
        except RateLimitError as e:
            if attempt == max_retries - 1:
                raise
            
            retry_after = None
            if e.response is not None:
                retry_after = e.response.headers.get("Retry-After")
                
            if retry_after and retry_after.isdigit():
                delay = float(retry_after)
            else:
                base_delay = 2 ** attempt
                delay = random.uniform(0, base_delay)
                
            logger.warning(f"Rate limited by NVIDIA. Retrying in {delay:.2f}s (attempt {attempt + 1}/{max_retries})")
            await asyncio.sleep(delay)
        except APIError as e:
            if attempt == max_retries - 1 or (e.status_code is not None and e.status_code < 500 and e.status_code != 429):
                raise
            base_delay = 2 ** attempt
            delay = random.uniform(0, base_delay)
            logger.warning(f"API Error from NVIDIA. Retrying in {delay:.2f}s (attempt {attempt + 1}/{max_retries})")
            await asyncio.sleep(delay)
        except httpx.HTTPStatusError as e:
            if attempt == max_retries - 1 or (e.response.status_code < 500 and e.response.status_code != 429):
                raise
            
            retry_after = e.response.headers.get("Retry-After")
            if retry_after and retry_after.isdigit():
                delay = float(retry_after)
            else:
                base_delay = 2 ** attempt
                delay = random.uniform(0, base_delay)
                
            logger.warning(f"HTTP Error from NVIDIA. Retrying in {delay:.2f}s (attempt {attempt + 1}/{max_retries})")
            await asyncio.sleep(delay)

class NvidiaProvider(BaseLLMProvider):
    """NVIDIA NIM LLM provider with retry logic, embeddings, and reranking."""
    provider_name: str = "nvidia"
    
    def __init__(self, api_key: str | None = None, base_url: str | None = None):
        key = api_key or settings.nvidia.api_key
        if not key or key == "nvapi-placeholder":
            logger.warning("NvidiaProvider initialized with placeholder or missing API key.")
            key = key or "nvapi-placeholder"
        url = base_url or settings.nvidia.base_url or NVIDIA_BASE_URL
        base_url_str = url.rstrip("/") + "/"
        self.client = AsyncOpenAI(
            base_url=url,
            api_key=key
        )
        self.httpx_client = httpx.AsyncClient(
            base_url=base_url_str,
            headers={
                "Authorization": f"Bearer {key}",
                "Accept": "application/json"
            },
            timeout=30.0
        )
        
    async def aclose(self) -> None:
        """Close underlying HTTP and AsyncOpenAI clients."""
        if not self.httpx_client.is_closed:
            await self.httpx_client.aclose()
        if hasattr(self.client, "close"):
            await self.client.close()
        
    async def generate(
        self,
        prompt: str,
        system_prompt: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 1024,
        json_schema: dict | None = None
    ) -> str:
        """Generate text using NVIDIA generation model with retry."""
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        
        extra_body = {}
        if json_schema:
            extra_body["guided_json"] = json_schema

        last_error: NotFoundError | None = None
        for model in GENERATION_MODELS:
            async def _call(model=model):
                return await self.client.chat.completions.create(
                    model=model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    extra_body=extra_body if extra_body else None
                )

            try:
                response = await _execute_with_retry(_call)
            except NotFoundError as e:
                logger.warning(
                    f"NVIDIA model '{model}' returned 404 (retired NIM function). "
                    f"Trying next generation model."
                )
                last_error = e
                continue
            return response.choices[0].message.content or ""

        raise last_error

    async def generate_stream(
        self,
        prompt: str,
        system_prompt: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 1024
    ) -> AsyncIterator[str]:
        """Stream text tokens using NVIDIA generation model."""
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        
        stream = None
        last_error: NotFoundError | None = None
        for model in GENERATION_MODELS:
            async def _init_stream(model=model):
                return await self.client.chat.completions.create(
                    model=model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    stream=True
                )

            try:
                stream = await _execute_with_retry(_init_stream)
            except NotFoundError as e:
                logger.warning(
                    f"NVIDIA model '{model}' returned 404 (retired NIM function). "
                    f"Trying next generation model."
                )
                last_error = e
                continue
            break

        # A 404 happens on stream setup, before any chunk reaches the caller, so
        # swapping models here is still safe -- nothing has been yielded yet.
        if stream is None:
            raise last_error

        async for chunk in stream:
            if chunk.choices and chunk.choices[0].delta and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content

    async def embed(
        self,
        texts: list[str],
        input_type: str = "query"
    ) -> list[list[float]]:
        """Generate embeddings using NVIDIA embedding model."""
        if not texts:
            return []
            
        mapped_input_type = "passage" if input_type in ("document", "passage") else "query"
        async def _call():
            return await self.client.embeddings.create(
                model=NVIDIA_EMBEDDING_MODEL,
                input=texts,
                extra_body={"input_type": mapped_input_type}
            )
            
        response = await _execute_with_retry(_call)
        return [data.embedding for data in response.data]

    async def rerank(
        self,
        query: str,
        passages: list[str],
        top_n: int = 5
    ) -> list[RerankResult]:
        """Rerank passages against a query using NVIDIA NIM Reranking API."""
        if not passages:
            return []
            
        async def _call():
            payload = {
                "model": NVIDIA_RERANKING_MODEL,
                "query": {"text": query},
                "passages": [{"text": p} for p in passages],
                "truncate": "END"
            }
            # Absolute URL: httpx skips base_url merging for absolute URLs, so this
            # correctly reaches ai.api.nvidia.com rather than the client's
            # integrate.api.nvidia.com base.
            response = await self.httpx_client.post(NVIDIA_RERANKING_URL, json=payload)
            response.raise_for_status()
            return response.json()
            
        data = await _execute_with_retry(_call)
        
        results = []
        for ranking in data.get("rankings", [])[:top_n]:
            idx = ranking["index"]
            score = float(ranking.get("logit", ranking.get("score", 0.0)))
            results.append(RerankResult(
                index=idx,
                score=score,
                text=passages[idx]
            ))
            
        return results

    async def health_check(self) -> ProviderHealth:
        """Perform a health check on the NVIDIA provider."""
        start_time = time.time()
        try:
            # Simple fast call to check health, e.g. models list
            await self.client.models.list()
            latency = (time.time() - start_time) * 1000
            return ProviderHealth(
                provider=self.provider_name,
                status="HEALTHY",
                latency_ms=latency
            )
        except Exception as e:
            return ProviderHealth(
                provider=self.provider_name,
                status="DOWN",
                latency_ms=(time.time() - start_time) * 1000,
                error=str(e)
            )


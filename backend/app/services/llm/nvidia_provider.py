from __future__ import annotations
import json
import logging
import time
import random
import asyncio
from typing import AsyncIterator, Any

from openai import AsyncOpenAI, RateLimitError, APIError, APIConnectionError, NotFoundError
import httpx

from app.config import settings
from app.services.llm.base_provider import BaseLLMProvider, RerankResult, ProviderHealth
from app.services.llm.embeddings import pin_dimensions
from app.services.llm.model_catalog import nvidia_generation_models, rerank_url

logger = logging.getLogger(__name__)

# Model IDs are settings (app/config.py, see app/services/llm/model_catalog.py), never constants here.
NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1"
# Reranking is not served from the OpenAI-compatible integrate.api.nvidia.com surface. It lives
# on a separate host, carries the model in the URL path as well as the body, and takes a
# {query, passages} payload instead of chat messages (URL: model_catalog.rerank_url).
#
# Reranking only improves ordering, so a slow or dead reranker must not hold a request up:
# two attempts of at most this long each, then the retriever keeps its fused order.
_RERANK_TIMEOUT_S = 8.0
_RERANK_MAX_ATTEMPTS = 2

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
            # APIConnectionError/APITimeoutError carry no status_code (reading it raised
            # AttributeError, masking the real error and skipping the backoff); they
            # are transient, so retry them like 5xx/429.
            status_code = getattr(e, "status_code", None)
            retryable = (
                isinstance(e, APIConnectionError)
                or status_code is None
                or status_code >= 500
                or status_code == 429
            )
            if attempt == max_retries - 1 or not retryable:
                raise
            base_delay = 2 ** attempt
            delay = random.uniform(0, base_delay)
            logger.warning(f"API Error from NVIDIA. Retrying in {delay:.2f}s (attempt {attempt + 1}/{max_retries})")
            await asyncio.sleep(delay)
        except httpx.TransportError as e:
            # Connection resets, DNS failures and timeouts on direct httpx calls (rerank) are
            # transient, like openai's APIConnectionError above.
            if attempt == max_retries - 1:
                raise
            delay = random.uniform(0, 2 ** attempt)
            logger.warning(
                f"Transport error from NVIDIA ({type(e).__name__}). Retrying in {delay:.2f}s "
                f"(attempt {attempt + 1}/{max_retries})"
            )
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
        # A missing/placeholder key is unusable: LLMRouter skips this provider
        # instead of sending requests that can only fail authentication.
        self.is_configured = bool(key and key.strip()) and key != "nvapi-placeholder"
        if not self.is_configured:
            logger.warning("NvidiaProvider initialized with placeholder or missing API key; the router will skip it.")
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
        
        # Generation model that served the most recent generate/generate_stream call
        # (the primary, or the 404 fallback). Read by LLMRouter's call log.
        self.last_generation_model: str | None = None
        
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

        # Models are tried in order; a 404 on one falls through to the next before the router
        # gives up on NVIDIA and fails over to Gemini. NVIDIA retires the NIM function behind
        # a model ID while leaving the ID listed in GET /v1/models, so a stale primary looks
        # valid in the catalog but 404s on inference.
        last_error: NotFoundError | None = None
        for model in nvidia_generation_models():
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
            self.last_generation_model = model
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
        for model in nvidia_generation_models():
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
            self.last_generation_model = model
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
        """Generate embeddings with the pinned NVIDIA model at the pinned dimension.

        The model is ``NVIDIA_EMBEDDING_MODEL`` and the size is ``EMBEDDING_DIMENSIONS``
        (CorpusPlan section 8). There is no other embedding model to fall back to.

        Raises:
            EmbeddingDimensionError: The model returned vectors shorter than the pinned size.
        """
        if not texts:
            return []
            
        mapped_input_type = "passage" if input_type in ("document", "passage") else "query"
        extra_body: dict[str, Any] = {"input_type": mapped_input_type}
        if settings.embedding_send_dimensions and settings.embedding_dimensions > 0:
            extra_body["dimensions"] = settings.embedding_dimensions

        async def _call():
            return await self.client.embeddings.create(
                model=settings.nvidia_embedding_model,
                input=texts,
                extra_body=extra_body
            )
            
        response = await _execute_with_retry(_call)
        vectors = [data.embedding for data in response.data]
        return pin_dimensions(vectors, settings.embedding_dimensions)

    async def rerank(
        self,
        query: str,
        passages: list[str],
        top_n: int = 5
    ) -> list[RerankResult]:
        """Rerank passages against a query using NVIDIA NIM Reranking API.

        The model is ``NVIDIA_RERANK_MODEL``; the endpoint is ``NVIDIA_RERANK_URL`` or the
        model-in-path URL derived from the model.
        """
        if not passages:
            return []
            
        model = settings.nvidia_rerank_model
        url = rerank_url(model)

        async def _call():
            payload = {
                "model": model,
                "query": {"text": query},
                "passages": [{"text": p} for p in passages],
                "truncate": "END"
            }
            # Absolute URL: httpx skips base_url merging for absolute URLs, so this
            # correctly reaches ai.api.nvidia.com rather than the client's
            # integrate.api.nvidia.com base.
            response = await self.httpx_client.post(url, json=payload, timeout=_RERANK_TIMEOUT_S)
            response.raise_for_status()
            return response.json()
            
        data = await _execute_with_retry(_call, max_retries=_RERANK_MAX_ATTEMPTS)
        
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


from __future__ import annotations
import json
import logging
import time
import asyncio
from typing import AsyncIterator, Any

from google import genai
from google.genai import errors, types

from app.config import settings
from app.services.llm.base_provider import BaseLLMProvider, RerankResult, ProviderHealth, StructuredCompletion
from app.services.llm.embeddings import EmbeddingNotSupportedError
from app.services.llm.structured import DEFAULT_STRUCTURED_TEMPERATURE, neutral_finish_reason, to_openapi_schema

logger = logging.getLogger(__name__)

# The generation model is the GEMINI_GENERATION_MODEL setting (app/config.py), read per call.
# There is deliberately no Gemini embedding model: embeddings are pinned to NVIDIA.


def _thinking_config(level: str | None = None) -> types.ThinkingConfig | None:
    """Thinking config for ``level`` (default ``GEMINI_THINKING_LEVEL``), or None when it is empty."""
    level = (settings.gemini_thinking_level if level is None else level).strip()
    return types.ThinkingConfig(thinking_level=level) if level else None


# Structured calls try ``responseJsonSchema`` first and fall back to ``responseSchema`` when the
# model or SDK rejects it. Providers are built per request, so the mode that worked is
# remembered here per model: the fallback costs one rejected call per process, not per request.
_SCHEMA_MODE_THAT_WORKED: dict[str, str] = {}


def _schema_modes(model: str) -> list[str]:
    """Schema modes to try for ``model``, in order, from ``GEMINI_STRUCTURED_SCHEMA_MODE``."""
    pinned = settings.gemini_structured_schema_mode
    if pinned != "auto":
        return [pinned]
    first = _SCHEMA_MODE_THAT_WORKED.get(model, "response_json_schema")
    return [first, "response_schema" if first == "response_json_schema" else "response_json_schema"]


def _schema_rejected(exc: BaseException) -> bool:
    """Whether ``exc`` means the schema field was refused, so the other mode is worth one try.

    A 400 from the API, or the SDK refusing the field itself (an older SDK has no
    ``response_json_schema``). A bad API key is also a 400, but another schema mode cannot fix it.
    """
    if isinstance(exc, (ValueError, TypeError)):
        return True
    if isinstance(exc, errors.ClientError) and exc.code == 400:
        text = str(exc).lower()
        return "api_key" not in text and "api key" not in text
    return False


class GeminiRerankError(RuntimeError):
    """Raised when Gemini failed to score every passage of a rerank call."""


class GeminiProvider(BaseLLMProvider):
    """Google Gemini LLM provider using google-genai SDK."""
    provider_name: str = "gemini"
    
    def __init__(self, api_key: str | None = None):
        key = api_key or settings.gemini.api_key
        # A missing/placeholder key is unusable: LLMRouter skips this provider
        # instead of sending requests that can only fail authentication.
        self.is_configured = bool(key and key.strip()) and key != "gemini-placeholder"
        if not self.is_configured:
            logger.warning("GeminiProvider initialized with placeholder or missing API key; the router will skip it.")
            key = key or "gemini-placeholder"
        self.client = genai.Client(api_key=key)

    async def aclose(self) -> None:
        """Close Gemini client resources if applicable."""
        if hasattr(self.client, "aio") and hasattr(self.client.aio, "close"):
            await self.client.aio.close()
        elif hasattr(self.client, "close"):
            self.client.close()
        
    async def generate(
        self,
        prompt: str,
        system_prompt: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 1024,
        json_schema: dict | None = None
    ) -> str:
        """Generate text using Gemini model."""
        config = types.GenerateContentConfig(
            temperature=temperature,
            max_output_tokens=max_tokens,
        )
        if system_prompt:
            config.system_instruction = system_prompt
            
        if json_schema:
            config.response_mime_type = "application/json"
            config.response_schema = json_schema
        else:
            config.thinking_config = _thinking_config()

        response = await self.client.aio.models.generate_content(
            model=settings.gemini_generation_model,
            contents=prompt,
            config=config
        )
        return response.text or ""

    async def generate_structured(
        self,
        prompt: str,
        system_prompt: str | None = None,
        temperature: float = DEFAULT_STRUCTURED_TEMPERATURE,
        max_tokens: int = 4096,
        json_schema: dict | None = None,
    ) -> StructuredCompletion:
        """One schema-constrained completion on the backup model.

        Sends ``responseJsonSchema`` and, if the model or SDK rejects it, ``responseSchema``
        (``GEMINI_STRUCTURED_SCHEMA_MODE`` pins one). The mode that worked is remembered for
        the process. Thinking is set only when ``GEMINI_STRUCTURED_THINKING_LEVEL`` is. The
        reply is returned unvalidated with its stop reason (``MAX_TOKENS`` reads as ``length``).

        Raises:
            ValueError: No ``json_schema`` was given.
        """
        if not json_schema:
            raise ValueError("generate_structured needs a json_schema")
        model = settings.gemini_generation_model
        modes = _schema_modes(model)
        for position, mode in enumerate(modes):
            config = types.GenerateContentConfig(
                temperature=temperature,
                max_output_tokens=max_tokens,
                response_mime_type="application/json",
            )
            if system_prompt:
                config.system_instruction = system_prompt
            config.thinking_config = _thinking_config(settings.gemini_structured_thinking_level)
            try:
                if mode == "response_json_schema":
                    config.response_json_schema = json_schema
                else:
                    config.response_schema = to_openapi_schema(json_schema)
                response = await self.client.aio.models.generate_content(
                    model=model, contents=prompt, config=config
                )
            except Exception as exc:  # noqa: BLE001 - SDK and API errors are heterogeneous
                if position + 1 < len(modes) and _schema_rejected(exc):
                    logger.warning(
                        "gemini_structured_schema_rejected mode=%s next=%s model=%s reason=%s",
                        mode, modes[position + 1], model, type(exc).__name__,
                    )
                    continue
                raise
            if settings.gemini_structured_schema_mode == "auto":
                _SCHEMA_MODE_THAT_WORKED[model] = mode
            candidates = getattr(response, "candidates", None) or []
            finish = neutral_finish_reason(getattr(candidates[0], "finish_reason", None)) if candidates else None
            return StructuredCompletion(text=response.text or "", finish_reason=finish, model=model)
        raise RuntimeError("no Gemini schema mode available")  # unreachable: _schema_modes is never empty

    async def generate_stream(
        self,
        prompt: str,
        system_prompt: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 1024
    ) -> AsyncIterator[str]:
        """Stream text tokens using Gemini model."""
        config = types.GenerateContentConfig(
            temperature=temperature,
            max_output_tokens=max_tokens,
        )
        if system_prompt:
            config.system_instruction = system_prompt
        config.thinking_config = _thinking_config()
            
        stream = await self.client.aio.models.generate_content_stream(
            model=settings.gemini_generation_model,
            contents=prompt,
            config=config
        )
        
        async for chunk in stream:
            if chunk.text:
                yield chunk.text

    async def embed(
        self,
        texts: list[str],
        input_type: str = "query"
    ) -> list[list[float]]:
        """Always refuse: Gemini never serves embeddings.

        Index and query vectors must come from one pinned model (NVIDIA), because vectors
        from two models are not comparable and would silently corrupt retrieval (AGENTS.md,
        CorpusPlan section 8).

        Raises:
            EmbeddingNotSupportedError: Always.
        """
        raise EmbeddingNotSupportedError(
            "Gemini does not serve embeddings: vectors are pinned to one NVIDIA model and size."
        )

    async def rerank(
        self,
        query: str,
        passages: list[str],
        top_n: int = 5
    ) -> list[RerankResult]:
        """Rerank passages against a query using Gemini LLM-based scoring."""
        if not passages:
            return []
            
        # Implement LLM-based scoring. Each outcome carries the scoring error (None on
        # success): a failed passage scores 0.0 unless EVERY passage failed.
        async def score_passage(index: int, passage: str) -> tuple[RerankResult, Exception | None]:
            error: Exception | None = None
            prompt = f"""
Given the query and the passage, score the relevance of the passage to the query on a scale of 0 to 10.
Return ONLY a valid JSON object in this format: {{"score": 8.5}}

Query: {query}
Passage: {passage}
"""
            try:
                schema = {
                    "type": "object", 
                    "properties": {"score": {"type": "number"}}, 
                    "required": ["score"]
                }
                result_text = await self.generate(
                    prompt=prompt,
                    system_prompt="You are an expert relevance scorer. Respond only with JSON.",
                    temperature=0.0,
                    max_tokens=50,
                    json_schema=schema
                )
                
                result_text = result_text.replace("```json", "").replace("```", "").strip()
                data = json.loads(result_text)
                score = float(data.get("score", 0.0))
            except Exception as e:
                logger.warning(f"Failed to score passage {index}: {e}")
                score = 0.0
                error = e
                
            return RerankResult(index=index, score=score, text=passage), error
            
        # Cap passages and limit concurrent API calls to avoid rate limits
        passages_to_rank = passages[:20]
        sem = asyncio.Semaphore(5)

        async def bounded_score(index: int, passage: str) -> tuple[RerankResult, Exception | None]:
            async with sem:
                return await score_passage(index, passage)

        tasks = [bounded_score(i, p) for i, p in enumerate(passages_to_rank)]
        outcomes = await asyncio.gather(*tasks)

        # All-zero scores from a total failure are not a ranking: raise so the
        # Reranker falls back to the fused order (and telemetry records the fallback).
        errors = [err for _, err in outcomes if err is not None]
        if errors and len(errors) == len(outcomes):
            raise GeminiRerankError(
                f"Gemini failed to score all {len(outcomes)} passages."
            ) from errors[-1]

        results = [result for result, _ in outcomes]
        results.sort(key=lambda x: x.score, reverse=True)
        return results[:top_n]

    async def health_check(self) -> ProviderHealth:
        """Perform a health check on the Gemini provider."""
        start_time = time.time()
        try:
            await self.client.aio.models.get_model(model=settings.gemini_generation_model)
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


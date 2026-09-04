from __future__ import annotations
import json
import logging
import time
import asyncio
from typing import AsyncIterator, Any

from google import genai
from google.genai import types

from app.config import settings
from app.services.llm.base_provider import BaseLLMProvider, RerankResult, ProviderHealth

logger = logging.getLogger(__name__)

GEMINI_GENERATION_MODEL = "gemini-2.0-flash"
GEMINI_EMBEDDING_MODEL = "models/text-embedding-004"

class GeminiProvider(BaseLLMProvider):
    """Google Gemini LLM provider using google-genai SDK."""
    provider_name: str = "gemini"
    
    def __init__(self, api_key: str | None = None):
        key = api_key or settings.gemini.api_key
        if not key or key == "gemini-placeholder":
            logger.warning("GeminiProvider initialized with placeholder or missing API key.")
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
            
        response = await self.client.aio.models.generate_content(
            model=GEMINI_GENERATION_MODEL,
            contents=prompt,
            config=config
        )
        return response.text or ""

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
            
        stream = await self.client.aio.models.generate_content_stream(
            model=GEMINI_GENERATION_MODEL,
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
        """Generate embeddings using Gemini embedding model."""
        if not texts:
            return []
            
        # Map input_type to task_type
        task_type = "RETRIEVAL_QUERY" if input_type == "query" else "RETRIEVAL_DOCUMENT"
        
        response = await self.client.aio.models.embed_content(
            model=GEMINI_EMBEDDING_MODEL,
            contents=texts,
            config=types.EmbedContentConfig(
                task_type=task_type,
                output_dimensionality=1024,
            ),
        )
        
        return [embedding.values for embedding in response.embeddings]

    async def rerank(
        self,
        query: str,
        passages: list[str],
        top_n: int = 5
    ) -> list[RerankResult]:
        """Rerank passages against a query using Gemini LLM-based scoring."""
        if not passages:
            return []
            
        # Implement LLM-based scoring
        async def score_passage(index: int, passage: str) -> RerankResult:
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
                
            return RerankResult(index=index, score=score, text=passage)
            
        # Cap passages and limit concurrent API calls to avoid rate limits
        passages_to_rank = passages[:20]
        sem = asyncio.Semaphore(5)

        async def bounded_score(index: int, passage: str) -> RerankResult:
            async with sem:
                return await score_passage(index, passage)

        tasks = [bounded_score(i, p) for i, p in enumerate(passages_to_rank)]
        results = await asyncio.gather(*tasks)
        
        results.sort(key=lambda x: x.score, reverse=True)
        return results[:top_n]

    async def health_check(self) -> ProviderHealth:
        """Perform a health check on the Gemini provider."""
        start_time = time.time()
        try:
            await self.client.aio.models.get_model(model=GEMINI_GENERATION_MODEL)
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


from __future__ import annotations

import httpx
import pytest
from unittest.mock import AsyncMock, MagicMock

from openai import NotFoundError

from app.services.llm.nvidia_provider import (
    NvidiaProvider,
    NVIDIA_GENERATION_MODEL,
    NVIDIA_FALLBACK_GENERATION_MODEL,
    NVIDIA_RERANKING_MODEL,
    NVIDIA_RERANKING_URL,
)


def _not_found() -> NotFoundError:
    """Build the 404 NVIDIA returns when a NIM function has been retired."""
    request = httpx.Request("POST", "https://integrate.api.nvidia.com/v1/chat/completions")
    response = httpx.Response(404, request=request, json={"status": 404, "title": "Not Found"})
    return NotFoundError("Not Found", response=response, body=None)


def _completion(text: str) -> MagicMock:
    message = MagicMock()
    message.content = text
    choice = MagicMock()
    choice.message = message
    completion = MagicMock()
    completion.choices = [choice]
    return completion


def _provider() -> NvidiaProvider:
    return NvidiaProvider(api_key="nvapi-test", base_url="https://integrate.api.nvidia.com/v1")


def test_generation_models_are_hosted_ids():
    """Guard against regressing to the retired 70b NIM or a self-host-only ID."""
    assert NVIDIA_GENERATION_MODEL == "nvidia/nemotron-3-super-120b-a12b"
    assert NVIDIA_FALLBACK_GENERATION_MODEL == "nvidia/nemotron-3.5-lightning-30b-a3b"


@pytest.mark.asyncio
async def test_generate_falls_back_to_secondary_model_on_404():
    """A retired primary NIM should fall through to the secondary before erroring."""
    provider = _provider()
    calls: list[str] = []

    async def create(**kwargs):
        calls.append(kwargs["model"])
        if kwargs["model"] == NVIDIA_GENERATION_MODEL:
            raise _not_found()
        return _completion("PD model is compliant.")

    provider.client.chat.completions.create = AsyncMock(side_effect=create)

    result = await provider.generate("Assess the PD model")

    assert result == "PD model is compliant."
    assert calls == [NVIDIA_GENERATION_MODEL, NVIDIA_FALLBACK_GENERATION_MODEL]
    await provider.aclose()


@pytest.mark.asyncio
async def test_generate_raises_when_every_model_404s():
    """With no live model left, the 404 propagates so the router fails over to Gemini."""
    provider = _provider()
    provider.client.chat.completions.create = AsyncMock(side_effect=lambda **kw: (_ for _ in ()).throw(_not_found()))

    with pytest.raises(NotFoundError):
        await provider.generate("Assess the PD model")

    await provider.aclose()


@pytest.mark.asyncio
async def test_generate_stream_swaps_model_before_yielding():
    """Stream setup 404s before any chunk is emitted, so the swap stays safe."""
    provider = _provider()
    calls: list[str] = []

    class _Stream:
        def __aiter__(self):
            return self

        def __init__(self):
            self._tokens = iter(["Basel ", "III"])

        async def __anext__(self):
            try:
                token = next(self._tokens)
            except StopIteration:
                raise StopAsyncIteration
            delta = MagicMock()
            delta.content = token
            choice = MagicMock()
            choice.delta = delta
            chunk = MagicMock()
            chunk.choices = [choice]
            return chunk

    async def create(**kwargs):
        calls.append(kwargs["model"])
        if kwargs["model"] == NVIDIA_GENERATION_MODEL:
            raise _not_found()
        return _Stream()

    provider.client.chat.completions.create = AsyncMock(side_effect=create)

    chunks = [chunk async for chunk in provider.generate_stream("Explain Basel III")]

    assert chunks == ["Basel ", "III"]
    assert calls == [NVIDIA_GENERATION_MODEL, NVIDIA_FALLBACK_GENERATION_MODEL]
    await provider.aclose()


@pytest.mark.asyncio
async def test_rerank_targets_the_retrieval_host_not_integrate():
    """Reranking lives on ai.api.nvidia.com with a model-in-path URL."""
    provider = _provider()
    captured: dict = {}

    async def post(url, json=None, **kwargs):
        captured["url"] = url
        captured["json"] = json
        request = httpx.Request("POST", url)
        return httpx.Response(
            200,
            request=request,
            json={"rankings": [{"index": 1, "logit": 4.2}, {"index": 0, "logit": 1.1}]},
        )

    provider.httpx_client.post = AsyncMock(side_effect=post)

    results = await provider.rerank("capital adequacy", ["unrelated text", "capital adequacy ratio"])

    assert captured["url"] == NVIDIA_RERANKING_URL
    assert captured["url"].startswith("https://ai.api.nvidia.com/v1/retrieval/")
    assert NVIDIA_RERANKING_MODEL in captured["url"]
    assert captured["json"]["query"] == {"text": "capital adequacy"}
    assert captured["json"]["passages"] == [{"text": "unrelated text"}, {"text": "capital adequacy ratio"}]

    assert [r.index for r in results] == [1, 0]
    assert results[0].text == "capital adequacy ratio"
    await provider.aclose()

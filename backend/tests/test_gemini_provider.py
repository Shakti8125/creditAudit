from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.schemas.retrieval import RetrievalCandidate
from app.services.llm.gemini_provider import GeminiProvider, GeminiRerankError
from app.services.llm.router import LLMRouter
from app.services.retrieval.reranker import Reranker

PASSAGES = ["PSI thresholds", "Gini minimum of 0.40", "Unrelated appendix"]
API_KEY_INVALID = '{"error": {"code": 400, "status": "INVALID_ARGUMENT", "details": [{"reason": "API_KEY_INVALID"}]}}'


def _provider() -> GeminiProvider:
    return GeminiProvider(api_key="gemini-test")


@pytest.mark.asyncio
async def test_rerank_raises_when_every_passage_fails():
    """All-zero scores from a total failure must not masquerade as a ranking."""
    provider = _provider()
    provider.generate = AsyncMock(side_effect=RuntimeError(API_KEY_INVALID))

    with pytest.raises(GeminiRerankError) as exc_info:
        await provider.rerank("minimum Gini", PASSAGES, top_n=3)

    assert isinstance(exc_info.value.__cause__, RuntimeError)
    assert provider.generate.await_count == len(PASSAGES)
    await provider.aclose()


@pytest.mark.asyncio
async def test_rerank_partial_failure_scores_failed_passages_zero():
    """Only some passages failing keeps the existing behaviour: failures score 0.0."""
    provider = _provider()

    async def generate(prompt: str, **kwargs):
        if "Passage: Unrelated appendix" in prompt:
            raise RuntimeError("transient")
        return json.dumps({"score": 9.0 if "Passage: Gini" in prompt else 4.0})

    provider.generate = AsyncMock(side_effect=generate)

    results = await provider.rerank("minimum Gini", PASSAGES, top_n=3)

    assert [(r.index, r.score) for r in results] == [(1, 9.0), (0, 4.0), (2, 0.0)]
    await provider.aclose()


def _candidates() -> list[RetrievalCandidate]:
    return [
        RetrievalCandidate(chunk_text=text, source="CBUAE-MMG-2022", section=f"Section {i}", score=1.0 - i / 10, retrieval_method="hybrid_rrf")
        for i, text in enumerate(PASSAGES)
    ]


@pytest.mark.asyncio
async def test_reranker_falls_back_when_gemini_scores_nothing():
    """NVIDIA rerank down + Gemini failing every passage -> Reranker fallback, not 0.00 scores."""
    nvidia = MagicMock()
    nvidia.rerank = AsyncMock(side_effect=RuntimeError("nvidia rerank 503"))
    gemini = _provider()
    gemini.generate = AsyncMock(side_effect=RuntimeError(API_KEY_INVALID))
    router = LLMRouter(nvidia=nvidia, gemini=gemini)
    candidates = _candidates()

    reranked, fallback = await Reranker(router).rerank_with_status("minimum Gini", candidates, top_n=2)

    assert fallback is True
    assert [c.chunk_text for c in reranked] == PASSAGES[:2]
    assert [c.score for c in reranked] == [c.score for c in candidates[:2]]
    assert [r.error_type for r in router.call_log if r.provider == "gemini"] == ["GeminiRerankError"]
    await gemini.aclose()

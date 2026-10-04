"""Model IDs are settings, not constants in a provider (PR-01, AGENTS.md rule 9)."""

from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from openai import NotFoundError

from app.config import Settings, settings
from app.services.llm import model_catalog
from app.services.llm.gemini_provider import GeminiProvider
from app.services.llm.nvidia_provider import NvidiaProvider
from app.services.llm.router import LLMRouter, configured_model

APP_DIR = Path(__file__).resolve().parent.parent / "app"
# A provider-model-looking string literal, such as "nvidia/llama-..." or "gemini-3.6-flash".
MODEL_ID_LITERAL = re.compile(r"""["'](?:(?:nvidia|meta|google)/[\w.\-]+|gemini-(?!placeholder)[\w.\-]+)["']""")


def test_no_model_id_literal_lives_outside_config() -> None:
    offenders = {
        str(path.relative_to(APP_DIR)): MODEL_ID_LITERAL.findall(path.read_text(encoding="utf-8"))
        for path in APP_DIR.rglob("*.py")
        if path.name != "config.py"
    }

    assert {name: ids for name, ids in offenders.items() if ids} == {}


def test_defaults_name_the_current_models_and_none_of_the_retired_ones() -> None:
    defaults = Settings.model_construct()

    assert defaults.nvidia_rerank_model == "nvidia/llama-nemotron-rerank-1b-v2"
    assert defaults.gemini_generation_model == "gemini-3.6-flash"
    assert defaults.nvidia_embedding_model == "nvidia/nemotron-3-embed-1b"
    assert defaults.embedding_dimensions == 1024
    everything = " ".join(str(v) for v in defaults.model_dump().values())
    # retired (rerankqa, 2.0-flash, text-embedding-004) or flagged by D4 (2.5-flash)
    for retired_in_default_use in ("gemini-2.0-flash", "gemini-2.5-flash", "text-embedding-004"):
        assert retired_in_default_use not in everything
    assert "rerankqa" not in defaults.nvidia_rerank_model


def test_the_risky_behaviours_are_off_by_default() -> None:
    defaults = Settings.model_construct()

    assert defaults.llm_latency_routing is False  # D4: Gemini is failover-only
    assert defaults.rerank_llm_fallback is False  # no 20-call LLM reranker
    assert defaults.llm_startup_probe is False  # no provider calls at start-up
    assert defaults.embedding_send_dimensions is False  # unverified against the hosted NIM
    assert defaults.gemini_thinking_level == ""  # nothing is sent until the probe says it works


def test_settings_load_model_ids_and_flags_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NVIDIA_RERANK_MODEL", "nvidia/env-rerank")
    monkeypatch.setenv("NVIDIA_RERANK_URL", "https://example.test/rerank")
    monkeypatch.setenv("GEMINI_GENERATION_MODEL", "gemini-env-flash")
    monkeypatch.setenv("EMBEDDING_DIMENSIONS", "512")
    monkeypatch.setenv("LLM_STARTUP_PROBE", "true")
    monkeypatch.setenv("LLM_LATENCY_ROUTING", "true")

    loaded = Settings(_env_file=None)

    assert loaded.nvidia_rerank_model == "nvidia/env-rerank"
    assert loaded.nvidia_rerank_url == "https://example.test/rerank"
    assert loaded.gemini_generation_model == "gemini-env-flash"
    assert loaded.embedding_dimensions == 512
    assert loaded.llm_startup_probe is True and loaded.llm_latency_routing is True


def test_the_catalog_puts_the_configured_id_first_without_duplicates() -> None:
    cfg = Settings.model_construct(
        nvidia_rerank_model="nvidia/b",
        nvidia_rerank_candidates="nvidia/a, nvidia/b ,,nvidia/c",
        gemini_generation_model="gemini-x",
        gemini_generation_candidates="gemini-y,gemini-x",
        nvidia_generation_model="nvidia/p",
        nvidia_fallback_generation_model="nvidia/p",
    )

    assert model_catalog.nvidia_rerank_candidates(cfg) == ("nvidia/b", "nvidia/a", "nvidia/c")
    assert model_catalog.gemini_generation_candidates(cfg) == ("gemini-x", "gemini-y")
    assert model_catalog.nvidia_generation_models(cfg) == ("nvidia/p",)


def test_the_rerank_url_override_applies_to_the_configured_model_only() -> None:
    cfg = Settings.model_construct(nvidia_rerank_model="nvidia/b", nvidia_rerank_url=" https://example.test/r ")

    assert model_catalog.rerank_url(cfg=cfg) == "https://example.test/r"
    assert model_catalog.rerank_url("nvidia/b", cfg) == "https://example.test/r"
    assert model_catalog.rerank_url("nvidia/other", cfg) == "https://ai.api.nvidia.com/v1/retrieval/nvidia/other/reranking"
    assert model_catalog.rerank_url(cfg=Settings.model_construct(nvidia_rerank_model="nvidia/b")) == (
        "https://ai.api.nvidia.com/v1/retrieval/nvidia/b/reranking"
    )


# --- the providers use whatever the settings say --------------------------------------------


def _completion(text: str) -> MagicMock:
    completion = MagicMock()
    completion.choices = [MagicMock(message=MagicMock(content=text))]
    return completion


def _not_found() -> NotFoundError:
    request = httpx.Request("POST", "https://integrate.api.nvidia.com/v1/chat/completions")
    return NotFoundError("nf", response=httpx.Response(404, request=request), body=None)


async def test_nvidia_generation_uses_the_configured_primary_then_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "nvidia_generation_model", "nvidia/custom-primary")
    monkeypatch.setattr(settings, "nvidia_fallback_generation_model", "nvidia/custom-fallback")
    provider = NvidiaProvider(api_key="nvapi-test")
    calls: list[str] = []

    async def create(**kwargs):
        calls.append(kwargs["model"])
        if kwargs["model"] == "nvidia/custom-primary":
            raise _not_found()
        return _completion("ok")

    provider.client.chat.completions.create = AsyncMock(side_effect=create)

    assert await provider.generate("prompt") == "ok"

    assert calls == ["nvidia/custom-primary", "nvidia/custom-fallback"]
    assert provider.last_generation_model == "nvidia/custom-fallback"
    await provider.aclose()


async def test_nvidia_rerank_uses_the_configured_model_and_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "nvidia_rerank_model", "nvidia/custom-rerank")
    monkeypatch.setattr(settings, "nvidia_rerank_url", "https://example.test/custom/reranking")
    provider = NvidiaProvider(api_key="nvapi-test")
    seen: dict = {}

    async def post(url, json=None, **kwargs):
        seen.update(url=url, model=json["model"])
        return httpx.Response(200, json={"rankings": [{"index": 0, "logit": 2.0}]}, request=httpx.Request("POST", url))

    provider.httpx_client.post = AsyncMock(side_effect=post)

    await provider.rerank("q", ["a"])

    assert seen == {"url": "https://example.test/custom/reranking", "model": "nvidia/custom-rerank"}
    await provider.aclose()


def _gemini_with_fakes() -> GeminiProvider:
    gemini = GeminiProvider(api_key="gemini-test")

    async def stream():
        for part in ("Basel ", "III"):
            yield SimpleNamespace(text=part)

    gemini.client.aio.models.generate_content = AsyncMock(return_value=SimpleNamespace(text="gemini answer"))
    gemini.client.aio.models.generate_content_stream = AsyncMock(return_value=stream())
    return gemini


async def test_gemini_backup_serves_generate_with_the_configured_model_when_nvidia_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "gemini_generation_model", "gemini-custom-flash")
    nvidia = NvidiaProvider(api_key="nvapi-test")
    nvidia.client.chat.completions.create = AsyncMock(side_effect=RuntimeError("nvidia down"))
    gemini = _gemini_with_fakes()
    router = LLMRouter(nvidia=nvidia, gemini=gemini)

    assert await router.generate("prompt", system_prompt="system") == "gemini answer"

    assert gemini.client.aio.models.generate_content.await_args.kwargs["model"] == "gemini-custom-flash"
    served = router.call_log[-1]
    assert (served.provider, served.model, served.success) == ("gemini", "gemini-custom-flash", True)
    await nvidia.aclose()
    await gemini.aclose()


async def test_gemini_backup_serves_generate_stream_with_the_configured_model_when_nvidia_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "gemini_generation_model", "gemini-custom-flash")
    nvidia = NvidiaProvider(api_key="nvapi-test")
    nvidia.client.chat.completions.create = AsyncMock(side_effect=RuntimeError("nvidia down"))
    gemini = _gemini_with_fakes()
    router = LLMRouter(nvidia=nvidia, gemini=gemini)

    chunks = [c async for c in router.generate_stream("prompt")]

    assert chunks == ["Basel ", "III"]
    assert gemini.client.aio.models.generate_content_stream.await_args.kwargs["model"] == "gemini-custom-flash"
    await nvidia.aclose()
    await gemini.aclose()


async def test_gemini_backup_serves_a_structured_call_with_the_configured_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "gemini_generation_model", "gemini-custom-flash")
    nvidia = NvidiaProvider(api_key="nvapi-test")
    nvidia.client.chat.completions.create = AsyncMock(side_effect=RuntimeError("nvidia down"))
    gemini = _gemini_with_fakes()
    router = LLMRouter(nvidia=nvidia, gemini=gemini)
    schema = {"type": "object", "properties": {"x": {"type": "string"}}}

    await router.generate("prompt", json_schema=schema)

    call = gemini.client.aio.models.generate_content.await_args.kwargs
    assert call["model"] == "gemini-custom-flash"
    assert call["config"].response_mime_type == "application/json"
    assert call["config"].response_schema == schema  # the structured contract itself is PR-02's
    await nvidia.aclose()
    await gemini.aclose()


async def test_gemini_thinking_level_is_sent_only_when_set_and_never_for_structured_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gemini = _gemini_with_fakes()

    await gemini.generate("prompt")
    assert gemini.client.aio.models.generate_content.await_args.kwargs["config"].thinking_config is None

    monkeypatch.setattr(settings, "gemini_thinking_level", "low")
    await gemini.generate("prompt")
    config = gemini.client.aio.models.generate_content.await_args.kwargs["config"]
    assert config.thinking_config is not None and str(config.thinking_config.thinking_level.value) == "LOW"

    await gemini.generate("prompt", json_schema={"type": "object"})
    assert gemini.client.aio.models.generate_content.await_args.kwargs["config"].thinking_config is None

    [_ async for _ in gemini.generate_stream("prompt")]
    assert gemini.client.aio.models.generate_content_stream.await_args.kwargs["config"].thinking_config is not None
    await gemini.aclose()


def test_the_router_reports_the_configured_model_per_method(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "nvidia_rerank_model", "nvidia/custom-rerank")
    monkeypatch.setattr(settings, "nvidia_embedding_model", "nvidia/custom-embed")
    router = LLMRouter(nvidia=MagicMock(), gemini=MagicMock())

    assert configured_model("nvidia", "rerank") == "nvidia/custom-rerank"
    assert configured_model("nvidia", "embed") == "nvidia/custom-embed"
    assert configured_model("gemini", "embed") == "unknown"  # Gemini never serves embeddings
    assert router.get_routing_decision("rerank").model == "nvidia/custom-rerank"
    assert router.get_routing_decision("embed").model == "nvidia/custom-embed"

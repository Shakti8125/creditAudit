"""Tests for the PR-00 verification probe (``scripts/diag/pr00_probe.py``).

The probe runs once against production with real keys, so the property that
matters most is that its output never carries a secret or a tenant identifier.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx

from scripts.diag import pr00_probe as probe

FAKE_NVIDIA = "nvapi-FAKEKEY1234567890"
FAKE_GEMINI = "AIzaFAKEGEMINIKEY0123456789"
FAKE_PINECONE = "pcsk_FAKEPINECONEKEY"
FAKE_REDIS_URL = "https://fake-host-123.upstash.io"
FAKE_REDIS_TOKEN = "FAKEREDISTOKENvalue"
FAKE_INDEX = "fake-index-name"
TENANT_ID = "7d0c5a4e-1111-2222-3333-444455556666"
DOC_ID = "a1b2c3d4-aaaa-bbbb-cccc-ddddeeeeffff"
QA_BROKEN_JSON = '{\n\n{\n  "differences": [{"area": "algorithm", "v1": "LR", "v2": "GBM"}],, "summary": "x"}'
VALID_JSON = '{"differences": [{"area": "algorithm", "v1": "LR", "v2": "GBM"}], "summary": "Algorithm changed."}'


def _cfg() -> probe.ProbeConfig:
    return probe.ProbeConfig(
        nvidia_api_key=FAKE_NVIDIA,
        gemini_api_key=FAKE_GEMINI,
        pinecone_api_key=FAKE_PINECONE,
        pinecone_index_name=FAKE_INDEX,
        redis_url=FAKE_REDIS_URL,
        redis_token=FAKE_REDIS_TOKEN,
        rate_limit_enabled=True,
        lua_dir=Path(__file__).resolve().parent.parent / "lua",
    )


def _chat(content: str, finish: str = "stop") -> dict[str, Any]:
    return {
        "choices": [{"finish_reason": finish, "message": {"content": content}}],
        "usage": {"completion_tokens": 42},
    }


def _handler(request: httpx.Request) -> httpx.Response:
    url = str(request.url)
    assert "key=" not in url, "the Gemini key must travel in a header, never in the URL"
    body = json.loads(request.content) if request.content else {}
    if url.endswith("/v1/models"):
        return httpx.Response(200, json={"data": [{"id": m} for m in _cfg().generation_models]})
    if "llama-3.2-nv-rerankqa-1b-v2/reranking" in url:
        # A provider error that echoes the Authorization header must be scrubbed.
        return httpx.Response(404, json={"error": {"message": f"Function not found for Bearer {FAKE_NVIDIA}"}})
    if url.endswith("/reranking"):
        return httpx.Response(200, json={"rankings": [{"index": 0, "logit": 3.1}, {"index": 1, "logit": -4.0}]})
    if url.endswith("/chat/completions"):
        if "response_format" in body:
            return httpx.Response(400, json={"error": {"message": "response_format json_schema not supported"}})
        if "nvext" in body:
            return httpx.Response(200, json=_chat(VALID_JSON))
        if "guided_json" in body:
            return httpx.Response(200, json=_chat(QA_BROKEN_JSON, "length"))
        return httpx.Response(200, json=_chat("OK"))
    if url.endswith("/embeddings"):
        dim = body.get("dimensions") or 2048
        return httpx.Response(200, json={"data": [{"embedding": [0.0] * dim}]})
    if "generativelanguage.googleapis.com" in url:
        assert request.headers.get("x-goog-api-key") == FAKE_GEMINI
        if url.endswith(":generateContent"):
            config = body.get("generationConfig", {})
            text = VALID_JSON if "responseJsonSchema" in config else "OK"
            return httpx.Response(
                200,
                json={
                    "modelVersion": "gemini-3.6-flash",
                    "candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": text}]}}],
                },
            )
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"models": [{"name": "models/gemini-3.6-flash"}, {"name": "models/gemini-embedding-2"}]})
        model = request.url.path.rsplit("/", 1)[-1]
        if model in ("gemini-2.0-flash", "text-embedding-004"):
            return httpx.Response(404, json={"error": {"status": "NOT_FOUND", "message": f"models/{model} is not found"}})
        return httpx.Response(200, json={"name": f"models/{model}", "supportedGenerationMethods": ["generateContent"]})
    raise AssertionError(f"unexpected request {request.method} {url}")


class _FakeIndexList:
    def names(self) -> list[str]:
        return [FAKE_INDEX]


class _FakeIndex:
    def describe_index_stats(self) -> dict[str, Any]:
        return {
            "dimension": 1024,
            "total_vector_count": 30,
            "namespaces": {
                f"user-docs:{TENANT_ID}:{DOC_ID}": {"vector_count": 20},
                f"user-docs:{TENANT_ID}:other-doc": {"vector_count": 10},
            },
        }


class _FakePinecone:
    def list_indexes(self) -> _FakeIndexList:
        return _FakeIndexList()

    def describe_index(self, name: str) -> dict[str, Any]:
        assert name == FAKE_INDEX
        return {
            "name": name,
            "dimension": 1024,
            "metric": "cosine",
            "host": "fake-index-abc.svc.pinecone.io",
            "spec": {"serverless": {"cloud": "aws", "region": "us-east-1"}},
            "status": {"ready": True, "state": "Ready"},
            "deletion_protection": "disabled",
        }

    def Index(self, host: str | None = None) -> _FakeIndex:
        return _FakeIndex()


class _FakeRedis:
    def __init__(self) -> None:
        self.loaded: list[str] = []

    async def ping(self) -> str:
        return "PONG"

    async def script_load(self, script: str) -> str:
        self.loaded.append(script)
        return "0123abcd"

    async def close(self) -> None:
        return None


def _records(lines: list[str]) -> list[dict[str, Any]]:
    return [json.loads(line.removeprefix("PR00 ")) for line in lines]


async def _run(handler: Any = _handler, sections: str = "nvidia,gemini,pinecone,redis") -> tuple[list[str], _FakeRedis]:
    cfg = _cfg()
    lines: list[str] = []
    emit = probe.Emitter(cfg.secrets, sink=lines.append)
    redis = _FakeRedis()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await probe.run(
            cfg,
            set(sections.split(",")),
            emit,
            client,
            pinecone_factory=lambda key: _FakePinecone(),
            redis_factory=lambda url, token: redis,
        )
    return lines, redis


async def test_full_run_never_prints_secrets_or_tenant_ids() -> None:
    lines, _ = await _run()
    output = "\n".join(lines)
    for secret in (FAKE_NVIDIA, FAKE_GEMINI, FAKE_PINECONE, FAKE_REDIS_URL, FAKE_REDIS_TOKEN, FAKE_INDEX, TENANT_ID, DOC_ID):
        assert secret not in output
    assert "fake-host-123" not in output
    assert all(line.startswith("PR00 {") for line in lines)


async def test_full_run_reports_the_facts_pr00_needs() -> None:
    lines, redis = await _run()
    records = _records(lines)
    by_section: dict[str, list[dict[str, Any]]] = {}
    for rec in records:
        by_section.setdefault(rec["s"], []).append(rec)

    config = by_section["config"][0]
    assert config["redis_url_scheme"] == "https"
    assert config["redis_host_is_upstash"] is True
    assert config["rate_limit_enabled"] is True

    rerank = {r["model"]: r for r in by_section["nvidia_rerank"]}
    assert rerank["nvidia/llama-3.2-nv-rerankqa-1b-v2"]["status"] == 404
    assert "***" in rerank["nvidia/llama-3.2-nv-rerankqa-1b-v2"]["error"]
    new = rerank["nvidia/llama-nemotron-rerank-1b-v2"]
    assert (new["status"], new["rankings"], new["top_index"]) == (200, 2, 0)

    structured = by_section["nvidia_structured"]
    assert len(structured) == 7
    deployed = next(r for r in structured if r["variant"] == "deployed")
    assert deployed["thinking"] is None
    assert deployed["json_strict_ok"] is False and deployed["finish_reason"] == "length"
    assert all(r["schema_ok"] for r in structured if r["variant"] == "nvext_guided_json")
    assert all(r["status"] == 400 for r in structured if r["variant"] == "response_format_json_schema")

    embeds = {r["requested_dimensions"]: r for r in by_section["nvidia_embed"]}
    assert embeds[None]["dimension"] == 2048 and embeds[1024]["dimension"] == 1024
    # The app pins the size (EMBEDDING_DIMENSIONS=1024): the 2048-wide default is sliced, so it matches.
    assert by_section["embed_vs_index"][0] == {
        "s": "embed_vs_index",
        "embed_dimension": 2048,
        "pinned_dimension": 1024,
        "effective_dimension": 1024,
        "index_dimension": 1024,
        "match": True,
    }

    gemini = {r["model"]: r["status"] for r in by_section["gemini_model"]}
    assert gemini["gemini-2.0-flash"] == 404 and gemini["gemini-3.6-flash"] == 200
    assert [r["model_version"] for r in by_section["gemini_generate"]] == ["gemini-3.6-flash"] * 3
    gstruct = by_section["gemini_structured"]
    assert len(gstruct) == 1 and gstruct[0]["schema_field"] == "responseJsonSchema" and gstruct[0]["schema_ok"] is True

    stats = by_section["pinecone_stats"][0]
    assert stats["cbuae_manuals_present"] is False and stats["cbuae_manuals_vectors"] == 0
    assert stats["by_prefix"] == {"user-docs:*": {"namespaces": 2, "vectors": 30}}
    assert by_section["pinecone_index"][0]["spec_kind"] == "serverless"

    assert by_section["redis"][0] == {"s": "redis", "configured": True, "client_ok": True, "ping_ok": True, "script_load_ok": True}
    assert len(redis.loaded) == 1
    assert by_section["done"][0]["sections"] == ["gemini", "nvidia", "pinecone", "redis"]


async def test_a_broken_section_does_not_stop_the_others() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/v1/models"):
            return httpx.Response(200, content=b"<html>not json</html>")
        return _handler(request)

    lines, _ = await _run(handler)
    records = _records(lines)
    assert {"s": "section_error", "section": "nvidia", "error_class": "JSONDecodeError"} in records
    assert any(r["s"] == "gemini_model" for r in records)
    assert any(r["s"] == "redis" for r in records)


async def test_only_selected_sections_run() -> None:
    lines, redis = await _run(sections="redis")
    sections = {r["s"] for r in _records(lines)}
    assert sections == {"config", "redis", "done"}
    assert len(redis.loaded) == 1


def test_scrub_removes_secrets_and_credential_patterns() -> None:
    emit = probe.Emitter([FAKE_NVIDIA, FAKE_REDIS_URL])
    assert emit.scrub(f"x {FAKE_NVIDIA} y") == "x *** y"
    assert "nvapi-" not in emit.scrub("Bearer nvapi-anotherkey")
    assert "AIza" not in emit.scrub("bad key AIzaSyA1234567890abcdef")
    assert "secret" not in emit.scrub("GET https://host/path?key=secret")
    assert len(emit.scrub("a" * 1000)) == 200


def test_tolerant_json() -> None:
    assert probe.tolerant_json("```json\n" + VALID_JSON + "\n```") is not None
    assert probe.tolerant_json("<think>plan</think>" + VALID_JSON + " trailing text") is not None
    assert probe.tolerant_json(QA_BROKEN_JSON) is None
    assert probe.tolerant_json("no json here") is None
    assert probe.strict_json_ok(VALID_JSON) is True
    assert probe.strict_json_ok("```json\n" + VALID_JSON + "\n```") is False
    assert probe.schema_ok(json.loads(VALID_JSON)) is True
    assert probe.schema_ok({"differences": [], "summary": "x"}) is False


def test_summarise_namespaces_hides_ids() -> None:
    summary = probe.summarise_namespaces(
        {
            "cbuae-manuals": {"vector_count": 0},
            f"user-docs:{TENANT_ID}:{DOC_ID}": {"vector_count": 5},
            "reg-2026-10": {"vector_count": 7},
            "somebody-else": {"vector_count": 1},
        }
    )
    assert TENANT_ID not in json.dumps(summary) and "somebody-else" not in json.dumps(summary)
    assert summary["cbuae_manuals_present"] is True and summary["cbuae_manuals_vectors"] == 0
    assert summary["by_prefix"]["reg-*"] == {"namespaces": 1, "vectors": 7}
    assert summary["by_prefix"]["(other)"] == {"namespaces": 1, "vectors": 1}


def test_gemini_openapi_schema_uppercases_types() -> None:
    converted = probe._gemini_openapi_schema(probe.DIFF_SCHEMA)
    assert converted["type"] == "OBJECT"
    assert converted["properties"]["differences"]["items"]["properties"]["area"]["type"] == "STRING"


# --- PR-01: the probe checks the models the app is configured to call -------------------------


def _cfg_with(**overrides: Any) -> probe.ProbeConfig:
    from app.config import Settings

    base = _cfg()
    base.models = Settings.model_construct(**overrides)
    return base


async def _run_cfg(cfg: probe.ProbeConfig, sections: str = "nvidia,gemini,pinecone", handler: Any = _handler):
    lines: list[str] = []
    emit = probe.Emitter(cfg.secrets, sink=lines.append)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await probe.run(
            cfg, set(sections.split(",")), emit, client, pinecone_factory=lambda key: _FakePinecone()
        )
    return _records(lines)


def test_probe_candidates_come_from_the_same_settings_as_the_app() -> None:
    from app.config import Settings
    from app.services.llm import model_catalog

    cfg = _cfg()
    defaults = Settings.model_construct()
    assert cfg.rerank_models == model_catalog.nvidia_rerank_candidates(defaults)
    assert cfg.generation_models == model_catalog.nvidia_generation_models(defaults)
    assert cfg.gemini_chain == model_catalog.gemini_generation_candidates(defaults)
    # the retired IDs are looked up too, so the probe can confirm they are gone
    assert {"gemini-2.0-flash", "text-embedding-004"} <= set(cfg.gemini_models)

    custom = _cfg_with(nvidia_rerank_model="nvidia/custom-rerank-x", gemini_generation_model="gemini-custom-flash")
    assert custom.rerank_models[0] == "nvidia/custom-rerank-x"
    assert custom.gemini_chain[0] == "gemini-custom-flash"
    assert custom.gemini_models[0] == "gemini-custom-flash"


async def test_the_configured_model_is_checked_first_and_marked() -> None:
    cfg = _cfg_with(nvidia_rerank_model="nvidia/custom-rerank-x", gemini_generation_model="gemini-3.5-flash")
    urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url).endswith("/reranking"):
            urls.append(str(request.url))
            return httpx.Response(200, json={"rankings": [{"index": 0, "logit": 1.0}]})
        return _handler(request)

    records = await _run_cfg(cfg, handler=handler)
    rerank = [r for r in records if r["s"] == "nvidia_rerank"]

    assert rerank[0]["model"] == "nvidia/custom-rerank-x" and rerank[0]["configured"] is True
    assert all(r["configured"] is False for r in rerank[1:])
    assert urls[0] == "https://ai.api.nvidia.com/v1/retrieval/nvidia/custom-rerank-x/reranking"
    gemini = [r for r in records if r["s"] == "gemini_generate"]
    assert [r["model"] for r in gemini][0] == "gemini-3.5-flash" and gemini[0]["configured"] is True
    config = next(r for r in records if r["s"] == "config")
    assert config["configured_models"]["nvidia_rerank"] == "nvidia/custom-rerank-x"


async def test_an_unpinned_dimension_is_compared_as_the_model_returns_it() -> None:
    records = await _run_cfg(_cfg_with(embedding_dimensions=0))

    row = next(r for r in records if r["s"] == "embed_vs_index")
    assert (row["embed_dimension"], row["effective_dimension"], row["match"]) == (2048, 2048, False)

from __future__ import annotations

import httpx

from scripts.demo import preflight
from scripts.diag import pr00_probe

NVIDIA_OK = [
    {"s": "nvidia_rerank", "model": "nvidia/llama-nemotron-rerank-1b-v2", "status": 200},
    {"s": "nvidia_generate", "model": "nvidia/nemotron-3-super-120b-a12b", "status": 200, "ms": 812},
    {"s": "nvidia_embed", "model": "nvidia/nemotron-3-embed-1b", "requested_dimensions": None, "status": 200, "dimension": 1024},
    {"s": "nvidia_structured", "variant": "deployed", "thinking": None, "status": 200, "finish_reason": "stop", "schema_ok": True},
]
PINECONE_OK = [
    {"s": "pinecone_index", "ok": True, "configured_index_listed": True, "ready": True, "dimension": 1024, "metric": "cosine"},
    {"s": "embed_vs_index", "embed_dimension": 1024, "index_dimension": 1024, "match": True},
]
GEMINI_OK = [{"s": "gemini_generate", "model": "gemini-3.6-flash", "status": 200}]


def by_name(checks):
    return {c.name: c for c in checks}


def test_everything_working_is_ready_with_no_warnings():
    checks = preflight.evaluate(NVIDIA_OK + PINECONE_OK + GEMINI_OK)

    assert all(c.level == preflight.OK for c in checks)
    assert preflight.verdict(checks) == (True, "READY.")


def test_missing_keys_fail_the_required_checks_and_name_the_variable():
    records = [{"s": "nvidia_skipped"}, {"s": "pinecone_skipped"}, {"s": "gemini_skipped"}]
    checks = by_name(preflight.evaluate(records))

    assert checks["Primary LLM answers"].level == preflight.FAIL
    assert "NVIDIA_API_KEY" in checks["Primary LLM answers"].detail
    assert "PINECONE_INDEX_NAME" in checks["Pinecone index ready"].detail
    assert checks["Gemini backup (free tier)"].level == preflight.WARN
    ready, summary = preflight.verdict(list(checks.values()))
    assert not ready and summary.startswith("NOT READY")


def test_a_dimension_mismatch_is_a_required_failure():
    mismatch = [
        {"s": "embed_vs_index", "embed_dimension": 2048, "index_dimension": 1024, "match": False}
    ]
    checks = by_name(preflight.evaluate(NVIDIA_OK + PINECONE_OK[:1] + mismatch + GEMINI_OK))

    check = checks["Embedding size matches the index"]
    assert check.level == preflight.FAIL and check.required
    assert "2048" in check.detail and "1024" in check.detail


def test_an_index_that_is_not_ready_fails():
    index = [{"s": "pinecone_index", "ok": True, "configured_index_listed": True, "ready": False, "state": "Initializing"}]
    checks = by_name(preflight.evaluate(NVIDIA_OK + index + GEMINI_OK))

    assert checks["Pinecone index ready"].level == preflight.FAIL
    assert "Initializing" in checks["Pinecone index ready"].detail


def test_a_dead_reranker_is_only_a_warning():
    records = [r for r in NVIDIA_OK if r["s"] != "nvidia_rerank"] + [
        {"s": "nvidia_rerank", "model": "old", "status": 404}
    ]
    checks = preflight.evaluate(records + PINECONE_OK + GEMINI_OK)

    rerank = by_name(checks)["Reranker"]
    assert rerank.level == preflight.WARN and not rerank.required
    assert "old: 404" in rerank.detail
    assert preflight.verdict(checks) == (True, "READY with 1 warning(s).")


def test_structured_output_names_the_variant_that_works_when_the_deployed_one_fails():
    structured = [
        {"s": "nvidia_structured", "variant": "deployed", "status": 200, "finish_reason": "length", "schema_ok": False},
        {"s": "nvidia_structured", "variant": "nvext_guided_json", "thinking": False, "status": 200, "finish_reason": "stop", "schema_ok": True},
    ]
    records = [r for r in NVIDIA_OK if r["s"] != "nvidia_structured"] + structured
    check = by_name(preflight.evaluate(records + PINECONE_OK + GEMINI_OK))["Structured output (gap analysis, compare)"]

    assert check.level == preflight.WARN
    assert "nvext_guided_json" in check.detail and "thinking off" in check.detail


def test_render_lists_every_check_and_the_verdict_without_colour_codes():
    text = preflight.render(preflight.evaluate(NVIDIA_OK + PINECONE_OK + GEMINI_OK), color=False)

    assert "\033[" not in text
    assert text.count("OK  ") == 7
    assert text.rstrip().endswith("READY.")


async def test_collect_runs_the_probe_quietly_and_parses_its_records(monkeypatch, capsys):
    async def fake_run(cfg, sections, emit, client, **_kwargs):
        emit("nvidia_generate", model="m", status=200, ms=5)
        emit("done", sections=sorted(sections))
        return {}

    monkeypatch.setattr(pr00_probe, "run", fake_run)
    cfg = pr00_probe.ProbeConfig(nvidia_api_key="nvapi-secret-value")

    async with httpx.AsyncClient() as client:
        records = await preflight.collect(cfg, {"nvidia"}, client)

    assert [r["s"] for r in records] == ["nvidia_generate", "done"]
    assert capsys.readouterr().out == ""  # the probe's own lines are not echoed


def test_default_sections_skip_redis():
    assert "redis" not in preflight.DEFAULT_SECTIONS


def test_a_dead_configured_reranker_names_the_candidate_that_works():
    rerank = [
        {"s": "nvidia_rerank", "model": "nvidia/old-rerank", "configured": True, "status": 404},
        {"s": "nvidia_rerank", "model": "nvidia/new-rerank", "configured": False, "status": 200},
    ]
    records = [r for r in NVIDIA_OK if r["s"] != "nvidia_rerank"] + rerank
    check = by_name(preflight.evaluate(records + PINECONE_OK + GEMINI_OK))["Reranker"]

    assert check.level == preflight.WARN and not check.required
    assert "NVIDIA_RERANK_MODEL=nvidia/new-rerank" in check.detail
    assert "nvidia/old-rerank returned 404" in check.detail


def test_a_working_configured_reranker_is_ok_even_when_a_candidate_is_dead():
    rerank = [
        {"s": "nvidia_rerank", "model": "nvidia/new-rerank", "configured": True, "status": 200},
        {"s": "nvidia_rerank", "model": "nvidia/old-rerank", "configured": False, "status": 404},
    ]
    records = [r for r in NVIDIA_OK if r["s"] != "nvidia_rerank"] + rerank
    check = by_name(preflight.evaluate(records + PINECONE_OK + GEMINI_OK))["Reranker"]

    assert check.level == preflight.OK and "nvidia/new-rerank" in check.detail


def test_a_dead_configured_gemini_model_names_the_one_that_works():
    gemini = [
        {"s": "gemini_generate", "model": "gemini-a", "configured": True, "status": 404},
        {"s": "gemini_generate", "model": "gemini-b", "configured": False, "status": 200},
    ]
    check = by_name(preflight.evaluate(NVIDIA_OK + PINECONE_OK + gemini))["Gemini backup (free tier)"]

    assert check.level == preflight.WARN
    assert "GEMINI_GENERATION_MODEL=gemini-b" in check.detail


def test_a_pinned_dimension_that_slices_the_model_output_matches_the_index():
    sliced = [{"s": "embed_vs_index", "embed_dimension": 2048, "pinned_dimension": 1024, "effective_dimension": 1024, "index_dimension": 1024, "match": True}]
    check = by_name(preflight.evaluate(NVIDIA_OK + PINECONE_OK[:1] + sliced + GEMINI_OK))["Embedding size matches the index"]

    assert check.level == preflight.OK
    assert "1024" in check.detail and "2048" in check.detail and "slices" in check.detail

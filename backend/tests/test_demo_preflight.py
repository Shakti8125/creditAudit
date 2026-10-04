from __future__ import annotations

import httpx

from scripts.demo import preflight
from scripts.diag import pr00_probe

NVIDIA_OK = [
    {"s": "nvidia_rerank", "model": "nvidia/llama-nemotron-rerank-1b-v2", "status": 200},
    {"s": "nvidia_generate", "model": "nvidia/nemotron-3-super-120b-a12b", "status": 200, "ms": 812},
    {"s": "nvidia_embed", "model": "nvidia/nemotron-3-embed-1b", "requested_dimensions": None, "status": 200, "dimension": 1024},
    {"s": "nvidia_structured", "variant": "deployed", "thinking": None, "status": 200, "finish_reason": "length", "schema_ok": False},
    {"s": "nvidia_structured", "variant": "nvext_guided_json", "thinking": False, "configured": True, "max_tokens": 4096,
     "status": 200, "finish_reason": "stop", "schema_ok": True},
]
PINECONE_OK = [
    {"s": "pinecone_index", "ok": True, "configured_index_listed": True, "ready": True, "dimension": 1024, "metric": "cosine"},
    {"s": "embed_vs_index", "embed_dimension": 1024, "index_dimension": 1024, "match": True},
]
GEMINI_OK = [
    {"s": "gemini_generate", "model": "gemini-3.6-flash", "status": 200},
    {"s": "gemini_structured", "schema_field": "responseJsonSchema", "configured": True, "status": 200,
     "finish_reason": "STOP", "schema_ok": True},
]


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


STRUCTURED = "Structured output (gap analysis, compare)"
GEMINI_STRUCTURED = "Structured output on the Gemini backup"


def _structured_rows(*rows: dict) -> list[dict]:
    """Probe records with the NVIDIA structured rows replaced by ``rows``."""
    return [r for r in NVIDIA_OK if r["s"] != "nvidia_structured"] + [{"s": "nvidia_structured", **r} for r in rows]


def _row(variant: str, thinking: bool, *, configured: bool = False, **fields) -> dict:
    base = {"variant": variant, "thinking": thinking, "configured": configured, "max_tokens": 4096,
            "status": 200, "finish_reason": "stop", "schema_ok": True}
    return {**base, **fields}


def test_a_working_configured_structured_request_is_ok_and_says_which_one() -> None:
    check = by_name(preflight.evaluate(NVIDIA_OK + PINECONE_OK + GEMINI_OK))[STRUCTURED]

    assert check.level == preflight.OK
    assert "NVIDIA_STRUCTURED_MODE=nvext_guided_json" in check.detail and "thinking off" in check.detail


def test_a_failing_configured_mode_names_the_mode_that_works_and_the_setting() -> None:
    records = _structured_rows(
        _row("nvext_guided_json", False, configured=True, status=400),
        _row("top_guided_json", False, schema_ok=False),
        _row("response_format_json_schema", False),
    )
    check = by_name(preflight.evaluate(records + PINECONE_OK + GEMINI_OK))[STRUCTURED]

    assert check.level == preflight.WARN and not check.required
    assert "answered 400" in check.detail
    assert "set NVIDIA_STRUCTURED_MODE=response_format_json_schema in backend/.env" in check.detail
    assert "NVIDIA_STRUCTURED_DISABLE_THINKING" not in check.detail  # only the mode has to change


def test_when_only_a_thinking_on_variant_works_both_settings_are_named() -> None:
    records = _structured_rows(
        _row("nvext_guided_json", False, configured=True, status=400, error="chat_template_kwargs not allowed"),
        _row("nvext_guided_json", True),
    )
    check = by_name(preflight.evaluate(records + PINECONE_OK + GEMINI_OK))[STRUCTURED]

    assert "NVIDIA_STRUCTURED_MODE=nvext_guided_json" in check.detail
    assert "NVIDIA_STRUCTURED_DISABLE_THINKING=false" in check.detail


def test_a_configured_request_that_thinks_in_the_budget_reports_the_budget_and_the_reasoning() -> None:
    records = _structured_rows(
        _row("nvext_guided_json", False, configured=True, finish_reason="length", schema_ok=False,
             completion_tokens=4096, reasoning_len=9000),
    )
    check = by_name(preflight.evaluate(records + PINECONE_OK + GEMINI_OK))[STRUCTURED]

    assert check.level == preflight.WARN
    assert "cut off at the 4096-token budget" in check.detail and "reasoning" in check.detail


def test_reasoning_text_with_thinking_off_is_reported() -> None:
    records = _structured_rows(
        _row("nvext_guided_json", False, configured=True, schema_ok=False, think_tag_in_content=True),
    )
    check = by_name(preflight.evaluate(records + PINECONE_OK + GEMINI_OK))[STRUCTURED]

    assert "reasoning text although thinking is off" in check.detail


def test_no_working_variant_says_so_and_names_the_backup() -> None:
    records = _structured_rows(
        _row("nvext_guided_json", False, configured=True, schema_ok=False),
        _row("top_guided_json", False, schema_ok=False),
    )
    check = by_name(preflight.evaluate(records + PINECONE_OK + GEMINI_OK))[STRUCTURED]

    assert check.level == preflight.WARN
    assert "no other variant returned valid JSON" in check.detail and "Gemini backup" in check.detail


def test_records_without_a_configured_row_are_not_trusted() -> None:
    records = _structured_rows(_row("nvext_guided_json", False))
    check = by_name(preflight.evaluate(records + PINECONE_OK + GEMINI_OK))[STRUCTURED]

    assert check.level == preflight.WARN and "did not run" in check.detail


def test_a_working_gemini_structured_form_is_ok() -> None:
    check = by_name(preflight.evaluate(NVIDIA_OK + PINECONE_OK + GEMINI_OK))[GEMINI_STRUCTURED]

    assert check.level == preflight.OK and "responseJsonSchema" in check.detail


def test_a_rejected_first_gemini_form_names_the_one_that_works_and_the_setting() -> None:
    gemini = [r for r in GEMINI_OK if r["s"] != "gemini_structured"] + [
        {"s": "gemini_structured", "schema_field": "responseJsonSchema", "configured": True, "status": 400},
        {"s": "gemini_structured", "schema_field": "responseSchema", "configured": False, "status": 200,
         "finish_reason": "STOP", "schema_ok": True},
    ]
    check = by_name(preflight.evaluate(NVIDIA_OK + PINECONE_OK + gemini))[GEMINI_STRUCTURED]

    assert check.level == preflight.WARN and not check.required
    assert "was rejected (status 400)" in check.detail and "falls back to it by itself" in check.detail
    assert "GEMINI_STRUCTURED_SCHEMA_MODE=response_schema" in check.detail


def test_a_gemini_form_that_is_accepted_but_returns_bad_json_is_not_described_as_a_fallback() -> None:
    gemini = [r for r in GEMINI_OK if r["s"] != "gemini_structured"] + [
        {"s": "gemini_structured", "schema_field": "responseSchema", "configured": True, "status": 200,
         "finish_reason": "STOP", "schema_ok": False},
        {"s": "gemini_structured", "schema_field": "responseJsonSchema", "configured": False, "status": 200,
         "finish_reason": "STOP", "schema_ok": True},
    ]
    check = by_name(preflight.evaluate(NVIDIA_OK + PINECONE_OK + gemini))[GEMINI_STRUCTURED]

    assert "not valid JSON" in check.detail and "falls back" not in check.detail
    assert "GEMINI_STRUCTURED_SCHEMA_MODE=response_json_schema" in check.detail


def test_gemini_structured_failing_in_both_forms_points_at_a_thinking_level_if_one_is_set() -> None:
    gemini = [r for r in GEMINI_OK if r["s"] != "gemini_structured"] + [
        {"s": "gemini_structured", "schema_field": "responseJsonSchema", "configured": True, "status": 400,
         "thinking_level": "low"},
        {"s": "gemini_structured", "schema_field": "responseSchema", "configured": False, "status": 400,
         "thinking_level": "low"},
    ]
    check = by_name(preflight.evaluate(NVIDIA_OK + PINECONE_OK + gemini))[GEMINI_STRUCTURED]

    assert check.level == preflight.WARN
    assert "GEMINI_STRUCTURED_THINKING_LEVEL=low" in check.detail


def test_gemini_structured_cut_off_names_the_budget_setting() -> None:
    gemini = [r for r in GEMINI_OK if r["s"] != "gemini_structured"] + [
        {"s": "gemini_structured", "schema_field": "responseJsonSchema", "configured": True, "status": 200,
         "finish_reason": "MAX_TOKENS", "schema_ok": False, "max_output_tokens": 4096},
    ]
    check = by_name(preflight.evaluate(NVIDIA_OK + PINECONE_OK + gemini))[GEMINI_STRUCTURED]

    assert "STRUCTURED_MAX_TOKENS" in check.detail


def test_gemini_structured_is_skipped_without_a_key() -> None:
    check = by_name(preflight.evaluate([{"s": "nvidia_skipped"}, {"s": "gemini_skipped"}]))[GEMINI_STRUCTURED]

    assert check.level == preflight.WARN and "no Gemini key" in check.detail


def test_render_lists_every_check_and_the_verdict_without_colour_codes():
    text = preflight.render(preflight.evaluate(NVIDIA_OK + PINECONE_OK + GEMINI_OK), color=False)

    assert "\033[" not in text
    assert text.count("OK  ") == 8
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

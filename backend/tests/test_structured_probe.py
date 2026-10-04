"""The probe's structured-output rows are the requests the app itself would send (PR-02).

``scripts/demo.sh preflight`` reads these rows to say whether the CONFIGURED request returns
valid JSON. So each row must be built from the same settings and the same request builder as
the app, and exactly one row per provider must be marked ``configured``.
"""

from __future__ import annotations

import json
from typing import Any

import httpx

from tests.test_pr00_probe import _cfg, _cfg_with, _handler, _run_cfg


def _capture(sink: list[tuple[str, dict[str, Any]]]) -> Any:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and (
            str(request.url).endswith("/chat/completions") or str(request.url).endswith(":generateContent")
        ):
            sink.append((str(request.url), json.loads(request.content)))
        return _handler(request)

    return handler


def _structured_chat_bodies(sink: list[tuple[str, dict[str, Any]]]) -> list[dict[str, Any]]:
    return [
        body
        for url, body in sink
        if url.endswith("/chat/completions") and ("nvext" in body or "guided_json" in body or "response_format" in body)
    ]


async def test_nvidia_structured_rows_send_the_apps_forms_budget_and_thinking_flag() -> None:
    sent: list[tuple[str, dict[str, Any]]] = []
    records = await _run_cfg(_cfg_with(structured_max_tokens=3000), handler=_capture(sent))
    bodies = _structured_chat_bodies(sent)
    rows = [r for r in records if r["s"] == "nvidia_structured"]

    assert len(bodies) == len(rows) == 7
    legacy = bodies[0]  # the baseline: what the app sent before PR-02
    assert "guided_json" in legacy and "nvext" not in legacy and "chat_template_kwargs" not in legacy
    assert (legacy["max_tokens"], legacy["temperature"]) == (1024, 0.7)
    for body in bodies[1:]:
        assert body["max_tokens"] == 3000 and body["temperature"] == 0.2
    by_form = [("nvext" in b, "guided_json" in b, "response_format" in b) for b in bodies[1:]]
    assert by_form == [(True, False, False), (False, True, False), (False, False, True)] * 2
    assert [b["chat_template_kwargs"]["enable_thinking"] for b in bodies[1:]] == [False] * 3 + [True] * 3
    assert all(r["max_tokens"] == 3000 for r in rows[1:])


async def test_exactly_one_nvidia_row_is_marked_configured_and_it_follows_the_settings() -> None:
    default_rows = [r for r in await _run_cfg(_cfg()) if r["s"] == "nvidia_structured"]
    assert [(r["variant"], r["thinking"]) for r in default_rows if r["configured"]] == [("nvext_guided_json", False)]

    cfg = _cfg_with(nvidia_structured_mode="response_format_json_schema", nvidia_structured_disable_thinking=False)
    rows = [r for r in await _run_cfg(cfg) if r["s"] == "nvidia_structured"]
    assert [(r["variant"], r["thinking"]) for r in rows if r["configured"]] == [("response_format_json_schema", True)]
    assert not next(r for r in rows if r["variant"] == "deployed")["configured"]


async def test_gemini_structured_row_uses_the_budget_the_form_order_and_thinking_level() -> None:
    sent: list[tuple[str, dict[str, Any]]] = []
    cfg = _cfg_with(
        structured_max_tokens=3000,
        gemini_structured_schema_mode="response_schema",
        gemini_structured_thinking_level="low",
    )
    records = await _run_cfg(cfg, handler=_capture(sent))
    bodies = [
        body
        for url, body in sent
        if url.endswith(":generateContent") and "responseMimeType" in body["generationConfig"]
    ]
    rows = [r for r in records if r["s"] == "gemini_structured"]

    assert len(bodies) == 2  # the fake rejects responseSchema, so the other form is tried
    first = bodies[0]["generationConfig"]
    assert first["responseSchema"]["type"] == "OBJECT"  # the OpenAPI form: upper-case types
    assert first["maxOutputTokens"] == 3000 and first["thinkingConfig"] == {"thinkingLevel": "low"}
    assert "responseJsonSchema" in bodies[1]["generationConfig"]
    assert [r["schema_field"] for r in rows] == ["responseSchema", "responseJsonSchema"]
    assert rows[0]["configured"] is True and rows[1]["configured"] is False
    assert rows[0]["thinking_level"] == "low" and rows[0]["max_output_tokens"] == 3000


async def test_gemini_structured_defaults_send_no_thinking_and_try_the_json_schema_form_first() -> None:
    sent: list[tuple[str, dict[str, Any]]] = []
    records = await _run_cfg(_cfg(), handler=_capture(sent))
    bodies = [
        body
        for url, body in sent
        if url.endswith(":generateContent") and "responseMimeType" in body["generationConfig"]
    ]

    assert len(bodies) == 1 and "responseJsonSchema" in bodies[0]["generationConfig"]
    assert "thinkingConfig" not in bodies[0]["generationConfig"]
    row = next(r for r in records if r["s"] == "gemini_structured")
    assert row["configured"] is True and row["thinking_level"] == "" and row["max_output_tokens"] == 4096


async def test_the_probe_reports_the_structured_settings() -> None:
    config = next(r for r in await _run_cfg(_cfg()) if r["s"] == "config")

    assert config["configured_structured"] == {
        "nvidia_mode": "nvext_guided_json",
        "nvidia_disable_thinking": True,
        "max_tokens": 4096,
        "max_tokens_cap": 8192,
        "gemini_schema_mode": "auto",
        "gemini_thinking_level": "",
    }

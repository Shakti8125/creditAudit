"""Structured output: request forms, validation, one repair, truncation, failover (PR-02, QA-005).

No network: the NVIDIA tests send requests through ``httpx.MockTransport`` to a real
``AsyncOpenAI`` client, so they assert the JSON body the provider really sends. Gemini and the
router use fakes. What no test here can show is which request form the hosted NIM honours;
``scripts/demo.sh preflight`` reports that against the live API.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from google.genai import errors as genai_errors
from openai import AsyncOpenAI
from pydantic import BaseModel, ConfigDict, ValidationError

from app.config import Settings, settings
from app.schemas.compare import CompareResponse
from app.services.llm.base_provider import StructuredCompletion
from app.services.llm.gemini_provider import GeminiProvider
from app.services.llm.nvidia_provider import NvidiaProvider
from app.services.llm.router import AllProvidersUnavailableError, LLMRouter
from app.services.llm.structured import (
    STRUCTURED_MODES,
    StructuredOutputError,
    build_repair_prompt,
    neutral_finish_reason,
    nvidia_structured_extra_body,
    parse_structured,
    run_structured,
    to_openapi_schema,
)

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "differences": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "category": {"type": "string"},
                    "description": {"type": "string"},
                    "doc_a_value": {"type": "string"},
                    "doc_b_value": {"type": "string"},
                },
                "required": ["category", "description", "doc_a_value", "doc_b_value"],
            },
        },
        "summary": {"type": "string"},
    },
    "required": ["differences", "summary"],
}
GOOD = {
    "differences": [
        {"category": "Algorithm", "description": "Changed", "doc_a_value": "Logistic regression", "doc_b_value": "GBM"}
    ],
    "summary": "The algorithm changed.",
}
GOOD_JSON = json.dumps(GOOD)
# The real QA-005 output: a doubled opening brace and a stray comma, cut off mid-table.
QA_BROKEN = '{\n\n{\n  "differences": [{"category": "Algorithm", "description": "x"}],, "summary": "The tab'


class Tiny(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str
    score: float = 0.0


def completion(text: str, finish: str | None = "stop") -> StructuredCompletion:
    return StructuredCompletion(text=text, finish_reason=finish)


# --------------------------------------------------------------------------
# Settings
# --------------------------------------------------------------------------


def test_defaults_follow_the_plan() -> None:
    defaults = Settings.model_construct()

    assert defaults.nvidia_structured_mode == "nvext_guided_json"
    assert defaults.nvidia_structured_disable_thinking is True
    assert defaults.structured_max_tokens == 4096
    assert defaults.structured_max_tokens_cap == 8192
    assert defaults.gemini_structured_schema_mode == "auto"
    assert defaults.gemini_structured_thinking_level == ""  # nothing is sent until the probe says it works


def test_the_structured_mode_loads_from_the_environment_and_rejects_unknown_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NVIDIA_STRUCTURED_MODE", "response_format_json_schema")
    monkeypatch.setenv("STRUCTURED_MAX_TOKENS", "6000")
    monkeypatch.setenv("NVIDIA_STRUCTURED_DISABLE_THINKING", "false")
    loaded = Settings()
    assert loaded.nvidia_structured_mode == "response_format_json_schema"
    assert loaded.structured_max_tokens == 6000
    assert loaded.nvidia_structured_disable_thinking is False

    monkeypatch.setenv("NVIDIA_STRUCTURED_MODE", "guided")
    with pytest.raises(ValidationError):
        Settings()


# --------------------------------------------------------------------------
# NVIDIA request bodies, as sent on the wire
# --------------------------------------------------------------------------


def _chat_response(content: str, finish: str = "stop") -> dict[str, Any]:
    return {
        "id": "x",
        "object": "chat.completion",
        "created": 0,
        "model": "m",
        "choices": [{"index": 0, "finish_reason": finish, "message": {"role": "assistant", "content": content}}],
    }


def _nvidia_with_wire(replies: list[httpx.Response] | None = None) -> tuple[NvidiaProvider, list[dict[str, Any]]]:
    """A real NvidiaProvider whose OpenAI client talks to a mock transport; returns the bodies it sent."""
    sent: list[dict[str, Any]] = []
    queue = list(replies or [])

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        if queue:
            return queue.pop(0)
        return httpx.Response(200, json=_chat_response(GOOD_JSON))

    provider = NvidiaProvider(api_key="nvapi-test", base_url="https://integrate.api.nvidia.com/v1")
    provider.client = AsyncOpenAI(
        api_key="nvapi-test",
        base_url="https://integrate.api.nvidia.com/v1",
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    return provider, sent


@pytest.mark.parametrize(
    ("mode", "present", "absent"),
    [
        ("nvext_guided_json", ["nvext"], ["guided_json", "response_format"]),
        ("top_guided_json", ["guided_json"], ["nvext", "response_format"]),
        ("response_format_json_schema", ["response_format"], ["nvext", "guided_json"]),
    ],
)
async def test_each_nvidia_mode_puts_the_schema_where_the_mode_says(
    monkeypatch: pytest.MonkeyPatch, mode: str, present: list[str], absent: list[str]
) -> None:
    monkeypatch.setattr(settings, "nvidia_structured_mode", mode)
    provider, sent = _nvidia_with_wire()

    result = await provider.generate_structured("task", system_prompt="system", json_schema=SCHEMA)

    body = sent[0]
    assert result.text == GOOD_JSON and result.finish_reason == "stop"
    assert all(key in body for key in present) and not any(key in body for key in absent)
    if mode == "nvext_guided_json":
        assert body["nvext"] == {"guided_json": SCHEMA}
    elif mode == "top_guided_json":
        assert body["guided_json"] == SCHEMA
    else:
        assert body["response_format"]["type"] == "json_schema"
        assert body["response_format"]["json_schema"]["schema"] == SCHEMA
    # Thinking is off for every structured form, and the messages carry the prompts.
    assert body["chat_template_kwargs"] == {"enable_thinking": False}
    assert [m["role"] for m in body["messages"]] == ["system", "user"]
    await provider.aclose()


async def test_the_default_mode_is_nvext_not_the_top_level_field_the_audit_found() -> None:
    provider, sent = _nvidia_with_wire()

    await provider.generate_structured("task", json_schema=SCHEMA)

    assert "guided_json" not in sent[0]  # the QA-005 root cause: a top-level guided_json
    assert sent[0]["nvext"]["guided_json"] == SCHEMA
    await provider.aclose()


async def test_the_plain_generate_json_schema_path_uses_the_same_form_and_thinking_off() -> None:
    provider, sent = _nvidia_with_wire()

    await provider.generate("task", json_schema=SCHEMA)

    assert sent[0]["nvext"] == {"guided_json": SCHEMA} and "guided_json" not in sent[0]
    assert sent[0]["chat_template_kwargs"] == {"enable_thinking": False}
    await provider.aclose()


async def test_a_plain_call_sends_no_structured_fields() -> None:
    provider, sent = _nvidia_with_wire()

    await provider.generate("task")

    assert not {"nvext", "guided_json", "response_format", "chat_template_kwargs"} & sent[0].keys()
    await provider.aclose()


async def test_thinking_is_left_alone_when_the_setting_is_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "nvidia_structured_disable_thinking", False)
    provider, sent = _nvidia_with_wire()

    await provider.generate_structured("task", json_schema=SCHEMA)

    assert "chat_template_kwargs" not in sent[0]
    await provider.aclose()


async def test_the_router_sends_the_structured_budget_not_the_chat_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "structured_max_tokens", 3000)
    provider, sent = _nvidia_with_wire()
    gemini = MagicMock(is_configured=False)
    router = LLMRouter(nvidia=provider, gemini=gemini)

    result = await router.generate_structured("task", CompareResponse, SCHEMA)

    assert isinstance(result, CompareResponse)
    assert sent[0]["max_tokens"] == 3000  # not the 1024 chat default
    assert sent[0]["temperature"] < 0.7  # a validated reply should not sample like chat
    await provider.aclose()


async def test_the_structured_budget_defaults_to_4096() -> None:
    provider, sent = _nvidia_with_wire()
    router = LLMRouter(nvidia=provider, gemini=MagicMock(is_configured=False))

    await router.generate_structured("task", CompareResponse, SCHEMA)

    assert sent[0]["max_tokens"] == 4096
    await provider.aclose()


async def test_a_length_stop_is_reported_as_length() -> None:
    provider, _ = _nvidia_with_wire([httpx.Response(200, json=_chat_response('{"differences": [', "length"))])

    result = await provider.generate_structured("task", json_schema=SCHEMA)

    assert result.finish_reason == "length"
    await provider.aclose()


async def test_a_retired_primary_model_falls_back_before_the_router_fails_over() -> None:
    not_found = httpx.Response(404, json={"status": 404, "title": "Not Found"})
    provider, sent = _nvidia_with_wire([not_found])

    result = await provider.generate_structured("task", json_schema=SCHEMA)

    assert [b["model"] for b in sent] == [settings.nvidia_generation_model, settings.nvidia_fallback_generation_model]
    assert result.model == settings.nvidia_fallback_generation_model
    await provider.aclose()


def test_the_body_builder_rejects_an_unknown_mode() -> None:
    with pytest.raises(ValueError, match="NVIDIA_STRUCTURED_MODE"):
        nvidia_structured_extra_body("guided", SCHEMA)
    assert set(STRUCTURED_MODES) == {"nvext_guided_json", "top_guided_json", "response_format_json_schema"}


# --------------------------------------------------------------------------
# Parsing
# --------------------------------------------------------------------------


def test_valid_json_passes_through() -> None:
    value, reason, problem = parse_structured(GOOD_JSON, CompareResponse)

    assert value is not None and value.summary == "The algorithm changed." and reason is None and problem == ""


@pytest.mark.parametrize(
    "raw",
    [
        f"```json\n{GOOD_JSON}\n```",
        f"<think>Let me compare {{the}} two documents.</think>\n{GOOD_JSON}",
        f"{GOOD_JSON}\n\nHope this helps!",
        f"Here is the comparison:\n{GOOD_JSON}",
        f'{{\n\n{GOOD_JSON}',  # a stray leading brace: the next one starts the object
    ],
)
def test_fences_think_blocks_and_stray_text_are_tolerated(raw: str) -> None:
    value, reason, _ = parse_structured(raw, CompareResponse)

    assert value is not None and reason is None
    assert value.differences[0].category == "Algorithm"


def test_a_bare_number_in_a_text_field_is_accepted_and_does_not_cost_a_repair() -> None:
    raw = json.dumps(
        {
            "differences": [{"category": "Metrics", "description": "Gini up", "doc_a_value": 0.52, "doc_b_value": 0.58}],
            "summary": "Better.",
        }
    )

    value, reason, _ = parse_structured(raw, CompareResponse)

    assert reason is None and value is not None
    assert value.differences[0].doc_a_value == "0.52"


def test_the_real_qa_output_is_invalid_json_and_says_where() -> None:
    value, reason, problem = parse_structured(QA_BROKEN, CompareResponse)

    assert value is None and reason == "invalid_json"
    assert problem.startswith("invalid JSON") and "line" in problem


@pytest.mark.parametrize("raw", ["", "I cannot help with that.", "<think>never closed {\"differences\": []}"])
def test_text_without_an_object_is_invalid_json(raw: str) -> None:
    value, reason, problem = parse_structured(raw, CompareResponse)

    assert value is None and reason == "invalid_json" and "no JSON object" in problem


def test_a_complete_object_with_the_wrong_fields_is_a_schema_mismatch_naming_the_fields() -> None:
    value, reason, problem = parse_structured('{"differences": [], "text": "x"}', CompareResponse)

    assert value is None and reason == "schema_mismatch"
    assert "summary" in problem
    assert "x" not in problem.replace("summary", "")  # field paths and messages only, never the values


# --------------------------------------------------------------------------
# run_structured: truncation, one repair, the typed error
# --------------------------------------------------------------------------


class Script:
    """A provider call that answers from a list and remembers what it was asked."""

    def __init__(self, *replies: StructuredCompletion | Exception) -> None:
        self.replies = list(replies)
        self.calls: list[tuple[str, int]] = []

    async def __call__(self, prompt: str, max_tokens: int) -> StructuredCompletion:
        self.calls.append((prompt, max_tokens))
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


async def _run(call: Script, **kwargs: Any) -> CompareResponse:
    kwargs.setdefault("max_tokens", 4096)
    kwargs.setdefault("max_tokens_cap", 8192)
    return await run_structured(call, "task", CompareResponse, SCHEMA, **kwargs)


async def test_valid_output_makes_exactly_one_call() -> None:
    call = Script(completion(GOOD_JSON))

    result = await _run(call)

    assert result.summary == "The algorithm changed."
    assert len(call.calls) == 1


async def test_invalid_output_triggers_exactly_one_repair_call_and_then_succeeds() -> None:
    call = Script(completion(QA_BROKEN), completion(GOOD_JSON))

    result = await _run(call)

    assert result.differences[0].doc_b_value == "GBM"
    assert len(call.calls) == 2
    repair_prompt, repair_tokens = call.calls[1]
    assert "invalid JSON" in repair_prompt  # the validation problem
    assert "differences" in repair_prompt  # the model's own previous reply
    assert '"required"' in repair_prompt  # and the schema
    assert repair_tokens == 4096


async def test_the_repair_prompt_goes_through_the_egress_check_before_it_is_sent() -> None:
    seen: list[str] = []

    async def egress(prompt: str) -> None:
        seen.append(prompt)

    call = Script(completion('{"differences": []}'), completion(GOOD_JSON))
    await _run(call, egress_check=egress)

    assert seen == [call.calls[1][0]]


async def test_a_blocked_repair_prompt_is_never_sent() -> None:
    async def egress(prompt: str) -> None:
        raise PermissionError("blocked by egress")

    call = Script(completion(QA_BROKEN), completion(GOOD_JSON))

    with pytest.raises(PermissionError):
        await _run(call, egress_check=egress)

    assert len(call.calls) == 1


async def test_still_invalid_after_the_repair_raises_the_typed_error_without_a_third_call() -> None:
    call = Script(completion(QA_BROKEN), completion('{"differences": []}'))

    with pytest.raises(StructuredOutputError) as caught:
        await _run(call)

    assert caught.value.reason == "schema_mismatch" and caught.value.attempts == 2
    assert len(call.calls) == 2
    assert "differences" not in str(caught.value)  # the model's text is not in the error


async def test_a_reply_cut_off_at_the_budget_is_not_a_success_even_when_it_parses() -> None:
    call = Script(completion(GOOD_JSON, "length"), completion(GOOD_JSON))

    result = await _run(call)

    assert result.summary == "The algorithm changed."
    assert [tokens for _, tokens in call.calls] == [4096, 8192]  # retried once with double the budget
    assert call.calls[0][0] == call.calls[1][0] == "task"  # the same prompt, not a repair


async def test_the_truncation_retry_doubles_up_to_the_cap() -> None:
    call = Script(completion('{"differences": [', "length"), completion(GOOD_JSON))

    await _run(call, max_tokens=6000, max_tokens_cap=8192)

    assert [tokens for _, tokens in call.calls] == [6000, 8192]


async def test_a_reply_still_cut_off_after_the_retry_is_a_typed_truncation_error_and_is_not_repaired() -> None:
    call = Script(completion('{"differences": [', "length"), completion('{"differences": [{"cat', "length"))

    with pytest.raises(StructuredOutputError) as caught:
        await _run(call)

    assert caught.value.reason == "truncated" and caught.value.attempts == 2
    assert len(call.calls) == 2  # no repair call: text that never ended cannot be completed by an edit


async def test_no_truncation_retry_when_the_budget_is_already_at_the_cap() -> None:
    call = Script(completion(GOOD_JSON, "length"))

    with pytest.raises(StructuredOutputError) as caught:
        await _run(call, max_tokens=8192, max_tokens_cap=8192)

    assert caught.value.reason == "truncated" and len(call.calls) == 1


async def test_truncation_then_invalid_gets_the_repair_with_the_doubled_budget() -> None:
    call = Script(completion('{"differences": [', "length"), completion(QA_BROKEN), completion(GOOD_JSON))

    result = await _run(call)

    assert result.summary == "The algorithm changed."
    assert [tokens for _, tokens in call.calls] == [4096, 8192, 8192]  # at most three calls


async def test_a_provider_error_propagates_unchanged() -> None:
    call = Script(RuntimeError("boom"))

    with pytest.raises(RuntimeError, match="boom"):
        await _run(call)


def test_the_repair_prompt_shortens_a_runaway_reply() -> None:
    prompt = build_repair_prompt(SCHEMA, "x" * 50000, "invalid JSON", truncated=False)

    assert len(prompt) < 20000 and "reply shortened" in prompt


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("stop", "stop"),
        ("length", "length"),
        ("content_filter", "content_filter"),
        (SimpleNamespace(name="STOP"), "stop"),
        (SimpleNamespace(name="MAX_TOKENS"), "length"),
        (SimpleNamespace(name="SAFETY"), "content_filter"),
        (None, None),
        (MagicMock(), None),
    ],
)
def test_finish_reasons_are_provider_neutral(raw: object, expected: str | None) -> None:
    assert neutral_finish_reason(raw) == expected


def test_openapi_conversion_upper_cases_types_and_folds_a_nullable_union() -> None:
    converted = to_openapi_schema(
        {
            "type": "object",
            "properties": {
                "a": {"type": "array", "items": {"type": "string"}},
                "b": {"anyOf": [{"type": "number"}, {"type": "null"}]},
                "s": {"type": "string", "enum": ["X", "Y"]},
            },
            "required": ["a"],
        }
    )

    assert converted["type"] == "OBJECT"
    assert converted["properties"]["a"] == {"type": "ARRAY", "items": {"type": "STRING"}}
    assert converted["properties"]["b"] == {"type": "NUMBER", "nullable": True}
    assert converted["properties"]["s"] == {"type": "STRING", "enum": ["X", "Y"]}
    assert converted["required"] == ["a"]


# --------------------------------------------------------------------------
# Gemini
# --------------------------------------------------------------------------


def _client_error(code: int = 400, message: str = "Unsupported schema field", status: str = "INVALID_ARGUMENT") -> Exception:
    return genai_errors.ClientError(code, {"error": {"code": code, "message": message, "status": status}})


def _gemini(*replies: Any) -> GeminiProvider:
    gemini = GeminiProvider(api_key="gemini-test")
    gemini.client.aio.models.generate_content = AsyncMock(side_effect=list(replies))
    return gemini


def _reply(text: str, finish: str = "STOP") -> SimpleNamespace:
    return SimpleNamespace(text=text, candidates=[SimpleNamespace(finish_reason=SimpleNamespace(name=finish))])


def _config(gemini: GeminiProvider, call: int = -1) -> Any:
    return gemini.client.aio.models.generate_content.await_args_list[call].kwargs["config"]


async def test_gemini_asks_for_response_json_schema_first() -> None:
    gemini = _gemini(_reply(GOOD_JSON))

    result = await gemini.generate_structured("task", system_prompt="system", max_tokens=3000, json_schema=SCHEMA)

    config = _config(gemini)
    assert config.response_json_schema == SCHEMA and config.response_schema is None
    assert config.response_mime_type == "application/json"
    assert config.max_output_tokens == 3000 and config.system_instruction == "system"
    assert config.thinking_config is None  # nothing is sent until the probe says it works
    call = gemini.client.aio.models.generate_content.await_args.kwargs
    assert call["model"] == settings.gemini_generation_model and call["contents"] == "task"
    assert (result.text, result.finish_reason) == (GOOD_JSON, "stop")
    await gemini.aclose()


async def test_gemini_falls_back_to_response_schema_when_the_first_is_rejected_and_remembers_it() -> None:
    gemini = _gemini(_client_error(), _reply(GOOD_JSON), _reply(GOOD_JSON))

    first = await gemini.generate_structured("task", json_schema=SCHEMA)
    second = await gemini.generate_structured("task", json_schema=SCHEMA)

    assert first.text == second.text == GOOD_JSON
    calls = gemini.client.aio.models.generate_content.await_args_list
    assert len(calls) == 3  # one rejected call in the whole process, not one per request
    assert calls[0].kwargs["config"].response_json_schema == SCHEMA
    assert calls[1].kwargs["config"].response_json_schema is None
    assert calls[1].kwargs["config"].response_schema == to_openapi_schema(SCHEMA)
    assert calls[2].kwargs["config"].response_schema == to_openapi_schema(SCHEMA)
    await gemini.aclose()


async def test_an_sdk_that_refuses_the_field_also_falls_back() -> None:
    gemini = _gemini(ValueError("response_json_schema is not supported"), _reply(GOOD_JSON))

    result = await gemini.generate_structured("task", json_schema=SCHEMA)

    assert result.text == GOOD_JSON and _config(gemini).response_schema == to_openapi_schema(SCHEMA)
    await gemini.aclose()


async def test_both_schema_modes_rejected_raises_the_last_error() -> None:
    gemini = _gemini(_client_error(), _client_error(message="Unknown field"))

    with pytest.raises(genai_errors.ClientError):
        await gemini.generate_structured("task", json_schema=SCHEMA)

    assert gemini.client.aio.models.generate_content.await_count == 2
    await gemini.aclose()


@pytest.mark.parametrize(
    "error",
    [
        _client_error(400, "API key not valid. Please pass a valid API key.", "INVALID_ARGUMENT"),
        _client_error(429, "quota", "RESOURCE_EXHAUSTED"),
        _client_error(404, "model not found", "NOT_FOUND"),
        genai_errors.ServerError(503, {"error": {"code": 503, "message": "overloaded", "status": "UNAVAILABLE"}}),
    ],
)
async def test_errors_a_different_schema_cannot_fix_are_not_retried(error: Exception) -> None:
    gemini = _gemini(error)

    with pytest.raises(type(error)):
        await gemini.generate_structured("task", json_schema=SCHEMA)

    assert gemini.client.aio.models.generate_content.await_count == 1
    await gemini.aclose()


async def test_a_pinned_schema_mode_makes_one_call_in_that_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "gemini_structured_schema_mode", "response_schema")
    gemini = _gemini(_reply(GOOD_JSON))

    await gemini.generate_structured("task", json_schema=SCHEMA)

    assert gemini.client.aio.models.generate_content.await_count == 1
    assert _config(gemini).response_schema == to_openapi_schema(SCHEMA) and _config(gemini).response_json_schema is None
    await gemini.aclose()


async def test_gemini_thinking_for_structured_calls_follows_its_own_setting(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "gemini_thinking_level", "high")  # plain-chat setting: not used here
    monkeypatch.setattr(settings, "gemini_structured_thinking_level", "low")
    gemini = _gemini(_reply(GOOD_JSON))

    await gemini.generate_structured("task", json_schema=SCHEMA)

    assert str(_config(gemini).thinking_config.thinking_level.value) == "LOW"
    await gemini.aclose()


async def test_gemini_reports_a_max_tokens_stop_as_length() -> None:
    gemini = _gemini(_reply('{"differences": [', "MAX_TOKENS"))

    result = await gemini.generate_structured("task", json_schema=SCHEMA)

    assert result.finish_reason == "length"
    await gemini.aclose()


async def test_gemini_without_a_schema_is_refused() -> None:
    gemini = _gemini()

    with pytest.raises(ValueError):
        await gemini.generate_structured("task")
    await gemini.aclose()


# --------------------------------------------------------------------------
# The router: validate, repair, fail over
# --------------------------------------------------------------------------


def _fake_provider(*replies: StructuredCompletion | Exception, configured: bool = True) -> MagicMock:
    provider = MagicMock()
    provider.is_configured = configured
    provider.generate_structured = AsyncMock(side_effect=list(replies))
    return provider


async def test_the_router_returns_the_validated_model() -> None:
    nvidia = _fake_provider(completion(GOOD_JSON))
    gemini = _fake_provider()
    router = LLMRouter(nvidia=nvidia, gemini=gemini)

    result = await router.generate_structured("task", CompareResponse, SCHEMA, system_prompt="system")

    assert isinstance(result, CompareResponse) and result.summary == "The algorithm changed."
    kwargs = nvidia.generate_structured.await_args.kwargs
    assert kwargs["json_schema"] == SCHEMA and kwargs["system_prompt"] == "system"
    gemini.generate_structured.assert_not_awaited()
    record = router.call_log[0]
    assert (record.method, record.provider, record.success) == ("generate_structured", "nvidia", True)
    assert record.model == settings.nvidia_generation_model


async def test_the_router_repairs_once_then_returns() -> None:
    nvidia = _fake_provider(completion(QA_BROKEN), completion(GOOD_JSON))
    router = LLMRouter(nvidia=nvidia, gemini=_fake_provider(configured=False))

    result = await router.generate_structured("task", CompareResponse, SCHEMA)

    assert result.summary == "The algorithm changed."
    assert nvidia.generate_structured.await_count == 2


async def test_still_invalid_after_the_repair_is_a_typed_error_not_text() -> None:
    nvidia = _fake_provider(completion(QA_BROKEN), completion(QA_BROKEN))
    router = LLMRouter(nvidia=nvidia, gemini=_fake_provider(configured=False))

    with pytest.raises(StructuredOutputError) as caught:
        await router.generate_structured("task", CompareResponse, SCHEMA)

    assert caught.value.reason == "invalid_json" and caught.value.providers == ("nvidia",)
    assert nvidia.generate_structured.await_count == 2


async def test_when_nvidia_errors_gemini_serves_the_structured_call_with_the_configured_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "gemini_generation_model", "gemini-custom-flash")
    nvidia = _fake_provider(RuntimeError("nvidia down"))
    gemini = _gemini(_reply(GOOD_JSON))
    router = LLMRouter(nvidia=nvidia, gemini=gemini)

    result = await router.generate_structured("task", CompareResponse, SCHEMA, system_prompt="system")

    assert result.summary == "The algorithm changed."
    call = gemini.client.aio.models.generate_content.await_args.kwargs
    assert call["model"] == "gemini-custom-flash"
    assert call["config"].response_json_schema == SCHEMA and call["config"].response_mime_type == "application/json"
    assert [(r.provider, r.method, r.success) for r in router.call_log] == [
        ("nvidia", "generate_structured", False),
        ("gemini", "generate_structured", True),
    ]
    assert router.call_log[-1].model == "gemini-custom-flash"
    await gemini.aclose()


async def test_gemini_also_repairs_and_a_rejected_first_schema_mode_does_not_break_failover() -> None:
    nvidia = _fake_provider(RuntimeError("nvidia down"))
    gemini = _gemini(_client_error(), _reply(QA_BROKEN), _reply(GOOD_JSON))
    router = LLMRouter(nvidia=nvidia, gemini=gemini)

    result = await router.generate_structured("task", CompareResponse, SCHEMA)

    assert result.summary == "The algorithm changed."
    assert gemini.client.aio.models.generate_content.await_count == 3  # fallback mode, bad reply, repair
    await gemini.aclose()


async def test_nvidia_output_that_stays_invalid_gets_a_second_opinion_from_gemini() -> None:
    nvidia = _fake_provider(completion(QA_BROKEN), completion(QA_BROKEN))
    gemini = _gemini(_reply(GOOD_JSON))
    router = LLMRouter(nvidia=nvidia, gemini=gemini)

    result = await router.generate_structured("task", CompareResponse, SCHEMA)

    assert result.summary == "The algorithm changed."
    assert nvidia.generate_structured.await_count == 2 and gemini.client.aio.models.generate_content.await_count == 1
    await gemini.aclose()


async def test_both_providers_invalid_is_one_typed_error_naming_both() -> None:
    nvidia = _fake_provider(completion(QA_BROKEN), completion(QA_BROKEN))
    gemini = _fake_provider(completion('{"summary": "x"}'), completion('{"summary": "x"}'))
    router = LLMRouter(nvidia=nvidia, gemini=gemini)

    with pytest.raises(StructuredOutputError) as caught:
        await router.generate_structured("task", CompareResponse, SCHEMA)

    assert caught.value.providers == ("nvidia", "gemini") and caught.value.reason == "schema_mismatch"


async def test_both_providers_failing_is_the_provider_outage_error() -> None:
    nvidia = _fake_provider(RuntimeError("nvidia down"))
    gemini = _fake_provider(RuntimeError("gemini down"))
    router = LLMRouter(nvidia=nvidia, gemini=gemini)

    with pytest.raises(AllProvidersUnavailableError) as caught:
        await router.generate_structured("task", CompareResponse, SCHEMA)

    assert isinstance(caught.value.__cause__, RuntimeError)


async def test_no_usable_provider_is_the_provider_outage_error() -> None:
    router = LLMRouter(nvidia=_fake_provider(configured=False), gemini=_fake_provider(configured=False))

    with pytest.raises(AllProvidersUnavailableError):
        await router.generate_structured("task", CompareResponse, SCHEMA)


async def test_truncation_retry_through_the_router_doubles_the_budget() -> None:
    nvidia = _fake_provider(completion('{"differences": [', "length"), completion(GOOD_JSON))
    router = LLMRouter(nvidia=nvidia, gemini=_fake_provider(configured=False))

    await router.generate_structured("task", CompareResponse, SCHEMA)

    assert [c.kwargs["max_tokens"] for c in nvidia.generate_structured.await_args_list] == [4096, 8192]


async def test_an_egress_block_on_the_repair_prompt_propagates_and_is_not_a_failover() -> None:
    async def egress(prompt: str) -> None:
        raise PermissionError("blocked by egress")

    nvidia = _fake_provider(completion(QA_BROKEN), completion(GOOD_JSON))
    gemini = _fake_provider(completion(GOOD_JSON))
    router = LLMRouter(nvidia=nvidia, gemini=gemini)

    with pytest.raises(PermissionError):
        await router.generate_structured("task", CompareResponse, SCHEMA, egress_check=egress)

    assert nvidia.generate_structured.await_count == 1
    gemini.generate_structured.assert_not_awaited()  # the blocked text is not sent to another provider either


async def test_structured_failures_have_their_own_breaker_and_do_not_stop_plain_generation() -> None:
    nvidia = _fake_provider(*[RuntimeError("bad") for _ in range(10)])
    nvidia.generate = AsyncMock(return_value="plain answer")
    gemini = _fake_provider(*[RuntimeError("bad") for _ in range(10)], configured=False)
    router = LLMRouter(nvidia=nvidia, gemini=gemini)

    for _ in range(settings.llm_breaker_failures):
        with pytest.raises(AllProvidersUnavailableError):
            await router.generate_structured("task", CompareResponse, SCHEMA)

    snapshot = router.breakers.snapshot()
    assert snapshot["nvidia/generate_structured"]["state"] == "OPEN"
    assert await router.generate("hello") == "plain answer"  # generation is unaffected
    assert router.breakers.get("nvidia", "generate").get_state().value == "CLOSED"


async def test_a_provider_without_its_own_structured_method_still_works_through_generate() -> None:
    """The base class default: a provider that only has ``generate`` serves a structured call."""
    from app.services.llm.base_provider import BaseLLMProvider

    class Plain(BaseLLMProvider):
        provider_name = "plain"

        async def generate(self, prompt, system_prompt=None, temperature=0.7, max_tokens=1024, json_schema=None):
            return GOOD_JSON

        async def generate_stream(self, *args, **kwargs):  # pragma: no cover - not used
            yield ""

        async def embed(self, texts, input_type="query"):  # pragma: no cover - not used
            return []

        async def rerank(self, query, passages, top_n=5):  # pragma: no cover - not used
            return []

        async def health_check(self):  # pragma: no cover - not used
            raise NotImplementedError

    result = await Plain().generate_structured("task", json_schema=SCHEMA)

    assert result.text == GOOD_JSON and result.finish_reason is None

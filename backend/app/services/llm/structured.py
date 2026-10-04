"""Structured output: request forms, tolerant parsing, validation and one repair (PR-02, QA-005).

The live audit saw gap analysis fail 5 of 5 times and compare return half a JSON table as its
"summary". This module is the contract that replaces it:

1. The request asks the provider for schema-constrained JSON in the form ``NVIDIA_STRUCTURED_MODE``
   names (``nvidia_structured_extra_body``), with thinking off and a structured token budget.
2. The reply is parsed tolerantly (code fences, ``<think>`` blocks and trailing text are
   ignored) and validated against the Pydantic model (``parse_structured``).
3. A reply cut off at the token budget (``finish_reason == "length"``) is never a success. It
   is retried once with double the budget (up to ``STRUCTURED_MAX_TOKENS_CAP``).
4. An invalid reply gets exactly one repair round trip that sends the model its own output
   and the validation errors (``run_structured``).
5. Still invalid: ``StructuredOutputError``. Raw model text is never returned to a caller
   as if it were a result, and never logged.

Provider specifics (which request form, which stop reason name) live in the providers; the
validate/repair loop here does not know which provider answered.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Awaitable, Callable
from typing import Any, Literal, TypeVar

from pydantic import BaseModel, ValidationError

from app.services.llm.base_provider import StructuredCompletion

logger = logging.getLogger(__name__)

STRUCTURED_MODES = ("nvext_guided_json", "top_guided_json", "response_format_json_schema")
# Structured replies should be deterministic enough to validate; the chat default (0.7) is not.
DEFAULT_STRUCTURED_TEMPERATURE = 0.2
SCHEMA_NAME = "structured_output"
# The model's own previous reply is echoed in the repair prompt; cap it so a runaway reply
# cannot turn the repair call into a second giant request.
MAX_REPAIR_ECHO_CHARS = 16000
# Brace positions tried when the first object does not decode (a stray leading `{`).
_MAX_BRACE_CANDIDATES = 20
_MAX_PROBLEMS = 5

FailureReason = Literal["invalid_json", "schema_mismatch", "truncated"]
ModelT = TypeVar("ModelT", bound=BaseModel)
# Called with the repair prompt before it is sent; raise to block it (the egress validator).
EgressCheck = Callable[[str], Awaitable[None]]
# One provider call: (prompt, max_tokens) -> the raw completion.
StructuredCall = Callable[[str, int], Awaitable[StructuredCompletion]]


class StructuredOutputError(Exception):
    """The model never produced output that validates, even after the allowed retries.

    The message and attributes describe the failure only. They never hold the model's text:
    a caller must not surface it, and it is not logged either.

    Attributes:
        reason: ``truncated`` (still cut off at the token cap), ``invalid_json`` or
            ``schema_mismatch`` (parsed, but the fields do not match the schema).
        attempts: Provider calls made (first call plus retries) for the last provider tried.
        providers: Providers whose output was tried and rejected, in order.
    """

    def __init__(self, reason: FailureReason, attempts: int = 1, providers: tuple[str, ...] = ()) -> None:
        self.reason: FailureReason = reason
        self.attempts = attempts
        self.providers = providers
        super().__init__(f"structured output failed: reason={reason} attempts={attempts}")


def nvidia_structured_extra_body(
    mode: str, schema: dict[str, Any], *, disable_thinking: bool = True
) -> dict[str, Any]:
    """Request-body fields (beyond model, messages and sampling) of an NVIDIA structured call.

    Args:
        mode: One of ``STRUCTURED_MODES``. ``nvext_guided_json`` is what the NIM docs show;
            ``top_guided_json`` is the older top-level form; ``response_format_json_schema``
            is the OpenAI-compatible form.
        schema: JSON schema the reply must match.
        disable_thinking: Add ``chat_template_kwargs.enable_thinking=false``.

    Returns:
        Fields to merge into the chat-completions body (the OpenAI client's ``extra_body``).

    Raises:
        ValueError: ``mode`` is not one of ``STRUCTURED_MODES``.
    """
    if mode == "nvext_guided_json":
        body: dict[str, Any] = {"nvext": {"guided_json": schema}}
    elif mode == "top_guided_json":
        body = {"guided_json": schema}
    elif mode == "response_format_json_schema":
        body = {
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": SCHEMA_NAME, "schema": schema},
            }
        }
    else:
        raise ValueError(f"Unknown NVIDIA_STRUCTURED_MODE {mode!r}; expected one of {', '.join(STRUCTURED_MODES)}")
    if disable_thinking:
        body["chat_template_kwargs"] = {"enable_thinking": False}
    return body


def to_openapi_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Convert a JSON Schema subset to the OpenAPI form Gemini's ``responseSchema`` takes.

    Types become upper case and ``anyOf: [X, null]`` becomes ``X`` with ``nullable``.
    ``responseSchema`` is the fallback for models or SDKs that reject ``responseJsonSchema``.
    """
    out: dict[str, Any] = {}
    for key, value in schema.items():
        if key == "type" and isinstance(value, str):
            out[key] = value.upper()
        elif key == "properties" and isinstance(value, dict):
            out[key] = {k: to_openapi_schema(v) for k, v in value.items()}
        elif key == "items" and isinstance(value, dict):
            out[key] = to_openapi_schema(value)
        elif key == "anyOf" and isinstance(value, list):
            non_null = [v for v in value if not (isinstance(v, dict) and v.get("type") == "null")]
            if len(non_null) == 1 and len(non_null) < len(value):
                out.update(to_openapi_schema(non_null[0]))
                out["nullable"] = True
            else:
                out[key] = [to_openapi_schema(v) for v in non_null]
        else:
            out[key] = value
    return out


def neutral_finish_reason(raw: object) -> str | None:
    """Map a provider's stop reason to ``stop``, ``length``, ``content_filter`` or a lower-cased name.

    Handles OpenAI-style strings (``stop``, ``length``) and Gemini enum members or names
    (``STOP``, ``MAX_TOKENS``, ``SAFETY``). Anything that is not a string or enum gives None.
    """
    name = getattr(raw, "name", raw)
    if not isinstance(name, str) or not name:
        return None
    name = name.lower()
    if name == "max_tokens":
        return "length"
    if name in {"safety", "blocklist", "prohibited_content", "spii", "recitation"}:
        return "content_filter"
    return name


_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_FENCE_RE = re.compile(r"```(?:json)?", re.IGNORECASE)


def _clean(text: str) -> str:
    """Drop ``<think>`` blocks (and an unterminated one) and markdown code fences."""
    cleaned = _THINK_RE.sub("", text or "")
    open_tag = re.search(r"<think>", cleaned, re.IGNORECASE)
    if open_tag:  # a thinking block that never closed: everything after it is reasoning
        cleaned = cleaned[: open_tag.start()]
    return _FENCE_RE.sub("", cleaned)


def _summarise(exc: ValidationError) -> str:
    """Field paths and messages of a validation error, without the offending values."""
    parts = [
        f"{'.'.join(str(p) for p in err['loc']) or '(root)'}: {err['msg']}" for err in exc.errors()[:_MAX_PROBLEMS]
    ]
    more = exc.error_count() - len(parts)
    return "; ".join(parts) + (f"; and {more} more" if more > 0 else "")


def parse_structured(
    text: str, schema_model: type[ModelT]
) -> tuple[ModelT | None, FailureReason | None, str]:
    """Parse and validate a model reply.

    Code fences, ``<think>`` blocks and text after the object are ignored. When the first
    ``{`` does not start a decodable object (a stray leading brace), later ones are tried.

    Args:
        text: Raw model output.
        schema_model: Pydantic model the reply must validate against.

    Returns:
        ``(value, None, "")`` on success, else ``(None, reason, problem)`` where ``problem``
        describes the failure with field paths and messages only, never the reply's content.
    """
    cleaned = _clean(text)
    decoder = json.JSONDecoder()
    first_failure: tuple[FailureReason, str] | None = None
    for tried, brace in enumerate(re.finditer(r"\{", cleaned)):
        if tried >= _MAX_BRACE_CANDIDATES:
            break
        try:
            obj, _end = decoder.raw_decode(cleaned, brace.start())
        except json.JSONDecodeError as exc:
            if first_failure is None:
                first_failure = ("invalid_json", f"invalid JSON: {exc.msg} at line {exc.lineno} column {exc.colno}")
            continue
        if tried > 0 and not obj:
            continue
        try:
            return schema_model.model_validate(obj), None, ""
        except ValidationError as exc:
            if tried == 0:
                # A complete object that does not match: scanning for inner objects would
                # only find fragments of it.
                return None, "schema_mismatch", _summarise(exc)
    if first_failure is not None:
        return None, first_failure[0], first_failure[1]
    return None, "invalid_json", "no JSON object found in the reply"


def build_repair_prompt(schema: dict[str, Any], previous_reply: str, problem: str, truncated: bool) -> str:
    """Prompt for the one repair call: the model's own reply plus what was wrong with it.

    Sends no document text, only the model's previous output (itself derived from masked
    input), the problem and the schema. The caller runs it through the egress check.
    """
    echo = _clean(previous_reply).strip()
    if len(echo) > MAX_REPAIR_ECHO_CHARS:
        echo = echo[:MAX_REPAIR_ECHO_CHARS] + "\n[...reply shortened...]"
    cut_off = "It was cut off before it finished. " if truncated else ""
    return (
        "Your previous reply could not be used. "
        f"{cut_off}Problem: {problem}.\n\n"
        "Return ONLY one complete JSON object that matches this JSON schema. "
        "No markdown fences, no commentary, no text before or after it.\n\n"
        f"JSON schema:\n{json.dumps(schema, separators=(',', ':'))}\n\n"
        f"Your previous reply:\n{echo}\n"
    )


def _outcome(
    completion: StructuredCompletion, schema_model: type[ModelT]
) -> tuple[ModelT | None, FailureReason | None, str]:
    """Validate one completion. A reply cut off at the token budget is never a success."""
    value, reason, problem = parse_structured(completion.text, schema_model)
    if completion.finish_reason == "length":
        return None, "truncated", "the reply was cut off at the output token limit"
    return value, reason, problem


async def run_structured(
    call: StructuredCall,
    prompt: str,
    schema_model: type[ModelT],
    schema: dict[str, Any],
    *,
    max_tokens: int,
    max_tokens_cap: int,
    egress_check: EgressCheck | None = None,
    provider: str = "",
) -> ModelT:
    """Call a provider for structured output, validate it, and retry the allowed times.

    Flow: first call. A reply cut off at the budget is retried once with double the budget
    (capped). An invalid reply (not JSON, or JSON that does not match) gets exactly one
    repair call that carries the model's own output and the validation problem. A reply
    that is still cut off at the cap is not repaired, because text that never ended cannot be
    completed by an edit. At most three provider calls are made (cut off, doubled, repair).

    Args:
        call: ``(prompt, max_tokens) -> StructuredCompletion`` for one provider. Provider
            errors propagate unchanged.
        prompt: The task prompt (already egress-validated by the caller).
        schema_model: Pydantic model the reply must validate against.
        schema: JSON schema, echoed in the repair prompt.
        max_tokens: Output budget of the first call.
        max_tokens_cap: Largest budget the truncation retry may use.
        egress_check: Awaited with the repair prompt before it is sent; raising blocks it.
        provider: Provider name, for log lines only.

    Returns:
        The validated model instance.

    Raises:
        StructuredOutputError: The reply never validated.
    """
    attempts = 1
    budget = max_tokens
    completion = await call(prompt, budget)
    value, reason, problem = _outcome(completion, schema_model)
    if value is not None:
        return value

    if reason == "truncated" and budget < max_tokens_cap:
        budget = min(budget * 2, max_tokens_cap)
        logger.warning(
            "structured_retry provider=%s why=truncated action=double_budget max_tokens=%d", provider, budget
        )
        completion = await call(prompt, budget)
        attempts += 1
        value, reason, problem = _outcome(completion, schema_model)
        if value is not None:
            return value

    if reason == "truncated":
        logger.warning("structured_failed provider=%s reason=truncated attempts=%d", provider, attempts)
        raise StructuredOutputError("truncated", attempts)

    logger.warning(
        "structured_retry provider=%s why=%s action=repair problem=%s", provider, reason, problem[:300]
    )
    repair_prompt = build_repair_prompt(schema, completion.text, problem, truncated=False)
    if egress_check is not None:
        await egress_check(repair_prompt)
    completion = await call(repair_prompt, budget)
    attempts += 1
    value, reason, problem = _outcome(completion, schema_model)
    if value is not None:
        return value
    assert reason is not None  # a failed outcome always carries its reason
    logger.warning(
        "structured_failed provider=%s reason=%s attempts=%d problem=%s", provider, reason, attempts, problem[:300]
    )
    raise StructuredOutputError(reason, attempts)

"""Client-safe HTTP errors for known RAG pipeline failures.

Maps the failures a user can meaningfully act on to stable, privacy-safe HTTP
responses. The full exception is logged server-side only: egress reports embed
the leaked entity text and provider errors embed upstream payloads (e.g. API key
diagnostics), so neither may reach the client.

Typed errors (PR-02): ``/compare`` and ``/gap-analysis`` ask for ``typed=True``, which makes
every failure body ``{"detail": <message>, "code": <stable code>, "retryable": <bool>}``.
``detail`` stays a plain string, so clients that only read ``detail`` keep working; ``code``
lets a client choose its own wording or action. The codes are the ``CODE_*`` constants below.
"""

from __future__ import annotations

import logging

from fastapi import HTTPException, Request, status
from fastapi.responses import JSONResponse

from app.services.llm.router import AllProvidersUnavailableError
from app.services.llm.structured import StructuredOutputError
from app.services.privacy.egress_validator import EgressViolationError

logger = logging.getLogger(__name__)

EGRESS_BLOCKED_DETAIL = (
    "Request blocked by the privacy egress check: the prompt would expose a registered entity."
)
PROVIDER_UNAVAILABLE_DETAIL = "The AI provider is currently unavailable. Please try again later."
STRUCTURED_INVALID_DETAIL = "The AI returned an invalid response. Please retry."
STRUCTURED_TRUNCATED_DETAIL = "The AI response was cut off before it finished. Please retry."
# Literal: Starlette renamed HTTP_422_UNPROCESSABLE_ENTITY (deprecated) across versions.
_HTTP_422 = 422

# Stable machine-readable codes of the typed error body (PR-02). Clients may rely on them.
CODE_STRUCTURED_INVALID = "structured_output_invalid"
CODE_STRUCTURED_TRUNCATED = "structured_output_truncated"
CODE_PROVIDER_UNAVAILABLE = "provider_unavailable"
CODE_EGRESS_BLOCKED = "egress_blocked"
CODE_OUTPUT_BLOCKED = "output_guardrail_blocked"
CODE_INPUT_BLOCKED = "input_guardrail_blocked"
CODE_GENERATION_FAILED = "generation_failed"


class TypedHTTPException(HTTPException):
    """An HTTPException whose JSON body also carries a stable ``code`` and ``retryable`` flag.

    Attributes:
        code: One of the ``CODE_*`` constants.
        retryable: Whether trying the same request again may succeed.
    """

    def __init__(self, status_code: int, detail: str, *, code: str, retryable: bool) -> None:
        super().__init__(status_code=status_code, detail=detail)
        self.code = code
        self.retryable = retryable


async def typed_http_exception_handler(request: Request, exc: TypedHTTPException) -> JSONResponse:
    """Render a ``TypedHTTPException`` as ``{"detail", "code", "retryable"}``."""
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail, "code": exc.code, "retryable": exc.retryable},
        headers=exc.headers,
    )


def typed_error(status_code: int, detail: str, code: str, retryable: bool) -> TypedHTTPException:
    """Build a typed error for an endpoint's own failures (guardrail blocks, generic failure)."""
    return TypedHTTPException(status_code, detail, code=code, retryable=retryable)


def client_http_error(exc: BaseException, endpoint: str, *, typed: bool = False) -> HTTPException | None:
    """Translate a known pipeline failure into a client-safe HTTPException.

    Args:
        exc: Exception that aborted the request.
        endpoint: Endpoint label for the server-side log line.
        typed: Return a ``TypedHTTPException`` (body with ``code`` and ``retryable``) instead
            of a plain one. Only the endpoints that document the typed shape ask for it.

    Returns:
        A 422 for an egress violation, a 503 when no LLM provider could serve the
        call, a 502 when structured output never validated, or None for any other
        (unexpected) exception, which the caller re-raises.
    """
    if isinstance(exc, EgressViolationError):
        # The report lists entity strings: log only the count.
        logger.warning(
            "Egress validation blocked a %s request (%d violations)",
            endpoint,
            len(exc.report.violations),
        )
        if typed:
            return typed_error(_HTTP_422, EGRESS_BLOCKED_DETAIL, CODE_EGRESS_BLOCKED, retryable=False)
        return HTTPException(
            status_code=_HTTP_422,
            detail=EGRESS_BLOCKED_DETAIL,
        )
    if isinstance(exc, AllProvidersUnavailableError):
        logger.error("No LLM provider could serve a %s request: %s", endpoint, exc, exc_info=exc)
        if typed:
            return typed_error(
                status.HTTP_503_SERVICE_UNAVAILABLE, PROVIDER_UNAVAILABLE_DETAIL, CODE_PROVIDER_UNAVAILABLE, True
            )
        return HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=PROVIDER_UNAVAILABLE_DETAIL,
        )
    if isinstance(exc, StructuredOutputError):
        # The error carries the reason and counts only, never the model's text.
        logger.error(
            "Structured output failed for %s: reason=%s attempts=%d providers=%s",
            endpoint, exc.reason, exc.attempts, ",".join(exc.providers),
        )
        truncated = exc.reason == "truncated"
        return typed_error(
            status.HTTP_502_BAD_GATEWAY,
            STRUCTURED_TRUNCATED_DETAIL if truncated else STRUCTURED_INVALID_DETAIL,
            CODE_STRUCTURED_TRUNCATED if truncated else CODE_STRUCTURED_INVALID,
            retryable=True,
        )
    return None

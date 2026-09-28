"""Client-safe HTTP errors for known RAG pipeline failures.

Maps the failures a user can meaningfully act on to stable, privacy-safe HTTP
responses. The full exception is logged server-side only: egress reports embed
the leaked entity text and provider errors embed upstream payloads (e.g. API key
diagnostics), so neither may reach the client.
"""

from __future__ import annotations

import logging

from fastapi import HTTPException, status

from app.services.llm.router import AllProvidersUnavailableError
from app.services.privacy.egress_validator import EgressViolationError

logger = logging.getLogger(__name__)

EGRESS_BLOCKED_DETAIL = (
    "Request blocked by the privacy egress check: the prompt would expose a registered entity."
)
PROVIDER_UNAVAILABLE_DETAIL = "The AI provider is currently unavailable. Please try again later."
# Literal: Starlette renamed HTTP_422_UNPROCESSABLE_ENTITY (deprecated) across versions.
_HTTP_422 = 422


def client_http_error(exc: BaseException, endpoint: str) -> HTTPException | None:
    """Translate a known pipeline failure into a client-safe HTTPException.

    Args:
        exc: Exception that aborted the request.
        endpoint: Endpoint label for the server-side log line.

    Returns:
        A 422 for an egress violation, a 503 when no LLM provider could serve the
        call, or None for any other (unexpected) exception, which the caller re-raises.
    """
    if isinstance(exc, EgressViolationError):
        # The report lists entity strings: log only the count.
        logger.warning(
            "Egress validation blocked a %s request (%d violations)",
            endpoint,
            len(exc.report.violations),
        )
        return HTTPException(
            status_code=_HTTP_422,
            detail=EGRESS_BLOCKED_DETAIL,
        )
    if isinstance(exc, AllProvidersUnavailableError):
        logger.error("No LLM provider could serve a %s request: %s", endpoint, exc, exc_info=exc)
        return HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=PROVIDER_UNAVAILABLE_DETAIL,
        )
    return None

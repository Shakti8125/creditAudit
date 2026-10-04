from __future__ import annotations

import json
import logging
from typing import Any, AsyncIterator, Callable, Dict, Optional, Union
from fastapi.responses import StreamingResponse

logger = logging.getLogger(__name__)

# Sent in the SSE ``error`` event. The real exception (which may embed an upstream
# provider payload, e.g. an API-key diagnostic) is logged server-side only.
SSE_ERROR_MESSAGE = "The AI analyst failed to complete this answer."


def sse_stream(
    generator: AsyncIterator[Union[str, Dict[str, Any]]],
    done_extra: Optional[Callable[[], Dict[str, Any]]] = None,
) -> StreamingResponse:
    """Wraps an async generator of string tokens or dicts into an SSE (Server-Sent Events) StreamingResponse.

    Format:
    data: {"type": "token", "content": "..."}\n\n
    data: {"type": "done"}\n\n
    data: {"type": "error", "content": "..."}\n\n

    The ``error`` event always carries the generic ``SSE_ERROR_MESSAGE``; the
    exception itself is logged server-side and never sent to the client.

    Args:
        generator: Tokens (strings) and event dicts to stream.
        done_extra: Called once after the generator finished, to add fields to the final
            ``done`` event (``/query`` adds ``"truncated": true`` for a cut-off answer). A
            failure here is logged and never turns a finished answer into an error.
    """
    async def event_generator() -> AsyncIterator[str]:
        try:
            async for item in generator:
                if isinstance(item, dict):
                    yield f"data: {json.dumps(item)}\n\n"
                else:
                    yield f"data: {json.dumps({'type': 'token', 'content': str(item)})}\n\n"
            done: Dict[str, Any] = {"type": "done"}
            if done_extra is not None:
                try:
                    done.update(done_extra())
                except Exception:  # noqa: BLE001 - extra fields must not break a finished stream
                    logger.exception("SSE done_extra failed")
            yield f"data: {json.dumps(done)}\n\n"
        except Exception as e:
            logger.exception("SSE stream aborted by %s", type(e).__name__)
            yield f"data: {json.dumps({'type': 'error', 'content': SSE_ERROR_MESSAGE})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


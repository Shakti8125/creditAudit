from __future__ import annotations

import json
from typing import Any, AsyncIterator, Dict, Union
from fastapi.responses import StreamingResponse


def sse_stream(generator: AsyncIterator[Union[str, Dict[str, Any]]]) -> StreamingResponse:
    """Wraps an async generator of string tokens or dicts into an SSE (Server-Sent Events) StreamingResponse.

    Format:
    data: {"type": "token", "content": "..."}\n\n
    data: {"type": "done"}\n\n
    data: {"type": "error", "content": "..."}\n\n
    """
    async def event_generator() -> AsyncIterator[str]:
        try:
            async for item in generator:
                if isinstance(item, dict):
                    yield f"data: {json.dumps(item)}\n\n"
                else:
                    yield f"data: {json.dumps({'type': 'token', 'content': str(item)})}\n\n"
            yield f"data: {json.dumps({'type': 'done'})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'content': str(e)})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


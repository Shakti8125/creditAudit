from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from typing import Any

import pytest

from app.utils.streaming import SSE_ERROR_MESSAGE, sse_stream

UPSTREAM = '{"error": {"code": 400, "details": [{"reason": "API_KEY_INVALID"}]}}'


async def _body(generator: AsyncIterator[Any]) -> list[dict[str, Any]]:
    response = sse_stream(generator)
    chunks = [chunk async for chunk in response.body_iterator]
    text = "".join(c if isinstance(c, str) else c.decode() for c in chunks)
    return [json.loads(block[len("data: "):]) for block in text.split("\n\n") if block.startswith("data: ")]


@pytest.mark.asyncio
async def test_error_event_is_generic_and_full_error_is_logged(caplog):
    async def failing() -> AsyncIterator[Any]:
        yield {"type": "trace", "content": "t-1"}
        yield "partial "
        raise RuntimeError(UPSTREAM)

    with caplog.at_level(logging.ERROR, logger="app.utils.streaming"):
        events = await _body(failing())

    assert events == [
        {"type": "trace", "content": "t-1"},
        {"type": "token", "content": "partial "},
        {"type": "error", "content": SSE_ERROR_MESSAGE},
    ]
    assert "API_KEY_INVALID" not in json.dumps(events)
    # Full error (with traceback) is kept in the server log.
    assert "API_KEY_INVALID" in caplog.text


@pytest.mark.asyncio
async def test_successful_stream_ends_with_done():
    async def ok() -> AsyncIterator[Any]:
        yield "answer"

    assert await _body(ok()) == [{"type": "token", "content": "answer"}, {"type": "done"}]
